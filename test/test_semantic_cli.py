"""Frontend inspection, target compilation and cache/output integrity."""

import contextlib
import io
import json
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

if sys.version_info < (3, 10):
    pytest.skip("optional semantic IR requires Python 3.10+", allow_module_level=True)
pytest.importorskip("xdsl")

from malbolge.compiler import cli
from malbolge.compiler.ir.interpreter import run_semantic
from malbolge.compiler.ir.semantic import parse_semantic
from malbolge.compiler.ir.semantic_passes import OPTIMIZATION_PASSES
from malbolge.malbolge20 import run


@pytest.fixture
def source(tmp_path):
    path = tmp_path / 'source.py'
    path.write_text('putchar(65)\n')
    return path


def invoke(source, arguments):
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        cli.main([str(source), '--backend=ir'] + arguments)
    return stdout.getvalue(), stderr.getvalue()


def expect_error(source, arguments, expected):
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr), pytest.raises(SystemExit) as error:
        cli.main([str(source)] + arguments)
    assert error.value.code == 1
    assert expected in stderr.getvalue() and 'Traceback' not in stderr.getvalue()
    assert source.read_text() == 'putchar(65)\n'


def test_semantic_frontend_inspection_never_invokes_target_lowering(source):
    with (patch.object(cli, 'compile_python_to_mg', side_effect=AssertionError('old frontend')),
          patch('malbolge.compiler.ir.lowering.lower_semantic_to_mg', side_effect=AssertionError('target adapter'))):
        text, stderr = invoke(source, ['--ir-frontend=semantic', '--stats'])
    assert run_semantic(parse_semantic(text)).output == b'A'
    stats = json.loads(stderr.splitlines()[-1])
    assert stats['semantic_ir']['passes'] == list(OPTIMIZATION_PASSES)
    assert [stage['stage'] for stage in stats['stages']] == ['python-to-semantic']


def test_semantic_and_lal_outputs_plus_real_mb_execution(source, tmp_path):
    semantic, lal, mc, mb = [tmp_path / name for name in ('semantic.mlir', 'lal.mlir', 'out.mc', 'out.mb')]
    _, stderr = invoke(source, ['--emit-semantic-ir', str(semantic), '--emit-ir', str(lal),
                                '--emit-mc', str(mc), '-o', str(mb), '--stats'])
    assert run_semantic(parse_semantic(semantic.read_text())).output == b'A'
    assert 'lal.' in lal.read_text()
    execution = run(mb.read_text(), max_steps=2_000_000, max_output=8)
    assert execution.output == b'A' and execution.stop_reason == 'terminated'
    stats = json.loads(stderr.splitlines()[-1])
    assert stats['ir_frontend'] == 'semantic'
    assert stats['ir']['passes'] == ['verify-lal']
    assert stats['semantic_ir']['passes'] == list(OPTIMIZATION_PASSES)


def test_frontend_options_and_semantic_output_aliases(source, tmp_path):
    expect_error(source, ['--backend=c', '--emit-semantic-ir', '-'], "requires backend='ir'")
    expect_error(source, ['--backend=ir', '--ir-frontend=compat', '--emit-semantic-ir', '-'],
                 'requires --ir-frontend=semantic')
    expect_error(source, ['--backend=ir', '--emit-semantic-ir', str(source)], 'overwrite')
    target = str(tmp_path / 'same')
    expect_error(source, ['--backend=ir', '--emit-semantic-ir', target, '--emit-ir', target], 'distinct')
    expect_error(source, ['--backend=ir', '--emit-semantic-ir', '-', '--emit-ir', '-'], 'distinct')


def test_unknown_semantic_pass_fails_before_frontend_or_output(source, tmp_path):
    target = tmp_path / 'out.mlir'
    target.write_text('last good IR')
    with patch('malbolge.compiler.ir.frontend.compile_python_to_semantic_ir',
               side_effect=AssertionError('frontend ran')):
        expect_error(source, ['--backend=ir', '--emit-semantic-ir', str(target),
                             '--semantic-passes=missing'], 'Unknown IR pass')
    assert target.read_text() == 'last good IR'


def test_cached_semantics_restored_verified_and_pass_order_keyed(source, tmp_path):
    target, cache = tmp_path / 'out.mlir', tmp_path / 'cache'
    arguments = ['--emit-semantic-ir', str(target), '--cache-dir', str(cache), '--stats']
    invoke(source, arguments)
    initial = target.read_text()
    with patch('malbolge.compiler.ir.frontend.compile_python_to_semantic_ir',
               side_effect=AssertionError('frontend ran')):
        _, stderr = invoke(source, arguments)
    stats = json.loads(stderr.splitlines()[-1])
    assert stats['semantic_ir']['cached_stage'] == 'semantic'
    assert stats['semantic_ir']['reports'] == []
    assert 'ir_digest' in stats['semantic_ir']['summary']
    next(cache.glob('*/program.semantic')).write_text('corrupt')
    invoke(source, arguments)
    assert target.read_text() == initial
    invoke(source, arguments + ['--semantic-passes=verify-semantic,verify-semantic'])
    assert len(list(cache.glob('*/manifest.json'))) == 2


def test_complete_image_cache_retains_both_pass_selections(source, tmp_path):
    target, cache = tmp_path / 'out.mb', tmp_path / 'cache'
    arguments = ['--ir-frontend=semantic', '-o', str(target), '--cache-dir', str(cache), '--stats']
    invoke(source, arguments)
    with patch('malbolge.compiler.ir.frontend.compile_python_to_semantic_ir',
               side_effect=AssertionError('frontend ran')):
        _, stderr = invoke(source, arguments)
    stats = json.loads(stderr.splitlines()[-1])
    assert stats['semantic_ir']['cached_stage'] == stats['ir']['cached_stage'] == 'mb'
    assert stats['semantic_ir']['passes'] == list(OPTIMIZATION_PASSES)
    assert stats['ir']['passes'] == ['verify-lal']
    assert stats['semantic_ir']['reports'] == stats['ir']['reports'] == []


def test_optimization_levels_are_explicit_and_preserve_observables(source):
    source.write_text('x=65\ny=x+1\nputchar(y)\n')
    raw, raw_stats = invoke(source, ['--opt-level=0', '--stats'])
    optimized, optimized_stats = invoke(source, ['--opt-level=1', '--stats'])
    raw_module, optimized_module = parse_semantic(raw), parse_semantic(optimized)
    assert run_semantic(raw_module).output == run_semantic(optimized_module).output == b'B'
    assert json.loads(raw_stats.splitlines()[-1])['semantic_ir']['passes'] == ['verify-semantic']
    assert json.loads(optimized_stats.splitlines()[-1])['semantic_ir']['passes'] == list(OPTIMIZATION_PASSES)
    assert sum(op.name == 'pysem.load' for op in optimized_module.walk()) < sum(
        op.name == 'pysem.load' for op in raw_module.walk())


def test_profile_and_named_passes_cannot_conflict(source):
    expect_error(source, ['--backend=ir', '--opt-level=0', '--semantic-passes=verify-semantic'],
                 'alternative selections')



def test_level_one_applies_to_non_ir_compilation(source):
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        cli.main([str(source), '--opt-level=1', '--no-cache', '--stats'])
    stats = json.loads(stderr.getvalue().splitlines()[-1])
    from malbolge.compiler import compile_python_to_mg
    assert stdout.getvalue() == compile_python_to_mg(source.read_text())
    assert stats['backend'] == 'direct'
    assert stats['optimization']['opt_level'] == 1
    assert stats['optimization']['arithmetic_optimizations'] is True
    assert stats['cache']['mode'] == 'disabled'
