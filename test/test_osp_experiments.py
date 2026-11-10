"""Fast tests for the independent, fixed-input OSP experiment controller."""

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("osp_experiments", ROOT / "scripts/osp_experiments.py")
OSP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OSP)


@pytest.mark.parametrize("name,count", [("manifest.json", 10), ("regressions.json", 3)])
def test_fixed_input_hashes_and_oracles(name, count):
    programs = OSP.load_manifest(ROOT / "benchmarks/osp" / name, "all")
    workloads = 0
    for program in programs:
        assert len(program["source_sha256"]) == 64
        for contract in program["workloads"]:
            result = OSP.oracle(program["source"], contract["stdin_hex"])
            assert OSP.matches(result, contract)
            workloads += 1
    assert workloads == count


def test_existing_public_corpus_is_compatible():
    programs = OSP.load_manifest(ROOT / "benchmarks/manifest.json", "all")
    assert len(programs) == 12
    assert sum(len(p["workloads"]) for p in programs) == 32
    for p in programs:
        for w in p["workloads"]:
            assert OSP.matches(OSP.oracle(p["source"], w["stdin_hex"]), w)


def test_lazy_input_consumption_is_not_just_output_equality():
    program = OSP.load_manifest(ROOT / "benchmarks/osp/manifest.json", cases=["short_circuit"])[0]
    outputs = [OSP.oracle(program["source"], w["stdin_hex"]) for w in program["workloads"]]
    assert [r["output_hex"] for r in outputs] == ["41", "41"]
    assert [r["input_consumed"] for r in outputs] == [1, 2]
    assert not OSP.matches(outputs[0], program["workloads"][1])


def test_unknown_case_is_an_error():
    with pytest.raises(ValueError, match="unknown cases"):
        OSP.load_manifest(ROOT / "benchmarks/osp/manifest.json", cases=["typo"])


def test_locked_hash_and_windows_newlines(tmp_path):
    source = 'print("Hi")\n'
    source_path = tmp_path / "input.py"
    source_path.write_bytes(source.replace("\n", "\r\n").encode())
    data = {"schema_version": 1, "programs": [{"id": "test", "path": "input.py", "tier": "smoke",
            "source_sha256": OSP.digest(source.encode()), "workloads": [{"id": "tiny", "stdin": "",
            "stdout": "Hi\n", "expected_input_consumed": 0, "max_steps": 100, "timeout_seconds": 1}]}]}
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(data))
    assert OSP.load_manifest(manifest)[0]["source"] == source
    source_path.write_text('print("changed")\n')
    with pytest.raises(ValueError, match="fingerprint differs"):
        OSP.load_manifest(manifest)


def test_termination_is_required():
    contract = {"expected_stdout_hex": "41", "expected_input_consumed": 1}
    assert not OSP.matches({"output_hex": "41", "input_consumed": 1, "stop_reason": "step_limit"}, contract)


def test_child_timeout_is_not_a_pass_or_successful_timing(tmp_path, monkeypatch):
    def timeout(*args, **kwargs):
        raise OSP.subprocess.TimeoutExpired("worker", 0.01)
    monkeypatch.setattr(OSP.subprocess, "run", timeout)
    result = OSP.child(Path(sys.executable), {"task": "oracle", "source": "pass", "stdin_hex": ""},
                       tmp_path / "receipt.json", 0.01)
    assert result["status"] == "timeout"
    assert "runtime_api_wall_seconds" not in result
    assert not list(tmp_path.glob("*.job.json"))


def test_actual_isolated_oracle_child(tmp_path):
    result = OSP.child(Path(sys.executable), {"task": "oracle", "source": "putchar(getchar())", "stdin_hex": "ff"},
                       tmp_path / "receipt.json", 10)
    assert result["status"] == "ok"
    assert result["result"] == {"output_hex": "ff", "input_consumed": 1, "stop_reason": "terminated"}


def test_error_child_does_not_succeed(tmp_path):
    result = OSP.child(Path(sys.executable), {"task": "not_a_task"}, tmp_path / "error.json", 10)
    assert result["status"] == "error"
    assert result["returncode"] == 1


def test_package_probe_rejects_checkout():
    import malbolge
    with pytest.raises(ValueError, match="forbidden source"):
        OSP.package_probe(Path(malbolge.__file__).resolve().parent)


def test_controller_oracle_mode_and_no_overwrite(tmp_path):
    args = SimpleNamespace(python=Path(sys.executable), forbid_source_root=None,
                           manifest=ROOT / "benchmarks/osp/manifest.json", suite="smoke", cases=None,
                           output_dir=tmp_path / "out", mode="oracle", backends=["direct"], engines=["python"],
                           opt_level=3, target_pipeline="structured", repeats=1)
    report = OSP.run(args)
    assert report["mode"] == "oracle"
    assert report["status"] == "passed"
    assert len(report["oracle"]) == 4
    assert report["samples"] == []
    with pytest.raises(FileExistsError):
        OSP.run(args)


def test_python_path_keeps_virtualenv_symlink(tmp_path, monkeypatch):
    alias = tmp_path / "python"
    try:
        alias.symlink_to(sys.executable)
    except OSError:
        pytest.skip("symlink creation unavailable on this host")
    args = SimpleNamespace(python=alias, forbid_source_root=None,
                           manifest=ROOT / "benchmarks/osp/manifest.json", suite="smoke", cases=["literal_output"],
                           output_dir=tmp_path / "out", mode="oracle", backends=["direct"], engines=["python"],
                           opt_level=3, target_pipeline="structured", repeats=1)
    seen = []
    actual = OSP.child
    def recording(python, *args):
        seen.append(python)
        return actual(python, *args)
    monkeypatch.setattr(OSP, "child", recording)
    assert OSP.run(args)["status"] == "passed"
    assert seen == [alias]
