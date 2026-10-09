"""Fixed workloads are validated and share exactly one compiled image."""

import csv
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.benchmark_suite import load_manifest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/benchmark_pipeline.py"


def fixture(tmp_path):
    (tmp_path / "echo.py").write_text("putchar(getchar())\n")
    manifest = {"schema_version": 1, "programs": [{
        "id": "echo", "path": "echo.py", "tier": "smoke", "description": "Two inputs",
        "workloads": [{"id": name, "stdin": value, "stdout": value,
                       "max_steps": 2000000, "timeout_seconds": 30}
                      for name, value in (("first", "A"), ("second", "B"))]}]}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path, manifest


def test_manifest_rejects_ambiguous_names_and_invalid_budgets(tmp_path):
    path, data = fixture(tmp_path)
    assert len(load_manifest(path)[1]) == 1
    data["programs"][0]["workloads"][0]["max_steps"] = True
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="step budget"):
        load_manifest(path)
    data["programs"][0]["workloads"][0]["max_steps"] = 1
    data["programs"].append(dict(data["programs"][0]))
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="unique"):
        load_manifest(path)


def test_compile_once_checks_two_different_inputs_and_writes_summary(tmp_path):
    path, _data = fixture(tmp_path)
    output = tmp_path / "results"
    command = [sys.executable, str(RUNNER), "--manifest", str(path),
               "--backends", "direct", "--output-dir", str(output)]
    run = subprocess.run(command, capture_output=True, timeout=30)
    assert run.returncode == 0, run.stderr.decode()
    report = json.loads((output / "report.json").read_text())
    assert report["all_requested_samples_passed"]
    assert report["mode"] == "benchmark"
    assert "logical_cores" in report["hardware"]
    assert not report["timing_policy"]["hardware_normalized"]
    assert report["run_state"] == "complete"
    assert report["requested_target_runs"] == report["completed_target_runs"] == 2
    assert len(report["samples"]) == 1
    assert len(list(output.rglob("program.mb"))) == 1
    sample = report["samples"][0]
    assert [w["runtime"]["output_hex"] for w in sample["workloads"]] == ["41", "42"]
    assert all(w["runtime"]["result"]["input_consumed"] == 1 for w in sample["workloads"])
    with (output / "summary.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert [row["workload"] for row in rows] == ["first", "second"]
    assert all(row["status"] == "ok" for row in rows)
    assert all(float(row["compile_seconds"]) > 0 and int(row["mb_bytes"]) > 0
               and float(row["run_seconds"]) > 0 and float(row["steps_per_second"]) > 0
               for row in rows)
    assert all(float(row["compile_cpu_seconds"]) >= 0 and float(row["run_cpu_seconds"]) >= 0
               and float(row["execute_cpu_seconds"]) >= 0 for row in rows)
    repeated = subprocess.run(command, capture_output=True, timeout=10)
    assert repeated.returncode == 2
    assert b"preserve earlier results" in repeated.stderr


def test_discarding_large_images_preserves_all_input_results_and_hashes(tmp_path):
    path, _data = fixture(tmp_path)
    output = tmp_path / "discarded"
    run = subprocess.run([sys.executable, str(RUNNER), "--manifest", str(path),
                          "--backends", "direct", "--discard-images",
                          "--output-dir", str(output)], capture_output=True, timeout=30)
    assert run.returncode == 0, run.stderr.decode()
    report = json.loads((output / "report.json").read_text())
    sample = report["samples"][0]
    assert not sample["image_retained"]
    assert sample["compile"]["image"]["bytes"] > 0
    assert len(sample["compile"]["image"]["sha256"]) == 64
    assert report["completed_target_runs"] == report["passed_target_runs"] == 2
    assert not list(output.rglob("program.mb"))


def test_bad_oracle_does_not_compile_and_is_not_a_performance_success(tmp_path):
    path, data = fixture(tmp_path)
    data["programs"][0]["workloads"][0]["stdout"] = "wrong"
    path.write_text(json.dumps(data))
    output = tmp_path / "failed"
    run = subprocess.run([sys.executable, str(RUNNER), "--manifest", str(path),
                          "--backends", "direct", "--stop-after", "mc",
                          "--output-dir", str(output)], capture_output=True, timeout=30)
    assert run.returncode == 1
    report = json.loads((output / "report.json").read_text())
    assert not report["all_requested_samples_passed"]
    assert report["mode"] == "lowering_check"
    assert "compile" not in report["samples"][0]
    assert not list(output.rglob("program.mb"))
