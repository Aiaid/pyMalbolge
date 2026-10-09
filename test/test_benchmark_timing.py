"""CPU/wall accounting and best-effort machine context for benchmark samples."""

import importlib.util
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/benchmark_pipeline.py"
SPEC = importlib.util.spec_from_file_location("benchmark_timing_driver", SCRIPT)
BENCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCH)


def test_mac_hardware_metadata_uses_bounded_readonly_queries(monkeypatch):
    monkeypatch.setattr(BENCH.sys, "platform", "darwin")
    queries = []
    values = {"machdep.cpu.brand_string": "Example CPU", "hw.logicalcpu": "12",
              "hw.physicalcpu": "8", "hw.memsize": "34359738368"}

    def run(argv, **kwargs):
        queries.append(argv)
        assert kwargs == {"capture_output": True, "text": True, "timeout": 2}
        return SimpleNamespace(returncode=0, stdout=values[argv[-1]])

    monkeypatch.setattr(BENCH.subprocess, "run", run)
    result = BENCH.hardware_environment()
    assert result["cpu_model"] == "Example CPU"
    assert result["logical_cores"] == 12
    assert result["physical_cores"] == 8
    assert result["ram_bytes"] == 34359738368
    assert all(argv[:2] == ["/usr/sbin/sysctl", "-n"] for argv in queries)
    assert result["python"] and result["platform"] and result["machine"]
    json.dumps(result)


def test_mac_context_records_load_and_first_power_line(monkeypatch):
    monkeypatch.setattr(BENCH.sys, "platform", "darwin")
    monkeypatch.setattr(BENCH.os, "getloadavg", lambda: (1.0, 2.0, 3.0))

    def read(argv):
        assert argv[:2] == ["/usr/bin/pmset", "-g"]
        return ("Now drawing from 'AC Power'\nBattery details" if argv[-1] == "batt"
                else "No thermal warning level has been recorded")

    monkeypatch.setattr(BENCH, "_read_system_command", read)
    result = BENCH.system_context()
    assert result["load_average_1_5_15"] == [1.0, 2.0, 3.0]
    assert result["power_source"] == "Now drawing from 'AC Power'"
    assert result["thermal_status_text"] == "No thermal warning level has been recorded"
    assert math.isfinite(result["unix_time_seconds"])
    assert math.isfinite(result["monotonic_seconds"])
    json.dumps(result)


def test_unavailable_context_does_not_fail(monkeypatch):
    monkeypatch.setattr(BENCH.sys, "platform", "darwin")

    def unavailable():
        raise OSError("not supported")

    monkeypatch.setattr(BENCH.os, "getloadavg", unavailable, raising=False)
    monkeypatch.setattr(BENCH, "_read_system_command", lambda argv: None)
    context = BENCH.system_context()
    assert context["load_average_1_5_15"] is None
    assert context["power_source"] is None
    assert context["thermal_status_text"] is None
    hardware = BENCH.hardware_environment()
    assert hardware["physical_cores"] is None
    assert hardware["ram_bytes"] is None
    assert hardware["python"]


@pytest.mark.parametrize("failure", [OSError("missing"),
                         BENCH.subprocess.TimeoutExpired(["metadata"], 2)])
def test_failed_system_command_returns_none(monkeypatch, failure):
    def run(*args, **kwargs):
        raise failure

    monkeypatch.setattr(BENCH.subprocess, "run", run)
    assert BENCH._read_system_command(["metadata"]) is None


def test_failed_exit_and_empty_system_output_return_none(monkeypatch):
    monkeypatch.setattr(BENCH.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(returncode=1, stdout="ignored"))
    assert BENCH._read_system_command(["metadata"]) is None
    monkeypatch.setattr(BENCH.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(returncode=0, stdout="\n"))
    assert BENCH._read_system_command(["metadata"]) is None


