#!/usr/bin/env python
"""Exercise a distribution installed into this interpreter's environment.

Copy this stdlib-only helper outside the checkout, then run it using the
installed environment's interpreter (preferably with ``-I``). No repository
fixtures, test dependencies, native compiler, or network are used. Each guest
execution is bounded and each subprocess has a 90-second timeout.
"""

import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import subprocess
import sys
import tempfile


class VerificationError(RuntimeError):
    """An installed release did not satisfy an acceptance contract."""


def require(condition, message):
    if not condition:
        raise VerificationError(message)


def is_within(path, root):
    path, root = Path(path).resolve(), Path(root).resolve()
    return path == root or root in path.parents


def last_json_object(stderr):
    """Compiler progress precedes its final JSON metrics line on stderr."""
    for line in reversed(stderr.splitlines()):
        try:
            result = json.loads(line)
        except (ValueError, UnicodeError):
            continue
        if isinstance(result, dict):
            return result
    raise VerificationError("CLI did not emit a JSON metrics object on stderr")


def cli(directory, arguments, expected_code=0):
    command = [sys.executable, "-I", "-m", "malbolge"] + list(arguments)
    process = subprocess.run(command, cwd=str(directory), capture_output=True,
                             timeout=90)
    require(process.returncode == expected_code,
            "CLI exited {} (expected {}): {}\n{}".format(
                process.returncode, expected_code, " ".join(arguments),
                process.stderr.decode("utf8", errors="replace")[-6000:]))
    return process


def original_program():
    # Self-authored straight-line input/output repeated three times, then halt.
    # A printable cell at address i decodes to (cell + i) % 94.
    opcodes = [23, 5, 23, 5, 23, 5, 81]
    return bytes((opcode - address - 33) % 94 + 33
                 for address, opcode in enumerate(opcodes))


def execute_image(directory, image, engine="python"):
    process = cli(directory, ["--variant=malbolge20", image,
                             "--engine=" + engine, "--input", "",
                             "--max-steps", "5000000", "--max-output", "64",
                             "--stats"])
    require(process.stdout == b"Hello, world!\n", "compiled output differs")
    stats = last_json_object(process.stderr)
    require(stats.get("stop_reason") == "terminated", "compiled program did not halt")
    require(stats.get("requested_engine") == engine, "requested engine not recorded")
    if engine != "auto":
        require(stats.get("engine") == engine, "requested execution engine not used")
    return stats


def verify(args):
    import malbolge
    from malbolge import native

    package = Path(malbolge.__file__).resolve().parent
    require(is_within(package, sys.prefix), "malbolge import is outside sys.prefix")
    require(not is_within(package, args.forbid_source_root),
            "malbolge imported from the forbidden source checkout")
    installed_version = metadata.version("malbolge")
    require(installed_version == malbolge.__version__ == args.expected_version,
            "version mismatch: metadata={!r}, module={!r}, expected={!r}".format(
                installed_version, malbolge.__version__, args.expected_version))
    available = native.native_available()
    require(not args.require_native or available, "required native VM is unavailable")
    require(not args.require_pure or not available, "pure installation exposes a native VM")
    report = {
        "success": True, "version": installed_version,
        "python": sys.version, "executable": sys.executable,
        "prefix": sys.prefix, "module_path": str(package),
        "forbid_source_root": str(Path(args.forbid_source_root).resolve()),
        "native_available": available, "require_ir": args.require_ir,
        "compilations": {},
    }
    with tempfile.TemporaryDirectory(prefix="malbolge-installed-") as temporary:
        directory = Path(temporary)
        require(not is_within(directory, args.forbid_source_root),
                "temporary smoke directory is inside the source checkout")
        (directory / "hello.py").write_text('print("Hello, world!")\n', encoding="utf8")
        variants = [("auto", []), ("direct", ["--backend=direct"])]
        if args.require_ir:
            variants.append(("ir", ["--backend=ir"]))
        for name, options in variants:
            image = "hello-{}.mb".format(name)
            process = cli(directory, ["compile", "hello.py", "-O3", "--no-cache",
                                      "-o", image, "--stats"] + options)
            stats = last_json_object(process.stderr)
            require(stats.get("cache", {}).get("mode") == "disabled",
                    "--no-cache did not disable the compiler cache")
            artifact = (directory / image).read_bytes()
            report["compilations"][name] = {
                "compiler": stats, "runtime": execute_image(directory, image),
                "image_bytes": len(artifact),
                "image_sha256": hashlib.sha256(artifact).hexdigest(),
            }
        auto_stats = execute_image(directory, "hello-auto.mb", "auto")
        require(auto_stats.get("engine") == ("native" if available else "python"),
                "auto engine did not select the available VM")
        report["auto_runtime"] = auto_stats

        (directory / "byte-io.mal").write_bytes(original_program())
        (directory / "input.bin").write_bytes(b"\x00\xffA")
        original_args = ["byte-io.mal", "--input-file", "input.bin", "--stats",
                         "--max-steps", "20", "--max-output", "3"]
        process = cli(directory, original_args)
        require(process.stdout == b"\x00\xffA", "Original Malbolge byte I/O differs")
        original_stats = last_json_object(process.stderr)
        require(original_stats.get("stop_reason") == "terminated", "Original VM did not halt")
        report["original_runtime"] = original_stats
        report["original_output_hex"] = process.stdout.hex()
        report["budget_contracts"] = {}
        for name, options, reason, output in (
                ("steps", ["--max-steps", "0"], "step_limit", b""),
                ("output", ["--max-output", "1"], "output_limit", b"\x00")):
            process = cli(directory, original_args + options, expected_code=3)
            stats = last_json_object(process.stderr)
            require(process.stdout == output and stats.get("stop_reason") == reason,
                    "{} budget contract differs".format(name))
            report["budget_contracts"][name] = stats
    # Hash the installed source and extension files, never checkout files or pyc.
    report["module_sha256"] = {
        str(path.relative_to(package)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(package.rglob("*"))
        if path.is_file() and path.suffix in (".py", ".so", ".pyd", ".dll", ".dylib")
    }
    return report


def write_report(path, report):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--forbid-source-root", required=True)
    parser.add_argument("--report", required=True)
    policy = parser.add_mutually_exclusive_group()
    policy.add_argument("--require-native", action="store_true")
    policy.add_argument("--require-pure", action="store_true")
    parser.add_argument("--require-ir", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = verify(args)
    except (VerificationError, subprocess.TimeoutExpired, ImportError) as error:
        report = {"success": False, "error": str(error), "error_type": type(error).__name__,
                  "expected_version": args.expected_version, "python": sys.version}
        write_report(args.report, report)
        parser.exit(1, "installed release verification failed: {}\n".format(error))
    write_report(args.report, report)
    print(json.dumps({"success": True, "version": report["version"],
                      "python": sys.version.split()[0],
                      "native_available": report["native_available"],
                      "require_ir": args.require_ir, "report": str(Path(args.report).resolve())}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
