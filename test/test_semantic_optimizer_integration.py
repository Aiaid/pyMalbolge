"""Pass selection owns arithmetic decisions; legacy references remain stable."""

import sys
from types import SimpleNamespace

import pytest

if sys.version_info < (3, 10):
    pytest.skip('optional semantic passes require Python 3.10+', allow_module_level=True)
pytest.importorskip('xdsl')

from malbolge.compiler.ir.frontend import compile_python_to_semantic_ir
from malbolge.compiler.ir.interpreter import run_semantic
from malbolge.compiler.ir.lowering import lower_semantic_to_mg
from malbolge.compiler.ir.semantic_passes import (
    CANDIDATE_OPTIMIZATION_PASSES, CANDIDATE_DECIMAL_PASSES, compile_python_semantic_result,
)
from malbolge.compiler.py2mg import compile_python_to_mg
from scripts import benchmark_pipeline as bench


def test_legacy_reference_is_unchanged_and_semantic_math_is_gated():
    source = 'n=getchar()\nputchar(n//1)\n'
    assert compile_python_to_mg(source) == compile_python_to_mg(source, arithmetic_optimizations=True)
    assert 'DEF ZZDIV' not in compile_python_to_mg(source)
    assert 'DEF ZZDIV' in compile_python_to_mg(source, arithmetic_optimizations=False)
    raw = compile_python_to_semantic_ir(source)
    assert 'DEF ZZDIV' in lower_semantic_to_mg(raw)
    optimized = compile_python_semantic_result(source, CANDIDATE_OPTIMIZATION_PASSES)
    assert 'DEF ZZDIV' not in lower_semantic_to_mg(optimized.module)
    assert run_semantic(raw, b'A').output == run_semantic(optimized.module, b'A').output == b'A'


@pytest.mark.parametrize('pipeline', [CANDIDATE_OPTIMIZATION_PASSES, CANDIDATE_DECIMAL_PASSES])
def test_benchmark_records_ir_and_fixed_raw_byte_contract(tmp_path, pipeline):
    source = 'putchar(getchar())\n'
    args = SimpleNamespace(backend='ir', semantic_passes=','.join(pipeline), legacy_arithmetic=False,
                           op_style='cluster', jmp_style='main', max_steps=2_000_000,
                           stdin_hex='ff', stdout_hex='ff', expected_input_consumed=1)
    compiler = bench.compile_sample(args, tmp_path, source)
    assert compiler['image']['bytes'] > 0
    assert compiler['structure']['legacy_target_arithmetic'] is False
    assert compiler['structure']['semantic_passes']['passes'] == list(pipeline)
    assert (tmp_path / 'program.semantic.mlir').exists()
    result = bench.runtime_sample(args, tmp_path, source, '\xff')
    assert result['passed'] and result['result']['input_consumed'] == 1


def test_fixed_expected_input_consumption_is_checked(tmp_path):
    source = 'putchar(getchar())\n'
    args = SimpleNamespace(backend='ir', semantic_passes='verify-semantic', legacy_arithmetic=False,
                           op_style='cluster', jmp_style='main', max_steps=2_000_000,
                           stdin_hex='41', stdout_hex='41', expected_input_consumed=0)
    bench.compile_sample(args, tmp_path, source)
    assert not bench.runtime_sample(args, tmp_path, source, 'A')['passed']
