"""Driver ordering, provenance, censoring, and fixed-oracle contracts."""

import csv
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts import benchmark_semantic_passes as bench


def selected_variants():
    return {name: bench.Variant(name, "direct" if name == "legacy_direct" else "ir",
                                () if name == "legacy_direct" else ("verify-semantic",),
                                name in ("legacy_direct", "semantic_legacy"))
            for name in bench.VARIANT_NAMES}


def args(tmp_path, *more):
    return bench.parse_args(["--output", str(tmp_path / "results"), "--cases", "char_io",
                             "--variants", "semantic_legacy", "semantic_none", "semantic_passes",
                             "--repeats", "2", "--warmups", "1", *more])


def fake_environment(monkeypatch, *, runtime_status="ok", compile_status="ok", changed=False):
    from scripts import benchmark_pipeline

    state = {"changed": False, "calls": []}
    initial = {"malbolge/core.py": "stable"}
    monkeypatch.setattr(bench, "source_fingerprint", lambda: initial if not state["changed"] else {"malbolge/core.py": "changed"})
    monkeypatch.setattr(benchmark_pipeline, "hardware_environment", lambda: {"logical_cores": 1})

    def invoke(task, directory, job, record, variant, max_steps, timeout):
        request = json.loads(job.read_text())
        state["calls"].append((task, directory.name, variant.id, request["id"], max_steps, timeout))
        common = {"source_sha256": bench.digest(request["source"].encode()),
                  "source_hashes": initial, "profiled": False}
        if task == "compile":
            (directory / "program.mb").write_bytes(b"image")
            if changed:
                state["changed"] = True
            if compile_status != "ok":
                return {"status": compile_status}
            raw = dict(common, wall_seconds_including_artifact_and_metric_writes=2.0,
                       cpu_seconds=1.0, process_peak_rss_bytes=100,
                       image={"bytes": 5, "sha256": bench.digest(b"image")},
                       stages=[{"stage": "mg2mc", "seconds": 0.5, "cpu_seconds": 0.25, "bytes": 10}],
                       structure={"semantic_before": {"total_operations": 20, "ir_bytes": 400},
                                  "semantic_after": {"total_operations": 10, "ir_bytes": 200}})
            return {"status": "ok", "raw": raw}
        assert task == "runtime"
        assert (directory / "program.mb").read_bytes() == b"image"
        if runtime_status == "child_timeout":
            return {"status": "child_timeout", "timeout_seconds": timeout}
        work = next(work for work in bench.CASES["char_io"].workloads if work.id == request["id"])
        raw = dict(common, passed=runtime_status == "ok", output_hex=work.stdout.hex(),
                   wall_seconds=4.0, cpu_seconds=3.0, execute_seconds=2.0,
                   execute_cpu_seconds=1.5, process_peak_rss_bytes=200,
                   result={"stop_reason": "terminated" if runtime_status == "ok" else runtime_status,
                           "steps": 123, "input_consumed": 1})
        return {"status": "ok", "raw": raw}

    monkeypatch.setattr(bench, "invoke_worker", invoke)
    return state


def test_all_fixed_oracles_include_binary_bytes_and_input_consumption():
    for case in bench.CASES.values():
        for workload in case.workloads:
            assert bench.validate_contract(case, workload)["passed"], (case.id, workload.id)
            job = workload.job(case.source)
            assert bytes.fromhex(job["stdin_hex"]) == workload.stdin
            assert bytes.fromhex(job["stdout_hex"]) == workload.stdout
            assert 0 < workload.timeout_seconds <= 120
            assert 0 <= workload.max_steps <= 100_000_000
    assert bench.CASES["wide_decimal"].workloads[-1].stdin == b"\xff"
    assert bench.CASES["wide_decimal"].workloads[-1].stdout == b"3486784400\n"
    assert "multiply_17" not in bench.DEFAULT_CASES
    assert "multiply_255" not in bench.DEFAULT_CASES
    assert "byte_decimal" not in bench.DEFAULT_CASES


def test_rotating_schedule_has_exact_coverage_and_unmeasured_warmups():
    plan = bench.schedule(("first", "second"), ("a", "b", "c"), 3, 1)
    assert len(plan) == 24
    assert len({(p["phase"], p["repeat"], p["case"], p["variant"]) for p in plan}) == 24
    assert [p["variant"] for p in plan[:6]] == ["a", "b", "c", "b", "c", "a"]
    assert [p["variant"] for p in plan[6:9]] == ["b", "c", "a"]
    assert {p["repeat"] for p in plan if p["phase"] == "measurement"} == {1, 2, 3}


