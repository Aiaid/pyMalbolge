"""Measure guarded ARM64 JIT cold/warm execution on identical accepted images.

Build the extension first. Example (output directory must not exist)::

    uv run --no-sync python scripts/benchmark_native_jit.py --output-dir /tmp/mb-jit

Default cases are four existing Nagoya fixtures plus a separately labeled
million-NOP/self-modification control. Every mode uses a fresh child process.
Cold JIT totals include code emission; warm JIT records bounded fresh-memory
warmup rounds until a pass emits no code before timing another fresh memory.
All training costs remain visible. Fixture fallback time is not JIT speed.
"""

import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import time

import benchmark_native_vm as baseline

ROOT = baseline.ROOT
ENGINES = ("python", "native", "jit_cold", "jit_warm", "nagoya_c")
STATS_COUNTERS = ("compiled_blocks", "compiled_bytes", "jit_blocks", "jit_steps",
                  "guard_failures", "fallback_steps", "cache_entries", "cache_code_bytes",
                  "cache_mapped_bytes")
EMISSION_CLOCKS = ("compile_cpu_seconds", "compile_wall_seconds")


def source_hashes():
    hashes = baseline.source_hashes()
    for name in ("malbolge/_native_jit.h", "scripts/benchmark_native_jit.py"):
        hashes[name] = baseline.digest((ROOT / name).read_bytes())
    return hashes


def snapshot_stats(memory):
    stats = dict(memory.jit_stats())
    for key in STATS_COUNTERS:
        if type(stats.get(key)) is not int or stats[key] < 0:
            raise RuntimeError("missing or invalid JIT counter: " + key)
    for key in EMISSION_CLOCKS:
        value = stats.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise RuntimeError("missing or invalid JIT emission clock: " + key)
    for key in ("enabled", "available"):
        if type(stats.get(key)) is not bool:
            raise RuntimeError("missing or invalid JIT flag: " + key)
    return stats


