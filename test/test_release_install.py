"""Acceptance helper must reject source leakage and misleading installations."""

import argparse
import importlib.util
import json
from pathlib import Path
import sys
import types

import pytest


@pytest.fixture
def helper():
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_release_install.py"
    spec = importlib.util.spec_from_file_location("verify_release_install", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def installation(helper, monkeypatch, tmp_path):
    prefix = tmp_path / "environment"
    package = prefix / "lib" / "site-packages" / "malbolge"
    native = types.SimpleNamespace(native_available=lambda: False)
    module = types.ModuleType("malbolge")
    module.__file__ = str(package / "__init__.py")
    module.__version__ = "1.2.3rc1"
    module.native = native
    monkeypatch.setitem(sys.modules, "malbolge", module)
    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.setattr(helper.metadata, "version", lambda name: "1.2.3rc1")
    args = argparse.Namespace(expected_version="1.2.3rc1",
                              forbid_source_root=str(tmp_path / "checkout"),
                              require_native=False, require_pure=False, require_ir=False)

    def no_cli(*args, **kwargs):
        pytest.fail("unsafe installation reached guest execution")

    monkeypatch.setattr(helper, "cli", no_cli)
    return args, module, native


def test_rejects_import_from_checkout(helper, installation):
    args, module, _ = installation
    # Even when a checkout sits inside the active environment, it is forbidden.
    args.forbid_source_root = str(Path(module.__file__).parent)
    with pytest.raises(helper.VerificationError, match="forbidden source"):
        helper.verify(args)


def test_rejects_import_outside_environment(helper, installation, tmp_path):
    args, module, _ = installation
    module.__file__ = str(tmp_path / "other" / "malbolge" / "__init__.py")
    with pytest.raises(helper.VerificationError, match="outside sys.prefix"):
        helper.verify(args)


@pytest.mark.parametrize("field", ["expected_version", "module_version", "metadata_version"])
def test_rejects_version_mismatch(helper, installation, monkeypatch, field):
    args, module, _ = installation
    if field == "expected_version":
        args.expected_version = "9.9.9"
    elif field == "module_version":
        module.__version__ = "9.9.9"
    else:
        monkeypatch.setattr(helper.metadata, "version", lambda name: "9.9.9")
    with pytest.raises(helper.VerificationError, match="version mismatch"):
        helper.verify(args)


@pytest.mark.parametrize("native_available", [False, True])
def test_rejects_wrong_native_policy(helper, installation, native_available):
    args, _, native = installation
    native.native_available = lambda: native_available
    args.require_native = not native_available
    args.require_pure = native_available
    with pytest.raises(helper.VerificationError, match="native VM"):
        helper.verify(args)


@pytest.mark.parametrize("outcome", ["success", "version_mismatch", "missing_dependency"])
def test_report_creates_parent_for_success_and_failure(
        helper, installation, monkeypatch, tmp_path, outcome):
    args, _, _ = installation
    report_path = tmp_path / "fresh" / "provenance" / "release.json"
    if outcome == "success":
        monkeypatch.setattr(helper, "verify", lambda args: {
            "success": True, "version": args.expected_version, "native_available": False})
    elif outcome == "version_mismatch":
        args.expected_version = "9.9.9"
    else:
        def missing_distribution(name):
            raise helper.metadata.PackageNotFoundError(name)
        monkeypatch.setattr(helper.metadata, "version", missing_distribution)
    argv = ["--expected-version", args.expected_version,
            "--forbid-source-root", args.forbid_source_root,
            "--report", str(report_path)]
    if outcome == "success":
        assert helper.main(argv) == 0
    else:
        with pytest.raises(SystemExit) as stopped:
            helper.main(argv)
        assert stopped.value.code == 1
    report = json.loads(report_path.read_text(encoding="utf8"))
    assert report["success"] is (outcome == "success")
    if outcome != "success":
        assert report["expected_version"] == args.expected_version
        assert report["error_type"] == (
            "VerificationError" if outcome == "version_mismatch" else "PackageNotFoundError")
        expected_message = "version mismatch" if outcome == "version_mismatch" else "malbolge"
        assert expected_message in report["error"]
