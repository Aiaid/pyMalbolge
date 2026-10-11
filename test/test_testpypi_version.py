"""TestPyPI stamping mutates only a disposable checkout's project version."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/prepare_testpypi_version.py"
SPEC = importlib.util.spec_from_file_location("prepare_testpypi_version", SCRIPT)
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)
SOURCE = '[project]\nname = "malbolge"\nversion = "1.0.0"\n'


@unittest.skipIf(helper.tomllib is None, "TestPyPI CI helper requires Python 3.11+")
class TestTestPyPIVersion(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.project = self.root / "pyproject.toml"
        self.project.write_bytes(SOURCE.encode("utf-8"))

    def invoke(self, *args, **kwargs):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, kwargs.get("environment", {}), clear=True):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = helper.main(["--pyproject", str(self.project)] + list(args))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_stamp_is_unique_across_runs_and_retries(self):
        pairs = ((1, 1), (1, 999), (2, 1), (2, 2), (100000000000, 999))
        versions = [helper.development_version(str(run), str(attempt))["test_version"]
                    for run, attempt in pairs]
        self.assertEqual(len(set(versions)), len(pairs))
        self.assertEqual(versions[:3],
                         ["1.0.1.dev1001", "1.0.1.dev1999", "1.0.1.dev2001"])

    def test_environment_defaults_and_json_contract(self):
        output = self.root / "github-output"
        code, stdout, stderr = self.invoke(environment={
            "GITHUB_RUN_ID": "12345", "GITHUB_RUN_ATTEMPT": "2",
            "GITHUB_OUTPUT": str(output),
        })
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(json.loads(stdout), {
            "base_version": "1.0.1", "test_version": "1.0.1.dev12345002",
            "run_id": 12345, "attempt": 2,
        })
        self.assertEqual(output.read_text(), "version=1.0.1.dev12345002\n")
        self.assertEqual(helper.tomllib.loads(self.project.read_text())["project"]["version"],
                         "1.0.1.dev12345002")

    def test_explicit_arguments_override_environment_and_append_output(self):
        output = self.root / "github-output"
        output.write_text("existing=value")
        other_output = self.root / "ignored-output"
        code, stdout, stderr = self.invoke(
            "--run-id", "42", "--attempt", "3", "--github-output", str(output),
            environment={"GITHUB_RUN_ID": "9", "GITHUB_RUN_ATTEMPT": "1",
                         "GITHUB_OUTPUT": str(other_output)},
        )
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(json.loads(stdout)["test_version"], "1.0.1.dev42003")
        self.assertEqual(output.read_text(), "existing=value\nversion=1.0.1.dev42003\n")
        self.assertFalse(other_output.exists())

    def test_exact_edit_preserves_other_versions_strings_comments_and_crlf(self):
        source = ('[tool.other]\r\nversion = "1.0.0"\r\n'
                  '[project]\r\nname = "malbolge"\r\n'
                  'description = """\r\nversion = "1.0.0"\r\n"""\r\n'
                  "  version = '1.0.0'  # stable\r\n"
                  '[project.urls]\r\nversion = "1.0.0"\r\n')
        self.project.write_bytes(source.encode("utf-8"))
        self.project.chmod(0o640)
        code, _, stderr = self.invoke("--run-id", "4", "--attempt", "1")
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(self.project.read_bytes(), source.replace(
            "  version = '1.0.0'", "  version = '1.0.1.dev4001'"
        ).encode("utf-8"))
        self.assertEqual(stat.S_IMODE(self.project.stat().st_mode), 0o640)

    def test_retrying_the_same_stamp_is_idempotent(self):
        for _ in range(2):
            code, _, stderr = self.invoke("--run-id", "4", "--attempt", "1")
            self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(self.project.read_text(), SOURCE.replace("1.0.0", "1.0.1.dev4001"))

    def test_missing_or_invalid_identifiers_fail_without_writes(self):
        arguments = ((), ("--run-id", "1"), ("--attempt", "1"),
                     ("--run-id", "0", "--attempt", "1"),
                     ("--run-id", "-1", "--attempt", "1"),
                     ("--run-id", "1.5", "--attempt", "1"),
                     ("--run-id", " 1", "--attempt", "1"),
                     ("--run-id", "1", "--attempt", "0"),
                     ("--run-id", "1", "--attempt", "1000"),
                     ("--run-id", "1", "--attempt", "+1"))
        output = self.root / "github-output"
        output.write_text("existing=value\n")
        for args in arguments:
            with self.subTest(args=args):
                code, stdout, stderr = self.invoke(
                    *(args + ("--github-output", str(output)))
                )
                self.assertEqual((code, stdout), (2, ""))
                self.assertTrue(stderr)
                self.assertEqual(self.project.read_text(), SOURCE)
                self.assertEqual(output.read_text(), "existing=value\n")

    def test_invalid_projects_fail_before_creating_output(self):
        fixtures = (
            '[tool.other]\nname="malbolge"\nversion="1.0.0"\n',
            SOURCE.replace('name = "malbolge"\n', ""),
            SOURCE.replace('"malbolge"', '"other"'),
            SOURCE.replace('version = "1.0.0"\n', ""),
            SOURCE + 'version = "2.0.0"\n',
            SOURCE + "[project]\n",
            SOURCE + "broken = [\n",
            SOURCE.replace('version = "1.0.0"', "version = 1"),
            SOURCE + 'dynamic = ["version"]\n',
            SOURCE + "dynamic = 7\n",
            SOURCE.replace('version = "1.0.0"', '"version" = "1.0.0"'),
        )
        output = self.root / "github-output"
        for source in fixtures:
            with self.subTest(source=source):
                self.project.write_bytes(source.encode("utf-8"))
                code, stdout, stderr = self.invoke(
                    "--run-id", "1", "--attempt", "1", "--github-output", str(output)
                )
                self.assertEqual((code, stdout), (2, ""))
                self.assertTrue(stderr)
                self.assertEqual(self.project.read_text(), source)
                self.assertFalse(output.exists())

    def test_output_cannot_overwrite_project_or_use_missing_directory(self):
        alias = self.root / "alias"
        os.link(str(self.project), str(alias))
        for output in (self.project, alias, self.root / "missing/output"):
            with self.subTest(output=output):
                code, stdout, stderr = self.invoke(
                    "--run-id", "1", "--attempt", "1", "--github-output", str(output)
                )
                self.assertEqual((code, stdout), (2, ""))
                self.assertTrue(stderr)
                self.assertEqual(self.project.read_text(), SOURCE)

    def test_atomic_replace_failure_preserves_source_and_cleans_temporary_file(self):
        with mock.patch.object(helper.os, "replace", side_effect=OSError("replace failed")):
            code, stdout, stderr = self.invoke("--run-id", "1", "--attempt", "1")
        self.assertEqual((code, stdout), (2, ""))
        self.assertIn("replace failed", stderr)
        self.assertEqual(self.project.read_text(), SOURCE)
        self.assertEqual(list(self.root.iterdir()), [self.project])

    def test_failed_output_write_restores_project_and_existing_output(self):
        output = self.root / "github-output"
        output.write_text("existing=value\n")
        real_open = Path.open

        class FailingWriter:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return self.stream.__exit__(*args)

            def __getattr__(self, name):
                return getattr(self.stream, name)

            def write(self, data):
                self.stream.write(data[:4])
                self.stream.flush()
                raise OSError("output failed")

        def patched_open(path, *args, **kwargs):
            stream = real_open(path, *args, **kwargs)
            return FailingWriter(stream) if path == output else stream

        with mock.patch.object(Path, "open", patched_open):
            code, stdout, stderr = self.invoke(
                "--run-id", "1", "--attempt", "1", "--github-output", str(output)
            )
        self.assertEqual((code, stdout), (2, ""))
        self.assertIn("output failed", stderr)
        self.assertEqual(self.project.read_text(), SOURCE)
        self.assertEqual(output.read_text(), "existing=value\n")

    def test_old_python_has_friendly_failure(self):
        with mock.patch.object(helper, "tomllib", None):
            code, stdout, stderr = self.invoke("--run-id", "1", "--attempt", "1")
        self.assertEqual((code, stdout), (2, ""))
        self.assertIn("requires Python 3.11", stderr)
        self.assertNotIn("Traceback", stderr)
        self.assertEqual(self.project.read_text(), SOURCE)


if __name__ == "__main__":
    unittest.main()
