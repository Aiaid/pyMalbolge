"""Interleaved, uncached semantic-pass comparisons on the project VM.

Run with uv run --no-sync python scripts/benchmark_semantic_passes.py --help.
Warmups also use fresh compiler/runtime processes and are retained separately.
No operating-system cache flush, profiling, native VM, or aggregate score is
part of this experiment. Fixed outputs and consumed-input counts are external
contracts, never inferred from an optimized program.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import contextlib
from dataclasses import dataclass
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
WORKER = ROOT / "scripts/benchmark_pipeline.py"


@dataclass(frozen=True)
class Workload:
    id: str
    stdin: bytes
    stdout: bytes
    input_consumed: int
    max_steps: int = 20_000_000
    timeout_seconds: float = 30

    def job(self, source):
        return {"id": self.id, "source": source,
                "stdin": self.stdin.decode("latin1"), "stdin_hex": self.stdin.hex(),
                "stdout": self.stdout.decode("latin1"), "stdout_hex": self.stdout.hex(),
                "expected_input_consumed": self.input_consumed,
                "max_steps": self.max_steps, "timeout_seconds": self.timeout_seconds}


@dataclass(frozen=True)
class Case:
    id: str
    source: str
    workloads: tuple[Workload, ...]
    slow: bool = False


CASES = {
    case.id: case for case in (
        Case("char_io", "x=getchar()\nputchar(x)\n", (
            Workload("ascii", b"Q", b"Q", 1), Workload("zero", b"\0", b"\0", 1))),
        Case("literal_fold", "putchar((20+30)+(17-2))\n", (Workload("fixed", b"", b"A", 0),)),
        Case("arithmetic_identities", "x=getchar()\nputchar(x+0)\nputchar(0+x)\nputchar(x-0)\nputchar(x//1)\nputchar(x%1+65)\n",
             (Workload("ascii", b"Q", b"QQQQA", 1),)),
        Case("constant_propagation", "x=65\ny=x+1\nz=y-1\nputchar(z)\n",
             (Workload("fixed", b"", b"A", 0),)),
        Case("call_global_loop", "g=65\ndef bump():\n    global g\n    g=g+1\n    return 0\ni=0\nwhile i<2:\n    old=g\n    bump()\n    putchar(old)\n    i=i+1\nputchar(g)\n",
             (Workload("fixed", b"", b"ABC", 0),)),
        Case("multiply_3", "x=getchar()\nputchar(x*3)\n", (Workload("small", b"\x03", b"\x09", 1),)),
        Case("multiply_17", "x=getchar()\nputchar(x*17)\n", (Workload("small", b"\x03", b"3", 1),)),
        Case("multiply_255", "x=getchar()\nputchar(x*255)\n", (Workload("small", b"\x01", b"\xff", 1),)),
        Case("byte_decimal", "n=getchar()\nprint(n)\n", (
            Workload("zero", b"\0", b"0\n", 1, 100_000_000, 120),
            Workload("small", b"\x07", b"7\n", 1, 100_000_000, 120),
            Workload("ascii", b"A", b"65\n", 1, 100_000_000, 120)), True),
        Case("wide_decimal", "n=getchar()+3486784145\nprint(n)\n", (
            Workload("base", b"\0", b"3486784145\n", 1, 100_000_000, 120),
            Workload("max", b"\xff", b"3486784400\n", 1, 100_000_000, 120)), True),
    )
}
DEFAULT_CASES = tuple(name for name, case in CASES.items()
                      if not case.slow and name not in ("multiply_17", "multiply_255"))
VARIANT_NAMES = ("legacy_direct", "semantic_legacy", "semantic_none", "semantic_passes", "semantic_decimal")
DEFAULT_VARIANTS = VARIANT_NAMES[:-1]


@dataclass(frozen=True)
class Variant:
    id: str
    backend: str
    semantic_passes: tuple[str, ...]
    legacy_arithmetic: bool


def variants():
    from malbolge.compiler.ir import require_ir_support
    require_ir_support()
    from malbolge.compiler.ir.semantic_passes import (
        CANDIDATE_OPTIMIZATION_PASSES, CANDIDATE_DECIMAL_PASSES,
    )
    return {variant.id: variant for variant in (
        Variant("legacy_direct", "direct", (), True),
        Variant("semantic_legacy", "ir", ("verify-semantic",), True),
        Variant("semantic_none", "ir", ("verify-semantic",), False),
        Variant("semantic_passes", "ir", tuple(CANDIDATE_OPTIMIZATION_PASSES), False),
        Variant("semantic_decimal", "ir", tuple(CANDIDATE_DECIMAL_PASSES), False),
    )}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def validate_contract(case, workload):
    """Check immutable fixtures against CPython, independently of target IR."""
    stream, consumed = io.StringIO(), 0

    def getchar():
        nonlocal consumed
        if consumed == len(workload.stdin):
            return 59049
        value = workload.stdin[consumed]
        consumed += 1
        return value

    with contextlib.redirect_stdout(stream):
        exec(compile(case.source, "<fixed-semantic-benchmark>", "exec"),
             {"getchar": getchar, "putchar": lambda value: stream.write(chr(value % 256))})
    output = stream.getvalue().encode("latin1")
    return {"output_hex": output.hex(), "input_consumed": consumed,
            "passed": output == workload.stdout and consumed == workload.input_consumed}


def source_fingerprint(root=ROOT):
    """Fingerprint compiler, VM, orchestration, and dependency declarations."""
    paths = list((root / "malbolge").rglob("*.py"))
    paths.extend(root / name for name in (
        "scripts/benchmark_pipeline.py", "scripts/benchmark_suite.py",
        "scripts/benchmark_semantic_passes.py", "pyproject.toml", "uv.lock"))
    return {str(path.relative_to(root)): digest(path.read_bytes())
            for path in sorted(set(paths)) if path.is_file()}


def schedule(case_ids, variant_ids, repeats, warmups):
    """Rotate first variant by case and round, retaining every planned job."""
    plan = []
    for round_index in range(warmups + repeats):
        phase = "warmup" if round_index < warmups else "measurement"
        repeat = round_index + 1 if phase == "warmup" else round_index - warmups + 1
        for case_index, case_id in enumerate(case_ids):
            offset = (round_index + case_index) % len(variant_ids)
            order = tuple(variant_ids[offset:]) + tuple(variant_ids[:offset])
            for position, variant_id in enumerate(order):
                plan.append({"sequence": len(plan), "phase": phase, "repeat": repeat,
                             "case": case_id, "variant": variant_id, "variant_position": position})
    return plan


def _selected(values, available, default, label):
    result = tuple(part for value in (values or default) for part in value.split(",") if part)
    if not result or len(result) != len(set(result)):
        raise ValueError(f"select unique, nonempty {label}")
    unknown = set(result) - set(available)
    if unknown:
        raise ValueError(f"unknown {label}: {', '.join(sorted(unknown))}")
    return result


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", nargs="+", help="case IDs, separated by spaces or commas; slow decimal cases are explicit")
    parser.add_argument("--variants", nargs="+", help="variant IDs, separated by spaces or commas")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1, help="unmeasured fresh-process rounds (default: 1)")
    parser.add_argument("--compile-timeout", type=float, default=300)
    parser.add_argument("--runtime-timeout", type=float, help="override runtime child budget, at most 120 seconds")
    parser.add_argument("--max-steps", type=int, help="override VM budget, at most 100000000")
    parser.add_argument("--output", "--output-dir", dest="output", type=Path)
    parser.add_argument("--list", action="store_true", help="list fixed cases and variants without creating files")
    args = parser.parse_args(argv)
    try:
        args.cases = _selected(args.cases, CASES, DEFAULT_CASES, "cases")
        args.variants = _selected(args.variants, VARIANT_NAMES, DEFAULT_VARIANTS, "variants")
        if args.repeats < 1 or args.warmups < 0:
            raise ValueError("repeats must be positive and warmups nonnegative")
        if not math.isfinite(args.compile_timeout) or not 0 < args.compile_timeout <= 300:
            raise ValueError("compile timeout must be positive and at most 300 seconds")
        if args.runtime_timeout is not None and (
            not math.isfinite(args.runtime_timeout) or not 0 < args.runtime_timeout <= 120
        ):
            raise ValueError("runtime timeout must be positive and at most 120 seconds")
        if args.max_steps is not None and not 0 <= args.max_steps <= 100_000_000:
            raise ValueError("max steps must be between 0 and 100000000")
        if not args.list and args.output is None:
            raise ValueError("provide --output with a new empty directory")
    except ValueError as exc:
        parser.error(str(exc))
    return args


def worker_command(task, directory, job, record, variant, max_steps):
    command = [sys.executable, str(WORKER), "--worker", task,
               "--job", str(job), "--record", record, "--directory", str(directory),
               "--backend", variant.backend, "--op-style", "cluster", "--jmp-style", "main",
               "--stop-after", "mb", "--max-steps", str(max_steps)]
    if variant.semantic_passes:
        command.extend(("--semantic-passes", ",".join(variant.semantic_passes)))
    if variant.legacy_arithmetic:
        command.append("--legacy-arithmetic")
    return command


def invoke_worker(task, directory, job, record, variant, max_steps, timeout):
    """A timed-out child has no trustworthy completed VM timing record."""
    command = worker_command(task, directory, job, record, variant, max_steps)
    started = time.perf_counter()
    try:
        child = subprocess.run(command, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"status": "child_timeout", "timeout_seconds": timeout,
                "whole_process_seconds": time.perf_counter() - started}
    result = {"whole_process_seconds": time.perf_counter() - started,
              "returncode": child.returncode}
    if child.returncode:
        return dict(result, status="child_failed", error=child.stderr.decode(errors="replace")[-4000:])
    path = directory / (record + ".json")
    if not path.is_file():
        return dict(result, status="missing_record")
    try:
        raw = json.loads(path.read_text(encoding="utf8"))
    except (ValueError, OSError) as exc:
        return dict(result, status="invalid_record", error=str(exc))
    if not isinstance(raw, dict):
        return dict(result, status="invalid_record")
    return dict(result, status="ok", raw=raw)


RUNTIME_FIELDS = ("run_seconds", "run_cpu_seconds", "execute_seconds", "execute_cpu_seconds", "steps")
METRICS = ("compile_seconds", "compile_cpu_seconds", "compiler_stage_seconds", "compiler_stage_cpu_seconds", "mb_bytes", "mc_bytes", *RUNTIME_FIELDS)
ROW_FIELDS = ("phase", "sequence", "case", "variant", "backend", "repeat", "workload", "status",
              "source_sha256", "stdin_hex", "expected_hex", "expected_input_consumed",
              *METRICS, "compiler_peak_rss_bytes", "runtime_peak_rss_bytes", "mb_sha256",
              "ir_before_operations", "ir_after_operations", "ir_before_bytes", "ir_after_bytes")


def _finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def classify_runtime(outcome, workload):
    status = outcome["status"]
    if status != "ok":
        return {"status": status, "worker": outcome}
    raw = outcome["raw"]
    result = raw.get("result", {})
    if not isinstance(result, dict):
        return {"status": "invalid_record", "partial": raw,
                "worker": {key: value for key, value in outcome.items() if key != "raw"}}
    reason = result.get("stop_reason")
    if reason != "terminated":
        return {"status": reason if isinstance(reason, str) and reason else "invalid_record", "worker": {key: value for key, value in outcome.items() if key != "raw"},
                "partial": raw}
    if raw.get("output_hex") != workload.stdout.hex():
        status = "output_mismatch"
    elif type(result.get("input_consumed")) is not int or result["input_consumed"] != workload.input_consumed:
        status = "input_mismatch"
    elif not raw.get("passed"):
        status = "worker_rejected"
    elif not all(_finite_number(raw.get(name)) for name in (
        "wall_seconds", "cpu_seconds", "execute_seconds", "execute_cpu_seconds"
    )) or type(result.get("steps")) is not int or result["steps"] < 0:
        status = "invalid_record"
    else:
        return {"status": "ok", "runtime": raw,
                "worker": {key: value for key, value in outcome.items() if key != "raw"}}
    return {"status": status, "partial": raw,
            "worker": {key: value for key, value in outcome.items() if key != "raw"}}


def sample_rows(report):
    rows = []
    for sample in report["samples"]:
        compiled = sample.get("compile", {})
        compilation = compiled.get("raw", {}) if compiled.get("status") == "ok" else {}
        image = compilation.get("image", {})
        stages = compilation.get("stages", [])
        structure = compilation.get("structure", {})
        for work in sample["workloads"]:
            runtime = work.get("runtime", {}) if work["status"] == "ok" else {}
            row = {key: sample[key] for key in ("phase", "sequence", "case", "variant", "backend", "repeat", "source_sha256")}
            row.update(workload=work["id"], status=work["status"], stdin_hex=work["stdin_hex"],
                       expected_hex=work["stdout_hex"], expected_input_consumed=work["expected_input_consumed"],
                       compile_seconds=compilation.get("wall_seconds_including_artifact_and_metric_writes"),
                       compile_cpu_seconds=compilation.get("cpu_seconds"),
                       compiler_stage_seconds=sum(stage["seconds"] for stage in stages) if stages else None,
                       compiler_stage_cpu_seconds=sum(stage["cpu_seconds"] for stage in stages) if stages else None,
                       mb_bytes=image.get("bytes"), mb_sha256=image.get("sha256"),
                       mc_bytes=next((stage.get("bytes") for stage in stages if stage["stage"] == "mg2mc"), None),
                       run_seconds=runtime.get("wall_seconds"), run_cpu_seconds=runtime.get("cpu_seconds"),
                       execute_seconds=runtime.get("execute_seconds"), execute_cpu_seconds=runtime.get("execute_cpu_seconds"),
                       steps=runtime.get("result", {}).get("steps"),
                       compiler_peak_rss_bytes=compilation.get("process_peak_rss_bytes"),
                       runtime_peak_rss_bytes=runtime.get("process_peak_rss_bytes"),
                       ir_before_operations=structure.get("semantic_before", {}).get("total_operations"),
                       ir_after_operations=structure.get("semantic_after", {}).get("total_operations"),
                       ir_before_bytes=structure.get("semantic_before", {}).get("ir_bytes"),
                       ir_after_bytes=structure.get("semantic_after", {}).get("ir_bytes"))
            rows.append(row)
    return rows


def summarize_rows(rows):
    groups = defaultdict(list)
    for row in rows:
        if row["phase"] == "measurement":
            groups[(row["case"], row["workload"], row["variant"])].append(row)
    medians, comparisons = [], []
    for (case, workload, variant), samples in sorted(groups.items()):
        complete = [row for row in samples if row["status"] == "ok" and all(_finite_number(row.get(key)) for key in METRICS)]
        summary = {"case": case, "workload": workload, "variant": variant,
                   "requested_repeats": len(samples), "complete_repeats": len(complete),
                   "status_counts": dict(sorted(Counter(row["status"] for row in samples).items()))}
        summary.update({key: statistics.median(row[key] for row in complete) if complete else None for key in METRICS})
        medians.append(summary)
        for baseline in ("semantic_legacy", "semantic_none"):
            if baseline == variant or (case, workload, baseline) not in groups:
                continue
            reference = {row["repeat"]: row for row in groups[(case, workload, baseline)]
                         if row["status"] == "ok" and all(_finite_number(row.get(key)) for key in METRICS)}
            paired = [(row, reference[row["repeat"]]) for row in complete if row["repeat"] in reference]
            comparison = {"case": case, "workload": workload, "variant": variant,
                          "baseline": baseline, "paired_complete_repeats": len(paired)}
            for key in METRICS:
                current = statistics.median(row[key] for row, _ in paired) if paired else None
                previous = statistics.median(row[key] for _, row in paired) if paired else None
                comparison[key + "_ratio"] = current / previous if previous else None
            comparisons.append(comparison)
    return medians, comparisons


def _write_csv(path, rows, fields):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(row[key], sort_keys=True) if isinstance(row.get(key), (dict, list)) else row.get(key)
                             for key in fields})
    temporary.replace(path)


class SourceChanged(RuntimeError):
    pass


class Driver:
    def __init__(self, args, selected_variants):
        self.args, self.variants = args, selected_variants
        self.output = args.output.resolve()
        self.initial = source_fingerprint()
        self.report = {"schema_version": 1, "kind": "semantic_pass_comparison", "run_state": "running",
            "started_unix": time.time(), "active": None, "python": sys.version,
            "source_hashes_at_start": self.initial, "source_changed_during_run": False,
            "method": "Fresh process for each cold compilation and each project-VM input; no compilation cache. One compiled image reused only across a case's inputs, then deleted. Variant order rotates each case and round. Warmups are retained but excluded from medians. OS caches are not flushed; host load/frequency are not controlled. No profiling, native-VM substitution, or aggregate SPEC score.",
            "censoring_policy": "Child timeouts have no VM timing or step result. Bounded unfinished VM records are retained only as partial; complete runtime CSV fields are null. Medians use complete correct workloads only; comparisons pair the same completed repeat IDs. Censored times are never runtime lower bounds.",
            "comparison_policy": "Ratios are variant / baseline: less than one means smaller/faster. Each case/workload is separate. Compilation is shared across inputs and must not be summed across workload rows.",
            "repeats": args.repeats, "warmups": args.warmups,
            "compile_timeout_seconds": args.compile_timeout,
            "style": "cluster/main",
            "image_retention": "discard_after_case_inputs", "oracles": [], "samples": []}
        for planned in schedule(args.cases, args.variants, args.repeats, args.warmups):
            case, variant = CASES[planned["case"]], self.variants[planned["variant"]]
            workloads = []
            for work in case.workloads:
                job = work.job(case.source)
                job.pop("source")
                if args.max_steps is not None:
                    job["max_steps"] = args.max_steps
                if args.runtime_timeout is not None:
                    job["timeout_seconds"] = args.runtime_timeout
                workloads.append(dict(job, status="not_run"))
            self.report["samples"].append(dict(planned, backend=variant.backend,
                semantic_passes=list(variant.semantic_passes), legacy_arithmetic=variant.legacy_arithmetic,
                source_sha256=digest(case.source.encode()), workloads=workloads, compile={"status": "not_run"}))
        measured = [s for s in self.report["samples"] if s["phase"] == "measurement"]
        self.report["requested_program_compiles"] = len(measured)
        self.report["requested_target_runs"] = sum(len(s["workloads"]) for s in measured)

    def save(self):
        rows = sample_rows(self.report)
        self.report["medians"], self.report["comparisons"] = summarize_rows(rows)
        measured = [row for row in rows if row["phase"] == "measurement"]
        self.report["status_counts"] = dict(sorted(Counter(row["status"] for row in measured).items()))
        self.report["warmup_status_counts"] = dict(sorted(Counter(row["status"] for row in rows
            if row["phase"] == "warmup").items()))
        self.report["complete_target_runs"] = sum(row["status"] == "ok" for row in measured)
        self.report["attempted_target_runs"] = sum("worker" in work for sample in self.report["samples"]
            if sample["phase"] == "measurement" for work in sample["workloads"])
        self.report["completed_program_compiles"] = sum(sample["compile"]["status"] == "ok"
            for sample in self.report["samples"] if sample["phase"] == "measurement")
        temporary = self.output / "report.json.tmp"
        temporary.write_text(json.dumps(self.report, indent=2) + "\n", encoding="utf8")
        temporary.replace(self.output / "report.json")
        _write_csv(self.output / "samples.csv", rows, ROW_FIELDS)
        _write_csv(self.output / "medians.csv", self.report["medians"],
                   ("case", "workload", "variant", "requested_repeats", "complete_repeats", "status_counts", *METRICS))
        _write_csv(self.output / "comparisons.csv", self.report["comparisons"],
                   ("case", "workload", "variant", "baseline", "paired_complete_repeats", *(key + "_ratio" for key in METRICS)))

    def check_sources(self):
        current = source_fingerprint()
        if current != self.initial:
            changed = sorted(key for key in set(current) | set(self.initial) if current.get(key) != self.initial.get(key))
            self.report.update(source_changed_during_run=True, source_hashes_at_end=current, changed_paths=changed)
            raise SourceChanged("compiler/VM/benchmark sources changed during the experiment: " + ", ".join(changed))

    def child(self, task, directory, job, record, variant, budget, timeout, source):
        self.check_sources()
        self.report["active"] = {"task": task, "directory": str(directory.relative_to(self.output)),
                                 "record": record, "started_unix": time.time(), "timeout_seconds": timeout}
        self.save()
        result = invoke_worker(task, directory, job, record, variant, budget, timeout)
        self.report["active"] = None
        self.check_sources()
        if result["status"] == "ok":
            raw = result["raw"]
            if raw.get("source_sha256") != digest(source.encode()):
                return dict(result, status="source_mismatch")
            hashes = raw.get("source_hashes")
            if not isinstance(hashes, dict) or not hashes or any(self.initial.get(key) != value for key, value in hashes.items()):
                raise SourceChanged("worker source fingerprint does not match experiment fingerprint")
            if raw.get("profiled"):
                return dict(result, status="profiled_record_rejected")
        return result

    def validate_oracles(self):
        for case_id in self.args.cases:
            case = CASES[case_id]
            for work in case.workloads:
                observation = validate_contract(case, work)
                self.report["oracles"].append(dict(observation, case=case_id, workload=work.id,
                    source_sha256=digest(case.source.encode()), method="CPython with byte I/O hooks, fixed expected output/input consumption"))
                self.save()
                if not observation["passed"]:
                    raise ValueError("fixed CPython oracle failed for " + case_id + "/" + work.id)

    def sample(self, sample):
        case, variant = CASES[sample["case"]], self.variants[sample["variant"]]
        directory = self.output / ("{:04d}-{}-{}-{}".format(sample["sequence"], sample["phase"], case.id, variant.id))
        directory.mkdir()
        (directory / "source.py").write_text(case.source, encoding="utf8")
        image = directory / "program.mb"
        sample["started_unix"] = time.time()
        try:
            for work in sample["workloads"]:
                (directory / ("job-" + work["id"] + ".json")).write_text(
                    json.dumps(dict(work, source=case.source)), encoding="utf8")
            first = sample["workloads"][0]
            compiled = self.child("compile", directory, directory / ("job-" + first["id"] + ".json"),
                                  "compile", variant, first["max_steps"], self.args.compile_timeout, case.source)
            if compiled["status"] == "ok":
                raw = compiled["raw"]
                image_record = raw.get("image", {})
                sha = image_record.get("sha256") if isinstance(image_record, dict) else None
                valid = (isinstance(image_record, dict) and isinstance(raw.get("structure", {}), dict)
                         and image.is_file() and image_record.get("bytes") == image.stat().st_size and image.stat().st_size > 0
                         and isinstance(sha, str) and len(sha) == 64 and all(char in "0123456789abcdef" for char in sha)
                         and all(_finite_number(raw.get(key)) for key in ("wall_seconds_including_artifact_and_metric_writes", "cpu_seconds"))
                         and isinstance(raw.get("stages"), list) and bool(raw["stages"])
                         and all(isinstance(stage, dict) and isinstance(stage.get("stage"), str)
                                 and _finite_number(stage.get("seconds")) and _finite_number(stage.get("cpu_seconds"))
                                 for stage in raw["stages"])
                         and any(stage["stage"] == "mg2mc" and _finite_number(stage.get("bytes")) for stage in raw["stages"]))
                if not valid:
                    compiled = dict(compiled, status="invalid_record")
            sample["compile"] = compiled
            self.save()
            for work, contract in zip(sample["workloads"], case.workloads):
                if compiled["status"] != "ok":
                    work["status"] = "compile_" + compiled["status"]
                else:
                    outcome = self.child("runtime", directory, directory / ("job-" + work["id"] + ".json"),
                                         "runtime-" + work["id"], variant, work["max_steps"], work["timeout_seconds"], case.source)
                    work.update(classify_runtime(outcome, contract))
                self.save()
        finally:
            if image.exists():
                image.unlink()
            sample["image_retained"] = False
            sample["finished_unix"] = time.time()
            self.save()
        print(f"{sample['phase']} {sample['repeat']} {case.id} {variant.id}: "
              + ", ".join(work["id"] + "=" + work["status"] for work in sample["workloads"]), flush=True)

    def run(self):
        from scripts import benchmark_pipeline

        if self.output.exists() and (not self.output.is_dir() or any(self.output.iterdir())):
            raise ValueError("use a new empty output directory to preserve earlier results")
        self.check_sources()
        self.output.mkdir(parents=True, exist_ok=True)
        self.report["hardware"] = benchmark_pipeline.hardware_environment()
        self.save()
        code = 0
        try:
            self.validate_oracles()
            for sample in self.report["samples"]:
                self.sample(sample)
            self.check_sources()
            failed = any(work["status"] != "ok" for sample in self.report["samples"] for work in sample["workloads"])
            self.report["run_state"] = "complete_with_failures" if failed else "complete"
            code = int(failed)
        except SourceChanged as exc:
            self.report.update(run_state="aborted_source_changed", source_changed_during_run=True, error=str(exc))
            code = 2
        except KeyboardInterrupt:
            self.report.update(run_state="interrupted", error="interrupted by user")
            code = 130
        except (ValueError, OSError) as exc:
            self.report.update(run_state="aborted", error=str(exc))
            code = 2
        finally:
            self.report["active"] = None
            self.report["source_hashes_at_end"] = source_fingerprint()
            self.report["finished_unix"] = time.time()
            self.report["all_requested_samples_passed"] = self.report["run_state"] == "complete"
            self.save()
        print("Results: " + str(self.output / "report.json"), flush=True)
        return code


def main(argv=None):
    args = parse_args(argv)
    if args.list:
        for case in CASES.values():
            print(case.id + (" [slow]" if case.slow else "") + ": " + ",".join(work.id for work in case.workloads))
        print("Variants: " + ",".join(VARIANT_NAMES))
        return 0
    try:
        selected = variants()
        return Driver(args, selected).run()
    except (ValueError, RuntimeError, ImportError, OSError) as exc:
        print("benchmark error: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
