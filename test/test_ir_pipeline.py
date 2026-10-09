"""Optional LAL pass architecture and compatibility-bridge contracts.

These are structural/determinism checks, not performance benchmarks.
"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import ClassVar

import pytest

from malbolge.compiler import ir

if sys.version_info < (3, 10):
    pytest.skip("Optional IR requires Python >= 3.10", allow_module_level=True)
pytest.importorskip("xdsl")

from xdsl.context import Context
from xdsl.dialects.builtin import IntAttr, ModuleOp
from xdsl.passes import ModulePass

from malbolge.compiler.ir.bridge import (
    compile_python_ir_result,
    compile_python_to_ir,
    compile_python_via_ir_to_mc,
    mc_to_ir_result,
)
from malbolge.compiler.ir.lal import (
    DataOp, EntryOp, TargetAttr, emit_mc, parse_lal, parse_mc, print_lal,
)
from malbolge.compiler.ir.passes import (
    PipelineError,
    VerifyLalPass,
    available_passes,
    run_pipeline,
    summarize_ir,
    validate_pass_names,
)
from malbolge.compiler.mg2mc import translate_mg_to_mc
from malbolge.compiler.py2mg import compile_python_to_mg


TINY_MC = "PROGRAM_START_TO ENTRY@MAIN\nROUTINE MAIN{\nENTRY:\nVALUE:65\n  END\n}\n"
SCOPED_MC = (
    "PROGRAM_START_TO ENTRY@MAIN\n"
    "FLAG 0/2, READY\nFLAG 8/9, PHASE\n"
    "UNIT{\nCUSTOM:5: DUP\n6: JMP\n}\n"
    "ROUTINE MAIN{\nENTRY:\n"
    "  NEXT READY\n  REV PHASE\n  CUSTOM\n  END\n}\n"
)
ROOT = Path(__file__).resolve().parents[1]


def test_imports_do_not_load_xdsl():
    code = """
