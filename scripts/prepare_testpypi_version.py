#!/usr/bin/env python3
"""Stamp a disposable CI checkout with a unique TestPyPI development version.

Run with Python 3.11+ (stdlib tomllib). The stable repository version is not
bumped: only the supplied checkout's project and module versions are rewritten.
"""

import argparse
import ast
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


BASE_VERSION = "1.1.0"
_DECIMAL = re.compile(r"[0-9]+\Z")
_RELEASE_VERSION = re.compile(r"(?P<base>[0-9]+\.[0-9]+\.[0-9]+)(?:\.dev[0-9]+)?\Z")
_VERSION_LINE = re.compile(
    r"^[ \t]*version[ \t]*=[ \t]*(?P<quote>['\"])(?P<value>[^'\"\r\n]*)"
    r"(?P=quote)[ \t]*(?:\#[^\r\n]*)?(?:\r?\n|\Z)", re.MULTILINE
)
_MODULE_VERSION_LINE = re.compile(
    r"^__version__[ \t]*=[ \t]*(?P<quote>['\"])(?P<value>[^'\"\r\n]*)"
    r"(?P=quote)[ \t]*(?:\#[^\r\n]*)?(?:\r?\n|\Z)", re.MULTILINE
)


def development_version(run_id, attempt, base_version=BASE_VERSION):
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
    match = _RELEASE_VERSION.fullmatch(base_version)
    if match is None or match.group("base") != base_version:
        raise ValueError("base version must be a numeric major.minor.patch release")
    return {
        "base_version": base_version,
        "test_version": "%s.dev%d" % (
            base_version, run_number * 1000 + attempt_number
        ),
        "run_id": run_number,
        "attempt": attempt_number,
    }


def project_document(source):
    """Read the static project version without importing the package."""
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
    return document


def replace_project_version(source, version):
    """Find the sole edit changing project.version, preserving other bytes.

    Re-parsing each candidate excludes lookalike assignments in other tables or
    multiline strings and proves the edit changes only the intended field.
    """
    document = project_document(source)
    old_version = document["project"]["version"]
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


def replace_module_version(source, old_version, version):
    """Change the sole plain module version assignment without executing it."""
    try:
        document = ast.parse(source)
    except SyntaxError:
        raise ValueError("malbolge/__init__.py must be valid Python") from None
    assignments = [node for node in document.body
                   if isinstance(node, ast.Assign) and len(node.targets) == 1
                   and isinstance(node.targets[0], ast.Name)
                   and node.targets[0].id == "__version__"]
    if len(assignments) != 1 or not isinstance(assignments[0].value, ast.Constant):
        raise ValueError("module must contain one plain __version__ string assignment")
    if assignments[0].value.value != old_version:
        raise ValueError("module __version__ must match [project].version")
    probe = "0.0.0.dev0" if old_version != "0.0.0.dev0" else "0.0.0.dev1"
    assignments[0].value = ast.Constant(value=probe)
    expected = ast.dump(document)
    replacements = []
    for candidate in _MODULE_VERSION_LINE.finditer(source):
        if candidate.group("value") != old_version:
            continue
        start, end = candidate.span("value")
        updated = source[:start] + probe + source[end:]
        if ast.dump(ast.parse(updated)) == expected:
            replacements.append(source[:start] + version + source[end:])
    if len(replacements) != 1:
        raise ValueError("module must contain one plain __version__ string assignment")
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


def write_versions(updates, github_output, version):
    """Atomically replace each file and restore all prior bytes on I/O failure."""
    def write_files(output=None, separator=b""):
        written = []
        try:
            for path, original, updated in updates:
                atomic_write(path, updated)
                written.append((path, original))
            if output is not None:
                output.write(separator + ("version=%s\n" % version).encode("ascii"))
                output.flush()
        except OSError:
            # Restore package identity even if truncating the output fails.
            try:
                if output is not None:
                    output.truncate(original_size)
            finally:
                for path, original in reversed(written):
                    atomic_write(path, original)
            raise

    if github_output is None:
        write_files()
        return
    for path, _, _ in updates:
        if (github_output.resolve() == path.resolve() or
                github_output.exists() and os.path.samefile(str(github_output), str(path))):
            raise ValueError("GitHub output must differ from version source files")
    existed = github_output.exists()
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
            write_files(output, separator)
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
        original = args.pyproject.read_bytes()
        source = original.decode("utf-8")
        current = project_document(source)["project"]["version"]
        match = _RELEASE_VERSION.fullmatch(current)
        if match is None:
            raise ValueError("project version must be a numeric release or development version")
        result = development_version(args.run_id, args.attempt, match.group("base"))
        updated = replace_project_version(
            source, result["test_version"]
        ).encode("utf-8")
        module = args.pyproject.parent / "malbolge" / "__init__.py"
        module_original = module.read_bytes()
        module_updated = replace_module_version(
            module_original.decode("utf-8"), current, result["test_version"]
        ).encode("utf-8")
        write_versions([(args.pyproject, original, updated),
                        (module, module_original, module_updated)],
                       args.github_output, result["test_version"])
    except (ValueError, OSError, UnicodeError) as error:
        print("prepare_testpypi_version: %s" % error, file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
