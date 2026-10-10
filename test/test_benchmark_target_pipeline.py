"""Benchmark selection, native handoffs and incomplete-sample boundaries."""

import csv
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.benchmark_suite import load_manifest, run_manifest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("benchmark_target_runner", ROOT / "scripts/benchmark_pipeline.py")
BENCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCH)


def arguments(**updates):
    options = dict(backend="direct", op_style="cluster", jmp_style="main",
                   max_steps=2000000, target_pipeline="structured", ir_frontend="semantic")
    options.update(updates)
    return SimpleNamespace(**options)


def test_old_worker_defaults_preserve_text_and_semantic():
    selection = BENCH.selection_metadata(SimpleNamespace())
    assert selection["target_pipeline"] == "text"
    assert selection["ir_frontend"] == "semantic"
    assert selection["compilation_cache"] == "disabled"


@pytest.mark.parametrize("backend,frontend", [("c", "semantic"), ("direct", "semantic"),
                                                ("ir", "compat"), ("ir", "semantic")])
def test_native_compile_and_runtime_skip_text_handoffs(tmp_path, monkeypatch, backend, frontend):
    if backend == "ir":
        pytest.importorskip("xdsl")
    from malbolge.compiler import mg2mc, mc2mb
    from malbolge.compiler import lal_model, memory_image

    def forbidden(*args, **kwargs):
        raise AssertionError("native benchmark entered text handoff/export")

    monkeypatch.setattr(mg2mc, "translate_mg_to_mc", forbidden)
    monkeypatch.setattr(mc2mb, "parse_mc_to_data", forbidden)
    monkeypatch.setattr(mc2mb._Assembler, "memory_init_code1", forbidden)
    monkeypatch.setattr(lal_model, "emit_lal_to_mc", forbidden)
    monkeypatch.setattr(memory_image, "image_to_data", forbidden)
    source, text = BENCH.CASES["echo"]
    args = arguments(backend=backend, ir_frontend=frontend, expected_input_consumed=1)
    compiled = BENCH.compile_sample(args, tmp_path, source)
    assert "mg-to-lal" in [stage["stage"] for stage in compiled["stages"]]
    assert "lal-to-memory-image" in [stage["stage"] for stage in compiled["stages"]]
    assert not compiled["diagnostic_exports"]
    assert compiled["structure"]["assembly_handoff"] == "LalProgram->MemoryImage"
    assert not (tmp_path / "program.mc").exists()
    assert not (tmp_path / "program.data").exists()
    result = BENCH.runtime_sample(args, tmp_path, source, text)
    assert result["passed"] and result["completed"]
    assert result["output_hex"] == "51"
    (tmp_path / "compile.json").write_text(json.dumps(compiled))
    (tmp_path / "runtime.json").write_text(json.dumps(result))
    trace = BENCH.trace_sample(args, tmp_path, source, text)
    assert trace["passed"]
    assert trace["entry_address"] == compiled["structure"]["data"]["entry_address"]


def test_native_diagnostic_exports_are_separate_from_stages(tmp_path):
    compiled = BENCH.compile_sample(arguments(diagnostic_exports=True), tmp_path, "putchar(65)\n")
    stages = [stage["stage"] for stage in compiled["stages"]]
    diagnostics = [stage["stage"] for stage in compiled["diagnostic_exports"]]
    assert "diagnostic.lal-to-mc" in diagnostics
    assert "diagnostic.image-to-data" in diagnostics
    assert not any(name.startswith("diagnostic.") for name in stages)
    assert (tmp_path / "program.mc").exists() and (tmp_path / "program.data").exists()


@pytest.mark.parametrize("reason", ["step_limit", "output_limit", "input_exhausted", "invalid_instruction"])
def test_incomplete_runtime_metrics_are_partial_only(tmp_path, monkeypatch, reason):
    from malbolge import core
    # A tiny real artifact keeps loading/validation genuine; inject only the VM
    # stop result to cover every bounded/invalid outcome without huge programs.
    BENCH.compile_sample(arguments(), tmp_path, "putchar(65)\n")
    monkeypatch.setattr(core, "run_memory", lambda *a, **kw:
                        core.RunResult(b"", reason, 7, 0, 0, 0, 0))
    result = BENCH.runtime_sample(arguments(stdout_hex="41"), tmp_path, "putchar(65)\n", "")
    assert not result["passed"] and not result["completed"]
    assert not BENCH.completed_runtime(result)
    for field in ("execute_seconds", "execute_cpu_seconds", "cpu_seconds", "wall_seconds"):
        assert field not in result
        assert field in result["partial_diagnostics"]["measurements"]
    assert result["partial_diagnostics"]["result"]["steps"] == 7


