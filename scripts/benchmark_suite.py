"""Small fixed-workload driver sharing the pipeline's measurement functions."""

import csv
import json
import math
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import time


def load_manifest(path):
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding="utf8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("programs"), list):
        raise ValueError("expected benchmark manifest schema_version 1 and programs list")
    programs, seen = [], set()
    for item in data["programs"]:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("program requires a source path")
        program = dict(item)
        name = program.get("id", "")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", name) or name in seen:
            raise ValueError("program IDs must be unique lowercase identifiers")
        seen.add(name)
        if program.get("tier") not in ("smoke", "standard", "stress"):
            raise ValueError("invalid benchmark tier for " + name)
        source = (path.parent / program["path"]).resolve()
        program["source"] = source.read_text(encoding="utf8")
        program["source_path"] = str(source)
        workloads, ids = program.get("workloads"), set()
        if not isinstance(workloads, list) or not workloads:
            raise ValueError("program requires at least one workload: " + name)
        for work in workloads:
            if not isinstance(work, dict):
                raise ValueError("invalid workload for " + name)
            identifier = work.get("id", "")
            if not isinstance(identifier, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", identifier) or identifier in ids:
                raise ValueError("workload IDs must be unique lowercase identifiers: " + name)
            ids.add(identifier)
            for field in ("stdin", "stdout"):
                if not isinstance(work.get(field), str) or not work[field].isascii():
                    raise ValueError("workload input/output must be ASCII text: " + name)
            if type(work.get("max_steps")) is not int or work["max_steps"] < 0:
                raise ValueError("workload requires a nonnegative step budget: " + name)
            consumed = work.get("expected_input_consumed")
            if consumed is not None and (type(consumed) is not int or
                                         not 0 <= consumed <= len(work["stdin"].encode("ascii"))):
                raise ValueError("invalid expected_input_consumed for " + name)
            timeout = work.get("timeout_seconds")
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
                raise ValueError("workload requires a positive timeout: " + name)
        programs.append(program)
    return path, programs


def run_manifest(args, pipeline):
    path, programs = load_manifest(args.manifest or pipeline.ROOT / "benchmarks/manifest.json")
    if args.cases:
        unknown = set(args.cases) - {p["id"] for p in programs}
        if unknown:
            raise ValueError("unknown benchmark programs: " + ", ".join(sorted(unknown)))
        programs = [p for p in programs if p["id"] in args.cases]
    else:
        tiers = {"smoke"} if (args.suite or "smoke") == "smoke" else {"smoke", "standard"}
        if args.suite == "all" or (args.list and args.suite is None):
            tiers.add("standard")
            tiers.add("stress")
        programs = [p for p in programs if p["tier"] in tiers]
    if args.list:
        for program in programs:
            print("{}\t{}\t{}\t{}".format(program["id"], program["tier"],
                  ",".join(w["id"] for w in program["workloads"]), program.get("description", "")))
        return 0
    if args.repeats < 1 or not math.isfinite(args.timeout) or args.timeout <= 0:
        raise ValueError("provide positive --repeats/--timeout")
    if args.max_steps is not None and args.max_steps < 0:
        raise ValueError("--max-steps must be nonnegative")
    if args.runtime and args.stop_after != "mb":
        raise ValueError("--runtime requires --stop-after mb")
    if args.trace and not args.runtime:
        raise ValueError("--trace requires --runtime")
    if args.workloads:
        available = {w["id"] for p in programs for w in p["workloads"]}
        if set(args.workloads) - available:
            raise ValueError("unknown workload ID")
        programs = [dict(p, workloads=[w for w in p["workloads"] if w["id"] in args.workloads])
                    for p in programs]
        programs = [p for p in programs if p["workloads"]]
    if not programs:
        raise ValueError("no benchmark programs selected")
    output = (args.output_dir.resolve() if args.output_dir is not None
              else Path(tempfile.mkdtemp(prefix="pymalbolge-bench-")))
    if output.exists() and any(output.iterdir()):
        raise ValueError("use a new empty output directory to preserve earlier results")
    output.mkdir(parents=True, exist_ok=True)
    hardware = pipeline.hardware_environment()
    if args.hardware_info:
        supplied = json.loads(args.hardware_info.read_text(encoding="utf8"))
        if not isinstance(supplied, dict):
            raise ValueError("hardware info must be a JSON object")
        hardware.update(supplied)
    report = {"schema_version": 2, "mode": "benchmark" if args.stop_after == "mb" else "lowering_check",
              "selection": pipeline.selection_metadata(args),
              "runner_sha256": pipeline.digest(Path(pipeline.__file__).read_bytes()),
              "suite_runner_sha256": pipeline.digest(Path(__file__).read_bytes()),
              "manifest_sha256": pipeline.digest(path.read_bytes()),
              "python": sys.version,
              "platform": " ".join((platform.system(), platform.release(), platform.machine())),
              "source_hashes_at_start": pipeline.fingerprint(), "profiled": args.profile,
              "method": "One cold compilation per program/backend/style/repeat, shared by its fixed input workloads. Each compilation, CPython oracle and VM execution uses a fresh child process. No compilation cache. VM phases exclude process startup; whole-process times include it. RSS is cumulative per-process peak, not a stage-local allocation. No filesystem cache flush or formal aggregate score.",
              "samples": []}
    report["hardware"] = hardware
    report["timing_policy"] = {"wall_clock": "time.perf_counter: elapsed time, including waiting/preemption",
                               "cpu_clock": "time.process_time: CPU used by this process, excluding waiting/preemption",
                               "background_load_controlled": False, "frequency_and_thermal_controlled": False,
                               "hardware_normalized": False, "repetitions": args.repeats,
                               "note": "CPU time still depends on hardware, frequency, temperature, cache and shared-memory pressure. Load averages are not CPU percentages. Single-pass timings are preliminary; compare repeated interleaved medians on a quiet same-machine environment for stronger claims."}
    if args.hardware_info:
        report["hardware_info_sha256"] = pipeline.digest(args.hardware_info.read_bytes())
    report.update(run_state="running", active=None, started_unix=time.time(),
                  requested_program_compiles=len(programs) * len(args.backends) * len(args.styles) * args.repeats,
                  requested_target_runs=(sum(len(p["workloads"]) for p in programs) * len(args.backends) * len(args.styles) * args.repeats if args.runtime else 0),
                  image_retention="discard_after_workloads" if args.discard_images else "keep")
    rows, failed = [], False
    fields = ["program", "backend", "style", "target_pipeline", "ir_frontend", "repeat", "workload", "status",
              "compile_seconds", "compile_cpu_seconds", "compiler_stage_seconds", "mb_bytes", "mc_bytes", "run_seconds",
              "run_cpu_seconds", "steps", "execute_seconds", "execute_cpu_seconds", "execute_cpu_wall_ratio", "steps_per_second",
              "cpython_code_seconds", "cpython_code_cpu_seconds", "peak_rss_bytes"]

    def save():
        report["completed_program_compiles"] = sum("compile" in s for s in report["samples"])
        report["attempted_target_runs"] = sum("runtime" in w for s in report["samples"] for w in s["workloads"])
        report["completed_target_runs"] = sum(
            w.get("runtime", {}).get("result", {}).get("stop_reason") == "terminated"
            for s in report["samples"] for w in s["workloads"])
        report["passed_target_runs"] = sum(w.get("runtime", {}).get("passed", False) for s in report["samples"] for w in s["workloads"])
        temporary = output / "report.json.tmp"
        temporary.write_text(json.dumps(report, indent=2) + "\n")
        temporary.replace(output / "report.json")
        with (output / "summary.csv").open("w", newline="", encoding="utf8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def child(task, directory, job, record, backend, style, budget, timeout, runtime_record=None):
        command = [sys.executable, str(Path(pipeline.__file__).resolve()), "--worker", task,
                   "--job", str(job), "--record", record, "--directory", str(directory),
                   "--backend", backend, "--op-style", style.split("/")[0],
                   "--jmp-style", style.split("/")[1], "--stop-after", args.stop_after,
                   "--max-steps", str(budget)]
        command.extend(pipeline.selection_arguments(args))
        if args.profile and task != "oracle":
            command.append("--profile")
        if getattr(args, "semantic_passes", None) is not None:
            command.extend(["--semantic-passes", args.semantic_passes])
        if getattr(args, "legacy_arithmetic", False):
            command.append("--legacy-arithmetic")
        if runtime_record:
            command.extend(["--runtime-record", runtime_record])
        started = time.perf_counter()
        report["active"] = {"task": task, "sample": directory.name, "record": record,
                            "started_unix": time.time(), "timeout_seconds": timeout}
        save()
        try:
            proc = subprocess.run(command, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            report["active"] = None
            return {"error": "timeout", "timeout_seconds": timeout,
                    "whole_child_timeout_seconds": timeout,
                    "completed": False, "passed": False,
                    "partial_diagnostics": {"whole_process_seconds": time.perf_counter() - started}}
        report["active"] = None
        result_path = directory / (record + ".json")
        if proc.returncode or not result_path.exists():
            return {"error": proc.stderr.decode(errors="replace")[-4000:],
                    "returncode": proc.returncode, "completed": False, "passed": False,
                    "partial_diagnostics": {"whole_process_seconds": time.perf_counter() - started}}
        result = json.loads(result_path.read_text())
        elapsed = time.perf_counter() - started
        if task == "runtime" and result.get("result", {}).get("stop_reason") != "terminated":
            result.setdefault("partial_diagnostics", {})["whole_process_seconds"] = elapsed
        else:
            result["whole_process_seconds"] = elapsed
        return result

    for program in programs:
        for backend in args.backends:
            for style in args.styles:
                for repeat in range(args.repeats):
                    directory = output / ("{}-{}-{}-{}".format(program["id"], backend, style.replace("/", "-"), repeat))
                    directory.mkdir(exist_ok=False)
                    (directory / "source.py").write_text(program["source"], encoding="utf8")
                    sample = {"program": program["id"], "backend": backend, "style": style,
                              "selection": pipeline.selection_metadata(args),
                              "repeat": repeat, "source_sha256": pipeline.digest(program["source"].encode("utf8")),
                              "workloads": []}
                    report["samples"].append(sample)
                    for work in program["workloads"]:
                        job = directory / (work["id"] + ".json")
                        job.write_text(json.dumps(dict(work, source=program["source"])))
                        oracle = child("oracle", directory, job, "oracle-" + work["id"], backend,
                                       style, work["max_steps"], min(args.timeout, 10))
                        sample["workloads"].append(dict(work, oracle=oracle))
                    if all(w["oracle"].get("passed") for w in sample["workloads"]):
                        first = program["workloads"][0]
                        sample["compile"] = child("compile", directory, directory / (first["id"] + ".json"),
                                                  "compile", backend, style, first["max_steps"], args.timeout)
                        save()
                    compilation = sample.get("compile", {})
                    compile_ok = "stages" in compilation
                    for work in sample["workloads"]:
                        passed = compile_ok and work["oracle"].get("passed", False)
                        if passed and args.runtime:
                            budget = args.max_steps if args.max_steps is not None else work["max_steps"]
                            record = "runtime-" + work["id"]
                            work["runtime"] = child("runtime", directory, directory / (work["id"] + ".json"),
                                                     record, backend, style, budget,
                                                     min(args.timeout, work["timeout_seconds"]))
                            passed = work["runtime"].get("passed", False)
                            if passed and args.trace:
                                work["trace"] = child("trace", directory, directory / (work["id"] + ".json"),
                                                      "trace-" + work["id"], backend, style, budget,
                                                      min(args.timeout, work["timeout_seconds"]), record)
                                passed = work["trace"].get("passed", False)
                        work["passed"] = bool(passed)
                        failed |= not passed
                        runtime = work.get("runtime", {})
                        measured_runtime = runtime if pipeline.completed_runtime(runtime) else {}
                        rows.append({"program": program["id"], "backend": backend, "style": style,
                                     "target_pipeline": pipeline.selection_metadata(args)["target_pipeline"],
                                     "ir_frontend": pipeline.selection_metadata(args)["ir_frontend"],
                                     "repeat": repeat, "workload": work["id"],
                                     "status": "ok" if passed and args.runtime else ("compiled_" + args.stop_after if passed else "failed"),
                                     "compile_seconds": compilation.get("wall_seconds_including_artifact_and_metric_writes"),
                                     "compile_cpu_seconds": compilation.get("cpu_seconds"),
                                     "compiler_stage_seconds": sum(s["seconds"] for s in compilation.get("stages", [])) if compile_ok else None,
                                     "mb_bytes": compilation.get("image", {}).get("bytes"),
                                     "mc_bytes": next((s["bytes"] for s in compilation.get("stages", []) if s["stage"] == "mg2mc"), None),
                                     "steps": measured_runtime.get("result", {}).get("steps"),
                                     "run_seconds": measured_runtime.get("wall_seconds"),
                                     "run_cpu_seconds": measured_runtime.get("cpu_seconds"),
                                     "execute_seconds": measured_runtime.get("execute_seconds"),
                                     "execute_cpu_seconds": measured_runtime.get("execute_cpu_seconds"),
                                     "execute_cpu_wall_ratio": measured_runtime.get("execute_cpu_wall_ratio"),
                                     "steps_per_second": measured_runtime.get("result", {}).get("steps", 0) / measured_runtime["execute_seconds"] if measured_runtime.get("execute_seconds", 0) > 0 else None,
                                     "cpython_code_seconds": work["oracle"].get("code_seconds"),
                                     "cpython_code_cpu_seconds": work["oracle"].get("code_cpu_seconds"),
                                     "peak_rss_bytes": measured_runtime.get("process_peak_rss_bytes")})
                        save()
                    image_path = directory / "program.mb"
                    sample["image_retained"] = image_path.exists() and not args.discard_images
                    if args.discard_images and image_path.exists():
                        image_path.unlink()
                    save()
                    print("{} {} {}: {}".format(program["id"], backend, style,
                          "ok" if all(w["passed"] for w in sample["workloads"]) else "failed"), flush=True)
    report["source_hashes_at_end"] = pipeline.fingerprint()
    report["source_changed_during_run"] = report["source_hashes_at_end"] != report["source_hashes_at_start"]
    report["all_requested_samples_passed"] = not failed
    report["run_state"] = "complete_with_failures" if failed else "complete"
    report["finished_unix"] = time.time()
    save()
    print("Results: {}".format(output / "summary.csv"), flush=True)
    return int(failed)
