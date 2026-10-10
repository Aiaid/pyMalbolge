"""Build the optional VM extension for the Python selected by uv.

Usage: uv run python scripts/build_native_vm.py
This developer prototype builds locally; distributable native wheels are
separate work. Pure Python wheels/sdists exclude these local binary products.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]


def build(output_dir=None, compiler=None):
    source = ROOT / "malbolge/_native_vm.c"
    dependencies = [source]
    jit_header = ROOT / "malbolge/_native_jit.h"
    if jit_header.is_file():
        dependencies.append(jit_header)
    source_hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in dependencies}
    suffix = sysconfig.get_config_var("EXT_SUFFIX")
    include = Path(sysconfig.get_path("include"))
    if not source.is_file():
        raise RuntimeError("Native VM source is missing: " + str(source))
    if not suffix or not (include / "Python.h").is_file():
        raise RuntimeError("This Python interpreter's extension headers are unavailable")
    if os.name != "posix":
        raise RuntimeError("This prototype builder currently supports macOS and Linux")
    selected = compiler or shlex.split(sysconfig.get_config_var("CC") or "cc")[0]
    executable = shutil.which(selected)
    if executable is None:
        raise RuntimeError("C compiler is unavailable: " + selected)
    directory = Path(output_dir).resolve() if output_dir else ROOT / "malbolge"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / ("_native_vm" + suffix)
    command = [executable, "-O3", "-std=c99", "-fPIC", "-I" + str(include)]
    plat_include = sysconfig.get_path("platinclude")
    if plat_include and plat_include != str(include):
        command.append("-I" + plat_include)
    if sys.platform == "darwin":
        command.extend(["-bundle", "-undefined", "dynamic_lookup"])
    else:
        command.append("-shared")
    with tempfile.TemporaryDirectory(prefix=".native-build-", dir=str(directory)) as temporary:
        staged = Path(temporary) / target.name
        argv = command + [str(source), "-o", str(staged)]
        start = time.perf_counter()
        completed = subprocess.run(argv, capture_output=True, timeout=120)
        elapsed = time.perf_counter() - start
        if completed.returncode:
            raise RuntimeError("Native VM build failed:\n" +
                               completed.stderr.decode("utf8", errors="replace"))
        current_hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in dependencies}
        if current_hashes != source_hashes:
            raise RuntimeError("Native VM source changed during compilation; retry after edits finish")
        os.replace(str(staged), str(target))
    version = subprocess.run([executable, "--version"], capture_output=True,
                             timeout=10).stdout.decode("utf8", errors="replace").strip()
    record = {"schema_version": 1, "python": sys.version,
              "extension_suffix": suffix, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "source_hashes": source_hashes,
              "binary_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
              "binary": str(target), "compiler": executable, "compiler_version": version,
              "compiler_flags": command[1:], "build_wall_seconds": elapsed,
              "diagnostics": completed.stderr.decode("utf8", errors="replace")}
    receipt_dir = ROOT / "build/native-vm" / (sysconfig.get_config_var("SOABI") or "unknown")
    receipt_dir.mkdir(parents=True, exist_ok=True)
    (receipt_dir / "build.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, help="default: repository malbolge directory")
    parser.add_argument("--cc", help="compiler executable; default: this Python's CC")
    args = parser.parse_args(argv)
    try:
        record = build(args.output_dir, args.cc)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        parser.exit(1, str(error) + "\n")
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
