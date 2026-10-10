"""Measure Python -> C/MG -> MC -> MB -> VM without compilation caches.

Run with ``uv run --no-sync python scripts/benchmark_pipeline.py --help``.
Each compiler/runtime sample runs in a fresh process. Profiling is optional
and its samples must not be compared with unprofiled wall-clock samples.
The benchmark's historical IR default is semantic (the compiler CLI defaults
to compat). Target handoffs default to text; structured is explicitly selected.
"""

import argparse
import ast
from collections import Counter
import contextlib
import cProfile
import gc
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import pstats
import statistics
import subprocess
import sys
import time

try:
    import resource
except ImportError:  # RSS measurement is unavailable on some platforms.
    resource = None


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUNNER_VERSION = 3


def selection_metadata(args):
    return {"runner_version": RUNNER_VERSION,
            "target_pipeline": getattr(args, "target_pipeline", "text"),
            "ir_frontend": getattr(args, "ir_frontend", "semantic"),
            "semantic_passes": getattr(args, "semantic_passes", None),
            "legacy_arithmetic": bool(getattr(args, "legacy_arithmetic", False)),
            "diagnostic_exports": bool(getattr(args, "diagnostic_exports", False)),
            "max_output": getattr(args, "max_output", 4096),
            "eof": getattr(args, "eof", "sentinel"),
            "compilation_cache": "disabled"}


def selection_arguments(args):
    """Keep all child tasks on the explicitly recorded compiler selection."""
    command = ["--target-pipeline", getattr(args, "target_pipeline", "text"),
               "--ir-frontend", getattr(args, "ir_frontend", "semantic"),
               "--max-output", str(getattr(args, "max_output", 4096)),
               "--eof", getattr(args, "eof", "sentinel")]
    if getattr(args, "diagnostic_exports", False):
        command.append("--diagnostic-exports")
    return command


def completed_runtime(record):
    return (record.get("passed", False) and
            record.get("result", {}).get("stop_reason") == "terminated")

