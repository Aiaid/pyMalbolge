"""Output semantics and typed-IR boundaries for decimal-output lowering."""

import json
from pathlib import Path
import random
import sys

import pytest

if sys.version_info < (3, 10):
    pytest.skip("optional semantic IR requires Python 3.10+", allow_module_level=True)
pytest.importorskip("xdsl")

from xdsl.dialects.builtin import FileLineColLoc, IntAttr, StringAttr

from malbolge.compiler.ir.decimal_passes import LowerDecimalOutputPass
from malbolge.compiler.ir.frontend import compile_python_to_semantic_ir
from malbolge.compiler.ir.interpreter import run_semantic
from malbolge.compiler.ir.lowering import lower_semantic_to_mg, lower_semantic_to_python_ast
from malbolge.compiler.ir.semantic import (
    BinaryOp, CallOp, ConstOp, LoadOp, MAX_WORD, PrintLiteralOp,
    PrintWordOp, ReadIntOp, create_semantic_context,
    get_program, parse_semantic, print_semantic, strings, verify_semantic,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "benchmarks/manifest.json").read_text())


def apply(module):
    LowerDecimalOutputPass().apply(create_semantic_context(), module)
    return module


def helpers(module):
    return [func for func in get_program(module).body.block.ops
            if func.attributes.get("pysem.generated_by") == StringAttr("lower-decimal-output")]


def compare_results(before, after):
    # IR operation/call/depth budgets intentionally describe different work
    # after lowering; compare observable behavior with sufficient budgets.
    assert (after.output, after.globals, after.return_value, after.input_consumed,
            after.status, after.error) == (
        before.output, before.globals, before.return_value, before.input_consumed,
        before.status, before.error)


def test_all_constant_words_become_literals_without_any_helper():
    module = compile_python_to_semantic_ir("print(0,1,10,3486784400,sep=':',end='!')\n")
    original_functions = tuple(get_program(module).body.block.ops)
    apply(module)
    assert tuple(get_program(module).body.block.ops) == original_functions
    assert not helpers(module)
    assert not any(isinstance(op, PrintWordOp) for op in module.walk())
    assert run_semantic(module).output == b"0:1:10:3486784400!"
    assert not any(isinstance(op, CallOp) for op in module.walk())


def test_no_word_output_is_exact_noop():
    module = compile_python_to_semantic_ir("print('Hello')\nputchar(65)\n")
    before = print_semantic(module)
    apply(module)
    assert print_semantic(module) == before
    assert not helpers(module)


def test_dynamic_output_is_a_real_typed_nonrecursive_helper_call():
    module = compile_python_to_semantic_ir("x=getchar()\nprint(x,x,sep=':')\n")
    prints = [(op.value, op.location, op.parent) for op in module.walk() if isinstance(op, PrintWordOp)]
    originals = [op for op in module.walk() if isinstance(op, (ReadIntOp, PrintLiteralOp))]
    apply(module)
    verify_semantic(module)
    helper, = helpers(module)
    assert helper.returns.data == "void"
    assert len(helper.parameters) == 1
    assert not helper.globals
    assert not any(isinstance(op, (CallOp, PrintWordOp, ReadIntOp)) for op in helper.walk())
    assert {op.kind.data for op in helper.walk() if isinstance(op, BinaryOp)} == {"add", "sub"}
    calls = [op for op in module.walk() if isinstance(op, CallOp) and op.callee.data == helper.sym_name.data]
    assert len(calls) == len(prints) == 2
    for call, (value, location, parent) in zip(calls, prints):
        assert list(call.arguments) == [value]
        assert call.location == location
        assert call.parent is parent
        assert not call.results
    assert [op for op in module.walk() if isinstance(op, (ReadIntOp, PrintLiteralOp))] == originals
    for operation in helper.walk():
        assert isinstance(operation.location, FileLineColLoc)
        assert operation.location.filename.data == "<lower-decimal-output>"
    assert run_semantic(module, b"A").output == b"65:65\n"
    assert "ZZPRINTINT" not in lower_semantic_to_mg(module)


def test_boundary_and_seeded_random_words_match_independent_decimal_oracles():
    values = {*range(10), 10, 99, 100, MAX_WORD}
    for exponent in range(10):
        values.update(value for value in (10**exponent - 1, 10**exponent, 10**exponent + 1)
                      if 0 <= value <= MAX_WORD)
    randomizer = random.Random(0xDEC1A1)
    values.update(randomizer.randrange(MAX_WORD + 1) for _ in range(128))
    values = sorted(values)
    source = "def render(value):\n    print(value)\n" + "".join(f"render({value})\n" for value in values)
    module = compile_python_to_semantic_ir(source)
    before = run_semantic(module, max_operations=2_000_000)
    apply(module)
    after = run_semantic(module, max_operations=2_000_000)
    compare_results(before, after)
    expected = "".join(f"{value}\n" for value in values).encode("ascii")
    assert after.status == "completed"
    assert after.output == expected
    assert len(helpers(module)) == 1
    # A second, ordinary-Python execution of generated IR checks arithmetic
    # independently of the semantic interpreter's operation dispatcher.
    output = bytearray()
    exec(compile(lower_semantic_to_python_ast(module), "<decimal-output-oracle>", "exec"),
         {"putchar": output.append, "print": lambda text, end="": output.extend((str(text) + end).encode())})
    assert bytes(output) == expected


