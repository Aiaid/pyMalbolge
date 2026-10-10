"""Compare execution of identical accepted Malbolge20 images in three VMs.

Build the optional extension first with scripts/build_native_vm.py. Run through
uv, for example::

    uv run --no-sync python scripts/benchmark_native_vm.py \
        --output-dir /tmp/malbolge-native-comparison --repeats 5

The output directory must not exist. Fixtures are never compiled. The Nagoya
correctness gate is separately instrumented and supplies no timing evidence.
Short fixture timings are exploratory evidence, not a general speed claim.
"""

import argparse
from array import array
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import shutil
import statistics
import struct
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "ref/nagoya-malbolge20-interpreter/malbolge20.c"
SOURCE_SHA256 = "0ea5d2cfd8e597256f91bae3ea505f2f8467e3704e5c362b24fc91b56b9782b0"
CLOCK_PREFIX = "PYMALBOLGE_EXEC_CLOCK:"
FIXTURES = {
    "mg_b_hi": (b"", b"Hi"),
    "mg_c_echo": (b"Q", b"Q"),
    "mg_d_repeat": (b"", b"AAAA"),
    "mg_e_call": (b"", b"X"),
}
ENGINES = ("python", "native", "nagoya_c")
SAFE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_snapshot():
    result = {"load_average": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
              "cpu_count": os.cpu_count()}
    # Hardware context is optional; it never influences execution or acceptance.
    sysctl = shutil.which("sysctl", path=SAFE_PATH)
    if sysctl:
        try:
            probe = subprocess.run([sysctl, "-n", "machdep.cpu.brand_string"],
                                   capture_output=True, timeout=5)
            result["cpu_description"] = (probe.stdout.decode("utf-8", errors="replace").strip()
                                         if probe.returncode == 0 else None)
        except (OSError, subprocess.TimeoutExpired):
            result["cpu_description"] = None
    return result


def source_hashes():
    paths = ["malbolge/core.py", "malbolge/native.py", "malbolge/_native_vm.c",
             "scripts/benchmark_native_vm.py", "scripts/build_native_vm.py",
             "scripts/verify_mb_reference.py"]
    if (ROOT / "malbolge/_native_jit.h").is_file():
        paths.append("malbolge/_native_jit.h")
    return {name: digest((ROOT / name).read_bytes()) for name in paths}


def canonical_memory(memory, engine):
    """Hash sorted uint32 LE page values and write masks, outside the timer.

    Both implementations use 4096-cell pages. Source cells are not counted as
    explicit non-source writes. Encoding/type/promotion choices are ignored.
    Page indices, complete page payloads, masks and allocated counts must agree.
    """
    if engine == "python":
        pages = []
        for page, block in sorted(memory._blocks.items()):
            # A bytearray is a packed-buffer input to array(), so expand its
            # individual cells explicitly instead of regrouping four bytes.
            values = array("I", list(block.values))
            if values.itemsize != 4:
                raise RuntimeError("memory fingerprint requires 32-bit array('I')")
            if sys.byteorder != "little":
                values.byteswap()
            pages.append((page, values.tobytes(), bytes(block.written)))
    else:
        pages = []
        for page, (values, written) in sorted(memory.export_pages().items()):
            values = bytes(values)
            if sys.byteorder != "little":
                words = array("I")
                words.frombytes(values)
                words.byteswap()
                values = words.tobytes()
            pages.append((page, values, written))
    values_hash, masks_hash = hashlib.sha256(), hashlib.sha256()
    last_page = -1
    for page, values, written in pages:
        values, written = bytes(values), bytes(written)
        expected_length = min(4096, 3 ** 20 - page * 4096) if type(page) is int else 0
        if (type(page) is not int or page <= last_page or not 0 < expected_length <= 4096 or
                len(written) != expected_length or len(values) != 4 * len(written) or
                any(value not in (0, 1) for value in written)):
            raise RuntimeError("malformed memory page export")
        header = struct.pack("<QI", page, len(written))
        values_hash.update(header)
        values_hash.update(values)
        masks_hash.update(header)
        masks_hash.update(written)
        last_page = page
    return {"encoding": "sorted-page-index-u64le,length-u32le,values-u32le,masks-u8",
            "page_size": 4096, "page_count": len(pages),
            "allocated_count": memory.get_allocated_count(),
            "page_values_sha256": values_hash.hexdigest(),
            "write_masks_sha256": masks_hash.hexdigest()}


