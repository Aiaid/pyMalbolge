"""Native while predicates preserve semantic SSA order and observable words.

These tests use explicit TargetWhile expansion for the ordinary-domain Python
oracle, and MG-to-MC acceptance for the backend boundary. They build no MB image.
"""
import ast
from itertools import product
import sys

import pytest

if sys.version_info < (3, 10):
    pytest.skip("native semantic conditions require Python 3.10+", allow_module_level=True)
pytest.importorskip("xdsl")

from xdsl.dialects.builtin import ModuleOp

from malbolge.compiler.ir.frontend import compile_python_to_semantic_ir
from malbolge.compiler.ir.interpreter import run_semantic
from malbolge.compiler.ir.lowering import (
    lower_semantic_to_mg, lower_semantic_to_python_ast, lower_semantic_to_target_ast,
)
from malbolge.compiler.ir.semantic import (
    BinaryOp, CompareOp, ConstOp, FuncOp, GetCharOp, PrintLiteralOp,
    ProgramOp, ReturnOp, WhileOp, YieldOp, print_semantic, verify_semantic,
)
from malbolge.compiler.mg2mc import translate_mg_to_mc
from malbolge.compiler.target_ast import TargetWhile
from test.test_semantic_target_interface import run_expanded


def native_target(module, enabled):
    return lower_semantic_to_target_ast(module, native_conditions=enabled)


def only_loop(tree):
    loops = [node for node in ast.walk(tree) if isinstance(node, TargetWhile)]
    assert len(loops) == 1
    return loops[0]


def assert_oracle(module, target, data=b"", expected=None):
    reference = run_semantic(module, data)
    output, consumed, status = run_expanded(target, data)
    assert (output, consumed, status) == (
        reference.output, reference.input_consumed, reference.status)
    if expected is not None:
        assert output == expected


def manual(condition_ops, body_ops=()):
    loop = WhileOp(condition_ops, body_ops)
    return ModuleOp([ProgramOp([], [FuncOp("entry", [], [],
        [loop, PrintLiteralOp("after"), ReturnOp()], returns="void")], entry="entry")])


def constant_region(value, prefix=()):
    constant = ConstOp(value)
    return [*prefix, constant, YieldOp(constant)]


@pytest.mark.parametrize("enabled", [False, True], ids=["word-then-truth", "native-predicate"])
def test_single_terminal_comparison_uses_requested_target_representation(enabled):
    module = compile_python_to_semantic_ir("x=0\nwhile x<2:\n    putchar(65+x)\n    x+=1\n")
    original = print_semantic(module)
    target = native_target(module, enabled)
    loop = only_loop(target)
    assert loop.condition_prelude
    assert isinstance(loop.test, ast.Compare if enabled else ast.Name)
    booleans = [node for statement in loop.condition_prelude for node in ast.walk(statement)
                if isinstance(node, ast.IfExp) and isinstance(node.test, ast.Compare)]
    assert len(booleans) == (0 if enabled else 1)
    if enabled:
        assert len(loop.test.ops) == len(loop.test.comparators) == 1
    assert_oracle(module, target, expected=b"AB")
    assert print_semantic(module) == original


def test_native_target_does_not_change_ordinary_python_view_or_semantic_ir():
    module = compile_python_to_semantic_ir("x=0\nwhile x<2:\n    x+=1\n")
    before = ast.dump(lower_semantic_to_python_ast(module), include_attributes=True)
    original = print_semantic(module)
    target = native_target(module, True)
    assert isinstance(only_loop(target).test, ast.Compare)
    ordinary = lower_semantic_to_python_ast(module)
    assert not any(isinstance(node, TargetWhile) for node in ast.walk(ordinary))
    assert ast.dump(ordinary, include_attributes=True) == before
    assert print_semantic(module) == original


@pytest.mark.parametrize("enabled", [False, True])
def test_left_global_snapshot_precedes_right_operand_mutation(enabled):
    module = compile_python_to_semantic_ir("""x=65
def change():
    global x
    x=66
    return 66
while x<change():
    putchar(x)
    break
putchar(67)
""")
    target = native_target(module, enabled)
    assert_oracle(module, target, expected=b"BC")
    if enabled:
        loop = only_loop(target)
        assert isinstance(loop.test, ast.Compare)
        left, right = loop.test.left, loop.test.comparators[0]
        assert isinstance(left, ast.Name) and isinstance(right, ast.Name)
        assignments = [(index, node) for index, node in enumerate(loop.condition_prelude)
                       if isinstance(node, ast.Assign)]
        left_index, left_capture = next((index, node) for index, node in assignments
                                       if node.targets[0].id == left.id)
        right_index, right_capture = next((index, node) for index, node in assignments
                                         if node.targets[0].id == right.id)
        assert isinstance(left_capture.value, ast.Name)
        assert isinstance(right_capture.value, ast.Call)
        assert left_capture.value.id != left.id
        assert left_index < right_index


@pytest.mark.parametrize("enabled", [False, True])
def test_ordered_operand_calls_and_errors_precede_predicate_and_body(enabled):
    module = compile_python_to_semantic_ir("""def left():
    putchar(76)
    return 65
def right():
    putchar(82)
    return 65//getchar()
while left()<right():
    putchar(66)
putchar(90)
""")
    target = native_target(module, enabled)
    assert_oracle(module, target, b"\0", b"LRerror\n")


@pytest.mark.parametrize("enabled", [False, True])
def test_left_error_prevents_right_operand_input(enabled):
    module = compile_python_to_semantic_ir("while 65//getchar()<getchar():\n    putchar(66)\nputchar(90)\n")
    target = native_target(module, enabled)
    assert_oracle(module, target, b"\0Z", b"error\n")
    assert run_expanded(target, b"\0Z")[1] == 1