def test_repeat_and_incremental_application_reuse_verified_helper():
    module = compile_python_to_semantic_ir("x=getchar()\nprint(x)\n")
    apply(module)
    first_helper, = helpers(module)
    first_text = print_semantic(module)
    apply(module)
    assert print_semantic(module) == first_text
    program = get_program(module)
    entry = next(func for func in program.body.block.ops if func.sym_name.data == program.entry.data)
    extra = LoadOp("x", "global")
    entry.body.block.insert_ops_before([extra, PrintWordOp(extra)], entry.body.block.last_op)
    expected = run_semantic(module, b"A")
    apply(module)
    assert helpers(module) == [first_helper]
    assert run_semantic(module, b"A").output == expected.output == b"65\n65"
    twice = print_semantic(module)
    apply(module)
    assert print_semantic(module) == twice


def test_modified_helper_marker_is_not_trusted_for_new_word_prints():
    module = compile_python_to_semantic_ir("x=getchar()\nprint(x)\n")
    apply(module)
    original_helper, = helpers(module)
    for ascii_zero in original_helper.walk():
        if isinstance(ascii_zero, ConstOp) and ascii_zero.value.data == 48:
            ascii_zero.properties["value"] = IntAttr(49)
    program = get_program(module)
    entry = next(func for func in program.body.block.ops if func.sym_name.data == program.entry.data)
    extra = LoadOp("x", "global")
    entry.body.block.insert_ops_before([extra, PrintWordOp(extra)], entry.body.block.last_op)
    expected = run_semantic(module, b"A")
    apply(module)
    assert len(helpers(module)) == 2
    assert run_semantic(module, b"A").output == expected.output == b"76\n65"


def test_helper_and_local_names_avoid_all_case_insensitive_namespaces():
    module = compile_python_to_semantic_ir("""MBDECIMALFORMAT=1
def mbdecimalxformat(MBDECIMALXXVALUE):
    local=MBDECIMALXXVALUE
    print(local)
mbdecimalxformat(65)
""")
    original = get_program(module)
    occupied = {name.lower() for name in strings(original.globals)}
    for func in original.body.block.ops:
        occupied.add(func.sym_name.data.lower())
        occupied.update(name.lower() for names in (func.parameters, func.locals, func.globals) for name in strings(names))
    apply(module)
    helper, = helpers(module)
    introduced = {helper.sym_name.data.lower(), *(name.lower() for name in strings(helper.parameters)),
                  *(name.lower() for name in strings(helper.locals))}
    assert not introduced.intersection(occupied)
    assert helper.sym_name.data.startswith("mbdecimalxxx")
    assert run_semantic(module).output == b"65\n"


@pytest.mark.parametrize("source,data,expected", [
    ('print("before",int(input("?")))\nprint("after")\n', b"bad\n", b"?error\n"),
    ('def read():\n    return int(input("?"))\nprint(read())\nprint("after")\n', b"\n", b"?error\n"),
    ('print(int(input("?")))\n', b"3486784401\n", b"?error\n"),
    ('x=int(input("?"))\nprint(x,x+1)\n', b"7\n", b"?7 8\n"),
    ('x=getchar()\nprint("before",65//x)\nprint("after")\n', b"\0", b"error\n"),
    ('x=1\ndef change():\n    global x\n    x=2\n    return x\nprint(x,change())\n', b"", b"1 2\n"),
])
def test_operand_capture_input_errors_prompts_and_effect_order(source, data, expected):
    module = compile_python_to_semantic_ir(source)
    input_ops = [op for op in module.walk() if isinstance(op, ReadIntOp)]
    before = run_semantic(module, data)
    apply(module)
    assert [op for op in module.walk() if isinstance(op, ReadIntOp)] == input_ops
    after = run_semantic(module, data)
    compare_results(before, after)
    assert after.output == expected
    lower_semantic_to_mg(module)


@pytest.mark.parametrize("program", MANIFEST["programs"], ids=lambda item: item["id"])
def test_full_fixed_corpus_semantic_oracles(program):
    source = (ROOT / "benchmarks" / program["path"]).read_text()
    before = compile_python_to_semantic_ir(source)
    after = apply(before.clone())
    for workload in program["workloads"]:
        old = run_semantic(before, workload["stdin"], max_operations=2_000_000)
        new = run_semantic(after, workload["stdin"], max_operations=2_000_000)
        compare_results(old, new)
        assert new.status == "completed", (program["id"], workload["id"], new.status)
        assert new.output == workload["stdout"].encode(), (program["id"], workload["id"])
    # Typed serialization carries the helper implementation and replays it.
    assert print_semantic(parse_semantic(print_semantic(after))) == print_semantic(after)


def test_only_named_pass_performs_decimal_rewrite():
    module = compile_python_to_semantic_ir("x=getchar()\nprint(x)\n")
    before = print_semantic(module)
    lower_semantic_to_python_ast(module)
    assert print_semantic(module) == before
    assert any(isinstance(op, PrintWordOp) for op in module.walk())
    apply(module)
    assert not any(isinstance(op, PrintWordOp) for op in module.walk())
    assert helpers(module)
