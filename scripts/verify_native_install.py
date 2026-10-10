#!/usr/bin/env python
"""Check an installed wheel from outside the checkout, without test extras.

Example: uv run --no-project --python /tmp/env/bin/python
    scripts/verify_native_install.py --require-native --forbid-source-root .
This is a correctness smoke check, not a performance benchmark.
"""
import argparse
from array import array
import hashlib
from importlib import import_module, metadata
from importlib.machinery import EXTENSION_SUFFIXES
import json
import os
from pathlib import Path
import platform
import sys
import sysconfig


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def instruction(opcode, address):
    return 33 + (opcode - address - 33) % 94


def program(*opcodes):
    return bytes(instruction(opcode, address)
                 for address, opcode in enumerate(opcodes))


def verify(args, report):
    import malbolge
    from malbolge import native, run, run20
    from malbolge.core import ENCRYPT, MalbolgeConfig, SparseMemory, run_memory

    forbidden = args.forbid_source_root
    if forbidden:
        check(not inside(Path.cwd(), forbidden), "smoke cwd is inside the checkout")
    modules = [malbolge, import_module("malbolge.core"), native]
    available = native.native_available()
    report["native_available"] = available
    check(available or not args.require_native, "required native extension is missing")
    check(not available or not args.require_pure, "pure fallback artifact contains a native extension")
    if available:
        modules.append(import_module("malbolge._native_vm"))
    report["modules"] = {}
    for module in modules:
        path = Path(module.__file__).resolve()
        check(inside(path, sys.prefix), "{} is outside the installation environment: {}".format(module.__name__, path))
        if forbidden:
            check(not inside(path, forbidden), "{} was imported from the checkout".format(module.__name__))
        report["modules"][module.__name__] = {
            "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    distribution = metadata.distribution("malbolge")
    check(inside(distribution.locate_file(""), sys.prefix), "distribution metadata is outside the installation environment")
    report["version"] = distribution.version
    report["wheel_metadata"] = distribution.read_text("WHEEL")
    if available:
        extension_path = report["modules"]["malbolge._native_vm"]["path"]
        check(any(extension_path.endswith(suffix) for suffix in EXTENSION_SUFFIXES), "native VM is not a compiled extension")
        wheel_metadata = report["wheel_metadata"] or ""
        check("Root-Is-Purelib: false" in wheel_metadata, "native artifact is marked as a pure wheel")
        tags = [line[5:].strip() for line in wheel_metadata.splitlines() if line.startswith("Tag: ")]
        check(tags and all(not tag.endswith("-none-any") for tag in tags), "native artifact has a universal pure-Python wheel tag")
    elif args.require_pure:
        wheel_metadata = report["wheel_metadata"] or ""
        check("Root-Is-Purelib: true" in wheel_metadata and "Tag: py3-none-any" in wheel_metadata, "pure fallback wheel metadata is incorrect")
    report["checks"] = []

    source = program(23, 5, 23, 5, 81)
    expected = run20(source, b"\x00\xff", engine="python")
    check(expected.output == b"\x00\xff", "Python byte I/O oracle failed")
    check(run20(source, b"\x00\xff") == expected, "default auto engine differs from Python")
    check(native.resolve_engine() == ("native" if available else "python"), "auto selected the wrong engine")
    if available:
        check(run20(source, b"\x00\xff", engine="native") == expected, "explicit native engine differs from Python")
    report["checks"].append("installed import and default auto selection")
    original = run(program(23, 5, 81), b"", eof="sentinel")
    check(original.stop_reason == "terminated" and original.output == b"\xa8",
          "Original Malbolge's Python path or EOF 59048 changed")
    check(run(program(23, 5, 81), b"\xff").output == b"\xff",
          "Original Malbolge byte I/O failed in the installed package")
    report["checks"].append("Original Malbolge Python byte I/O and EOF contract")
    if not available:
        check(not args.require_jit, "required JIT extension is missing")
        report["jit"] = {"status": "unavailable: no native extension"}
        return

    config = MalbolgeConfig.malbolge20()

    def pair(source, writes=()):
        python = SparseMemory(config)
        python.initialize_source(source)
        compiled = native.NativeMemory(source)
        for address, value in writes:
            python[address] = compiled[address] = value
        return python, compiled

    def pages(python, compiled):
        expected = {
            number: (array("I", list(block.values)).tobytes(), bytes(block.written))
            for number, block in python._blocks.items()
        }
        check(compiled.export_pages() == expected, "native memory cells/write masks differ")
        check(compiled.get_allocated_count() == python.get_allocated_count(), "native allocation accounting differs")

    def differential(source, data=b"", writes=(), jit=False, **limits):
        python, compiled = pair(source, writes)
        expected = run_memory(python, config, data, **limits)
        actual = native.run_memory(compiled, data, jit=jit, **limits)
        check(actual == expected, "VM result/registers/budgets differ: {} != {}".format(actual, expected))
        pages(python, compiled)
        return actual, compiled

    for data in (b"\x00\xff", bytearray(b"AZ"), memoryview(b"XY"), "é"):
        result, _ = differential(source, data)
        check(result.output == (data.encode("utf8") if isinstance(data, str) else bytes(data)), "input bytes were changed")
    for eof, reason in (("stop", "input_exhausted"), ("sentinel", "terminated")):
        result, _ = differential(program(23, 5, 81), eof=eof)
        check(result.stop_reason == reason, "EOF policy was changed")
    for budget in (0, 1, 2, 3, 5):
        differential(source, b"AB", max_steps=budget)
    result, _ = differential(source, b"AB", max_output=1)
    check(result.stop_reason == "output_limit" and result.output == b"A", "output budget was ignored")
    result, _ = differential(b"", max_steps=5)
    check(result.stop_reason == "invalid_instruction", "invalid instruction was accepted")
    report["checks"].append("byte input, EOF, exact budgets and invalid instruction parity")

    python, compiled = pair(program(68, 81), ((4097, 123), (config.memory_size - 1, 456)))
    reference, snapshot = python.copy(), compiled.copy()
    detached = compiled.export_pages()
    python[4097] = compiled[4097] = 789
    reference[4098] = snapshot[4098] = 321
    pages(python, compiled)
    pages(reference, snapshot)
    check(snapshot[4097] == 123 and compiled[4098] == python[4098], "COW snapshots share mutations")
    check(detached != compiled.export_pages() and detached != snapshot.export_pages(), "page exports changed with their owner")
    result, memory = differential(program(68, 68, 81))
    check(result.stop_reason == "terminated", "self-encrypting program did not halt")
    check(memory[0] == ENCRYPT[program(68)[0] - 33], "NOP did not encrypt itself")
    # MOVD redirects ROT into future code, which must subsequently be rejected.
    future = bytearray(instruction(68, i) for i in range(128))
    for address, opcode in enumerate((40, 40, 39)):
        future[address] = instruction(opcode, address)
    result, _ = differential(bytes(future), writes=((41, 79),), max_steps=128)
    check(result.stop_reason == "invalid_instruction" and result.c == 80, "mutation of future code was ignored")
    report["checks"].append("COW pages, detached exports and self-modifying future code")

    jit_available = native.jit_available()
    report["jit"] = {"available": jit_available}
    check(jit_available or not args.require_jit, "required ARM64 machine-code JIT is unavailable")
    check(not jit_available or not args.expect_no_jit, "unexpected JIT capability on this platform")
    if jit_available:
        nops = bytes(instruction(68, i) for i in range(4097))
        result, memory = differential(nops, jit=True, max_steps=len(nops))
        stats = memory.jit_stats()
        check(stats["enabled"] and stats["jit_steps"] > 0 and stats["jit_blocks"] > 0, "JIT used only scalar fallback")
        check(stats["jit_steps"] + stats["fallback_steps"] == result.steps, "JIT coverage accounting differs")
        differential(bytes(future), writes=((41, 79),), jit=True, max_steps=128)
        report["jit"].update(status="machine code executed", stats=stats)
        report["checks"].append("JIT machine-code execution and self-modification parity")
    else:
        try:
            run20(program(81), engine="jit")
        except RuntimeError:
            pass
        else:
            raise RuntimeError("explicit unsupported JIT silently succeeded")
        report["jit"]["status"] = "unsupported; explicit engine rejected"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    artifact = parser.add_mutually_exclusive_group()
    artifact.add_argument("--require-native", action="store_true")
    artifact.add_argument("--require-pure", action="store_true")
    policy = parser.add_mutually_exclusive_group()
    policy.add_argument("--require-jit", action="store_true")
    policy.add_argument("--expect-no-jit", action="store_true")
    parser.add_argument("--forbid-source-root", type=Path)
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--report", type=Path)
    output.add_argument("--report-dir", type=Path)
    args = parser.parse_args()
    report = {
        "status": "failed", "python": sys.version, "executable": sys.executable,
        "prefix": sys.prefix, "platform": platform.platform(),
        "machine": platform.machine(), "soabi": sysconfig.get_config_var("SOABI"),
        "build_identifier": os.environ.get("CIBUILDWHEEL_BUILD_IDENTIFIER"),
        "source_commit": os.environ.get("GITHUB_SHA"),
        "workflow_run": os.environ.get("GITHUB_RUN_ID"),
        "workflow_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
    }
    try:
        verify(args, report)
        report["status"] = "passed"
    except Exception as error:
        report["error"] = "{}: {}".format(type(error).__name__, error)
    text = json.dumps(report, indent=2, sort_keys=True)
    destination = args.report
    if args.report_dir:
        identifier = report["build_identifier"] or "{}-{}-{}".format(sys.implementation.cache_tag, sys.platform, platform.machine())
        destination = args.report_dir / (identifier + ".json")
    if destination:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text + "\n", encoding="utf8")
    print(text)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