@pytest.mark.parametrize("enabled", [False, True])
def test_input_error_keeps_prompt_but_suppresses_right_call(enabled):
    module = compile_python_to_semantic_ir("""def right():
    putchar(82)
    return 1
while int(input("?"))<right():
    putchar(66)
putchar(90)
""")
    assert_oracle(module, native_target(module, enabled), b"\n", b"?error\n")


@pytest.mark.parametrize("enabled", [False, True])
def test_sibling_recursive_operands_keep_distinct_snapshots(enabled):
    module = compile_python_to_semantic_ir("""def fib(n):
    if n<2:
        return n
    return fib(n-1)+fib(n-2)
while fib(5)>fib(4):
    putchar(65)
    break
""")
    target = native_target(module, enabled)
    assert_oracle(module, target, expected=b"A")
    if enabled:
        loop = only_loop(target)
        assert isinstance(loop.test.left, ast.Name)
        assert isinstance(loop.test.comparators[0], ast.Name)
        assert loop.test.left.id != loop.test.comparators[0].id


@pytest.mark.parametrize("source,data,expected", [
    ("while 0<getchar()<3:\n    break\nputchar(65)\n", b"\1", b"A"),
    ("while getchar() and 0:\n    putchar(66)\nputchar(65)\n", b"\1", b"A"),
    ("while not getchar():\n    break\nputchar(65)\n", b"\0", b"A"),
    ("while 0 if getchar() else 1:\n    break\nputchar(65)\n", b"\1", b"A"),
])
def test_chained_boolean_not_and_conditional_expression_conditions_fall_back(source, data, expected):
    module = compile_python_to_semantic_ir(source)
    before, after = native_target(module, False), native_target(module, True)
    assert not isinstance(only_loop(after).test, ast.Compare)
    assert ast.dump(before, include_attributes=True) == ast.dump(after, include_attributes=True)
    assert_oracle(module, after, data, expected)


def test_reused_comparison_word_falls_back_without_changing_extra_use():
    compare = CompareOp(["lt"], [constant_region(1), constant_region(0)])
    five = ConstOp(5)
    numerical_use = BinaryOp("add", compare, five)
    module = manual([five, compare, numerical_use, YieldOp(compare)])
    verify_semantic(module)
    assert len(tuple(compare.result.uses)) == 2
    target = native_target(module, True)
    assert isinstance(only_loop(target).test, ast.Name)
    assert any(isinstance(node, ast.IfExp) for node in ast.walk(target))
    assert_oracle(module, target, expected=b"after")


def test_comparison_followed_by_an_effect_is_not_a_terminal_candidate():
    compare = CompareOp(["eq"], [constant_region(1), constant_region(0)])
    read = GetCharOp()
    module = manual([compare, read, YieldOp(compare)])
    verify_semantic(module)
    assert len(tuple(compare.result.uses)) == 1
    target = native_target(module, True)
    assert isinstance(only_loop(target).test, ast.Name)
    assert_oracle(module, target, b"A", b"after")


@pytest.mark.parametrize("enabled", [False, True])
def test_comparisons_used_as_numbers_still_produce_zero_or_one(enabled):
    module = compile_python_to_semantic_ir("x=getchar()\nprint(x<70)\nwhile x<65:\n    break\nprint(x<70)\n")
    target = native_target(module, enabled)
    assert_oracle(module, target, b"A", b"1\n1\n")
    booleans = [node for node in ast.walk(target)
                if isinstance(node, ast.IfExp) and isinstance(node.test, ast.Compare)]
    assert len(booleans) == (2 if enabled else 3)


@pytest.mark.parametrize("enabled", [False, True])
def test_constant_false_predicate_preserves_prefix_and_both_operand_effects_once(enabled):
    prefix, left, right = GetCharOp(), GetCharOp(), GetCharOp()
    comparison = CompareOp(["lt"], [constant_region(2, [left]), constant_region(1, [right])])
    module = manual([prefix, comparison, YieldOp(comparison)], [PrintLiteralOp("badbody")])
    target = native_target(module, enabled)
    assert isinstance(only_loop(target).test, ast.Compare if enabled else ast.Name)
    assert_oracle(module, target, b"PLRZ", b"after")
    assert run_expanded(target, b"PLRZ")[1] == 3


_BACKEND_OPTIONS = tuple(product((False, True), repeat=3))


@pytest.mark.parametrize("native,structured,skip", _BACKEND_OPTIONS,
                         ids=[f"native={n},structured={s},skip-init={i}" for n, s, i in _BACKEND_OPTIONS])
def test_native_predicates_cross_both_target_interface_options_and_translate_to_mc(native, structured, skip):
    module = compile_python_to_semantic_ir("x=0\nwhile x<2:\n    putchar(65+x)\n    x+=1\n")
    mg = lower_semantic_to_mg(module, native_conditions=native,
                              structured_while=structured,
                              skip_generated_initialization=skip)
    assert "DEF MAIN" in mg
    assert "ENTRY" in translate_mg_to_mc(mg)


def test_native_condition_defaults_on_and_can_be_disabled_explicitly():
    module = compile_python_to_semantic_ir("x=0\nwhile x<2:\n    x+=1\n")
    default = lower_semantic_to_target_ast(module)
    explicit = native_target(module, True)
    assert isinstance(only_loop(default).test, ast.Compare)
    assert ast.dump(default, include_attributes=True) == ast.dump(explicit, include_attributes=True)
    assert isinstance(only_loop(native_target(module, False)).test, ast.Name)
