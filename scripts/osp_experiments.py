"""Bounded, fixed-input OSP acceptance using an explicitly selected Python.

The controller uses only the standard library. Each oracle, compilation and
VM sample is a fresh ``python -I`` child. Run only trusted local manifests:
the CPython oracle intentionally executes their source programs.
"""

import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "benchmarks/osp/manifest.json"
SCHEMA_VERSION = 1


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n",
                          encoding="utf8")


def within(path, root):
    path, root = Path(path).resolve(), Path(root).resolve()
    return path == root or root in path.parents


def load_manifest(path, suite="smoke", cases=None):
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding="utf8"))
    if data.get("schema_version") != 1:
        raise ValueError("manifest schema_version must be 1")
    tiers = {"smoke"} if suite == "smoke" else {"smoke", "standard"}
    selected, seen = [], set()
    for entry in data["programs"]:
        name = entry["id"]
        if not name or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in name):
            raise ValueError("program IDs must use lowercase letters, digits and underscores")
        if name in seen:
            raise ValueError("duplicate program ID: " + name)
        seen.add(name)
        if (cases and name not in cases) or (not cases and suite != "all" and entry["tier"] not in tiers):
            continue
        source_path = (path.parent / entry["path"]).resolve()
        raw = source_path.read_bytes()
        # Git may check out text as CRLF on Windows. Lock logical UTF-8 source,
        # and retain the raw file hash separately rather than claim byte parity.
        source = raw.decode("utf8").replace("\r\n", "\n")
        source_hash = digest(source.encode("utf8"))
        if entry.get("source_sha256") not in (None, source_hash):
            raise ValueError("source fingerprint differs: " + name)
        jobs, workloads = [], set()
        for item in entry["workloads"]:
            if not item["id"] or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in item["id"]):
                raise ValueError("workload IDs must use lowercase letters, digits and underscores")
            if item["id"] in workloads:
                raise ValueError("duplicate workload ID: " + name)
            workloads.add(item["id"])
            stdin = (bytes.fromhex(item["stdin_hex"]) if "stdin_hex" in item
                     else item["stdin"].encode("ascii"))
            stdout = (bytes.fromhex(item["stdout_hex"]) if "stdout_hex" in item
                      else item["stdout"].encode("ascii"))
            consumed = item.get("expected_input_consumed", len(stdin))
            if type(consumed) is not int or not 0 <= consumed <= len(stdin):
                raise ValueError("invalid expected input consumption: " + name)
            steps, timeout = item["max_steps"], item["timeout_seconds"]
            if type(steps) is not int or steps <= 0 or not 0 < timeout <= 3600:
                raise ValueError("positive bounded steps/timeout required: " + name)
            jobs.append({"workload": item["id"], "stdin_hex": stdin.hex(),
                         "expected_stdout_hex": stdout.hex(),
                         "expected_input_consumed": consumed,
                         "max_steps": steps, "timeout_seconds": timeout,
                         "max_output": max(64, len(stdout) + 1)})
        if not jobs:
            raise ValueError("program has no workloads: " + name)
        selected.append({"id": name, "source": source,
                         "source_sha256": source_hash,
                         "raw_source_sha256": digest(raw), "workloads": jobs})
    if cases and set(cases) - seen:
        raise ValueError("unknown cases: " + ", ".join(sorted(set(cases) - seen)))
    if not selected:
        raise ValueError("no programs selected")
    return selected


def oracle(source, stdin_hex):
    output = io.StringIO()
    incoming = io.StringIO(bytes.fromhex(stdin_hex).decode("latin1"))
    previous = sys.stdin
    sys.stdin = incoming
    try:
        def getchar():
            value = incoming.read(1)
            return ord(value) if value else 3 ** 20 - 1

        with contextlib.redirect_stdout(output):
            exec(compile(source, "<osp-oracle>", "exec"),
                 {"getchar": getchar,
                  "putchar": lambda value: output.write(chr(value % 256))})
    finally:
        sys.stdin = previous
    return {"output_hex": output.getvalue().encode("latin1").hex(),
            "input_consumed": incoming.tell(), "stop_reason": "terminated"}