def worker(args):
    sys.path.insert(0, str(ROOT))
    from malbolge.core import MalbolgeConfig, SparseMemory, parse_source, run_memory
    if platform.python_implementation() != "CPython":
        raise RuntimeError("this comparison requires CPython")
    sources = source_hashes()
    native_mode = args.worker != "python"
    jit_mode = args.worker in ("jit_cold", "jit_warm")
    extension_hash = extension_path = None
    if native_mode:
        from malbolge import native
        import malbolge._native_vm as extension
        extension_path = str(extension.__file__)
        extension_hash = baseline.digest(Path(extension_path).read_bytes())
    config = MalbolgeConfig.malbolge20()
    source = args.image.read_bytes()
    data = bytes.fromhex(args.input_hex)
    prep_wall, prep_cpu = time.perf_counter(), time.process_time()
    cells = parse_source(source, config)

    def new_memory():
        if native_mode:
            return native.NativeMemory(cells)
        memory = SparseMemory(config)
        memory.initialize_source(cells)
        return memory

    def execute(memory):
        if native_mode:
            return native.run_memory(memory, data, max_steps=args.max_steps,
                                     max_output=args.max_output, eof="sentinel", jit=jit_mode)
        return run_memory(memory, config, data, max_steps=args.max_steps,
                          max_output=args.max_output, eof="sentinel")

    memory = new_memory()
    prepared_cpu, prepared_wall = time.process_time(), time.perf_counter()
    initial_stats = snapshot_stats(memory) if native_mode else None
    if jit_mode and any(initial_stats[key] for key in ("cache_entries", "cache_code_bytes")):
        raise RuntimeError("fresh child JIT code cache is not empty before its first execution")
    warmup = None
    warmup_rounds = []
    warmup_total = None
    if args.worker == "jit_warm":
        phase_wall_start, phase_cpu_start = time.perf_counter(), time.process_time()
        # Cache shape promotion may need several full traversals. Each round
        # uses fresh VM memory and is retained; never hide training cost.
        for round_index in range(args.max_warmup_runs):
            if round_index:
                memory = new_memory()
            wall_start, cpu_start = time.perf_counter(), time.process_time()
            warm_result = execute(memory)
            cpu_end, wall_end = time.process_time(), time.perf_counter()
            warmup = {"round": round_index + 1,
                      "execute_cpu_seconds": cpu_end - cpu_start,
                      "execute_wall_seconds": wall_end - wall_start,
                      "result": warm_result.to_dict(), "jit_stats": snapshot_stats(memory),
                      "memory": baseline.canonical_memory(memory, "native")}
            warmup_rounds.append(warmup)
            stats = warmup["jit_stats"]
            if not stats["compiled_blocks"] and not any(stats[k] for k in EMISSION_CLOCKS):
                break
        else:
            raise RuntimeError("JIT cache did not stabilize within --max-warmup-runs")
        warmup_total = {
            "rounds": len(warmup_rounds),
            "phase_cpu_seconds": time.process_time() - phase_cpu_start,
            "phase_wall_seconds": time.perf_counter() - phase_wall_start,
            "execute_cpu_seconds": sum(r["execute_cpu_seconds"] for r in warmup_rounds),
            "execute_wall_seconds": sum(r["execute_wall_seconds"] for r in warmup_rounds),
            "compile_cpu_seconds": sum(r["jit_stats"]["compile_cpu_seconds"] for r in warmup_rounds),
            "compile_wall_seconds": sum(r["jit_stats"]["compile_wall_seconds"] for r in warmup_rounds),
            "compiled_blocks": sum(r["jit_stats"]["compiled_blocks"] for r in warmup_rounds),
            "compiled_bytes": sum(r["jit_stats"]["compiled_bytes"] for r in warmup_rounds)}
        init_wall, init_cpu = time.perf_counter(), time.process_time()
        memory = new_memory()
        warmup["fresh_memory_prepare_cpu_seconds"] = time.process_time() - init_cpu
        warmup["fresh_memory_prepare_wall_seconds"] = time.perf_counter() - init_wall
    if args.bounded:
        result = execute(memory)
        clocks = {}
    else:
        wall_start, cpu_start = time.perf_counter(), time.process_time()
        result = execute(memory)  # Native RunResult conversion/emission are included.
        cpu_end, wall_end = time.process_time(), time.perf_counter()
        clocks = {"execute_cpu_seconds": cpu_end - cpu_start,
                  "execute_wall_seconds": wall_end - wall_start}
    stats = snapshot_stats(memory) if native_mode else None
    sample = dict(clocks, result=result.to_dict(), memory=baseline.canonical_memory(memory, args.worker),
                  prepare_cpu_seconds=prepared_cpu - prep_cpu,
                  prepare_wall_seconds=prepared_wall - prep_wall,
                  python=sys.version, executable=sys.executable, implementation=platform.python_implementation(),
                  source_hashes=sources, image_sha256=baseline.digest(source),
                  extension_sha256=extension_hash, extension_path=extension_path,
                  host_byte_order=sys.byteorder, initial_jit_stats=initial_stats,
                  jit_stats=stats, warmup=warmup,
                  warmup_rounds=warmup_rounds, warmup_total=warmup_total,
                  cache_protocol="fresh child, import and memory initialization only before first run")
    if source_hashes() != sources or (native_mode and baseline.digest(Path(extension_path).read_bytes()) != extension_hash):
        raise RuntimeError("VM/JIT source or binary changed during worker")
    print(json.dumps(sample), flush=True)