def test_real_samples_keep_output_and_partition_cpu_time(tmp_path, monkeypatch):
    # Avoid dependence on the host's metadata support in the semantic test.
    snapshots = []

    def context():
        snapshot = {"sample": len(snapshots)}
        snapshots.append(snapshot)
        return snapshot

    monkeypatch.setattr(BENCH, "system_context", context)
    source, input_text = BENCH.CASES["echo"]
    args = SimpleNamespace(backend="direct", op_style="cluster", jmp_style="main",
                           max_steps=2000000, stop_after="mc")
    lowering = BENCH.compile_sample(args, tmp_path, source)
    assert lowering["image"] == {} and not (tmp_path / "program.mb").exists()
    args.stop_after = "mb"
    compiled = BENCH.compile_sample(args, tmp_path, source)
    runtime = BENCH.runtime_sample(args, tmp_path, source, input_text)
    assert runtime["passed"] and runtime["output_hex"] == b"Q".hex()
    assert runtime["result"]["stop_reason"] == "terminated"
    assert runtime["result"]["steps"] > 0
    for record in (lowering, compiled, runtime):
        assert record["system_after"]["sample"] == record["system_before"]["sample"] + 1
        for key, value in record.items():
            if key.endswith("seconds") or key.endswith("ratio"):
                assert value is not None and math.isfinite(value) and value >= 0, key
        json.dumps(record)
    for stage in compiled["stages"]:
        assert math.isfinite(stage["cpu_seconds"]) and stage["cpu_seconds"] >= 0
    phases = ("read", "parse_validate", "initialize", "prepare_gc", "execute")
    assert sum(runtime[name + "_cpu_seconds"] for name in phases) == pytest.approx(
        runtime["cpu_seconds"])
    assert sum(runtime[name + "_seconds"] for name in phases) == pytest.approx(
        runtime["wall_seconds"])
    assert runtime["execute_cpu_wall_ratio"] == pytest.approx(
        runtime["execute_cpu_seconds"] / runtime["execute_seconds"])


def test_oracle_worker_reports_cpu_without_changing_output(tmp_path, monkeypatch):
    monkeypatch.setattr(BENCH, "fingerprint", lambda: {})
    job = tmp_path / "job.json"
    job.write_text(json.dumps({"source": "n = int(input())\nprint(n + 1)\n",
                               "stdin": "7\n", "stdout": "8\n"}))
    args = SimpleNamespace(job=job, directory=str(tmp_path), profile=False,
                           worker="oracle", record="oracle")
    BENCH.worker(args)
    result = json.loads((tmp_path / "oracle.json").read_text())
    assert result["passed"] and result["output_hex"] == b"8\n".hex()
    for key in ("code_seconds", "code_cpu_seconds", "code_cpu_wall_ratio"):
        assert math.isfinite(result[key]) and result[key] >= 0


def test_metadata_collection_is_outside_measured_intervals(tmp_path, monkeypatch):
    # A deterministic clock charges metadata gathering 100 seconds per call.
    # Compiler/VM work does not advance this fake clock, so any metadata cost
    # leaking into either interval is observable without a speed threshold.
    clock = {"seconds": 0.0}
    monkeypatch.setattr(BENCH, "time", SimpleNamespace(
        perf_counter=lambda: clock["seconds"], process_time=lambda: clock["seconds"]))

    def context():
        clock["seconds"] += 100
        return {"fake_metadata_clock": clock["seconds"]}

    monkeypatch.setattr(BENCH, "system_context", context)
    source, input_text = BENCH.CASES["echo"]
    args = SimpleNamespace(backend="direct", op_style="cluster", jmp_style="main",
                           max_steps=2000000)
    compiled = BENCH.compile_sample(args, tmp_path, source)
    runtime = BENCH.runtime_sample(args, tmp_path, source, input_text)
    assert compiled["wall_seconds_including_artifact_and_metric_writes"] == 0
    assert compiled["cpu_seconds"] == 0
    assert runtime["wall_seconds"] == runtime["cpu_seconds"] == 0
    assert runtime["passed"]
    assert clock["seconds"] == 400


def test_cpu_wall_ratio_with_zero_wall_time_is_unavailable():
    assert BENCH.cpu_wall_ratio(0, 0) is None
    assert BENCH.cpu_wall_ratio(2, 4) == 0.5
