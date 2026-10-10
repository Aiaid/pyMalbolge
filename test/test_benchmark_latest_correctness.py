"""Correctness gate for fixed corpus inputs, independent of target timing.

CPython counts actual ASCII/binary input reads. Raw and default optimized IR
execute through the independent semantic interpreter; operation counts only
bound this oracle and never describe Malbolge throughput.
"""
import contextlib
from functools import lru_cache
import io
import json
from pathlib import Path
import sys

import pytest

if sys.version_info < (3, 10):
    pytest.skip('semantic oracle requires Python 3.10+', allow_module_level=True)
pytest.importorskip('xdsl')

from malbolge.compiler.ir.frontend import compile_python_to_semantic_ir, SemanticFrontendError
from malbolge.compiler.ir.interpreter import run_semantic
from malbolge.compiler.ir.semantic_passes import run_semantic_pipeline
from malbolge.compiler.py2mg import compile_python_to_mg, Py2MgError

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / 'benchmarks/manifest.json').read_text())
WORKLOADS = [(program, workload) for program in MANIFEST['programs']
             for workload in program['workloads']]


def cpython_oracle(source, data):
    """Execute actual CPython with counted reads; report its natural exceptions."""
    stream = io.StringIO(data.decode('latin1'))
    output = io.StringIO()
    previous = sys.stdin
    sys.stdin = stream
    status, error = 'completed', None
    def getchar():
        value = stream.read(1)
        return ord(value) if value else 59049
    try:
        with contextlib.redirect_stdout(output):
            exec(compile(source, '<latest-corpus-oracle>', 'exec'),
                 {'getchar': getchar, 'putchar': lambda value: output.write(chr(value % 256))})
    except (ValueError, ZeroDivisionError) as exc:
        status, error = 'runtime_error', type(exc).__name__
    finally:
        sys.stdin = previous
    return {'output_hex': output.getvalue().encode('latin1').hex(),
            'input_consumed': stream.tell(), 'status': status, 'error': error}


@lru_cache(maxsize=None)
def semantic_modules(source):
    raw = compile_python_to_semantic_ir(source)
    optimized = run_semantic_pipeline(raw).module
    return raw, optimized


def semantic_oracle(module, data):
    result = run_semantic(module, data, max_operations=1000000,
                          max_calls=100000, max_call_depth=128, max_output=4096)
    return {'output_hex': result.output.hex(), 'input_consumed': result.input_consumed,
            'status': result.status, 'error': result.error,
            'oracle_operations': result.operations, 'oracle_calls': result.calls}


def manifest_records():
    records = []
    for program, work in WORKLOADS:
        source = (ROOT / 'benchmarks' / program['path']).read_text()
        data, expected = work['stdin'].encode('ascii'), work['stdout'].encode('ascii')
        raw, optimized = semantic_modules(source)
        reference = cpython_oracle(source, data)
        results = {'cpython': reference, 'semantic_raw': semantic_oracle(raw, data),
                   'semantic_default': semantic_oracle(optimized, data)}
        passed = all(r['status'] == 'completed' and r['output_hex'] == expected.hex()
                     and r['input_consumed'] == len(data) for r in results.values())
        records.append({'program': program['id'], 'workload': work['id'],
                        'input_hex': data.hex(), 'expected_hex': expected.hex(),
                        'expected_input_consumed': len(data), 'results': results,
                        'passed': passed})
    return records


@pytest.mark.parametrize('program,work', WORKLOADS,
                         ids=[p['id'] + '/' + w['id'] for p, w in WORKLOADS])
def test_full_corpus_cpython_raw_and_default_semantics(program, work):
    source = (ROOT / 'benchmarks' / program['path']).read_text()
    data, expected = work['stdin'].encode('ascii'), work['stdout'].encode('ascii')
    reference = cpython_oracle(source, data)
    assert reference == {'output_hex': expected.hex(), 'input_consumed': len(data),
                         'status': 'completed', 'error': None}
    for module in semantic_modules(source):
        result = semantic_oracle(module, data)
        assert result['status'] == 'completed', result
        assert result['output_hex'] == expected.hex(), result
        assert result['input_consumed'] == reference['input_consumed'], result


