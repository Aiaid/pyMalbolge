"""Shared, build-time-only compiler adapter for the optional CPython VM.

No package import or checkout binary is needed. Setuptools supplies platform
compiler/SDK discovery and Python's extension linking rules; Hatchling owns
distribution metadata and file selection. This module also runs as a private
worker process so compiler output cannot corrupt the developer JSON receipt.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shlex
import struct
import subprocess
import sys
import sysconfig
import tempfile
import time


class NativeBuildError(RuntimeError):
    """An optional native compilation could not be completed."""


def _source_hashes(root, dependencies):
    return {
        str(path.relative_to(root)).replace(os.sep, "/"):
        hashlib.sha256(path.read_bytes()).hexdigest()
        for path in dependencies
    }


def build_native_extension(root, output_dir, compiler=None):
    """Build a fresh extension into output_dir and return a provenance receipt.

    ``compiler`` is an optional Unix CC executable/command override. The standard
    compiler environment (CC, CFLAGS, CPPFLAGS, LDFLAGS, ARCHFLAGS, SDKROOT,
    MACOSX_DEPLOYMENT_TARGET, and Windows SDK discovery) remains available to
    setuptools. Cross-compilation and custom Windows CC overrides are rejected
    until their output/tag contracts are validated. Temporary products are
    removed on success and failure; an
    existing destination binary is replaced only after a successful build.
    """
    root = Path(root).resolve()
    output_dir = Path(output_dir).resolve()
    if sys.implementation.name != "cpython":
        raise NativeBuildError("The native VM currently requires CPython")
    if sys.platform not in ("darwin", "linux", "win32"):
        raise NativeBuildError("The native VM build supports macOS, Linux and Windows")
    source = root / "malbolge" / "_native_vm.c"
    dependencies = [source, root / "malbolge" / "_native_jit.h"]
    for path in dependencies:
        if not path.is_file():
            raise NativeBuildError("Native VM source is missing: " + str(path))
    suffix = sysconfig.get_config_var("EXT_SUFFIX")
    include = sysconfig.get_path("include")
    if not suffix or not include or not (Path(include) / "Python.h").is_file():
        raise NativeBuildError("This Python interpreter's extension headers are unavailable")

    try:
        source_hashes = _source_hashes(root, dependencies)
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / ("_native_vm" + suffix)
        environment = os.environ.copy()
        if compiler is not None:
            environment["CC"] = compiler
        if sys.platform == "darwin":
            # Python.org's universal2 interpreter may default to both slices.
            # Source installs build only this running host, just as the CI
            # native-architecture configuration does. Keep this default local
            # to the worker, and preserve explicit caller overrides.
            environment.setdefault("ARCHFLAGS", "-arch " + platform.machine().lower())
        # Do not generate __pycache__ in an sdist or a read-only checkout.
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        with tempfile.TemporaryDirectory(prefix=".native-build-", dir=str(output_dir)) as directory:
            temporary = Path(directory)
            record_path = temporary / "compiler.json"
            command = [sys.executable, str(Path(__file__).resolve()),
                       str(root), str(temporary), str(record_path)]
            start = time.perf_counter()
            completed = subprocess.run(command, cwd=str(temporary), env=environment,
                                       capture_output=True, timeout=120)
            elapsed = time.perf_counter() - start
            diagnostics = (completed.stdout + completed.stderr).decode("utf8", errors="replace")
            if completed.returncode:
                raise NativeBuildError("Native VM build failed:\n" + diagnostics.strip())
            record = json.loads(record_path.read_text(encoding="utf8"))
            staged = Path(record.pop("binary"))
            if not staged.is_file() or staged.name != target.name:
                raise NativeBuildError("The native compiler did not produce the expected extension")
            if _source_hashes(root, dependencies) != source_hashes:
                raise NativeBuildError("Native VM source changed during compilation; retry after edits finish")
            binary_hash = hashlib.sha256(staged.read_bytes()).hexdigest()
            os.replace(str(staged), str(target))
        record.update({
            "schema_version": 1,
            "python": sys.version,
            "extension_suffix": suffix,
            "source_sha256": source_hashes["malbolge/_native_vm.c"],
            "source_hashes": source_hashes,
            "binary_sha256": binary_hash,
            "binary": str(target),
            "build_wall_seconds": elapsed,
            "diagnostics": diagnostics,
        })
        return record
    except (OSError, subprocess.TimeoutExpired) as error:
        raise NativeBuildError("Native VM build failed: " + str(error)) from error


def _validate_host_target():
    """Keep this initial wheel builder scoped to the running host ABI."""
    supplied_platform = os.environ.pop("_PYTHON_HOST_PLATFORM", None)
    try:
        host_platform = sysconfig.get_platform()
    finally:
        if supplied_platform is not None:
            os.environ["_PYTHON_HOST_PLATFORM"] = supplied_platform
    if supplied_platform is not None and supplied_platform != host_platform:
        # cibuildwheel uses a universal2 Python.org interpreter for thin
        # native builds, and sets this override to the requested host slice.
        # A deployment-version difference does not imply cross-compilation.
        macos_target = re.fullmatch(r"macosx-\d+(?:\.\d+)*-(arm64|x86_64)", supplied_platform)
        native_macos = (sys.platform == "darwin" and macos_target is not None and
                        macos_target.group(1) == platform.machine().lower())
        if not native_macos:
            raise NativeBuildError("Cross-target _PYTHON_HOST_PLATFORM is not supported")
    if os.environ.get("_PYTHON_SYSCONFIGDATA_NAME"):
        raise NativeBuildError("Custom target Python sysconfig data is not supported")
    if os.name == "nt":
        if os.environ.get("CC"):
            raise NativeBuildError("Custom CC overrides are not supported with MSVC; use standard Visual Studio discovery")
        return
    host_arch = platform.machine().lower()
    for variable in ("ARCHFLAGS", "CFLAGS", "CPPFLAGS", "LDFLAGS", "CC", "LDSHARED"):
        flags = shlex.split(os.environ.get(variable, ""))
        for index, flag in enumerate(flags):
            if flag == "-arch":
                architecture = flags[index + 1] if index + 1 < len(flags) else ""
                if architecture.lower() != host_arch:
                    raise NativeBuildError("Cross-target architecture in {} is not supported: {}".format(variable, architecture))
            if flag in ("-target", "--target") or flag.startswith(("--target=", "-target=")):
                raise NativeBuildError("Explicit target triples in {} are not supported".format(variable))
            if flag in ("-m32", "-m64") and int(flag[2:]) != struct.calcsize("P") * 8:
                raise NativeBuildError("Cross-target pointer width in {} is not supported".format(variable))


def _macos_native_tag(binary, wheel_tag):
    """Use the new extension's thin Mach-O architecture, not Python's slices.

    The standard wheel tag already incorporates the actual deployment floor.
    Its architecture can still say universal2 when Python is universal2 but
    ARCHFLAGS selected one slice. Mach-O's fixed 64-bit header distinguishes
    that case from an actual fat binary without requiring a separate tool.
    """
    with Path(binary).open("rb") as stream:
        header = stream.read(32)
    byte_orders = {b"\xcf\xfa\xed\xfe": "<", b"\xfe\xed\xfa\xcf": ">"}
    byte_order = byte_orders.get(header[:4])
    if byte_order is None or len(header) != 32:
        raise NativeBuildError("Expected a thin 64-bit Mach-O extension; fat/universal or invalid binaries are unsupported")
    fields = struct.unpack(byte_order + "8I", header)
    cpu_type, cpu_subtype = fields[1], fields[2] & 0x00ffffff
    architecture = {(0x01000007, 3): "x86_64", (0x0100000c, 0): "arm64"}.get((cpu_type, cpu_subtype))
    if architecture is None or architecture != platform.machine().lower():
        raise NativeBuildError("Mach-O extension architecture does not match the running host")
    match = re.fullmatch(r"([^-]+-[^-]+-macosx_\d+_\d+)_[a-zA-Z0-9_]+", wheel_tag)
    if match is None:
        raise NativeBuildError("Unexpected macOS wheel tag: " + wheel_tag)
    return match.group(1) + "_" + architecture


def _compile_extension(root, temporary):
    """Worker implementation; intentionally imported only at build time."""
    try:
        from setuptools import Distribution, Extension
        from setuptools.command.build_ext import build_ext
        try:
            from setuptools.command.bdist_wheel import bdist_wheel
        except ImportError:
            from wheel.bdist_wheel import bdist_wheel
    except ImportError as error:
        raise NativeBuildError(
            "setuptools and wheel are required to build the native VM; run "
            "uv run --with setuptools --with wheel python scripts/build_native_vm.py"
        ) from error

    _validate_host_target()
    commands = []

    class NativeBuildExt(build_ext):
        def build_extensions(self):
            # Defaults are portable within each compiler family, without
            # host-specific CPU tuning. SDK, architecture and linker options
            # still come from Python/setuptools and the caller's environment.
            flags = ["/O2", "/std:c11"] if self.compiler.compiler_type == "msvc" else ["-O3", "-std=c99"]
            for extension in self.extensions:
                extension.extra_compile_args = flags
            # Setuptools 84 uses call(); older compatible releases use
            # spawn(). Wrap the active entry point without replacing its
            # platform-specific environment and command handling.
            executor_name = "call" if hasattr(self.compiler, "call") else "spawn"
            execute = getattr(self.compiler, executor_name)

            def record_spawn(command, **kwargs):
                commands.append([str(argument) for argument in command])
                return execute(command, **kwargs)

            setattr(self.compiler, executor_name, record_spawn)
            super().build_extensions()

    extension = Extension(
        "malbolge._native_vm",
        sources=[str(root / "malbolge" / "_native_vm.c")],
        depends=[str(root / "malbolge" / "_native_jit.h")],
    )
    distribution = Distribution({"name": "malbolge-native-build", "ext_modules": [extension]})
    command = NativeBuildExt(distribution)
    command.build_temp = str(temporary / "objects")
    command.build_lib = str(temporary / "lib")
    command.inplace = False
    command.force = True
    command.ensure_finalized()
    command.run()
    binary = Path(command.get_ext_fullpath(extension.name)).resolve()
    # Verify the freshly built module itself, without importing the package.
    # A cross-target/incompatible extension must not receive a host wheel tag.
    specification = importlib.util.spec_from_file_location("_native_vm", str(binary))
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    wheel_command = bdist_wheel(distribution)
    wheel_command.bdist_dir = command.build_lib
    # get_tag needs finalized options, but no egg-info or distribution build.
    wheel_command.dist_info_dir = str(temporary / "dist-info")
    wheel_command.ensure_finalized()
    wheel_tag = "-".join(wheel_command.get_tag())
    if sys.platform == "darwin":
        wheel_tag = _macos_native_tag(binary, wheel_tag)
    compiler = commands[0][0] if commands else "unknown"
    try:
        version_command = [compiler] if command.compiler.compiler_type == "msvc" else [compiler, "--version"]
        version_result = subprocess.run(version_command, capture_output=True, timeout=10)
        compiler_version = (version_result.stdout + version_result.stderr).decode("utf8", errors="replace").strip()
    except (OSError, subprocess.TimeoutExpired):
        compiler_version = "unavailable"
    return {
        "binary": str(binary),
        "compiler": compiler,
        "compiler_type": command.compiler.compiler_type,
        "compiler_version": compiler_version,
        # Full effective arguments, including Python/SDK/environment options.
        "compiler_flags": commands[0][1:] if commands else [],
        "compiler_argv": commands,
        "wheel_tag": wheel_tag,
    }


if __name__ == "__main__":
    # This private entry point is invoked only by build_native_extension.
    try:
        result = _compile_extension(Path(sys.argv[1]), Path(sys.argv[2]))
        Path(sys.argv[3]).write_text(json.dumps(result), encoding="utf8")
    except Exception as error:
        sys.exit("{}: {}".format(type(error).__name__, error))