@pytest.mark.parametrize("flags", [
    ["--repeats", "0"], ["--warmups", "-1"], ["--compile-timeout", "301"],
    ["--compile-timeout", "nan"], ["--runtime-timeout", "121"],
    ["--max-steps", "100000001"], ["--cases", "missing"],
    ["--variants", "semantic_none,semantic_none"],
])
def test_invalid_arguments_create_nothing(tmp_path, flags):
    output = tmp_path / "must-not-exist"
    with pytest.raises(SystemExit) as exc:
        bench.parse_args(["--output", str(output), *flags])
    assert exc.value.code == 2
    assert not output.exists()


def test_driver_compiles_once_per_case_round_variant_and_discards_images(tmp_path, monkeypatch):
    state = fake_environment(monkeypatch)
    options = args(tmp_path)
    driver = bench.Driver(options, selected_variants())
    assert driver.run() == 0
    compiles = [call for call in state["calls"] if call[0] == "compile"]
    runtimes = [call for call in state["calls"] if call[0] == "runtime"]
    assert len(compiles) == 9  # Three warmup plus six measured compiles.
    assert len(runtimes) == 18  # Two inputs share each compiled image.
    assert not list(options.output.rglob("program.mb"))
    report = json.loads((options.output / "report.json").read_text())
    assert report["run_state"] == "complete"
    assert report["requested_program_compiles"] == report["completed_program_compiles"] == 6
    assert report["requested_target_runs"] == report["complete_target_runs"] == report["attempted_target_runs"] == 12
    assert report["warmup_status_counts"] == {"ok": 6}
    assert all(item["complete_repeats"] == 2 for item in report["medians"])
    assert all(item["paired_complete_repeats"] == 2 for item in report["comparisons"])
    assert all(item["run_seconds_ratio"] == 1 for item in report["comparisons"])
    with (options.output / "samples.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 18
    assert all(row["ir_before_operations"] == "20" and row["ir_after_operations"] == "10" for row in rows)
    assert all(float(row["compiler_stage_cpu_seconds"]) == 0.25 for row in rows)
    assert all(sample["compile"]["raw"]["source_hashes"] for sample in report["samples"])
    with pytest.raises(ValueError, match="new empty"):
        bench.Driver(options, selected_variants()).run()


@pytest.mark.parametrize("status", ["step_limit", "child_timeout", "output_limit", "invalid_instruction"])
def test_unfinished_runs_keep_status_and_raw_partial_but_no_complete_vm_metrics(tmp_path, monkeypatch, status):
    fake_environment(monkeypatch, runtime_status=status)
    options = args(tmp_path, "--warmups", "0", "--repeats", "1", "--variants", "semantic_none")
    assert bench.Driver(options, selected_variants()).run() == 1
    report = json.loads((options.output / "report.json").read_text())
    assert report["status_counts"] == {status: 2}
    assert report["completed_program_compiles"] == 1
    assert report["complete_target_runs"] == 0
    assert all(row["complete_repeats"] == 0 and row["compile_seconds"] is None for row in report["medians"])
    for work in report["samples"][0]["workloads"]:
        assert "runtime" not in work
        if status == "child_timeout":
            assert "partial" not in work
        else:
            assert work["partial"]["result"]["steps"] == 123
    with (options.output / "samples.csv").open() as stream:
        for row in csv.DictReader(stream):
            assert all(row[key] == "" for key in bench.RUNTIME_FIELDS)
            assert row["compile_seconds"] == "2.0"  # Independently completed compile remains raw evidence.


def test_failed_compile_skips_all_inputs_and_removes_partial_artifact(tmp_path, monkeypatch):
    state = fake_environment(monkeypatch, compile_status="child_timeout")
    options = args(tmp_path, "--warmups", "0", "--repeats", "1", "--variants", "semantic_none")
    assert bench.Driver(options, selected_variants()).run() == 1
    assert len(state["calls"]) == 1
    assert not list(options.output.rglob("program.mb"))
    report = json.loads((options.output / "report.json").read_text())
    assert report["status_counts"] == {"compile_child_timeout": 2}
    assert report["attempted_target_runs"] == 0


def test_source_change_aborts_with_checkpoint_and_pending_coverage(tmp_path, monkeypatch):
    state = fake_environment(monkeypatch, changed=True)
    options = args(tmp_path, "--warmups", "0")
    assert bench.Driver(options, selected_variants()).run() == 2
    assert len(state["calls"]) == 1
    report = json.loads((options.output / "report.json").read_text())
    assert report["run_state"] == "aborted_source_changed"
    assert report["source_changed_during_run"]
    assert report["changed_paths"] == ["malbolge/core.py"]
    assert report["status_counts"] == {"not_run": 12}
    assert not list(options.output.rglob("program.mb"))


def test_timeout_ignores_even_a_late_complete_looking_record(tmp_path, monkeypatch):
    (tmp_path / "runtime.json").write_text(json.dumps({"execute_seconds": 999, "result": {"steps": 999}}))
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])
    monkeypatch.setattr(bench.subprocess, "run", timeout)
    result = bench.invoke_worker("runtime", tmp_path, tmp_path / "job.json", "runtime",
                                 selected_variants()["semantic_none"], 100, 1)
    assert result["status"] == "child_timeout"
    assert "raw" not in result and "execute_seconds" not in result and "steps" not in result


