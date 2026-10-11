#!/usr/bin/env python3
"""Stamp a disposable CI checkout with a unique TestPyPI development version.

Run with Python 3.11+ (stdlib tomllib). The stable repository version is not
bumped: only the supplied checkout's static project version is rewritten.
"""

import argparse
import copy
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

try:
    import tomllib
except ImportError:
    tomllib = None


BASE_VERSION = "1.0.1"
_DECIMAL = re.compile(r"[0-9]+\Z")
_VERSION_LINE = re.compile(
    r"^[ \t]*version[ \t]*=[ \t]*(?P<quote>['\"])(?P<value>[^'\"\r\n]*)"
    r"(?P=quote)[ \t]*(?:\#[^\r\n]*)?(?:\r?\n|\Z)", re.MULTILINE
)


def development_version(run_id, attempt):
    """Return an injective version stamp for positive run IDs and attempts 1..999."""
    values = []
    for label, value in (("run ID", run_id), ("attempt", attempt)):
        if not isinstance(value, str) or not _DECIMAL.fullmatch(value):
            raise ValueError("%s must be a positive decimal integer" % label)
        number = int(value)
        if number <= 0:
            raise ValueError("%s must be a positive decimal integer" % label)
        values.append(number)
    run_number, attempt_number = values
    if attempt_number > 999:
        raise ValueError("attempt must be between 1 and 999")
    return {
        "base_version": BASE_VERSION,
        "test_version": "%s.dev%d" % (
            BASE_VERSION, run_number * 1000 + attempt_number
        ),
        "run_id": run_number,
        "attempt": attempt_number,
    }


def replace_project_version(source, version):
    """Validate complete TOML, then find the sole edit changing project.version.

    Re-parsing each candidate proves the edit changes only the intended field.
    This also excludes lookalike assignments in other tables or multiline strings.
    Formatting, comments, and line endings are preserved byte-for-byte otherwise.
    """
    if tomllib is None:
        raise ValueError("this CI helper requires Python 3.11 or newer")
    try:
        document = tomllib.loads(source)
    except tomllib.TOMLDecodeError:
        raise ValueError("pyproject.toml must be valid TOML") from None
    project = document.get("project")
    if not isinstance(project, dict) or project.get("name") != "malbolge":
        raise ValueError("[project].name must be malbolge")
    old_version = project.get("version")
    if not isinstance(old_version, str) or not old_version:
        raise ValueError("[project] must contain one static string version")
    dynamic = project.get("dynamic", [])
    if not isinstance(dynamic, list):
        raise ValueError("[project].dynamic must be a list")
    if "version" in dynamic:
        raise ValueError("[project].version cannot also be dynamic")
    expected = copy.deepcopy(document)
    # Use a distinct probe even when retrying the same stamp, so equality also
    # proves which field is being edited on an idempotent invocation.
    probe = "0.0.0.dev0" if old_version != "0.0.0.dev0" else "0.0.0.dev1"
    expected["project"]["version"] = probe
    replacements = []
    for candidate in _VERSION_LINE.finditer(source):
        if candidate.group("value") != old_version:
            continue
        start, end = candidate.span("value")
        updated = source[:start] + probe + source[end:]
        try:
            if tomllib.loads(updated) == expected:
                replacements.append(source[:start] + version + source[end:])
        except tomllib.TOMLDecodeError:
            continue
    if len(replacements) != 1:
        raise ValueError("[project].version must be one plain quoted version field")
    return replacements[0]


def atomic_write(path, payload):
    """Replace a file atomically, preserving its permission bits."""
    mode = stat.S_IMODE(path.stat().st_mode)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=str(path.parent), delete=False) as output:
            temporary = Path(output.name)
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
            os.fchmod(output.fileno(), mode)
        os.replace(str(temporary), str(path))
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink()


def write_version(pyproject, original, updated, github_output, version):
    if github_output is None:
        atomic_write(pyproject, updated)
        return
    if github_output.resolve() == pyproject.resolve():
        raise ValueError("GitHub output must differ from pyproject.toml")
    if github_output.exists() and os.path.samefile(str(github_output), str(pyproject)):
        raise ValueError("GitHub output must differ from pyproject.toml")
    existed = github_output.exists()
    project_written = False
    # Reserve a usable output file before touching the project. On an I/O
    # failure, restore the project and the previous output contents.
    try:
        with github_output.open("ab+") as output:
            output.seek(0, os.SEEK_END)
            original_size = output.tell()
            separator = b""
            if original_size:
                output.seek(-1, os.SEEK_END)
                if output.read(1) != b"\n":
                    separator = b"\n"
            try:
                atomic_write(pyproject, updated)
                project_written = True
                output.write(separator + ("version=%s\n" % version).encode("ascii"))
                output.flush()
            except OSError:
                output.truncate(original_size)
                if project_written:
                    atomic_write(pyproject, original)
                raise
    except OSError:
        if not existed and github_output.is_file():
            github_output.unlink()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID"))
    parser.add_argument("--attempt", default=os.environ.get("GITHUB_RUN_ATTEMPT"))
    parser.add_argument("--github-output", type=Path,
                        default=os.environ.get("GITHUB_OUTPUT"))
    args = parser.parse_args(argv)
    try:
        result = development_version(args.run_id, args.attempt)
        original = args.pyproject.read_bytes()
        updated = replace_project_version(
            original.decode("utf-8"), result["test_version"]
        ).encode("utf-8")
        write_version(args.pyproject, original, updated,
                      args.github_output, result["test_version"])
    except (ValueError, OSError, UnicodeError) as error:
        print("prepare_testpypi_version: %s" % error, file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
