"""Semantic pass contracts and the explicit target-adapter boundary."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import ClassVar

import pytest

if sys.version_info < (3, 10):
    pytest.skip("optional semantic IR requires Python 3.10+", allow_module_level=True)
pytest.importorskip("xdsl")

from xdsl.dialects.builtin import IntAttr
from xdsl.passes import ModulePass
from malbolge.compiler.ir import compile_semantic_to_mc
from malbolge.compiler.ir.frontend import compile_python_to_semantic_ir
from malbolge.compiler.ir.interpreter import run_semantic
from malbolge.compiler.ir.passes import PipelineError, available_passes
from malbolge.compiler.ir.semantic import MOD, ConstOp, parse_semantic, print_semantic
from malbolge.compiler.ir.semantic_passes import (
    VerifySemanticPass, compile_python_semantic_result, run_semantic_pipeline,
    validate_semantic_pass_names, OPTIMIZATION_PASSES,
)
from malbolge.compiler.mc2mb import assemble_mc_to_mb
from malbolge.malbolge20 import run


def test_dialects_have_separate_explicit_pass_selections(monkeypatch):
    assert available_passes() == ("verify-lal",)
    assert validate_semantic_pass_names() == OPTIMIZATION_PASSES
    from malbolge.compiler.ir import frontend
    monkeypatch.setattr(frontend, 'compile_python_to_semantic_ir',
                        lambda _: pytest.fail('frontend ran before pass selection'))
    with pytest.raises(PipelineError, match='Unknown IR pass'):
        compile_python_semantic_result('invalid source', ('verify-lal',))


def test_semantic_reports_do_not_manufacture_target_metrics():
    result = compile_python_semantic_result('putchar(65)', ('verify-semantic',), snapshots=True)
    payload = result.to_dict()
    json.dumps(payload)
    assert payload['passes'] == ['verify-semantic']
    report = payload['reports'][0]
    assert report['before'] == report['after']
    assert 'mc_digest' not in report['before'] and 'mc_bytes' not in report['before']
    assert report['before']['operation_counts']['pysem.putchar'] == 1
    assert [item['stage'] for item in payload['snapshots']] == ['input', '1:verify-semantic']


@dataclass(frozen=True)
class ChangeOutput(ModulePass):
    name: ClassVar[str] = 'change-output'

    def apply(self, ctx, module):
        for op in module.walk():
            if isinstance(op, ConstOp) and op.value.data == 65:
                op.properties['value'] = IntAttr(66)


@dataclass(frozen=True)
class InvalidWord(ModulePass):
    name: ClassVar[str] = 'invalid-word'

    def apply(self, ctx, module):
        for op in module.walk():
            if isinstance(op, ConstOp):
                op.properties['value'] = IntAttr(MOD)
                break


def test_semantic_pass_edit_is_authoritative_through_real_target_adapter():
    original = compile_python_to_semantic_ir('putchar(65)')
    before = print_semantic(original)
    registry = {'change-output': ChangeOutput, 'verify-semantic': VerifySemanticPass}
    result = run_semantic_pipeline(original, ('change-output', 'verify-semantic'), registry=registry)
    assert print_semantic(original) == before
    assert run_semantic(result.module).output == b'B'
    assert result.reports[0].before.ir_digest != result.reports[0].after.ir_digest
    image = assemble_mc_to_mb(compile_semantic_to_mc(result.module))
    execution = run(image, max_steps=2_000_000, max_output=8)
    assert execution.output == b'B' and execution.stop_reason == 'terminated'


def test_failed_post_pass_verification_keeps_input_unchanged():
    module = compile_python_to_semantic_ir('putchar(65)')
    before = print_semantic(module)
    with pytest.raises(PipelineError, match='after pass.*invalid-word'):
        run_semantic_pipeline(module, ('invalid-word',), registry={'invalid-word': InvalidWord})
    assert print_semantic(module) == before


def test_empty_semantic_pipeline_still_validates_and_clones():
    module = compile_python_to_semantic_ir('putchar(65)')
    result = run_semantic_pipeline(module, ())
    assert result.module is not module and not result.reports
    assert print_semantic(module) == print_semantic(result.module)


def test_source_locations_survive_inspection_and_reload():
    original = compile_python_to_semantic_ir('x=7\ny=x+2\nputchar(y)\n')
    text = print_semantic(original)
    restored = parse_semantic(text)
    assert [op.location for op in restored.walk()] == [op.location for op in original.walk()]
    assert '<python-subset>' in text


def test_oracle_uses_the_bounded_vm_text_input_contract():
    module = compile_python_to_semantic_ir('putchar(getchar())')
    result = run_semantic(module, 'é')
    assert result.output == b'\xc3' and result.input_consumed == 1
    assert run_semantic(module, 'é'.encode('utf8')).output == result.output
    with pytest.raises(TypeError, match='text or bytes-like'):
        run_semantic(module, 2)


def test_semantic_location_and_structure_canary_across_hash_seeds():
    source = ('def next_byte(value):\n    return value + 1\n'
              'byte = getchar()\nputchar(next_byte(byte))\n')
    script = '''import json
from malbolge.compiler.ir import compile_python_semantic_result
print(json.dumps(compile_python_semantic_result(%r, snapshots=True).to_dict(), sort_keys=True))
''' % source
    outputs = [subprocess.check_output([sys.executable, '-c', script],
                 cwd=Path(__file__).resolve().parents[1],
                 env=dict(os.environ, PYTHONHASHSEED=seed))
               for seed in ('0', '1', '73', 'random')]
    assert len(set(outputs)) == 1
    summary = json.loads(outputs[0])['reports'][0]['after']
    # Pinned xDSL/dialect/source-location canary; review deliberate changes.
    assert summary['total_operations'] == 15
    assert summary['ir_digest'] == 'b57dc7988ae7e244c03596f6a8903b7a0964ad2d00afe94694defd52fbf1b811'
