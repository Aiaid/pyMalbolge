"""Hatchling wheel hook for an optional freshly compiled CPython extension."""
import os
from pathlib import Path
import runpy
import sys
import tempfile

from hatchling.builders.hooks.plugin.interface import BuildHookInterface
from packaging.tags import parse_tag, sys_tags


# Load this exact sibling file without importing malbolge or requiring the
# project's root on sys.path. run_path does not write source-tree bytecode.
_helper = runpy.run_path(str(Path(__file__).with_name("native_build.py")))
NativeBuildError = _helper["NativeBuildError"]
build_native_extension = _helper["build_native_extension"]


def _validate_wheel_tag(record):
    value = record.get("wheel_tag")
    valid = False
    if isinstance(value, str):
        try:
            tags = parse_tag(value)
        except ValueError:
            tags = set()
        if len(tags) == 1:
            tag = next(iter(tags))
            valid = (tag.interpreter.startswith("cp") and
                     tag.abi not in ("none", "abi3") and tag.platform != "any" and
                     not tag.platform.startswith(("manylinux", "musllinux")) and
                     tag in sys_tags())
    if not valid:
        raise RuntimeError("Native build produced an invalid or incompatible wheel tag: {!r}".format(value))
    return value


class NativeBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def _cleanup(self):
        staging = getattr(self, "_native_staging", None)
        if staging is not None:
            staging.cleanup()
            self._native_staging = None

    def initialize(self, version, build_data):
        self._cleanup()
        if self.target_name != "wheel":
            return
        mode = os.environ.get("MALBOLGE_NATIVE_BUILD", "auto")
        if mode not in ("auto", "required", "disabled"):
            raise ValueError("MALBOLGE_NATIVE_BUILD must be auto, required or disabled (got {!r})".format(mode))
        if mode == "disabled":
            print("Native VM build disabled; producing a pure Python wheel", file=sys.stderr)
            return
        if version == "editable":
            message = ("Editable installs do not compile the native VM; "
                       "run uv run --with setuptools --with wheel python scripts/build_native_vm.py "
                       "to build it explicitly in the checkout")
            if mode == "required":
                raise RuntimeError("MALBOLGE_NATIVE_BUILD=required: " + message)
            print(message, file=sys.stderr)
            return

        self._native_staging = tempfile.TemporaryDirectory(prefix="malbolge-wheel-native-")
        try:
            try:
                record = build_native_extension(self.root, self._native_staging.name)
            except NativeBuildError as error:
                if mode == "required":
                    raise RuntimeError("MALBOLGE_NATIVE_BUILD=required: " + str(error)) from error
                print("Native VM unavailable; producing a pure Python wheel:\n" + str(error), file=sys.stderr)
                self._cleanup()
                return
            binary = Path(record["binary"])
            # Do not swallow missing-file or packaging/file-selection errors
            # as optional compilation failures.
            if not binary.is_file():
                raise FileNotFoundError("Native build artifact is missing: " + str(binary))
            tag = _validate_wheel_tag(record)
            build_data["force_include"][str(binary)] = "malbolge/" + binary.name
            build_data["pure_python"] = False
            build_data["infer_tag"] = True
            # Setuptools computes CPython ABI/platform tags from the current
            # interpreter and, on macOS, the built Mach-O deployment target.
            # Hatch's host-version inference alone would overstate that floor.
            build_data["tag"] = tag
            print("Built native VM extension: " + binary.name, file=sys.stderr)
        except BaseException:
            self._cleanup()
            raise

    def finalize(self, version, build_data, artifact_path):
        self._cleanup()

    def clean(self, versions):
        self._cleanup()