def spawn_worker(args, engine, case, bounded=False):
    command = [args.uv, "run", "--offline", "--no-sync"]
    if args.python:
        command += ["--python", args.python]
    command += ["python", str(Path(__file__).resolve()), "--worker", engine,
                "--image", case["image"], "--input-hex", case["input_hex"],
                "--max-warmup-runs", str(args.max_warmup_runs)]
    if bounded:
        command += ["--bounded", "--max-steps", str(args.gate_max_steps),
                    "--max-output", str(args.gate_max_output)]
    environment = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME", "LD_PRELOAD", "DYLD_INSERT_LIBRARIES"):
        environment.pop(key, None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["UV_CACHE_DIR"] = str(args.output_dir / "uv-cache")
    completed = subprocess.run(command, input=b"", capture_output=True, cwd=ROOT,
                               env=environment, timeout=args.timeout)
    if completed.returncode:
        raise RuntimeError("%s worker failed: %s" % (engine, completed.stderr.decode("utf-8", errors="replace")))
    return json.loads(completed.stdout)


def probe_capability(args):
    """Use a separate child so capability probes cannot prewarm timed caches."""
    command = [args.uv, "run", "--offline", "--no-sync"]
    if args.python:
        command += ["--python", args.python]
    command += ["python", str(Path(__file__).resolve()), "--probe"]
    environment = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME", "LD_PRELOAD", "DYLD_INSERT_LIBRARIES"):
        environment.pop(key, None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["UV_CACHE_DIR"] = str(args.output_dir / "uv-cache")
    completed = subprocess.run(command, capture_output=True, cwd=ROOT, env=environment, timeout=args.timeout)
    if completed.returncode:
        raise RuntimeError("JIT capability probe failed: " + completed.stderr.decode("utf-8", errors="replace"))
    probe = json.loads(completed.stdout)
    if not probe["available"]:
        raise RuntimeError("actual machine-code JIT is unavailable on this host/build")
    return probe


def check_sample(sample, engine, case, reference, sources, memory, runtime=None):
    baseline.check_result(sample, case, reference, sources, memory)
    if runtime:
        if sample["python"] != runtime["python"] or sample["executable"] != runtime["executable"]:
            raise RuntimeError("worker CPython runtime changed during comparison")
        if engine != "python" and sample["extension_sha256"] != runtime["native_extension_sha256"]:
            raise RuntimeError("native/JIT binary changed during comparison")
    if engine in ("jit_cold", "jit_warm"):
        stats = sample["jit_stats"]
        if not stats["available"] or not stats["enabled"]:
            raise RuntimeError("requested JIT was unavailable or disabled")
        if stats["jit_steps"] + stats["fallback_steps"] != reference["steps"]:
            raise RuntimeError("JIT/fallback counters do not account for executed steps")
        if engine == "jit_warm":
            warmup = sample["warmup"]
            for warmed in sample["warmup_rounds"]:
                baseline.check_result(dict(warmed, source_hashes=sources, image_sha256=case["image_sha256"]),
                                      case, reference, sources, memory)
                counted = warmed["jit_stats"]
                if counted["jit_steps"] + counted["fallback_steps"] != reference["steps"]:
                    raise RuntimeError("warmup round lost instruction accounting")
            if stats["compiled_blocks"] or any(stats[key] != 0 for key in EMISSION_CLOCKS):
                raise RuntimeError("warm run emitted new code; it is not an accepted warmed sample")
            # A populated cache can translate short prefixes that fell back
            # before the warmup emitted their shape. Partitioning may change;
            # architectural results/pages and zero new emission define parity.
        if case["kind"] == "synthetic_nop_self_modification_control" and stats["jit_steps"] <= 0:
            raise RuntimeError("control executed no actual translated machine-code steps")
    elif engine == "native" and sample["jit_stats"]["enabled"]:
        raise RuntimeError("plain native mode unexpectedly enabled JIT")


def metric(values):
    return {"median": statistics.median(values), "min": min(values), "max": max(values)}


def summarize(runs, steps):
    result = {}
    for engine in ENGINES:
        samples = [run for run in runs if run["engine"] == engine]
        row = {key: metric([sample[key] for sample in samples])
               for key in ("execute_cpu_seconds", "execute_wall_seconds")}
        cpu = row["execute_cpu_seconds"]["median"]
        row["steps_per_cpu_second"] = steps / cpu if cpu > 0 else None
        if engine in ("jit_cold", "jit_warm"):
            row["jit_stats"] = {key: metric([sample["jit_stats"][key] for sample in samples])
                                for key in STATS_COUNTERS + EMISSION_CLOCKS}
            row["coverage"] = metric([sample["jit_stats"]["jit_steps"] / steps for sample in samples])
            row["jit_execution_observed"] = row["coverage"]["max"] > 0
            row["jit_coverage_zero"] = row["coverage"]["max"] == 0
            row["interpretation"] = ("actual translated NOP steps plus fallback" if row["coverage"]["min"] > 0
                                     else "no translated steps in at least one sample; no JIT speed claim")
            if engine == "jit_warm":
                row["last_warmup_round"] = {key: metric([sample["warmup"][key] for sample in samples])
                                 for key in ("execute_cpu_seconds", "execute_wall_seconds")}
                row["last_warmup_round"]["jit_stats"] = {
                    key: metric([sample["warmup"]["jit_stats"][key] for sample in samples])
                    for key in STATS_COUNTERS + EMISSION_CLOCKS}
                row["last_warmup_round"]["fresh_memory_prepare_cpu_seconds"] = metric([
                    sample["warmup"]["fresh_memory_prepare_cpu_seconds"] for sample in samples])
                row["last_warmup_round"]["fresh_memory_prepare_wall_seconds"] = metric([
                    sample["warmup"]["fresh_memory_prepare_wall_seconds"] for sample in samples])
                row["warmup_total"] = {
                    key: metric([sample["warmup_total"][key] for sample in samples])
                    for key in ("rounds", "phase_cpu_seconds", "phase_wall_seconds",
                                "execute_cpu_seconds", "execute_wall_seconds",
                                "compile_cpu_seconds", "compile_wall_seconds",
                                "compiled_blocks", "compiled_bytes")}
        result[engine] = row
    # Ratios describe complete clocks. Coverage remains adjacent to the ratio.
    for engine in ("jit_cold", "jit_warm"):
        native_cpu = result["native"]["execute_cpu_seconds"]["median"]
        jit_cpu = result[engine]["execute_cpu_seconds"]["median"]
        result[engine]["native_over_total_cpu_ratio"] = (native_cpu / jit_cpu
            if jit_cpu > 0 and result[engine]["coverage"]["min"] > 0 else None)
    return result


def native_build_receipt(args, sample, sources):
    candidates = ([args.native_build_receipt] if args.native_build_receipt else
                  sorted((ROOT / "build/native-vm").glob("*/build.json")))
    required = {name: sources[name] for name in ("malbolge/_native_vm.c", "malbolge/_native_jit.h")}
    for path in candidates:
        data = path.read_bytes()
        receipt = json.loads(data)
        hashes = receipt.get("source_hashes", {})
        if (receipt.get("binary_sha256") == sample["extension_sha256"] and
                all(hashes.get(name) == value for name, value in required.items()) and
                Path(receipt.get("binary", "")).resolve() == Path(sample["extension_path"]).resolve()):
            (args.output_dir / "native-build.json").write_bytes(data)
            return {"status": "matched", "receipt": receipt, "receipt_sha256": baseline.digest(data)}
    raise RuntimeError("no matching native/JIT build receipt; rebuild with scripts/build_native_vm.py")


def compare(args):
    args.output_dir = args.output_dir.resolve()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    report_path = args.output_dir / "report.json"
    report = {"schema_version": 1, "status": "preparing", "engines": list(ENGINES),
              "repeats": args.repeats, "platform": platform.platform(), "machine": platform.machine(),
              "host_byte_order": sys.byteorder, "parent_python": sys.version, "python_selector": args.python,
              "load_before": baseline.load_snapshot(), "samples": [],
              "gate_max_steps": args.gate_max_steps, "gate_max_output": args.gate_max_output,
              "child_timeout_seconds": args.timeout,
              "method": "Identical images; five cyclic serial fresh children per repetition. Preload/validate/initialize outside clocks. Cold total includes machine-code emission and all JIT dispatch/guards/fallback/wrapper work. Warm child records full warmup with separate memory and then times another fresh memory, requiring zero new emission. No emission time subtracted. Final page/receipt inspections outside clocks. C exec unchanged and final stdout flush outside clocks. Separate bounded reference gate supplies no timing. Actual translated steps and fallback are reported; short fixture/synthetic results are exploratory."}
    baseline.write_json(report_path, report)
    try:
        sources = source_hashes()
        report["source_hashes"] = sources
        report["capability_probe"] = probe_capability(args)
        snapshot = args.output_dir / "verify_mb_reference_snapshot.py"
        snapshot.write_bytes((ROOT / "scripts/verify_mb_reference.py").read_bytes())
        spec = importlib.util.spec_from_file_location("jit_reference_gate", snapshot)
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        binary, build = baseline.timed_reference(baseline.REFERENCE, args.output_dir)
        report["nagoya_timing_build"] = build
        gate_binary, gate_manifest = gate.build_reference_gate(baseline.REFERENCE, args.output_dir / "correctness-only")
        report["reference_gate_build"] = gate_manifest
        names = args.cases or list(baseline.FIXTURES) + ["linear_nop_1m"]
        cases = baseline.make_cases(names, args.output_dir)
        report["cases"] = cases
        report["status"] = "running"
        baseline.write_json(report_path, report)
        print("Prepared pinned Nagoya timing copy and independent correctness gate.", flush=True)
        runtime = None
        for case in cases:
            record = {"case": case, "status": "unvalidated", "runs": [], "correctness": {}}
            report["samples"].append(record)
            try:
                reference = gate.verify_image(gate_binary, Path(case["image"]), bytes.fromhex(case["input_hex"]),
                                              bytes.fromhex(case["expected_output_hex"]), case["expected_consumed"],
                                              args.gate_max_steps, args.gate_max_output, args.timeout)
                record["reference_correctness"] = reference
                if not reference["gate_pass"]:
                    raise RuntimeError("reference correctness gate rejected image: " + reference["reason"])
                python_gate = spawn_worker(args, "python", case, bounded=True)
                check_sample(python_gate, "python", case, reference, sources, None, runtime)
                record["correctness"]["python"] = python_gate
                for engine in ("native", "jit_cold", "jit_warm"):
                    sample = spawn_worker(args, engine, case, bounded=True)
                    candidate_runtime = {"python": sample["python"], "implementation": sample["implementation"],
                                         "executable": sample["executable"], "native_extension_path": sample["extension_path"],
                                         "native_extension_sha256": sample["extension_sha256"]}
                    if runtime is not None and runtime != candidate_runtime:
                        raise RuntimeError("native/JIT runtime changed between gates")
                    runtime = candidate_runtime
                    if python_gate["python"] != runtime["python"] or python_gate["executable"] != runtime["executable"]:
                        raise RuntimeError("Python/native/JIT workers use different CPython runtimes")
                    check_sample(sample, engine, case, reference, sources, python_gate["memory"], runtime)
                    record["correctness"][engine] = sample
                report["worker_runtime"] = runtime
                if "native_build" not in report:
                    report["native_build"] = native_build_receipt(args, record["correctness"]["native"], sources)
                print("%s: all correctness gates accepted (%d steps)." % (case["name"], reference["steps"]), flush=True)
                for repetition in range(args.repeats):
                    offset = repetition % len(ENGINES)
                    order = ENGINES[offset:] + ENGINES[:offset]
                    for engine in order:
                        if engine == "nagoya_c":
                            completed = subprocess.run([str(binary), case["image"]],
                                                       input=bytes.fromhex(case["input_hex"]), capture_output=True,
                                                       cwd=args.output_dir, timeout=args.timeout)
                            if completed.returncode or completed.stdout.hex() != case["expected_output_hex"]:
                                raise RuntimeError("timed Nagoya failed or output differs")
                            lines = completed.stderr.decode("utf-8", errors="replace").splitlines()
                            if len(lines) != 1 or not lines[0].startswith(baseline.CLOCK_PREFIX):
                                raise RuntimeError("missing/malformed Nagoya clock receipt")
                            sample = json.loads(lines[0][len(baseline.CLOCK_PREFIX):])
                        else:
                            sample = spawn_worker(args, engine, case)
                            check_sample(sample, engine, case, reference, sources, python_gate["memory"], runtime)
                        for key in ("execute_cpu_seconds", "execute_wall_seconds"):
                            if type(sample[key]) not in (int, float) or not math.isfinite(sample[key]) or sample[key] < 0:
                                raise RuntimeError("invalid execution clock receipt")
                        sample.update(engine=engine, repetition=repetition, order=list(order), status="accepted")
                        record["runs"].append(sample)
                    baseline.write_json(report_path, report)
                record["summary"] = summarize(record["runs"], reference["steps"])
                record["status"] = "accepted"
                print("%s: accepted %d timed runs per mode." % (case["name"], args.repeats), flush=True)
            except subprocess.TimeoutExpired:
                record.update(status="child_timeout", error="whole-child timeout; no clocks or speed inferred")
            except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
                record.update(status="failed", error=str(exc))
            baseline.write_json(report_path, report)
        stability = {
            "sources": source_hashes() == sources,
            "reference": baseline.digest(baseline.REFERENCE.read_bytes()) == baseline.SOURCE_SHA256,
            "images": all(baseline.digest(Path(case["image"]).read_bytes()) == case["image_sha256"] and
                (case["original_image"] is None or baseline.digest(Path(case["original_image"]).read_bytes()) == case["image_sha256"])
                for case in cases),
            "timed_reference_binary": baseline.digest(binary.read_bytes()) == build["binary_sha256"],
            "timed_reference_source": baseline.digest((args.output_dir / "nagoya-exec-clock.c").read_bytes()) == build["timed_source_sha256"],
            "native_binary": runtime is not None and baseline.digest(Path(runtime["native_extension_path"]).read_bytes()) == runtime["native_extension_sha256"]}
        report["stability"] = stability
        if not all(stability.values()):
            for record in report["samples"]:
                record.pop("summary", None)
                record["runs"] = []
                record.update(status="invalidated", error="source/image/binary changed during comparison")
        controls = [record for record in report["samples"] if record["case"]["kind"] == "synthetic_nop_self_modification_control"]
        report["actual_jit_control_pass"] = (all(record["status"] == "accepted" for record in controls)
                                              if controls else None)
        report["control_status"] = ("accepted" if report["actual_jit_control_pass"] else "failed") if controls else "not_selected"
        all_jit_runs = []
        for record in report["samples"]:
            jit_runs = [sample for sample in record["runs"] if sample["engine"] in ("jit_cold", "jit_warm")]
            record["jit_execution_observed"] = any(sample["jit_stats"]["jit_steps"] > 0 for sample in jit_runs)
            record["jit_coverage_zero"] = (not record["jit_execution_observed"]) if jit_runs else None
            all_jit_runs.extend(jit_runs)
        report["jit_execution_observed"] = any(sample["jit_stats"]["jit_steps"] > 0 for sample in all_jit_runs)
        report["jit_coverage_zero"] = (not report["jit_execution_observed"]) if all_jit_runs else None
        report["status"] = ("accepted" if all(stability.values()) and
                            all(record["status"] == "accepted" for record in report["samples"]) else "failed")
    except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError, ImportError) as exc:
        report.update(status="failed", error=str(exc))
    finally:
        report["load_after"] = baseline.load_snapshot()
        baseline.write_json(report_path, report)
    print("Report: %s (%s)" % (report_path, report["status"]), flush=True)
    return 0 if report["status"] == "accepted" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", type=Path, help="new evidence directory; must not exist")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--cases", nargs="+", choices=list(baseline.FIXTURES) + ["linear_nop_1m"])
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--max-warmup-runs", type=int, default=12,
                        help="fresh-memory warmup runs until a pass emits no code")
    parser.add_argument("--gate-max-steps", type=int, default=2_000_000)
    parser.add_argument("--gate-max-output", type=int, default=4096)
    parser.add_argument("--python", help="optional uv CPython selector; extension must match ABI")
    parser.add_argument("--native-build-receipt", type=Path)
    parser.add_argument("--uv", default=shutil.which("uv"))
    parser.add_argument("--worker", choices=ENGINES[:-1], help=argparse.SUPPRESS)
    parser.add_argument("--image", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--input-hex", default="", help=argparse.SUPPRESS)
    parser.add_argument("--bounded", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--max-steps", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--max-output", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--probe", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.max_warmup_runs <= 32:
        parser.error("--max-warmup-runs must be between 1 and 32")
    if args.probe:
        sys.path.insert(0, str(ROOT))
        from malbolge import native
        print(json.dumps({"available": bool(native.jit_available()), "python": sys.version,
                          "protocol": "separate capability child; no timed worker cache reuse"}), flush=True)
        return 0
    if args.worker:
        if args.image is None:
            parser.error("worker requires --image")
        worker(args)
        return 0
    if args.output_dir is None or not args.uv:
        parser.error("--output-dir and an available uv are required")
    if args.repeats < 1 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--repeats must be >=1 and --timeout finite and positive")
    if args.gate_max_steps < 1 or args.gate_max_output < 1:
        parser.error("gate budgets must be positive")
    if args.cases and len(set(args.cases)) != len(args.cases):
        parser.error("case names must be unique")
    if args.output_dir.exists():
        parser.error("--output-dir exists; choose a fresh directory")
    return compare(args)


if __name__ == "__main__":
    sys.exit(main())