def matches(result, contract):
    return (result.get("output_hex") == contract["expected_stdout_hex"]
            and result.get("input_consumed") == contract["expected_input_consumed"]
            and result.get("stop_reason") == "terminated")


def package_probe(forbid_root=None):
    from importlib import metadata
    import malbolge
    from malbolge import native

    package = Path(malbolge.__file__).resolve().parent
    if forbid_root and within(package, forbid_root):
        raise ValueError("package imports from the forbidden source checkout")
    versions = {}
    for name in ("malbolge", "xdsl", "textual"):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    if versions["malbolge"] != malbolge.__version__:
        raise ValueError("distribution metadata and module versions differ")
    hashes = {str(p.relative_to(package)).replace(os.sep, "/"): digest(p.read_bytes())
              for p in sorted(package.rglob("*"))
              if p.is_file() and p.suffix in (".py", ".so", ".pyd")}
    return {"versions": versions, "module_version": malbolge.__version__,
            "python": sys.version, "implementation": platform.python_implementation(),
            "system": platform.system(), "release": platform.release(),
            "machine": platform.machine(), "logical_cpus": os.cpu_count(),
            "native_available": native.native_available(),
            "outside_forbidden_source": bool(forbid_root),
            "package_files_sha256": hashes,
            "package_fingerprint_sha256": digest(json.dumps(hashes, sort_keys=True).encode())}


def worker(job):
    task = job["task"]
    if task == "probe":
        return package_probe(job.get("forbid_source_root"))
    if task == "oracle":
        return oracle(job["source"], job["stdin_hex"])
    if task == "compile":
        from malbolge.compiler import resolve_optimization_policy, build_compilation_plan

        policy = resolve_optimization_policy(job["backend"], opt_level=job["opt_level"],
                                             target_pipeline=job["target_pipeline"])
        start, cpu = time.perf_counter(), time.process_time()
        plan = build_compilation_plan(job["source"], policy, "cluster", "main")
        image = plan.to_mb().encode("ascii")
        wall, cpu = time.perf_counter() - start, time.process_time() - cpu
        Path(job["image_path"]).write_bytes(image)
        return {"image_bytes": len(image), "image_sha256": digest(image),
                "compile_api_wall_seconds": wall, "compile_api_cpu_seconds": cpu,
                "selection": plan.metadata(), "cache": "disabled_library_api"}
    if task == "runtime":
        from malbolge import run20

        image = Path(job["image_path"]).read_bytes()
        if digest(image) != job["image_sha256"]:
            raise ValueError("compiled image fingerprint changed before execution")
        start, cpu = time.perf_counter(), time.process_time()
        result = run20(image, bytes.fromhex(job["stdin_hex"]), engine=job["engine"],
                       max_steps=job["max_steps"], max_output=job["max_output"], eof="sentinel")
        wall, cpu = time.perf_counter() - start, time.process_time() - cpu
        record = result.to_dict()
        record.update(engine=job["engine"], image_sha256=job["image_sha256"])
        if result.stop_reason == "terminated":
            record.update(runtime_api_wall_seconds=wall, runtime_api_cpu_seconds=cpu)
        else:
            record["partial_diagnostics"] = {"elapsed_wall_seconds": wall,
                                              "elapsed_cpu_seconds": cpu}
        return record
    raise ValueError("unknown worker task")


def child(python, job, output, timeout):
    job_path = output.with_suffix(".job.json")
    write_json(job_path, job)
    start = time.perf_counter()
    try:
        process = subprocess.run([str(python), "-I", str(Path(__file__).resolve()),
                                  "--worker", str(job_path)],
                                 capture_output=True, timeout=timeout, cwd=str(output.parent))
    except subprocess.TimeoutExpired:
        result = {"status": "timeout", "elapsed_to_stop_seconds": time.perf_counter() - start,
                  "timeout_seconds": timeout}
    else:
        try:
            result = json.loads(process.stdout.decode("utf8"))
        except (ValueError, UnicodeError):
            result = {"status": "error", "error": "worker returned no JSON"}
        result["returncode"] = process.returncode
        result["child_wall_seconds"] = time.perf_counter() - start
        if process.stderr:
            result["stderr_tail"] = process.stderr.decode("utf8", errors="replace")[-2000:]
        if process.returncode and result.get("status") == "ok":
            result["status"] = "error"
    write_json(output, result)
    job_path.unlink()
    return result


