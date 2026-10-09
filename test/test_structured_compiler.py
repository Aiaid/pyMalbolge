"""Compiler/CLI and optional xDSL integration of the native target handoff."""

import hashlib
import itertools
import json
import subprocess
import sys
from pathlib import Path

import pytest

from malbolge import compiler
from malbolge.core import MalbolgeConfig, create_memory, parse_source, run_memory


ROOT = Path(__file__).resolve().parents[1]
STYLES = tuple(itertools.product(("cluster", "inline"), ("main", "direct")))
SOURCE = "putchar(65)\n"


def _cli(*args):
    return subprocess.run([sys.executable, "-m", "malbolge", "compile", *map(str, args)],
                          cwd=ROOT, capture_output=True, timeout=30)


def _stats(result):
    return json.loads(result.stderr.decode().splitlines()[-1])


@pytest.mark.parametrize("backend", ("c", "direct"))
@pytest.mark.parametrize("op_style,jmp_style", STYLES)
def test_python_api_native_parity_without_text_handoff(monkeypatch, backend, op_style, jmp_style):
    expected = compiler.compile_python_to_mb(SOURCE, backend, op_style=op_style,
                                             jmp_style=jmp_style)

    def forbidden(*args, **kwargs):
        pytest.fail("native compiler used a legacy text handoff")

    monkeypatch.setattr(compiler, "translate_mg_to_mc", forbidden)
    monkeypatch.setattr(compiler, "assemble_mc_to_mb", forbidden)
    actual = compiler.compile_python_to_mb(SOURCE, backend, op_style=op_style,
                                           jmp_style=jmp_style, target_pipeline="structured")
    assert actual == expected
    config = MalbolgeConfig.malbolge20()
    memory = create_memory(config)
    memory.initialize_source(parse_source(actual, config))
    result = run_memory(memory, config, max_steps=1000000, max_output=4)
    assert (result.stop_reason, result.output) == ("terminated", b"A")


def test_pipeline_selector_validates_before_frontend(monkeypatch):
    monkeypatch.setattr(compiler, "compile_python_to_mg", lambda value: pytest.fail("frontend ran"))
    with pytest.raises(ValueError, match="target_pipeline"):
        compiler.compile_python_to_mb("invalid source", "direct", target_pipeline="missing")


def test_structured_cli_exports_and_separates_cache_identity(tmp_path):
    source = tmp_path / "source.py"
    source.write_text(SOURCE)
    cache = tmp_path / "cache"
    reference = tmp_path / "reference.mb"
    native = tmp_path / "native.mb"
    mc = tmp_path / "native.mc"
    first = _cli(source, "--backend", "direct", "--cache-dir", cache,
                 "--stats", "-o", reference)
    assert first.returncode == 0, first.stderr
    second = _cli(source, "--backend", "direct", "--target-pipeline", "structured",
                  "--cache-dir", cache, "--stats", "--emit-mc", mc, "-o", native)
    assert second.returncode == 0, second.stderr
    report = _stats(second)
    assert report["target_pipeline"] == "structured"
    assert "mg2lal" in [stage["stage"] for stage in report["stages"]]
    assert not any(stage["stage"] == "mg2mc" for stage in report["stages"])
    assert not report["stages"][-1]["cache_hit"]
    assert native.read_bytes() == reference.read_bytes()
    assert compiler.assemble_mc_to_mb(mc.read_text()).encode() == native.read_bytes()
    assert len(list(cache.iterdir())) == 2
    third = _cli(source, "--backend", "direct", "--target-pipeline", "structured",
                 "--cache-dir", cache, "--stats", "-o", native)
    assert third.returncode == 0, third.stderr
    assert _stats(third)["stages"][-1]["cache_hit"]
    assert native.read_bytes() == reference.read_bytes()