# All cases stay inside the subset's common, non-overflowing CPython semantics.
# Runtime input prevents folding away the operations being measured.
CASES = {
    "literal": ('print("Hi")\n', ""),
    "echo": ("x = getchar()\nputchar(x)\n", "Q"),
    "loop": ("n = getchar() - 48\nx = 0\nwhile x < n:\n    putchar(65 + x)\n    x += 1\n", "3"),
    "call": ("def inc(x):\n    return x + 1\nx = getchar()\nputchar(inc(x))\n", "@"),
    "multiply": ("x = getchar() - 48\nputchar(x * 3 + 48)\n", "2"),
    "divide_one": ("x = getchar()\nputchar(x // 1)\n", "Q"),
    "modulo_one": ("x = getchar()\nputchar(x % 1 + 65)\n", "Q"),
    "decimal": ("n = int(input())\nprint(n)\n", "7\n"),
    "fib_iter": ("n = int(input())\na = 0\nb = 1\nfor i in range(n):\n    a, b = b, a + b\nprint(a)\n", "7\n"),
    "fib_rec": ("def fib(n):\n    if n < 2:\n        return n\n    return fib(n-1) + fib(n-2)\nn = int(input())\nprint(fib(n))\n", "7\n"),
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint():
    paths = sorted((ROOT / "malbolge").glob("*.py"))
    paths += sorted((ROOT / "malbolge/compiler").rglob("*.py"))
    return {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in paths}


def peak_rss():
    if resource is None:
        return None
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def _read_system_command(argv):
    """Read bounded OS metadata; unavailable commands never fail a sample."""
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def hardware_environment():
    """Static hardware/runtime metadata, without device or process inventories."""
    # platform.platform()/processor() may internally invoke unbounded uname
    # subprocesses. These individual fields use the OS uname API instead.
    result = {"python": sys.version, "python_implementation": platform.python_implementation(),
              "platform": " ".join((platform.system(), platform.release(), platform.machine())),
              "machine": platform.machine(),
              "cpu_model": None, "logical_cores": os.cpu_count(),
              "physical_cores": None, "ram_bytes": None}
    if sys.platform == "darwin":
        result["cpu_model"] = (_read_system_command(["/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string"])
                               or result["cpu_model"])
        for key, name in (("logical_cores", "hw.logicalcpu"),
                          ("physical_cores", "hw.physicalcpu"), ("ram_bytes", "hw.memsize")):
            value = _read_system_command(["/usr/sbin/sysctl", "-n", name])
            try:
                result[key] = int(value) if value is not None else result[key]
            except ValueError:
                pass
    elif hasattr(os, "sysconf"):
        try:
            pages, size = os.sysconf("SC_PHYS_PAGES"), os.sysconf("SC_PAGE_SIZE")
            result["ram_bytes"] = pages * size if pages > 0 and size > 0 else None
        except (OSError, ValueError):
            pass
    return result


def system_context():
    """Best-effort load/power/thermal snapshots; load averages are not CPU %."""
    try:
        load_average = list(os.getloadavg())
    except (AttributeError, OSError):
        load_average = None
    result = {"unix_time_seconds": time.time(), "monotonic_seconds": time.monotonic(),
              "load_average_1_5_15": load_average, "power_source": None,
              "thermal_status_text": None}
    if sys.platform == "darwin":
        battery = _read_system_command(["/usr/bin/pmset", "-g", "batt"])
        result["power_source"] = battery.splitlines()[0] if battery else None
        result["thermal_status_text"] = _read_system_command(["/usr/bin/pmset", "-g", "therm"])
    return result


def cpu_wall_ratio(cpu_seconds, wall_seconds):
    # CPU time excludes scheduling/waiting, but still depends on hardware,
    # clock/thermal state and caches. This ratio is not system CPU utilization.
    return cpu_seconds / wall_seconds if wall_seconds > 0 else None


def oracle(source, input_text):
    output = io.StringIO()
    stream = io.StringIO(input_text)
    previous = sys.stdin
    sys.stdin = stream
    try:
        with contextlib.redirect_stdout(output):
            exec(compile(source, "<benchmark>", "exec"), {
                "putchar": lambda n: output.write(chr(n % 256)),
                "getchar": lambda: ord(stream.read(1)),
            })
    finally:
        sys.stdin = previous
    return output.getvalue().encode("latin1")


def text_structure(source):
    # Strip comments; these are textual construct counts, not execution counts.
    lines = [line.split("#", 1)[0].strip() for line in source.splitlines()]
    names = []
    for line in lines:
        if not line:
            continue
        first = line.split()[0]
        names.append("LABEL" if first.endswith(":") else first)
    return dict(sorted(Counter(names).items()))


def data_structure(text):
    lines = iter(text.splitlines())
    sections = Counter()
    words = Counter()
    initialized = Counter()
    entry = None
    for line in lines:
        if line.startswith("ENTRY_ADDRESS:"):
            entry = int(line.split(":", 1)[1])
        elif line.startswith(("DIRECT_UNIT_CODE:", "INDIRECT_UNIT_CODE:", "ROUTINE_CODE:")):
            kind = line.split(":", 1)[0]
            next(lines)  # offset
            length = int(next(lines).split(":", 1)[1])
            values = [int(next(lines)) for _ in range(length)]
            sections[kind] += 1
            words[kind] += length
            initialized[kind] += sum(value != -1 for value in values)
    return {"entry_address": entry, "sections": dict(sections),
            "words_including_dup": dict(words), "non_dup_words": dict(initialized)}


def image_structure(image):
    """Count typed image segments without introducing a .data handoff."""
    headers = {"direct": "DIRECT_UNIT_CODE", "indirect": "INDIRECT_UNIT_CODE",
               "routine": "ROUTINE_CODE"}
    sections, words, initialized = Counter(), Counter(), Counter()
    for segment in image.segments:
        name = headers[segment.kind]
        sections[name] += 1
        words[name] += len(segment.words)
        initialized[name] += sum(value != -1 for value in segment.words)
    return {"entry_address": image.entry, "sections": dict(sections),
            "words_including_dup": dict(words), "non_dup_words": dict(initialized)}


def compile_sample(args, directory, source):
    from malbolge.compiler import compile_python_to_c, compile_c_to_mg, compile_python_to_mg
    from malbolge.compiler.mg2mc import translate_mg_to_mc
    from malbolge.compiler.mc2mb import parse_mc_to_data, _Assembler

    stages, diagnostics = [], []
    selection = selection_metadata(args)
    if selection["target_pipeline"] not in ("text", "structured"):
        raise ValueError("target_pipeline must be text or structured")
    if selection["ir_frontend"] not in ("compat", "semantic"):
        raise ValueError("ir_frontend must be compat or semantic")
    if (args.backend == "ir" and selection["ir_frontend"] == "compat" and
            (selection["semantic_passes"] is not None or selection["legacy_arithmetic"])):
        raise ValueError("semantic options require --ir-frontend semantic")
    native = selection["target_pipeline"] == "structured"
    structure = {"python_ast_nodes": len(list(ast.walk(ast.parse(source))))}

    def stage(name, fn):
        start, cpu = time.perf_counter(), time.process_time()
        value = fn()
        record = {"stage": name, "seconds": time.perf_counter() - start,
                  "cpu_seconds": time.process_time() - cpu,
                  "process_peak_rss_bytes_so_far": peak_rss()}
        if isinstance(value, str):
            record["bytes"] = len(value.encode("utf8"))
            record["sha256"] = digest(value.encode("utf8"))
        stages.append(record)
        return value

    system_before = system_context()
    started, cpu_started = time.perf_counter(), time.process_time()

    def finish(image):
        wall, cpu = time.perf_counter() - started, time.process_time() - cpu_started
        result = {"stages": stages, "structure": structure, "image": image,
                  "selection": selection, "diagnostic_exports": diagnostics,
                  "wall_seconds_including_artifact_and_metric_writes": wall,
                  "cpu_seconds": cpu, "cpu_wall_ratio": cpu_wall_ratio(cpu, wall),
                  "process_peak_rss_bytes": peak_rss(), "system_before": system_before}
        result["system_after"] = system_context()
        return result

    if args.backend == "ir" and selection["ir_frontend"] == "semantic":
        from malbolge.compiler.ir.frontend import compile_python_to_semantic_ir
        from malbolge.compiler.ir.semantic import print_semantic
        from malbolge.compiler.ir.semantic_passes import run_semantic_pipeline, summarize_semantic
        from malbolge.compiler.ir.lowering import lower_semantic_to_mg
        from dataclasses import asdict
        selected = getattr(args, "semantic_passes", None)
        if isinstance(selected, str):
            selected = tuple(name.strip() for name in selected.split(",")) if selected else ()
        module = stage("python-to-semantic", lambda: compile_python_to_semantic_ir(source))
        structure["semantic_before"] = asdict(summarize_semantic(module))
        optimized = stage("semantic-passes", lambda: run_semantic_pipeline(module, selected))
        structure["semantic_passes"] = optimized.to_dict()
        structure["semantic_after"] = asdict(summarize_semantic(optimized.module))
        (directory / "program.semantic.mlir").write_text(print_semantic(optimized.module), encoding="utf8")
        legacy_arithmetic = bool(getattr(args, "legacy_arithmetic", False))
        structure["legacy_target_arithmetic"] = legacy_arithmetic
        mg = stage("semantic-to-mg", lambda: lower_semantic_to_mg(
            optimized.module, arithmetic_optimizations=legacy_arithmetic))
    elif args.backend == "c":
        c = stage("py2c", lambda: compile_python_to_c(source))
        (directory / "program.c").write_text(c, encoding="utf8")
        mg = stage("c2mg", lambda: compile_c_to_mg(c))
    else:
        mg = stage("py2mg", lambda: compile_python_to_mg(source))
    (directory / "program.mg").write_text(mg, encoding="utf8")
    structure["mg_constructs"] = text_structure(mg)
    mc = None
    if native:
        from malbolge.compiler.mg2mc import translate_mg_to_lal
        from malbolge.compiler.mc2mb import layout_lal_to_image
        from malbolge.compiler.lal_model import FlagDecl, RoutineDecl
        model = stage("mg-to-lal", lambda: translate_mg_to_lal(
            mg, op_style=args.op_style, jmp_style=args.jmp_style))
        if args.backend == "ir":
            from malbolge.compiler.ir.lal import model_to_lal, lal_to_model
            lal = stage("lal-to-xdsl", lambda: model_to_lal(model))
            model = stage("xdsl-to-lal", lambda: lal_to_model(lal))
        structure["lal_declarations"] = len(model.declarations)
        structure["lal_routine_records"] = sum(len(d.body) for d in model.declarations
                                                if isinstance(d, RoutineDecl))
        flags = Counter("%d/%d" % (d.initial, d.period) for d in model.declarations
                        if isinstance(d, FlagDecl))
        structure["mc_flags_by_initial_period"] = dict(sorted(flags.items()))
        if getattr(args, "stop_after", "mb") == "mc" or selection["diagnostic_exports"]:
            from malbolge.compiler.lal_model import emit_lal_to_mc
            # Diagnostic serialization is measured separately from assembly.
            position = len(stages)
            mc = stage("diagnostic.lal-to-mc", lambda: emit_lal_to_mc(model))
            diagnostics.extend(stages[position:])
            del stages[position:]
            (directory / "program.mc").write_text(mc, encoding="utf8")
            structure["diagnostic_mc_constructs"] = text_structure(mc)
        if getattr(args, "stop_after", "mb") == "mc":
            return finish({})
        memory_image = stage("lal-to-memory-image", lambda: layout_lal_to_image(model))
        structure["data"] = image_structure(memory_image)
        structure["assembly_handoff"] = "LalProgram->MemoryImage"
        if selection["diagnostic_exports"]:
            from malbolge.compiler.memory_image import image_to_data
            position = len(stages)
            data_export = stage("diagnostic.image-to-data", lambda: image_to_data(memory_image))
            diagnostics.extend(stages[position:])
            del stages[position:]
            (directory / "program.data").write_text(data_export, encoding="utf8")
    else:
        mc = stage("mg2mc", lambda: translate_mg_to_mc(
            mg, op_style=args.op_style, jmp_style=args.jmp_style))
        if args.backend == "ir":
            from malbolge.compiler.ir.lal import parse_mc, emit_mc
            lal = stage("mc-to-lal", lambda: parse_mc(mc))
            mc = stage("lal-to-mc", lambda: emit_mc(lal))
        (directory / "program.mc").write_text(mc, encoding="utf8")
        structure["mc_constructs"] = text_structure(mc)
        flags = Counter()
        for line in mc.splitlines():
            parts = line.split()
            if parts and parts[0] == "FLAG":
                flags[parts[1].rstrip(",")] += 1
        structure["mc_flags_by_initial_period"] = dict(sorted(flags.items()))
        if getattr(args, "stop_after", "mb") == "mc":
            return finish({})
        data = stage("mc2mb.parse_layout", lambda: parse_mc_to_data(mc))
        structure["data"] = data_structure(data)
        structure["assembly_handoff"] = "MC->data-text"
    asm = _Assembler()
    stage("mc2mb.setup_bootstrap", asm.setup_data_module)
    stage("mc2mb.generate_bootstrap", lambda: asm.memory_init_image(memory_image)
          if native else asm.memory_init_code1(data))
    structure["bootstrap_code_end"] = asm.C
    image_path = directory / "program.mb"

    def emit():
        count, sha = 0, hashlib.sha256()
        with image_path.open("wb") as stream:
            for chunk in asm.iter_finish():
                stream.write(chunk)
                sha.update(chunk)
                count += len(chunk)
        return {"bytes": count, "sha256": sha.hexdigest()}

    image = stage("mc2mb.emit", emit)
    stages[-1].update(image)
    structure["generated_source_cells"] = len(asm.code)
    structure["padding_source_cells"] = image["bytes"] - structure["generated_source_cells"]
    if mc is not None:
        structure["mb_to_mc_byte_ratio"] = image["bytes"] / len(mc.encode("utf8"))
    return finish(image)


def runtime_sample(args, directory, source, input_text):
    from malbolge.core import MalbolgeConfig, SparseMemory, parse_source, run_memory

    config = MalbolgeConfig.malbolge20()
    system_before = system_context()
    start, cpu_start = time.perf_counter(), time.process_time()
    image = (directory / "program.mb").read_bytes()
    loaded, cpu_loaded = time.perf_counter(), time.process_time()
    parsed = parse_source(image, config)
    validated, cpu_validated = time.perf_counter(), time.process_time()
    memory = SparseMemory(config)
    memory.initialize_source(parsed)
    initialized, cpu_initialized = time.perf_counter(), time.process_time()
    # Compilation objects live in a different process and cannot inflate this peak.
    gc.collect()
    executing, cpu_executing = time.perf_counter(), time.process_time()
    input_hex = getattr(args, "stdin_hex", None)
    input_bytes = bytes.fromhex(input_hex) if input_hex is not None else input_text.encode("ascii")
    result = run_memory(memory, config, input_bytes,
                        max_steps=args.max_steps, max_output=getattr(args, "max_output", 4096),
                        eof=getattr(args, "eof", "sentinel"))
    ended, cpu_ended = time.perf_counter(), time.process_time()
    system_after = system_context()
    output_hex = getattr(args, "stdout_hex", None)
    expected = bytes.fromhex(output_hex) if output_hex is not None else oracle(source, input_text)
    record = {"read_seconds": loaded - start, "parse_validate_seconds": validated - loaded,
            "initialize_seconds": initialized - validated, "execute_seconds": ended - executing,
            "prepare_gc_seconds": executing - initialized,
            "read_cpu_seconds": cpu_loaded - cpu_start,
            "parse_validate_cpu_seconds": cpu_validated - cpu_loaded,
            "initialize_cpu_seconds": cpu_initialized - cpu_validated,
            "prepare_gc_cpu_seconds": cpu_executing - cpu_initialized,
            "execute_cpu_seconds": cpu_ended - cpu_executing,
            "cpu_seconds": cpu_ended - cpu_start,
            "cpu_wall_ratio": cpu_wall_ratio(cpu_ended - cpu_start, ended - start),
            "execute_cpu_wall_ratio": cpu_wall_ratio(cpu_ended - cpu_executing, ended - executing),
            "system_before": system_before, "system_after": system_after,
            "wall_seconds": ended - start, "process_peak_rss_bytes": peak_rss(),
            "result": result.to_dict(), "output_hex": result.output.hex(),
            "expected_hex": expected.hex(),
            "passed": (result.stop_reason == "terminated" and result.output == expected
                       and (getattr(args, "expected_input_consumed", None) is None
                            or result.input_consumed == args.expected_input_consumed))}
    record["completed"] = result.stop_reason == "terminated"
    if not record["completed"]:
        partial = {key: record.pop(key) for key in list(record)
                   if key.endswith("seconds") or key.endswith("ratio")
                   or key == "process_peak_rss_bytes"}
        record["partial_diagnostics"] = {"measurements": partial,
                                         "result": result.to_dict()}
    return record


def trace_sample(args, directory, source, input_text):
    """Observe execution separately; callback overhead is never a speed sample."""
    from test.diagnostics.traced_run import run

    compiler = json.loads((directory / "compile.json").read_text())
    runtime_name = getattr(args, "runtime_record", None) or "runtime"
    runtime = json.loads((directory / (runtime_name + ".json")).read_text())
    entry = compiler["structure"]["data"]["entry_address"]
    bootstrap_end = compiler["structure"]["bootstrap_code_end"]
    observations = {"first_program_step": None, "first_output_step": None,
                    "terminal_bootstrap_jump_step": None,
                    "first_exit_bootstrap_region_step": None}
    counts = {"bootstrap": Counter(), "program": Counter()}

    def on_exec(step, address, opcode):
        terminal = observations["terminal_bootstrap_jump_step"]
        if terminal is not None and step == terminal + 1:
            observations["first_program_step"] = step
        if not 0 <= address < bootstrap_end and observations["first_exit_bootstrap_region_step"] is None:
            observations["first_exit_bootstrap_region_step"] = step
        phase = "bootstrap" if observations["first_program_step"] is None else "program"
        counts[phase][str(opcode)] += 1
        if opcode == 5 and observations["first_output_step"] is None:
            observations["first_output_step"] = step

    def on_regs(step, a, address, d):
        if address == bootstrap_end - 1 and d == entry:
            observations["terminal_bootstrap_jump_step"] = step

    result = run((directory / "program.mb").read_bytes(), input_text,
                 eof=getattr(args, "eof", "sentinel"), on_exec=on_exec, on_regs=on_regs,
                 max_steps=args.max_steps)
    # The diagnostic loop uses a zero-based stop index, unlike run_memory's
    # executed-step count. A terminating halt is itself an executed step.
    steps = result.steps + (result.reason == "end")
    return dict(observations, entry_address=entry, counts_by_opcode=counts,
                bootstrap_code_end=bootstrap_end,
                total_executed_steps=steps, output_hex=result.output.encode("latin1").hex(),
                note="Separate instrumented execution; zero-based observation indices. Current assembler's final bootstrap jump executes at C=bootstrap_code_end-1 with D=ENTRY_ADDRESS; program phase starts at the next step, checked against first exit from the bootstrap region. ENTRY_ADDRESS is a dispatch descriptor, not necessarily an executed PC. Revalidate if the bootstrap/layout strategy changes. Callback times are not speed measurements.",
                passed=(result.reason == "end" and result.output.encode("latin1") == oracle(source, input_text)
                        and steps == runtime["result"]["steps"] and observations["first_program_step"] is not None
                        and observations["first_program_step"] == observations["first_exit_bootstrap_region_step"]))


def worker(args):
    job = json.loads(args.job.read_text(encoding="utf8")) if args.job else None
    source, input_text = (job["source"], job["stdin"]) if job else CASES[args.case]
    if job:
        args.stdin_hex = job.get("stdin_hex")
        args.stdout_hex = job.get("stdout_hex")
        args.expected_input_consumed = job.get("expected_input_consumed")
    directory = Path(args.directory)
    profiler = cProfile.Profile() if args.profile else None
    if profiler:
        profiler.enable()
    if args.worker == "compile":
        result = compile_sample(args, directory, source)
    elif args.worker == "runtime":
        result = runtime_sample(args, directory, source, input_text)
    elif args.worker == "trace":
        result = trace_sample(args, directory, source, input_text)
    else:
        start, cpu_start = time.perf_counter(), time.process_time()
        output = oracle(source, input_text)
        wall, cpu = time.perf_counter() - start, time.process_time() - cpu_start
        result = {"code_seconds": wall, "code_cpu_seconds": cpu,
                  "code_cpu_wall_ratio": cpu_wall_ratio(cpu, wall), "output_hex": output.hex(),
                  "passed": output == job["stdout"].encode("ascii")}
    record = args.record or args.worker
    if profiler:
        profiler.disable()
        profiler.dump_stats(str(directory / (record + ".prof")))
        output = io.StringIO()
        pstats.Stats(profiler, stream=output).strip_dirs().sort_stats("tottime").print_stats(25)
        (directory / (record + "-profile.txt")).write_text(output.getvalue())
    result["source_hashes"] = fingerprint()
    result["source_sha256"] = digest(source.encode("utf8"))
    result["profiled"] = args.profile
    result["selection"] = selection_metadata(args)
    (directory / (record + ".json")).write_text(json.dumps(result, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", nargs="+", help="select built-in cases or manifest program IDs")
    parser.add_argument("--manifest", type=Path, help="fixed program/input/output corpus")
    parser.add_argument("--suite", choices=["smoke", "standard", "all"], help="manifest tier; defaults to smoke")
    parser.add_argument("--workloads", nargs="+", help="select named manifest inputs")
    parser.add_argument("--list", action="store_true", help="list manifest programs without compiling")
    parser.add_argument("--stop-after", choices=["mc", "mb"], default="mb", help="use mc for quick lowering-only comparisons")
    parser.add_argument("--backends", nargs="+", choices=["direct", "c", "ir"], default=["direct", "c"])
    parser.add_argument("--semantic-passes", help="IR semantic pass names; exact order, comma-separated")
    parser.add_argument("--target-pipeline", choices=["text", "structured"], default="text",
                        help="assembly handoff (default: text; structured uses native LAL/image)")
    parser.add_argument("--ir-frontend", choices=["compat", "semantic"], default="semantic",
                        help="IR source frontend (benchmark historical default: semantic)")
    parser.add_argument("--diagnostic-exports", action="store_true",
                        help="separately export native MC/data diagnostics outside compiler stage totals")
    parser.add_argument("--legacy-arithmetic", action="store_true",
                        help="IR comparison only: enable the old adapter arithmetic shortcuts")
    parser.add_argument("--styles", nargs="+", choices=["cluster/main", "cluster/direct", "inline/main", "inline/direct"], default=["cluster/main"])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--discard-images", action="store_true", help="remove generated MB images after all their inputs finish; keep hashes and reports")
    parser.add_argument("--hardware-info", type=Path, help="optional previously collected hardware JSON when system probes are restricted")
    parser.add_argument("--runtime", action="store_true", help="execute images on bounded project VM (default when producing MB)")
    parser.add_argument("--trace", action="store_true", help="with --runtime, separately count bootstrap/program opcodes (slower diagnostic execution)")
    parser.add_argument("--profile", action="store_true", help="profile samples (timings include profiler overhead)")
    parser.add_argument("--timeout", type=float, default=300, help="seconds per child process")
    parser.add_argument("--max-steps", type=int, help="override manifest budget; built-in default 150M")
    parser.add_argument("--max-output", type=int, default=4096, help="VM output byte limit (default: 4096)")
    parser.add_argument("--eof", choices=["sentinel", "stop"], default="sentinel",
                        help="VM EOF behavior (default: sentinel)")
    parser.add_argument("--worker", choices=["compile", "runtime", "trace", "oracle"], help=argparse.SUPPRESS)
    parser.add_argument("--case", help=argparse.SUPPRESS)
    parser.add_argument("--job", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--record", help=argparse.SUPPRESS)
    parser.add_argument("--runtime-record", help=argparse.SUPPRESS)
    parser.add_argument("--backend", choices=["direct", "c", "ir"], help=argparse.SUPPRESS)
    parser.add_argument("--op-style", default="cluster", help=argparse.SUPPRESS)
    parser.add_argument("--jmp-style", default="main", help=argparse.SUPPRESS)
    parser.add_argument("--directory", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.max_output < 0:
        parser.error("--max-output must be nonnegative")
    if args.worker:
        worker(args)
        return 0
    if args.stop_after == "mb":
        args.runtime = True
    if args.manifest or args.suite or args.list or args.workloads:
        from scripts.benchmark_suite import run_manifest
        try:
            return run_manifest(args, sys.modules[__name__])
        except (ValueError, OSError) as error:
            parser.error(str(error))
    args.max_steps = args.max_steps if args.max_steps is not None else 150000000
    args.cases = args.cases or ["literal", "echo", "loop", "call", "multiply"]
    if any(case not in CASES for case in args.cases):
        parser.error("unknown built-in case; use --list for the fixed corpus")
    if not args.output_dir or args.repeats < 1 or args.timeout <= 0 or args.max_steps < 0:
        parser.error("provide --output-dir, positive --repeats/--timeout and nonnegative --max-steps")
    if args.runtime and args.stop_after == "mc":
        parser.error("--runtime requires --stop-after mb")
    if args.trace and not args.runtime:
        parser.error("--trace requires --runtime")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    initial_hashes = fingerprint()
    report = {"schema_version": 1, "python": sys.version,
              "platform": " ".join((platform.system(), platform.release(), platform.machine())),
              "selection": selection_metadata(args),
              "runner_sha256": digest(Path(__file__).read_bytes()),
              "source_hashes_at_start": initial_hashes, "profiled": args.profile,
              "method": "Fresh sequential compiler and runtime processes; no compilation cache; medians of unaggregated samples. RSS is each process's cumulative high-water mark, not a stage-local peak. Timed compiler functions exclude metric/artifact writes except MB emission; compiler wall includes them. OS filesystem cache is not flushed. Runtime includes only project VM, not native reference.",
              "samples": []}
    failed = False
    for case in args.cases:
        source, input_text = CASES[case]
        for backend in args.backends:
            for style in args.styles:
                op_style, jmp_style = style.split("/")
                for repeat in range(args.repeats):
                    directory = args.output_dir / (case + "-" + backend + "-" + op_style + "-" + jmp_style + "-" + str(repeat))
                    directory.mkdir(exist_ok=False)
                    (directory / "source.py").write_text(source)
                    sample = {"case": case, "backend": backend, "style": style, "repeat": repeat,
                              "selection": selection_metadata(args),
                              "source_sha256": digest(source.encode()), "input_hex": input_text.encode().hex()}
                    tasks = ["compile"] + (["runtime"] if args.runtime else []) + (["trace"] if args.trace else [])
                    for task in tasks:
                        command = [sys.executable, str(Path(__file__).resolve()), "--worker", task,
                                   "--case", case, "--backend", backend, "--op-style", op_style,
                                   "--jmp-style", jmp_style, "--directory", str(directory),
                                   "--max-steps", str(args.max_steps), "--stop-after", args.stop_after]
                        command.extend(selection_arguments(args))
                        if args.profile:
                            command.append("--profile")
                        if args.semantic_passes is not None:
                            command.extend(["--semantic-passes", args.semantic_passes])
                        if args.legacy_arithmetic:
                            command.append("--legacy-arithmetic")
                        started = time.perf_counter()
                        try:
                            child = subprocess.run(command, capture_output=True, timeout=args.timeout)
                            path = directory / (task + ".json")
                            if child.returncode == 0 and path.exists():
                                sample[task] = json.loads(path.read_text())
                                elapsed = time.perf_counter() - started
                                if task == "runtime" and sample[task].get("result", {}).get("stop_reason") != "terminated":
                                    sample[task].setdefault("partial_diagnostics", {})["whole_process_seconds"] = elapsed
                                else:
                                    sample[task]["whole_process_seconds"] = elapsed
                                if task in ("runtime", "trace") and not sample[task]["passed"]:
                                    failed = True
                                    break
                            else:
                                sample[task] = {"error": child.stderr.decode(errors="replace")[-4000:], "returncode": child.returncode}
                                failed = True
                                break
                        except subprocess.TimeoutExpired:
                            sample[task] = {"error": "timeout", "timeout_seconds": args.timeout,
                                            "completed": False, "passed": False,
                                            "partial_diagnostics": {"whole_process_seconds": time.perf_counter() - started}}
                            failed = True
                            break
                    image_path = directory / "program.mb"
                    sample["image_retained"] = image_path.exists() and not args.discard_images
                    if args.discard_images and image_path.exists():
                        image_path.unlink()
                    report["samples"].append(sample)
                    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
                    print(json.dumps({"case": case, "backend": backend, "style": style,
                                      "repeat": repeat, "compile_seconds": sample.get("compile", {}).get("wall_seconds_including_artifact_and_metric_writes"),
                                      "mb_bytes": sample.get("compile", {}).get("image", {}).get("bytes"),
                                      "runtime": sample.get("runtime", {}).get("result", {}).get("stop_reason")}), flush=True)
    report["source_hashes_at_end"] = fingerprint()
    report["source_changed_during_run"] = report["source_hashes_at_end"] != initial_hashes
    groups = {}
    for sample in report["samples"]:
        groups.setdefault((sample["case"], sample["backend"], sample["style"]), []).append(sample)
    report["medians"] = []
    for (case, backend, style), samples in groups.items():
        summary = {"case": case, "backend": backend, "style": style}
        for task, field in (("compile", "wall_seconds_including_artifact_and_metric_writes"), ("runtime", "execute_seconds")):
            values = [sample[task][field] for sample in samples if field in sample.get(task, {})
                      and (task != "runtime" or completed_runtime(sample[task]))]
            if values:
                summary[task + "_seconds"] = statistics.median(values)
        report["medians"].append(summary)
    report["all_requested_samples_passed"] = not failed
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