def make_manifest(tmp_path, consumed=1):
    (tmp_path / "echo.py").write_text("putchar(getchar())\n")
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"schema_version": 1, "programs": [{
        "id": "echo", "path": "echo.py", "tier": "smoke",
        "workloads": [{"id": "one", "stdin": "A", "stdout": "A",
                       "expected_input_consumed": consumed, "max_steps": 10,
                       "timeout_seconds": 1}]}]}))
    return path


@pytest.mark.parametrize("consumed", [True, -1, 2, "1"])
def test_manifest_validates_expected_input_consumption(tmp_path, consumed):
    with pytest.raises(ValueError, match="expected_input_consumed"):
        load_manifest(make_manifest(tmp_path, consumed))


@pytest.mark.parametrize("timeout", [False, True])
def test_suite_propagates_native_options_and_never_reports_partial_runtime_as_full(tmp_path, monkeypatch, timeout):
    manifest = make_manifest(tmp_path)
    commands = []

    def child(command, **kwargs):
        commands.append(command)
        task = command[command.index("--worker") + 1]
        job = json.loads(Path(command[command.index("--job") + 1]).read_text())
        assert job["expected_input_consumed"] == 1
        if task == "runtime" and timeout:
            raise BENCH.subprocess.TimeoutExpired(command, 1)
        directory = Path(command[command.index("--directory") + 1])
        record = command[command.index("--record") + 1]
        if task == "oracle":
            value = {"passed": True, "code_seconds": 0.1, "code_cpu_seconds": 0.1}
        elif task == "compile":
            value = {"stages": [{"stage": "mg-to-lal", "seconds": 0.1}],
                     "image": {"bytes": 10}, "cpu_seconds": 0.1}
        else:
            value = {"passed": False, "completed": False,
                     "result": {"stop_reason": "step_limit", "steps": 10},
                     "partial_diagnostics": {"measurements": {"execute_seconds": 0.5}}}
        (directory / (record + ".json")).write_text(json.dumps(value))
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(BENCH.subprocess, "run", child)
    monkeypatch.setattr(BENCH, "hardware_environment", lambda: {})
    args = arguments(manifest=manifest, cases=None, suite="all", list=False,
                     repeats=1, timeout=1, runtime=True, stop_after="mb", trace=False,
                     workloads=None, output_dir=tmp_path / "results", hardware_info=None,
                     profile=False, backends=["ir"], styles=["cluster/main"], discard_images=False,
                     semantic_passes="verify-semantic", legacy_arithmetic=False)
    assert run_manifest(args, BENCH) == 1
    for command in commands:
        assert command[command.index("--target-pipeline") + 1] == "structured"
        assert command[command.index("--ir-frontend") + 1] == "semantic"
        assert command[command.index("--semantic-passes") + 1] == "verify-semantic"
    report = json.loads((args.output_dir / "report.json").read_text())
    assert report["selection"]["target_pipeline"] == "structured"
    assert report["selection"]["runner_version"] == BENCH.RUNNER_VERSION
    assert report["attempted_target_runs"] == 1
    assert report["completed_target_runs"] == 0
    runtime = report["samples"][0]["workloads"][0]["runtime"]
    assert "whole_process_seconds" not in runtime
    assert "whole_process_seconds" in runtime["partial_diagnostics"]
    with (args.output_dir / "summary.csv").open() as stream:
        row = next(csv.DictReader(stream))
    assert row["status"] == "failed"
    for field in ("steps", "run_seconds", "execute_seconds", "steps_per_second"):
        assert row[field] == ""


def test_input_consumption_mismatch_is_a_correctness_failure(tmp_path):
    source, text = BENCH.CASES["echo"]
    args = arguments(expected_input_consumed=0)
    BENCH.compile_sample(args, tmp_path, source)
    result = BENCH.runtime_sample(args, tmp_path, source, text)
    assert result["completed"] and not result["passed"]
    assert result["result"]["input_consumed"] == 1


def test_ir_compat_refuses_ignored_semantic_options(tmp_path):
    with pytest.raises(ValueError, match="semantic options"):
        BENCH.compile_sample(arguments(backend="ir", ir_frontend="compat",
                                      semantic_passes="verify-semantic"), tmp_path, "putchar(65)\n")