import sys
import malbolge.compiler
import malbolge.compiler.ir
import malbolge.compiler.ir.bridge
assert not any(name == 'xdsl' or name.startswith('xdsl.') for name in sys.modules)
"""
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True)


def test_dependency_errors_are_actionable(monkeypatch):
    def missing(name):
        raise ir.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(ir.metadata, "version", missing)
    with pytest.raises(ir.IRDependencyError, match="uv sync --extra ir"):
        ir.require_ir_support()
    monkeypatch.setattr(ir.metadata, "version", lambda name: "0.68.0")
    with pytest.raises(ir.IRDependencyError, match="xdsl==0.69.0; found 0.68.0"):
        ir.require_ir_support()
    monkeypatch.setattr(ir.sys, "version_info", (3, 9, 0))
    with pytest.raises(ir.IRDependencyError, match="Python 3.10 or newer"):
        ir.require_ir_support()


def test_default_registry_is_explicit_and_stable():
    assert available_passes() == ("verify-lal",)
    assert validate_pass_names() == ("verify-lal",)
    assert validate_pass_names(()) == ()
    assert issubclass(VerifyLalPass, ModulePass)
    with pytest.raises(PipelineError, match="Unknown IR pass.*canonicalize"):
        validate_pass_names(("verify-lal", "canonicalize"))
    with pytest.raises(PipelineError, match="sequence"):
        validate_pass_names("verify-lal")
    with pytest.raises(PipelineError, match="nonempty"):
        validate_pass_names(("",))


def test_unknown_pass_rejected_before_frontend(monkeypatch):
    from malbolge.compiler import py2mg

    def should_not_run(source):
        pytest.fail("Frontend ran before pass-name validation")

    monkeypatch.setattr(py2mg, "compile_python_to_mg", should_not_run)
    with pytest.raises(PipelineError, match="Unknown IR pass"):
        compile_python_to_ir("invalid syntax", passes=("missing",))


def test_unknown_pass_rejected_before_mc_parser(monkeypatch):
    from malbolge.compiler.ir import lal

    def should_not_run(source):
        pytest.fail("MC parser ran before pass-name validation")

    monkeypatch.setattr(lal, "parse_mc", should_not_run)
    with pytest.raises(PipelineError, match="Unknown IR pass"):
        mc_to_ir_result("invalid MC", passes=("missing",))


def test_verification_boundaries_and_reports(monkeypatch):
    from malbolge.compiler.ir import passes

    module = parse_mc(TINY_MC)
    verifier = passes.verify_lal
    calls = []

    def counted(op):
        calls.append(op)
        verifier(op)

    monkeypatch.setattr(passes, "verify_lal", counted)
    result = run_pipeline(module, snapshots=True)
    # Input, before pass, VerifyLalPass body, after pass, final output.
    assert len(calls) == 5
    assert result.module is not module
    assert result.reports[0].before == result.reports[0].after
    assert result.reports[0].before.total_operations == sum(
        result.reports[0].before.operation_counts.values()
    )
    assert [item.stage for item in result.snapshots] == ["input", "1:verify-lal"]
    report = result.to_dict()
    assert report["xdsl_version"] == "0.69.0"
    assert report["passes"] == ["verify-lal"]
    assert json.loads(json.dumps(report)) == report
    assert print_lal(parse_lal(result.snapshots[-1].text)) == print_lal(result.module)


def test_empty_pipeline_still_verifies():
    result = run_pipeline(parse_mc(TINY_MC), ())
    assert result.reports == ()
    assert result.snapshots == ()
    assert emit_mc(result.module) == emit_mc(parse_mc(TINY_MC))


@dataclass(frozen=True)
class IncrementDataPass(ModulePass):
    """A test-only real rewrite, deliberately absent from the default registry."""

    name: ClassVar[str] = "test-increment-data"

    def apply(self, ctx: Context, op: ModuleOp) -> None:
        for operation in op.walk():
            if isinstance(operation, DataOp):
                operation.properties["value"] = IntAttr(operation.value.data + 1)


@dataclass(frozen=True)
class BreakEntryPass(ModulePass):
    name: ClassVar[str] = "test-break-entry"

    def apply(self, ctx: Context, op: ModuleOp) -> None:
        for operation in op.walk():
            if isinstance(operation, EntryOp):
                operation.properties["target"] = TargetAttr("MISSING", "MAIN")


def test_custom_module_pass_changes_ir_and_emitted_mc_without_mutating_source():
    module = parse_mc(TINY_MC)
    before = print_lal(module)
    result = run_pipeline(
        module, (IncrementDataPass.name,),
        registry={IncrementDataPass.name: IncrementDataPass}, snapshots=True,
    )
    assert print_lal(module) == before
    assert "  65\n" in emit_mc(module)
    assert "  66\n" in emit_mc(result.module)
    report = result.reports[0]
    assert report.before.ir_digest != report.after.ir_digest
    assert report.before.mc_digest != report.after.mc_digest
    assert report.before.operation_counts == report.after.operation_counts
    assert result.snapshots[0].text != result.snapshots[1].text


def test_invalid_post_pass_rejected_and_input_unchanged():
    module = parse_mc(TINY_MC)
    before = print_lal(module)
    with pytest.raises(PipelineError, match="after pass 'test-break-entry'.*MISSING"):
        run_pipeline(module, (BreakEntryPass.name,), registry={BreakEntryPass.name: BreakEntryPass})
    assert print_lal(module) == before


def test_invalid_input_is_rejected_before_pass_runs():
    module = parse_mc(TINY_MC)
    entry = next(operation for operation in module.walk() if isinstance(operation, EntryOp))
    entry.properties["target"] = TargetAttr("MISSING", "MAIN")
    with pytest.raises(PipelineError, match="pipeline input"):
        run_pipeline(module, (IncrementDataPass.name,), registry={IncrementDataPass.name: IncrementDataPass})
    data = next(operation for operation in module.walk() if isinstance(operation, DataOp))
    assert data.value.data == 65


def test_registry_requires_matching_module_pass():
    with pytest.raises(PipelineError, match="matching ModulePass"):
        run_pipeline(parse_mc(TINY_MC), ("wrong",), registry={"wrong": VerifyLalPass})


@pytest.mark.parametrize("op_style", ("cluster", "inline"))
@pytest.mark.parametrize("jmp_style", ("main", "direct"))
def test_compatibility_bridge_roundtrips_existing_codegen(op_style, jmp_style):
    source = "putchar(65)\n"
    legacy_mc = translate_mg_to_mc(
        compile_python_to_mg(source), op_style=op_style, jmp_style=jmp_style
    )
    canonical = emit_mc(parse_mc(legacy_mc))
    assert compile_python_via_ir_to_mc(source, op_style, jmp_style) == canonical
    result = compile_python_ir_result(source, op_style, jmp_style, snapshots=True)
    assert emit_mc(result.module) == canonical
    assert result.reports[0].before == result.reports[0].after


@pytest.mark.parametrize("source,expected_counts,expected_ir,expected_mc", [
    (
        TINY_MC,
        {"builtin.module": 1, "lal.data": 1, "lal.entry": 1,
         "lal.instruction": 1, "lal.label": 2, "lal.routine": 1},
        "875230bfbab3a76bde13736f3b0250f2c6f346b5d0786cd79288e17ecb145916",
        "6f550b84ee925ad4cb73aad2003c8414cb298df43dfea41e787bf2ef829217cb",
    ),
    (
        SCOPED_MC,
        {"builtin.module": 1, "lal.entry": 1, "lal.flag": 2,
         "lal.instruction": 4, "lal.label": 1, "lal.routine": 1,
         "lal.unit": 1, "lal.unit_cell": 2, "lal.unit_label": 1},
        "aa78e5eab481ffdb48e6744e109e3fb5cc8614ae3f472954584fb4e28a24ebb3",
        "31060cc281cf8b2ea0659ef6a121b0c86c4499e21249c3af3596389ef41e8ef3",
    ),
], ids=["data-and-entry", "flag-periods-and-unit-scope"])
def test_textual_digest_hashseed_determinism(source, expected_counts, expected_ir, expected_mc):
    script = """
import json
from malbolge.compiler.ir.lal import parse_mc
from malbolge.compiler.ir.passes import run_pipeline
source = %r
print(json.dumps(run_pipeline(parse_mc(source), snapshots=True).to_dict(), sort_keys=True))
""" % source
    outputs = []
    for seed in ("0", "1", "73", "random"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        outputs.append(subprocess.check_output([sys.executable, "-c", script], cwd=ROOT, env=env))
    assert all(output == outputs[0] for output in outputs)
    module = parse_mc(source)
    summary = summarize_ir(module)
    # Version-pinned serialization canaries: update only after inspecting a
    # deliberate dialect/printer change with the pinned xDSL version.
    # The scoped fixture deliberately includes period-2/9 flags, structured
    # targets, and a custom UNIT region. Flags serialize their separate symbol
    # namespace as unit_name; routine and local labels retain sym_name.
    assert summary.ir_digest == expected_ir
    assert summary.mc_digest == expected_mc
    assert summary.operation_counts == expected_counts
    assert summary.total_operations == sum(expected_counts.values())
    assert summary.mc_digest == hashlib.sha256(emit_mc(module).encode()).hexdigest()