# Errors follow the compiler's checked unsigned input/arithmetic contract;
# CPython itself need not emit error\n or share early malformed-input consumption.
CANARIES = [
    ('nested-break-continue', 'for i in range(3):\n    j=0\n    while j<3:\n        j+=1\n        if j==1:\n            continue\n        if i==1:\n            break\n        putchar(64+j)\n    if i==1:\n        continue\n    putchar(68+i)\n', b'', b'BCDBCF', 0, 'completed'),
    ('double-recursion', 'def fib(n):\n    if n<2:\n        return n\n    return fib(n-1)+fib(n-2)\nn=int(input())\nprint(fib(n),fib(n-1))\n', b'6\n', b'8 5\n', 2, 'completed'),
    ('dynamic-arithmetic', 'n=int(input())\nm=int(input())\nprint(n*m,n//m,n%m)\n', b'123\n17\n', b'2091 7 4\n', 7, 'completed'),
    ('byte-input-keeps-unread-tail', 'x=getchar()\nputchar(x)\n', b'\xffZ', b'\xff', 1, 'completed'),
    ('decimal-whitespace-plus', 'print(int(input()))\n', b'\t+65 \r\n', b'65\n', 7, 'completed'),
    ('condition-call-error', 'def condition():\n    return 65//getchar()\ndef work():\n    while condition():\n        putchar(65)\nwork()\nputchar(90)\n', b'\0Z', b'error\n', 1, 'runtime_error'),
    ('decimal-empty-line-error', 'while int(input("?")):\n    putchar(65)\nputchar(90)\n', b'\n7\n', b'?error\n', 1, 'runtime_error'),
    ('decimal-malformed-early-stop', 'print(int(input()))\nputchar(90)\n', b'12x\n99\n', b'error\n', 3, 'runtime_error'),
    ('decimal-word-overflow', 'print(int(input()))\nputchar(90)\n', b'3486784401\n', b'error\n', 10, 'runtime_error'),
]


def canary_records():
    records = []
    for name, source, data, output, consumed, status in CANARIES:
        raw, optimized = semantic_modules(source)
        results = {'cpython_context': cpython_oracle(source, data),
                   'semantic_raw': semantic_oracle(raw, data),
                   'semantic_default': semantic_oracle(optimized, data)}
        passed = all(r['output_hex'] == output.hex() and r['input_consumed'] == consumed
                     and r['status'] == status for key, r in results.items() if key != 'cpython_context')
        records.append({'name': name, 'source': source, 'input_hex': data.hex(),
                        'expected_hex': output.hex(), 'expected_input_consumed': consumed,
                        'expected_semantic_status': status, 'results': results,
                        'passed': passed, 'contract': 'checked unsigned compiler contract; CPython exceptions/overflow may differ on invalid inputs'})
    return records


@pytest.mark.parametrize('name,source,data,output,consumed,status', CANARIES,
                         ids=[r[0] for r in CANARIES])
def test_nonliteral_and_error_contract_canaries(name, source, data, output, consumed, status):
    if status == 'completed':
        reference = cpython_oracle(source, data)
        assert reference['status'] == status
        assert reference['output_hex'] == output.hex()
        assert reference['input_consumed'] == consumed
    for module in semantic_modules(source):
        result = semantic_oracle(module, data)
        assert (result['output_hex'], result['input_consumed'], result['status']) == (
            output.hex(), consumed, status), result


@pytest.mark.parametrize('source', ['print(1//0)\n',
                                    'def f():\n    return 1%0\nprint(f())\n',
                                    'putchar(missing)\n'])
def test_source_diagnostic_contract_matches_direct(source):
    with pytest.raises(Py2MgError) as direct:
        compile_python_to_mg(source)
    with pytest.raises(SemanticFrontendError) as semantic:
        compile_python_to_semantic_ir(source)
    assert (semantic.value.lineno, semantic.value.message) == (
        direct.value.lineno, direct.value.message)