def test_fixed_input_consumption_and_output_are_checked_independently():
    work = bench.CASES["char_io"].workloads[0]
    raw = {"passed": True, "output_hex": "51", "result": {"stop_reason": "terminated", "input_consumed": 2, "steps": 1},
           "wall_seconds": 1, "cpu_seconds": 1, "execute_seconds": 1, "execute_cpu_seconds": 1}
    assert bench.classify_runtime({"status": "ok", "raw": raw}, work)["status"] == "input_mismatch"
    raw["result"]["input_consumed"] = 1
    raw["output_hex"] = "52"
    assert bench.classify_runtime({"status": "ok", "raw": raw}, work)["status"] == "output_mismatch"


@pytest.mark.parametrize("result", [None, [], {"stop_reason": 3}, {"stop_reason": None}])
def test_malformed_successful_worker_output_is_explicitly_rejected(result):
    work = bench.CASES["char_io"].workloads[0]
    record = bench.classify_runtime({"status": "ok", "raw": {"result": result}}, work)
    assert record["status"] == "invalid_record"
    assert "runtime" not in record


def test_pairwise_medians_use_same_completed_repeats_and_exclude_warmups():
    rows = []
    for variant, repeat, status, metric, phase in (
        ("semantic_none", 1, "ok", 10, "measurement"),
        ("semantic_none", 2, "step_limit", 1, "measurement"),
        ("semantic_passes", 1, "ok", 5, "measurement"),
        ("semantic_passes", 2, "ok", 100, "measurement"),
        ("semantic_passes", 1, "ok", 999, "warmup"),
    ):
        rows.append(dict(phase=phase, case="case", workload="work", variant=variant,
                         repeat=repeat, status=status, **dict.fromkeys(bench.METRICS, metric)))
    medians, comparisons = bench.summarize_rows(rows)
    candidate = next(row for row in medians if row["variant"] == "semantic_passes")
    assert candidate["run_seconds"] == 52.5
    comparison, = comparisons
    assert comparison["paired_complete_repeats"] == 1
    assert comparison["run_seconds_ratio"] == 0.5


def test_worker_invocation_has_explicit_baseline_gates_and_no_profiling(tmp_path):
    for name, variant in selected_variants().items():
        command = bench.worker_command("compile", tmp_path, tmp_path / "job.json", "compile", variant, 100)
        assert command[0] == sys.executable
        assert ("--legacy-arithmetic" in command) == (name in ("legacy_direct", "semantic_legacy"))
        assert ("--semantic-passes" in command) == (variant.backend == "ir")
        assert "--profile" not in command and "--trace" not in command


def test_recursive_fingerprint_includes_ir_and_runner(tmp_path):
    (tmp_path / "malbolge/compiler/ir").mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "malbolge/compiler/ir/example.py").write_text("first")
    (tmp_path / "scripts/benchmark_semantic_passes.py").write_text("runner")
    hashes = bench.source_fingerprint(tmp_path)
    assert set(hashes) == {"malbolge/compiler/ir/example.py", "scripts/benchmark_semantic_passes.py"}
    (tmp_path / "malbolge/compiler/ir/example.py").write_text("second")
    assert hashes != bench.source_fingerprint(tmp_path)