def worker(args):
    sys.path.insert(0, str(ROOT))
    from malbolge.core import MalbolgeConfig, SparseMemory, parse_source, run_memory
    if platform.python_implementation() != "CPython":
        raise RuntimeError("this comparison requires CPython")
    actual_sources = source_hashes()
    extension_hash = None
    if args.worker == "native":
        from malbolge import native
        import malbolge._native_vm as extension
        extension_hash = digest(Path(extension.__file__).read_bytes())
    config = MalbolgeConfig.malbolge20()
    data = bytes.fromhex(args.input_hex)
    source = args.image.read_bytes()
    prepare_wall, prepare_cpu = time.perf_counter(), time.process_time()
    cells = parse_source(source, config)
    if args.worker == "python":
        memory = SparseMemory(config)
        memory.initialize_source(cells)
        execute = lambda: run_memory(memory, config, data, max_steps=args.max_steps,
                                     max_output=args.max_output, eof="sentinel")
    else:
        memory = native.NativeMemory(cells)
        execute = lambda: native.run_memory(memory, data, max_steps=args.max_steps,
                                            max_output=args.max_output, eof="sentinel")
    prepared_cpu, prepared_wall = time.process_time(), time.perf_counter()
    if args.bounded:
        result = execute()
        clocks = {}
    else:
        wall_start, cpu_start = time.perf_counter(), time.process_time()
        result = execute()  # Includes Native tuple -> RunResult conversion.
        cpu_end, wall_end = time.process_time(), time.perf_counter()
        clocks = {"execute_cpu_seconds": cpu_end - cpu_start,
                  "execute_wall_seconds": wall_end - wall_start}
    memory_state = canonical_memory(memory, args.worker)
    if source_hashes() != actual_sources:
        raise RuntimeError("VM source changed during worker execution")
    if args.worker == "native" and digest(Path(extension.__file__).read_bytes()) != extension_hash:
        raise RuntimeError("native extension changed during worker execution")
    print(json.dumps(dict(clocks, result=result.to_dict(), memory=memory_state,
                          prepare_cpu_seconds=prepared_cpu - prepare_cpu,
                          prepare_wall_seconds=prepared_wall - prepare_wall,
                          python=sys.version, executable=sys.executable,
                          implementation=platform.python_implementation(),
                          source_hashes=actual_sources, extension_sha256=extension_hash,
                          extension_path=str(extension.__file__) if args.worker == "native" else None,
                          native_byte_order=sys.byteorder,
                          image_sha256=digest(source))), flush=True)