def test_base_native_cli_keeps_xdsl_optional(tmp_path):
    source = tmp_path / "source.py"
    source.write_text(SOURCE)
    code = """
import sys
class NoXDSL:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'xdsl' or fullname.startswith('xdsl.'):
            raise AssertionError('base target pipeline imported xDSL')
sys.meta_path.insert(0, NoXDSL())
from malbolge.compiler.cli import main
main(sys.argv[1:])
assert not any(name == 'xdsl' or name.startswith('xdsl.') for name in sys.modules)
"""
    result = subprocess.run([sys.executable, "-c", code, str(source), "--backend", "direct",
                             "--target-pipeline", "structured", "-o", str(tmp_path / "native.mb")],
                            cwd=ROOT, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("frontend", ("compat", "semantic"))
def test_ir_native_pipeline_preserves_verified_module_authority(monkeypatch, frontend):
    pytest.importorskip("xdsl")
    from malbolge.compiler.ir import bridge, lal
    from malbolge.compiler import mg2mc

    expected = compiler.compile_python_to_mb(SOURCE, "ir", ir_frontend=frontend)

    def forbidden(*args, **kwargs):
        pytest.fail("native IR path parsed a complete MC text")

    monkeypatch.setattr(mg2mc, "translate_mg_to_mc", forbidden)
    monkeypatch.setattr(lal, "parse_mc", forbidden)
    module = bridge.compile_python_ir_result(SOURCE, frontend=frontend,
                                             target_pipeline="structured").module
    actual = compiler.compile_python_to_mb(SOURCE, "ir", ir_frontend=frontend,
                                           target_pipeline="structured")
    assert actual == expected
    from malbolge.compiler.mc2mb import layout_lal_to_image
    from malbolge.compiler.memory_image import image_to_data
    exported = lal.lal_to_model(module)
    reconstructed = lal.model_to_lal(exported)
    assert lal.print_lal(reconstructed) == lal.print_lal(module)
    assert image_to_data(layout_lal_to_image(exported))


def test_ir_adapter_rejects_invalid_core_model():
    pytest.importorskip("xdsl")
    from malbolge.compiler.ir.lal import LalIRError, model_to_lal
    from malbolge.compiler.lal_model import LalProgram

    with pytest.raises(LalIRError, match="invalid structured LAL"):
        model_to_lal(LalProgram("not a target", ()))


def test_transformed_ir_records_reach_memory_layout():
    pytest.importorskip("xdsl")
    from xdsl.dialects.builtin import IntAttr
    from malbolge.compiler.ir.lal import DataOp, lal_to_model, parse_mc
    from malbolge.compiler.mc2mb import layout_lal_to_image

    module = parse_mc("PROGRAM_START_TO ENTRY@MAIN\nROUTINE MAIN{\nENTRY:\nEND\nVALUE:65\n}\n")
    before = layout_lal_to_image(lal_to_model(module))
    for op in module.walk():
        if isinstance(op, DataOp):
            op.properties["value"] = IntAttr(66)
    after = layout_lal_to_image(lal_to_model(module))
    assert after != before
    assert any(66 in segment.words for segment in after.segments)


@pytest.mark.parametrize("frontend", ("compat", "semantic"))
def test_structured_ir_cli_exports_ir_and_mc_and_keeps_cache_reports(tmp_path, frontend):
    pytest.importorskip("xdsl")
    source = tmp_path / "source.py"
    source.write_text(SOURCE)
    image, mc, ir_file = (tmp_path / name for name in ("native.mb", "native.mc", "native.mlir"))
    common = (source, "--backend", "ir", "--ir-frontend", frontend,
              "--target-pipeline", "structured", "--cache-dir", tmp_path / "cache",
              "--emit-ir", ir_file, "--emit-mc", mc, "--stats", "-o", image)
    first = _cli(*common)
    assert first.returncode == 0, first.stderr
    report = _stats(first)
    assert report["ir"]["passes"] == ["verify-lal"]
    assert not report["ir"]["cache_hit"]
    assert image.read_bytes() == compiler.assemble_mc_to_mb(mc.read_text()).encode()
    sha = hashlib.sha256(image.read_bytes()).hexdigest()
    second = _cli(*common)
    assert second.returncode == 0, second.stderr
    assert _stats(second)["ir"]["cache_hit"]
    assert _stats(second)["ir"]["reports"] == []
    assert hashlib.sha256(image.read_bytes()).hexdigest() == sha