def run(args):
    # Preserve a virtualenv's python symlink: resolving it selects the base
    # interpreter and silently changes which installed distribution is tested.
    args.python = Path(os.path.abspath(str(args.python)))
    if args.forbid_source_root:
        args.forbid_source_root = str(Path(args.forbid_source_root).resolve())
    programs = load_manifest(args.manifest, args.suite, args.cases)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": SCHEMA_VERSION, "status": "running", "mode": args.mode,
              "manifest_sha256": digest(args.manifest.read_bytes()),
              "runner_sha256": digest(Path(__file__).read_bytes()),
              "selection": {"suite": args.suite, "cases": args.cases,
                            "backends": args.backends, "engines": args.engines,
                            "opt_level": args.opt_level, "target_pipeline": args.target_pipeline,
                            "repeats": args.repeats, "eof": "sentinel"},
              "measurement_scope": {
                  "compile": "fresh-process API; excludes imports, file write and image hashing",
                  "runtime": "fresh-process run20 API; includes validation/init/execute, excludes read/hash/imports",
                  "child_wall": "diagnostic whole child; not API time",
                  "oracle": "CPython with byte helpers; not an independent target VM",
                  "timing_claim": "acceptance only" if args.repeats == 1 else "repeated same-host samples; no universal speed claim",
                  "timeouts": "incomplete; not a successful timing or speed ratio"},
              "programs": [{k: v for k, v in p.items() if k != "source"} for p in programs],
              "oracle": [], "samples": []}
    write_json(output / "report.json", report)
    if args.mode == "run":
        probe = child(args.python, {"task": "probe", "forbid_source_root": args.forbid_source_root},
                      output / "environment.json", 30)
        report["environment"] = probe
        if probe["status"] != "ok" or (args.expected_version and
                probe.get("result", {}).get("module_version") != args.expected_version):
            report.update(status="failed", error="package/version prerequisite failed")
            write_json(output / "report.json", report)
            return report
    for program in programs:
        for workload in program["workloads"]:
            name = "%s-%s" % (program["id"], workload["workload"])
            result = child(args.python, dict(workload, task="oracle", source=program["source"]),
                           output / ("oracle-" + name + ".json"), 15)
            passed = result["status"] == "ok" and matches(result["result"], workload)
            report["oracle"].append({"program": program["id"], "workload": workload["workload"],
                                     "passed": passed, "receipt": "oracle-" + name + ".json"})
    if not all(r["passed"] for r in report["oracle"]):
        report.update(status="failed", error="CPython expected-output/input contract failed")
        write_json(output / "report.json", report)
        return report
    if args.mode == "run":
        for repeat in range(args.repeats):
            backends = args.backends[repeat % len(args.backends):] + args.backends[:repeat % len(args.backends)]
            for program in programs:
                for backend in backends:
                    stem = "%s-%s-r%d" % (program["id"], backend, repeat)
                    image_path = output / (stem + ".mb")
                    compiled = child(args.python, {"task": "compile", "source": program["source"],
                                     "backend": backend, "opt_level": args.opt_level,
                                     "target_pipeline": args.target_pipeline, "image_path": str(image_path)},
                                     output / (stem + "-compile.json"), args.compile_timeout)
                    row = {"program": program["id"], "backend": backend, "repeat": repeat,
                           "compile_receipt": stem + "-compile.json", "runtime": [], "passed": False}
                    if compiled["status"] == "ok":
                        row["image"] = {k: compiled["result"][k] for k in ("image_bytes", "image_sha256")}
                        engines = args.engines[repeat % len(args.engines):] + args.engines[:repeat % len(args.engines)]
                        for workload in program["workloads"]:
                            for engine in engines:
                                filename = "%s-%s-%s.json" % (stem, workload["workload"], engine)
                                executed = child(args.python, dict(workload, task="runtime", engine=engine,
                                                 image_path=str(image_path), image_sha256=compiled["result"]["image_sha256"]),
                                                 output / filename, workload["timeout_seconds"])
                                passed = executed["status"] == "ok" and matches(executed["result"], workload)
                                row["runtime"].append({"workload": workload["workload"], "engine": engine,
                                                       "passed": passed, "receipt": filename})
                        row["passed"] = all(r["passed"] for r in row["runtime"])
                    if image_path.exists() and not args.keep_images:
                        image_path.unlink()
                    report["samples"].append(row)
                    write_json(output / "report.json", report)
        final_probe = child(args.python, {"task": "probe", "forbid_source_root": args.forbid_source_root},
                            output / "environment-after.json", 30)
        report["package_unchanged"] = (final_probe["status"] == "ok" and
            final_probe["result"]["package_fingerprint_sha256"] ==
            report["environment"]["result"]["package_fingerprint_sha256"])
        images = {}
        for sample in report["samples"]:
            if "image" in sample:
                images.setdefault((sample["program"], sample["backend"]), set()).add(sample["image"]["image_sha256"])
        report["repeat_image_identity"] = (all(len(hashes) == 1 for hashes in images.values())
                                           if args.repeats > 1 else None)
    try:
        current_inputs = load_manifest(args.manifest, args.suite, args.cases)
        report["inputs_unchanged"] = (digest(args.manifest.read_bytes()) == report["manifest_sha256"] and
            [(p["id"], p["source_sha256"]) for p in current_inputs] ==
            [(p["id"], p["source_sha256"]) for p in programs])
    except (OSError, ValueError):
        report["inputs_unchanged"] = False
    report["status"] = ("passed" if all(r["passed"] for r in report["samples"])
                        and report.get("package_unchanged", True)
                        and report.get("repeat_image_identity") is not False
                        and report["inputs_unchanged"] else "failed")
    write_json(output / "report.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--mode", choices=("oracle", "run"), default="oracle")
    parser.add_argument("--suite", choices=("smoke", "standard", "all"), default="smoke")
    parser.add_argument("--cases", nargs="+")
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--expected-version")
    parser.add_argument("--forbid-source-root")
    parser.add_argument("--backends", nargs="+", choices=("auto", "direct", "c", "ir"), default=["auto", "direct"])
    parser.add_argument("--engines", nargs="+", choices=("python", "native"), default=["python"])
    parser.add_argument("--opt-level", type=int, choices=range(4), default=3)
    parser.add_argument("--target-pipeline", choices=("text", "structured"), default="structured")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--compile-timeout", type=float, default=180)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--keep-images", action="store_true")
    args = parser.parse_args(argv)
    if args.worker:
        try:
            result = worker(json.loads(args.worker.read_text(encoding="utf8")))
            print(json.dumps({"status": "ok", "result": result}))
            return 0
        except Exception as error:
            print(json.dumps({"status": "error", "error_type": type(error).__name__, "error": str(error)}))
            return 1
    if not args.output_dir:
        parser.error("--output-dir is required and must be a new directory")
    if not 1 <= args.repeats <= 10 or not 0 < args.compile_timeout <= 3600:
        parser.error("repeats must be 1..10 and compile timeout must be (0, 3600]")
    if len(set(args.backends)) != len(args.backends) or len(set(args.engines)) != len(args.engines):
        parser.error("duplicate backends/engines are not allowed")
    try:
        report = run(args)
    except (ValueError, OSError, KeyError) as error:
        parser.exit(2, str(error) + "\n")
    print(json.dumps({"status": report["status"], "mode": report["mode"],
                      "oracle_workloads": len(report["oracle"]), "compile_samples": len(report["samples"]),
                      "report": str(args.output_dir / "report.json")}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