def timed_reference(source, output_dir):
    """Only instrument main's call boundary; preserve exec and its helpers."""
    original = source.read_bytes()
    if digest(original) != SOURCE_SHA256:
        raise RuntimeError("Nagoya source differs from the pinned audited version")
    text = original.decode("utf-8")
    helpers = r'''
#include <time.h>
static double vm_clock_seconds(struct timespec ts) {
  return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}
static void vm_clock_read(clockid_t kind, struct timespec *value) {
  if (clock_gettime(kind, value) != 0) { perror("clock_gettime"); exit(70); }
}
'''
    text = "#define _POSIX_C_SOURCE 200809L\n" + helpers + text
    # Helpers need the C declarations before their definitions.
    text = text.replace("#include <time.h>", "#include <time.h>\n#include <stdio.h>\n#include <stdlib.h>", 1)
    main = "int main( int argc, char **argv )\n{"
    call = "  exec( flag, mem, init );//実行"
    if text.count(main) != 1 or text.count(call) != 1:
        raise RuntimeError("pinned C timing insertion anchors differ")
    text = text.replace(main, main + "\n  struct timespec prepare_cpu_start;\n"
                        "  vm_clock_read(CLOCK_PROCESS_CPUTIME_ID, &prepare_cpu_start);\n")
    text = text.replace(call, r'''
  struct timespec wall_start, cpu_start, cpu_end, wall_end;
  vm_clock_read(CLOCK_MONOTONIC, &wall_start);
  vm_clock_read(CLOCK_PROCESS_CPUTIME_ID, &cpu_start);
  exec( flag, mem, init );
  vm_clock_read(CLOCK_PROCESS_CPUTIME_ID, &cpu_end);
  vm_clock_read(CLOCK_MONOTONIC, &wall_end);
  fflush(stdout); /* Final flush is outside the execution clocks. */
  fprintf(stderr, "PYMALBOLGE_EXEC_CLOCK:{\"execute_wall_seconds\":%.12f,"
                  "\"execute_cpu_seconds\":%.12f,"
                  "\"prepare_cpu_seconds\":%.12f}\n",
          vm_clock_seconds(wall_end)-vm_clock_seconds(wall_start),
          vm_clock_seconds(cpu_end)-vm_clock_seconds(cpu_start),
          vm_clock_seconds(cpu_start)-vm_clock_seconds(prepare_cpu_start));
''')
    anchor = "void exec( int flag[59049], unsigned int **mem, unsigned int init[59049][2] )\n{"
    original_tail = original.decode("utf-8").split(anchor, 1)[1]
    if text.split(anchor, 1)[1] != original_tail:
        raise RuntimeError("timing instrumentation changed exec/helper bodies")
    generated, binary = output_dir / "nagoya-exec-clock.c", output_dir / "nagoya-exec-clock"
    generated.write_text(text, encoding="utf-8")
    compiler = shutil.which("clang", path=SAFE_PATH)
    if compiler is None:
        raise RuntimeError("clang is unavailable")
    command = [compiler, "-O3", "-std=c99", str(generated), "-lm", "-o", str(binary)]
    environment = {"PATH": SAFE_PATH, "LANG": "C", "LC_ALL": "C", "TMPDIR": str(output_dir)}
    import resource
    cpu_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    wall_start = time.perf_counter()
    built = subprocess.run(command, capture_output=True, timeout=60, env=environment, cwd=output_dir)
    build_wall = time.perf_counter() - wall_start
    cpu_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    build_cpu = ((cpu_after.ru_utime + cpu_after.ru_stime) -
                 (cpu_before.ru_utime + cpu_before.ru_stime))
    if built.returncode:
        raise RuntimeError("Nagoya timing copy build failed: " + built.stderr.decode("utf-8", errors="replace"))
    version = subprocess.run([compiler, "--version"], capture_output=True, timeout=10, env=environment)
    return binary, {"source_sha256": digest(original), "timed_source_sha256": digest(generated.read_bytes()),
                    "binary_sha256": digest(binary.read_bytes()), "exec_and_helpers_unchanged": True,
                    "exec_and_helpers_sha256": digest((anchor + original_tail).encode("utf-8")),
                    "compiler_argv": command, "compiler_flags": ["-O3", "-std=c99", "-lm"],
                    "compiler_version": version.stdout.decode("utf-8", errors="replace").strip(),
                    "build_wall_seconds": build_wall, "build_children_cpu_seconds": build_cpu,
                    "build_diagnostics": built.stderr.decode("utf-8", errors="replace")}


def make_cases(names, output_dir):
    inputs = output_dir / "inputs"
    inputs.mkdir()
    cases = []
    for name in names:
        if name in FIXTURES:
            data, expected = FIXTURES[name]
            original = ROOT / "test/fixtures/nagoya" / (name + ".mb")
            source = original.read_bytes()
            kind = "existing_generated_fixture"
        else:
            data, expected, original = b"", b"", None
            length = 1_000_000
            source = bytearray(length + 1)
            for position in range(length + 1):
                opcode = 81 if position == length else 68
                value = (opcode - position) % 94
                source[position] = value if value >= 33 else value + 94
            source = bytes(source)
            kind = "synthetic_nop_self_modification_control"
        image = inputs / (name + ".mb")
        image.write_bytes(source)
        cases.append({"name": name, "kind": kind, "original_image": str(original) if original else None,
                      "image": str(image), "image_bytes": len(source), "image_sha256": digest(source),
                      "input_hex": data.hex(), "expected_output_hex": expected.hex(),
                      "expected_consumed": len(data)})
    return cases


def check_result(sample, case, reference, sources, expected_memory=None):
    result = sample["result"]
    if (result["stop_reason"] != "terminated" or result["output_hex"] != case["expected_output_hex"] or
            result["input_consumed"] != reference["input_consumed"] or result["steps"] != reference["steps"] or
            result["registers"] != reference["registers"] or result["output_count"] != reference["output_count"]):
        raise RuntimeError("VM output/consumption/HALT/steps/registers differ from separate reference gate")
    if sample["source_hashes"] != sources or sample["image_sha256"] != case["image_sha256"]:
        raise RuntimeError("source or image changed during comparison")
    if expected_memory is not None and sample["memory"] != expected_memory:
        raise RuntimeError("Python/native final memory pages, write masks or allocation counts differ")


def spawn_worker(args, engine, case, bounded=False):
    command = [args.uv, "run", "--offline", "--no-sync"]
    if args.python:
        command += ["--python", args.python]
    command += ["python", str(Path(__file__).resolve()), "--worker", engine,
                "--image", case["image"], "--input-hex", case["input_hex"]]
    if bounded:
        command += ["--bounded", "--max-steps", str(args.gate_max_steps),
                    "--max-output", str(args.gate_max_output)]
    environment = dict(os.environ)
    # No user Python startup/preload hooks, compiler flags or benchmark paths.
    for key in ("PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME", "LD_PRELOAD", "DYLD_INSERT_LIBRARIES"):
        environment.pop(key, None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["UV_CACHE_DIR"] = str(args.output_dir / "uv-cache")
    completed = subprocess.run(command, input=b"", capture_output=True,
                               cwd=ROOT, env=environment, timeout=args.timeout)
    if completed.returncode:
        raise RuntimeError("%s worker failed: %s" % (engine, completed.stderr.decode("utf-8", errors="replace")))
    return json.loads(completed.stdout)


def summarize(runs, steps):
    summary = {}
    for engine in ENGINES:
        samples = [run for run in runs if run["engine"] == engine]
        clocks = {}
        for key in ("execute_cpu_seconds", "execute_wall_seconds"):
            values = [sample[key] for sample in samples]
            clocks[key] = {"median": statistics.median(values), "min": min(values), "max": max(values)}
        median = clocks["execute_cpu_seconds"]["median"]
        clocks["steps_per_cpu_second"] = steps / median if median > 0 else None
        summary[engine] = clocks
    native_cpu = summary["native"]["execute_cpu_seconds"]["median"]
    c_cpu = summary["nagoya_c"]["execute_cpu_seconds"]["median"]
    python_cpu = summary["python"]["execute_cpu_seconds"]["median"]
    summary["python_over_native_cpu_ratio"] = python_cpu / native_cpu if native_cpu > 0 else None
    summary["native_over_nagoya_cpu_ratio"] = native_cpu / c_cpu if c_cpu > 0 else None
    return summary


def native_build_receipt(args, sample, sources):
    candidates = ([args.native_build_receipt] if args.native_build_receipt else
                  sorted((ROOT / "build/native-vm").glob("*/build.json")))
    for path in candidates:
        data = path.read_bytes()
        receipt = json.loads(data)
        if (receipt.get("binary_sha256") == sample["extension_sha256"] and
                receipt.get("source_sha256") == sources["malbolge/_native_vm.c"] and
                Path(receipt.get("binary", "")).resolve() == Path(sample["extension_path"]).resolve()):
            (args.output_dir / "native-build.json").write_bytes(data)
            return {"status": "matched", "receipt": receipt, "receipt_sha256": digest(data)}
    if args.native_build_receipt:
        raise RuntimeError("specified native build receipt does not match the loaded extension/source")
    return {"status": "unavailable", "compiler_flags": None,
            "reason": "no matching build/native-vm/*/build.json receipt; native build costs/flags unknown"}


def compare(args):
    args.output_dir = args.output_dir.resolve()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    report_path = args.output_dir / "report.json"
    report = {"schema_version": 1, "status": "preparing", "repeats": args.repeats,
              "platform": platform.platform(), "machine": platform.machine(),
              "host_byte_order": sys.byteorder,
              "parent_python": sys.version, "python_selector": args.python,
              "load_before": load_snapshot(), "samples": [],
              "method": "Same image, three engines, fresh sequential uv workers for Python/native; cyclic engine order per repetition. Preload/validate/initialize outside process CPU and wall clocks. Native wrapper RunResult conversion and natural lazy page allocation inside clocks. C exec body unchanged; final stdout flush outside clocks. Separate bounded correctness gates supply no timings. No compilation/size optimization comparison; short samples are exploratory.",
              "gate_max_steps": args.gate_max_steps, "gate_max_output": args.gate_max_output,
              "child_timeout_seconds": args.timeout}
    write_json(report_path, report)
    try:
        sources = source_hashes()
        report["source_hashes"] = sources
        gate_source = ROOT / "scripts/verify_mb_reference.py"
        snapshot = args.output_dir / "verify_mb_reference_snapshot.py"
        snapshot.write_bytes(gate_source.read_bytes())
        spec = importlib.util.spec_from_file_location("benchmark_reference_gate", snapshot)
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        binary, build = timed_reference(REFERENCE, args.output_dir)
        report["nagoya_timing_build"] = build
        gate_binary, gate_manifest = gate.build_reference_gate(REFERENCE, args.output_dir / "correctness-only")
        report["reference_gate_build"] = gate_manifest
        cases = make_cases(args.cases or list(FIXTURES), args.output_dir)
        report["cases"] = cases
        report["status"] = "running"
        write_json(report_path, report)
        print("Prepared pinned C timing copy and separate correctness gate.", flush=True)
        for case in cases:
            record = {"case": case, "status": "unvalidated", "runs": []}
            report["samples"].append(record)
            try:
                reference = gate.verify_image(gate_binary, Path(case["image"]),
                                              bytes.fromhex(case["input_hex"]), bytes.fromhex(case["expected_output_hex"]),
                                              case["expected_consumed"], args.gate_max_steps,
                                              args.gate_max_output, args.timeout)
                record["reference_correctness"] = reference
                if not reference["gate_pass"]:
                    raise RuntimeError("separate reference gate rejected image: " + reference["reason"])
                bounded_python = spawn_worker(args, "python", case, bounded=True)
                check_result(bounded_python, case, reference, sources)
                bounded_native = spawn_worker(args, "native", case, bounded=True)
                check_result(bounded_native, case, reference, sources, bounded_python["memory"])
                record["python_correctness"] = bounded_python
                record["native_correctness"] = bounded_native
                extension_hash = bounded_native["extension_sha256"]
                runtime = {"python": bounded_python["python"],
                           "implementation": bounded_python["implementation"],
                           "executable": bounded_python["executable"],
                           "native_extension_path": bounded_native["extension_path"],
                           "native_extension_sha256": extension_hash}
                if bounded_native["python"] != runtime["python"]:
                    raise RuntimeError("Python/native workers used different CPython versions")
                if "worker_runtime" in report and report["worker_runtime"] != runtime:
                    raise RuntimeError("worker runtime or native binary changed between cases")
                report["worker_runtime"] = runtime
                if "native_build" not in report:
                    report["native_build"] = native_build_receipt(args, bounded_native, sources)
                print("%s: three correctness gates accepted (%d steps)." % (case["name"], reference["steps"]), flush=True)
                for repetition in range(args.repeats):
                    offset = repetition % len(ENGINES)
                    order = ENGINES[offset:] + ENGINES[:offset]
                    for engine in order:
                        if engine == "nagoya_c":
                            completed = subprocess.run([str(binary), case["image"]],
                                                       input=bytes.fromhex(case["input_hex"]), capture_output=True,
                                                       cwd=args.output_dir, timeout=args.timeout)
                            if completed.returncode or completed.stdout.hex() != case["expected_output_hex"]:
                                raise RuntimeError("timed Nagoya execution failed or output differs")
                            lines = completed.stderr.decode("utf-8", errors="replace").splitlines()
                            if len(lines) != 1 or not lines[0].startswith(CLOCK_PREFIX):
                                raise RuntimeError("timed Nagoya clock receipt missing or malformed")
                            sample = json.loads(lines[0][len(CLOCK_PREFIX):])
                        else:
                            sample = spawn_worker(args, engine, case)
                            check_result(sample, case, reference, sources, bounded_python["memory"])
                            if sample["python"] != runtime["python"] or sample["executable"] != runtime["executable"]:
                                raise RuntimeError("worker runtime changed between gate and timed execution")
                            if engine == "native" and sample["extension_sha256"] != extension_hash:
                                raise RuntimeError("native extension changed between gate and timed execution")
                        for key in ("execute_cpu_seconds", "execute_wall_seconds"):
                            if not math.isfinite(sample[key]) or sample[key] < 0:
                                raise RuntimeError("invalid execution clock receipt")
                        sample.update(engine=engine, repetition=repetition, status="accepted", order=list(order))
                        record["runs"].append(sample)
                    write_json(report_path, report)
                record["summary"] = summarize(record["runs"], reference["steps"])
                record["status"] = "accepted"
                print("%s: accepted %d timed runs per engine." % (case["name"], args.repeats), flush=True)
            except subprocess.TimeoutExpired:
                record.update(status="child_timeout", error="whole-child timeout; no execution clock or speed inferred")
            except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
                record.update(status="failed", error=str(exc))
            write_json(report_path, report)
        report["source_stability"] = source_hashes() == sources
        report["reference_stability"] = digest(REFERENCE.read_bytes()) == SOURCE_SHA256
        report["image_stability"] = all(digest(Path(case["image"]).read_bytes()) == case["image_sha256"] and
            (case["original_image"] is None or digest(Path(case["original_image"]).read_bytes()) == case["image_sha256"])
            for case in cases)
        report["timed_reference_binary_stability"] = digest(binary.read_bytes()) == build["binary_sha256"]
        report["timed_reference_source_stability"] = digest((args.output_dir / "nagoya-exec-clock.c").read_bytes()) == build["timed_source_sha256"]
        runtime = report.get("worker_runtime")
        report["native_binary_stability"] = (runtime is not None and
            digest(Path(runtime["native_extension_path"]).read_bytes()) == runtime["native_extension_sha256"])
        stable = all(report[key] for key in ("source_stability", "reference_stability", "image_stability",
                                           "timed_reference_binary_stability", "timed_reference_source_stability",
                                           "native_binary_stability"))
        if not stable:
            for record in report["samples"]:
                record.pop("summary", None)
                record["runs"] = []
                record.update(status="invalidated", error="source/image/binary changed during comparison")
        report["status"] = "accepted" if stable and all(r["status"] == "accepted" for r in report["samples"]) else "failed"
    except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError, ImportError) as exc:
        report.update(status="failed", error=str(exc))
    finally:
        report["load_after"] = load_snapshot()
        write_json(report_path, report)
    print("Report: %s (%s)" % (report_path, report["status"]), flush=True)
    return 0 if report["status"] == "accepted" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", type=Path, help="new evidence directory; must not already exist")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--cases", nargs="+", choices=list(FIXTURES) + ["linear_nop_1m"])
    parser.add_argument("--timeout", type=float, default=15.0, help="whole-child timeout in seconds")
    parser.add_argument("--gate-max-steps", type=int, default=2_000_000)
    parser.add_argument("--gate-max-output", type=int, default=4096)
    parser.add_argument("--python", help="optional uv Python selector; extension must match its ABI")
    parser.add_argument("--native-build-receipt", type=Path,
                        help="optional native builder JSON receipt; otherwise discover a matching local receipt")
    parser.add_argument("--uv", default=shutil.which("uv"), help="uv executable")
    parser.add_argument("--worker", choices=("python", "native"), help=argparse.SUPPRESS)
    parser.add_argument("--image", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--input-hex", default="", help=argparse.SUPPRESS)
    parser.add_argument("--bounded", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--max-steps", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--max-output", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        if args.image is None:
            parser.error("worker requires --image")
        worker(args)
        return 0
    if args.output_dir is None or not args.uv:
        parser.error("--output-dir and an available uv executable are required")
    if args.repeats < 1 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--repeats must be >= 1 and --timeout finite and > 0")
    if args.gate_max_steps < 1 or args.gate_max_output < 1:
        parser.error("gate budgets must be positive")
    if args.cases and len(set(args.cases)) != len(args.cases):
        parser.error("case names must be unique")
    if args.output_dir.exists():
        parser.error("--output-dir already exists; choose a fresh directory")
    return compare(args)


if __name__ == "__main__":
    sys.exit(main())
