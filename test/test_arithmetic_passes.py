"""Oracle and structural acceptance for independent arithmetic IR passes."""

import json
from pathlib import Path
import random

import pytest

pytest.importorskip("xdsl")

from xdsl.context import Context
from xdsl.dialects.builtin import FileLineColLoc, IntAttr, ModuleOp, StringAttr

from malbolge.compiler.ir.arithmetic_passes import (
    FoldArithmeticPass, LowerConstantMultiplyPass, SimplifyArithmeticPass,
    SimplifyControlPass,
)
from malbolge.compiler.ir.frontend import compile_python_to_semantic_ir
from malbolge.compiler.ir.interpreter import run_semantic
from malbolge.compiler.ir.semantic import (
    MOD, BinaryOp, BoolOp, CallOp, CompareOp, ConstOp, FuncOp, GetCharOp,
    IfExprOp, IfOp, LoadOp, PrintLiteralOp, PrintWordOp, ProgramOp, ReadIntOp,
    ReturnOp, SemanticIRError, StoreOp, UnaryOp, UnboundNameOp, WhileOp,
    YieldOp, parse_semantic, print_semantic, verify_semantic,
)


ALL_PASSES = (FoldArithmeticPass(), SimplifyArithmeticPass(),
              LowerConstantMultiplyPass(), SimplifyControlPass())
ROOT = Path(__file__).resolve().parents[1]


def module(ops, *, globals=(), locals=(), functions=()):
    return ModuleOp([ProgramOp(globals, [*functions, FuncOp(
        "main", [], locals, ops, returns="void", globals=globals)])])


def observation(result):
    return (result.output, result.globals, result.return_value,
            result.input_consumed, result.calls, result.status, result.error)


def transformed(original, passes=ALL_PASSES):
    verify_semantic(original)
    text = print_semantic(original)
    result = original.clone()
    for instance in passes:
        instance.apply(Context(), result)
        verify_semantic(result)
    assert print_semantic(original) == text
    # Rewrites must leave serializable regions, real SSA uses and valid scope.
    recovered = parse_semantic(print_semantic(result))
    assert print_semantic(recovered) == print_semantic(result)
    return result


def equivalent(original, data=b"", passes=ALL_PASSES):
    result = transformed(original, passes)
    assert observation(run_semantic(result, data)) == observation(run_semantic(original, data))
    return result


@pytest.mark.parametrize("kind,left,right,expected", [
    ("add", MOD - 1, 1, 0), ("sub", 0, 1, MOD - 1),
    ("mul", MOD - 1, MOD - 1, 1), ("mul", 123456, 789012, 3265086645),
    ("floordiv", MOD - 1, 7, (MOD - 1) // 7),
    ("mod", MOD - 1, 7, (MOD - 1) % 7),
])
def test_constant_word_arithmetic(kind, left, right, expected):
    a, b = ConstOp(left), ConstOp(right)
    arithmetic = BinaryOp(kind, a, b)
    arithmetic.location = FileLineColLoc(StringAttr("sample.py"), IntAttr(4), IntAttr(7))
    original = module([a, b, arithmetic, PrintWordOp(arithmetic)])
    result = equivalent(original, passes=(FoldArithmeticPass(),))
    assert not any(isinstance(op, BinaryOp) for op in result.walk())
    output = next(op for op in result.walk() if isinstance(op, PrintWordOp))
    assert output.value.owner.value.data == expected
    assert output.value.owner.location == arithmetic.location


@pytest.mark.parametrize("kind", ["floordiv", "mod"])
def test_constant_zero_divisor_remains_checked_even_when_unused(kind):
    one, zero = ConstOp(1), ConstOp(0)
    checked = BinaryOp(kind, one, zero)
    original = module([PrintLiteralOp("before"), one, zero, checked,
                       PrintLiteralOp("unreachable")])
    result = equivalent(original)
    assert any(isinstance(op, BinaryOp) and op.kind.data == kind for op in result.walk())
    assert run_semantic(result).output == b"beforeerror\n"


@pytest.mark.parametrize("kind,value,expected", [("pos", MOD-1, MOD-1),
                                                 ("not", 0, 1), ("not", 2, 0)])
def test_unary_constants(kind, value, expected):
    constant = ConstOp(value)
    unary = UnaryOp(kind, constant)
    result = equivalent(module([constant, unary, PrintWordOp(unary)]),
                        passes=(FoldArithmeticPass(),))
    assert run_semantic(result).output == str(expected).encode()
    assert not any(isinstance(op, UnaryOp) for op in result.walk())


@pytest.mark.parametrize("source,data,expected", [
    ("print(getchar()+0,0+getchar(),getchar()-0)\n", b"ABC", b"65 66 67\n"),
    ("print(getchar()*0,0*getchar(),getchar()*1,1*getchar())\n", b"ABCD", b"0 0 67 68\n"),
    ("print(getchar()//1,getchar()%1,+getchar())\n", b"ABC", b"65 0 67\n"),
    ("print((1//getchar())*0)\nprint(9)\n", b"\0", b"error\n"),
    ("print(0*(1%getchar()))\nprint(9)\n", b"\0", b"error\n"),
    ("print(int(input('N:'))*0)\n", b"bad\n", b"N:error\n"),
    ("print((getchar()*0) and getchar())\n", b"AB", b"0\n"),
    ("print((getchar()*0) > 1 < int(input()))\n", b"Abad\n", b"0\n"),
    ("while getchar()*0:\n    print(int(input()))\nprint(7)\n", b"Abad\n", b"7\n"),
    ("g=3\ndef touch():\n    global g\n    g=9\n    putchar(65)\n    return 7\n"
     "print(g*1,touch()*0,g+0)\n", b"", b"A3 0 9\n"),
])
def test_identities_keep_all_input_call_global_and_failure_effects(source, data, expected):
    original = compile_python_to_semantic_ir(source)
    result = equivalent(original, data)
    assert run_semantic(result, data).output == expected


def test_replacement_updates_alias_uses_without_erasing_the_producer():
    read, zero = GetCharOp(), ConstOp(0)
    identity = BinaryOp("add", read, zero)
    double = BinaryOp("add", identity, identity)
    original = module([read, zero, identity, double, PrintWordOp(identity), PrintWordOp(double)])
    result = equivalent(original, b"A", passes=(SimplifyArithmeticPass(),))
    kept = next(op for op in result.walk() if isinstance(op, GetCharOp))
    assert kept.result.uses.get_length() == 3
    assert sum(isinstance(op, GetCharOp) for op in result.walk()) == 1
    assert run_semantic(result, b"A").output == b"65130"


@pytest.mark.parametrize("producer", ["load", "unbound_name"])
def test_multiply_zero_does_not_erase_a_potentially_failing_producer(producer):
    value = LoadOp("uninitialized") if producer == "load" else UnboundNameOp("missing")
    zero = ConstOp(0)
    product = BinaryOp("mul", value, zero)
    original = module([value, zero, product, PrintWordOp(product)], locals=["uninitialized"])
    result = transformed(original)
    with pytest.raises(SemanticIRError) as before:
        run_semantic(original)
    with pytest.raises(SemanticIRError) as after:
        run_semantic(result)
    assert str(before.value) == str(after.value)
    assert any(isinstance(op, type(value)) for op in result.walk())


def test_multiply_expansion_reuses_one_call_and_frozen_global_operand():
    source = ("g=7\ndef touch():\n    global g\n    g=9\n    putchar(65)\n"
              "    return 255\nprint(g*17,touch()*17,g*255)\n")
    original = compile_python_to_semantic_ir(source)
    result = equivalent(original)
    assert run_semantic(result).output == b"A119 4335 2295\n"
    assert sum(isinstance(op, CallOp) for op in result.walk()) == 1
    assert sum(isinstance(op, LoadOp) for op in result.walk()) == 2


def test_division_self_is_not_simplified_without_a_nonzero_proof():
    read = GetCharOp()
    divided = BinaryOp("floordiv", read, read)
    result = equivalent(module([read, divided, PrintWordOp(divided)]), b"\0")
    assert any(isinstance(op, BinaryOp) and op.kind.data == "floordiv" for op in result.walk())
    assert run_semantic(result, b"\0").status == "runtime_error"


FACTORS = list(range(17)) + [17, 31, 63, 127, 255, 256, 257, 1023, 1024,
                            4096, MOD - 1, MOD - 2, MOD - 17, 123456789]


@pytest.mark.parametrize("factor", FACTORS)
@pytest.mark.parametrize("literal_on_left", [False, True])
def test_bounded_multiply_chains_match_modular_oracle(factor, literal_on_left):
    read, literal = ReadIntOp(), ConstOp(factor)
    operands = (literal, read) if literal_on_left else (read, literal)
    multiply = BinaryOp("mul", *operands)
    multiply.location = FileLineColLoc(StringAttr("multiply.py"), IntAttr(3), IntAttr(5))
    original = module([read, literal, multiply, PrintWordOp(multiply)])
    result = transformed(original, (LowerConstantMultiplyPass(),))
    generator = random.Random(factor)
    values = [0, 1, 2, MOD // 2, MOD - 2, MOD - 1]
    values += [generator.randrange(MOD) for _ in range(8)]
    for value in values:
        data = (str(value) + "\n").encode()
        actual = run_semantic(result, data)
        assert observation(actual) == observation(run_semantic(original, data))
        assert actual.output == str(value * factor % MOD).encode()
    replacements = [op for op in result.walk() if isinstance(op, BinaryOp)]
    assert len(replacements) <= 12
    assert all(op.location == multiply.location for op in replacements)
    if factor in (17, 255, 256, MOD-1, MOD-17):
        assert all(op.kind.data != "mul" for op in replacements)


@pytest.mark.parametrize("factor,cost", [(17, 5), (255, 9), (256, 8),
                                        (MOD-1, 1), (MOD-17, 6)])
def test_literal_multiply_uses_a_bounded_add_sub_plan(factor, cost):
    read, literal = GetCharOp(), ConstOp(factor)
    multiply = BinaryOp("mul", read, literal)
    result = equivalent(module([read, literal, multiply, PrintWordOp(multiply)]), b"A",
                        passes=(LowerConstantMultiplyPass(),))
    arithmetic = [op for op in result.walk() if isinstance(op, BinaryOp)]
    assert len(arithmetic) == cost
    assert {op.kind.data for op in arithmetic} <= {"add", "sub"}


def test_expensive_literal_and_dynamic_multiply_keep_generic_path():
    read, other, literal = GetCharOp(), GetCharOp(), ConstOp(123456789)
    expensive = BinaryOp("mul", read, literal)
    dynamic = BinaryOp("mul", read, other)
    original = module([read, other, literal, expensive, dynamic,
                       PrintWordOp(expensive), PrintWordOp(dynamic)])
    result = equivalent(original, b"AB", passes=(LowerConstantMultiplyPass(),))
    assert sum(isinstance(op, BinaryOp) and op.kind.data == "mul" for op in result.walk()) == 2


def test_lower_chain_budget_is_configurable_and_checked():
    read, literal = GetCharOp(), ConstOp(17)
    multiply = BinaryOp("mul", read, literal)
    original = module([read, literal, multiply, PrintWordOp(multiply)])
    limited = transformed(original, (LowerConstantMultiplyPass(max_operations=4),))
    assert any(isinstance(op, BinaryOp) and op.kind.data == "mul" for op in limited.walk())
    for bad in (-1, True, 1.5):
        with pytest.raises(ValueError, match="budget"):
            LowerConstantMultiplyPass(max_operations=bad).apply(Context(), original.clone())


def constant_region(value, prefix=()):
    constant = ConstOp(value)
    return [*prefix, constant, YieldOp(constant)]


def emitter(name, text):
    zero = ConstOp(0)
    return FuncOp(name, [], [], [PrintLiteralOp(text), zero, ReturnOp(zero)])


@pytest.mark.parametrize("kind,left,right,expected", [
    ("lt", 1, 2, 1), ("le", 2, 2, 1), ("gt", 2, 1, 1),
    ("ge", 2, 2, 1), ("eq", 1, 2, 0), ("ne", MOD-1, 0, 1),
])
def test_constant_comparisons_keep_reached_region_effects(kind, left, right, expected):
    comparison = CompareOp([kind], [constant_region(left, [GetCharOp(), CallOp("left", [])]),
                                   constant_region(right, [GetCharOp(), CallOp("right", [])])])
    original = module([comparison, PrintWordOp(comparison)],
                      functions=[emitter("left", "L"), emitter("right", "R")])
    result = equivalent(original, b"ab",
                        passes=(FoldArithmeticPass(),))
    assert not any(isinstance(op, CompareOp) for op in result.walk())
    assert run_semantic(result, b"ab").output == b"LR" + str(expected).encode()
    assert run_semantic(result, b"ab").input_consumed == 2


def test_false_comparison_discards_only_unreached_regions():
    read = ReadIntOp("unreachable")
    comparison = CompareOp(["lt", "lt"], [constant_region(2, [GetCharOp()]),
                                          constant_region(1, [GetCharOp()]), [read, YieldOp(read)]])
    result = equivalent(module([comparison, PrintWordOp(comparison)]), b"abBAD\n",
                        passes=(FoldArithmeticPass(),))
    assert not any(isinstance(op, (CompareOp, ReadIntOp)) for op in result.walk())
    assert run_semantic(result, b"abBAD\n").input_consumed == 2


def test_comparison_with_dynamic_reached_operand_is_not_folded():
    read = GetCharOp()
    comparison = CompareOp(["lt"], [constant_region(1), [read, YieldOp(read)]])
    result = equivalent(module([comparison, PrintWordOp(comparison)]), b"A",
                        passes=(FoldArithmeticPass(),))
    assert any(isinstance(op, CompareOp) for op in result.walk())


@pytest.mark.parametrize("control", ["if", "if_expr", "bool", "while"])
def test_control_simplification_keeps_selected_effects_and_drops_unreached_traps(control):
    read, zero, one = GetCharOp(), ConstOp(0), ConstOp(1)
    functions = [emitter("mark", "yes")]
    if control == "if":
        operation = IfOp(one, [PrintLiteralOp("yes")], [UnboundNameOp("unreachable")])
        original = module([read, one, operation], functions=functions)
    elif control == "if_expr":
        trap = UnboundNameOp("unreachable")
        operation = IfExprOp(one, constant_region(7, [CallOp("mark", [])]), [trap, YieldOp(trap)])
        original = module([read, one, operation, PrintWordOp(operation)], functions=functions)
    elif control == "bool":
        trap = UnboundNameOp("unreachable")
        operation = BoolOp("and", [constant_region(0, [read, CallOp("mark", [])]),
                                    [trap, YieldOp(trap)]])
        original = module([operation, PrintWordOp(operation)], functions=functions)
    else:
        operation = WhileOp([read, CallOp("mark", []), zero, YieldOp(zero)],
                            [UnboundNameOp("unreachable")])
        original = module([operation], functions=functions)
    result = equivalent(original, b"A", passes=(SimplifyControlPass(),))
    assert not any(isinstance(op, (IfOp, IfExprOp, BoolOp, WhileOp, UnboundNameOp))
                   for op in result.walk())
    assert run_semantic(result, b"A").input_consumed == 1


def test_while_false_still_propagates_condition_error_before_body():
    one, zero = ConstOp(1), ConstOp(0)
    checked = BinaryOp("floordiv", one, zero)
    condition = [one, zero, checked, YieldOp(zero)]
    loop = WhileOp(condition, [PrintLiteralOp("badbody")])
    original = module([PrintLiteralOp("before"), loop, PrintLiteralOp("after")])
    result = equivalent(original, passes=(SimplifyControlPass(),))
    assert not any(isinstance(op, WhileOp) for op in result.walk())
    assert run_semantic(result).output == b"beforeerror\n"


def test_dynamic_boolean_prefix_keeps_unproven_regions_lazy():
    first, last = GetCharOp(), ReadIntOp("last")
    expression = BoolOp("and", [[first, YieldOp(first)], constant_region(0), [last, YieldOp(last)]])
    original = module([expression, PrintWordOp(expression)])
    result = equivalent(original, b"Ainvalid\n", passes=(SimplifyControlPass(),))
    assert any(isinstance(op, BoolOp) for op in result.walk())
    assert run_semantic(result, b"Ainvalid\n").input_consumed == 1


def test_nondecisive_boolean_prefix_inlines_final_dynamic_value_once():
    read = GetCharOp()
    expression = BoolOp("and", [constant_region(7, [CallOp("mark", [])]), [read, YieldOp(read)]])
    original = module([expression, PrintWordOp(expression)], functions=[emitter("mark", "prefix")])
    result = equivalent(original, b"A", passes=(SimplifyControlPass(),))
    assert not any(isinstance(op, BoolOp) for op in result.walk())
    assert run_semantic(result, b"A").output == b"prefix65"


def test_selected_branch_mutation_after_rewrite_changes_the_result():
    original = compile_python_to_semantic_ir("print(7 if 1 else 8)\n")
    result = transformed(original, (SimplifyControlPass(),))
    selected = next(op for op in result.walk() if isinstance(op, ConstOp) and op.value.data == 7)
    selected.properties["value"] = IntAttr(9)
    assert run_semantic(result).output == b"9\n"


def test_random_constant_trees_fold_in_one_ordered_walk():
    generator = random.Random(917)
    for _ in range(50):
        operations = [ConstOp(generator.randrange(MOD)) for _ in range(8)]
        values = [operation.result for operation in operations]
        for _ in range(20):
            kind = generator.choice(["add", "sub", "mul", "floordiv", "mod"])
            operation = BinaryOp(kind, generator.choice(values), generator.choice(values))
            operations.append(operation)
            values.append(operation.result)
        original = module([*operations, PrintWordOp(values[-1])])
        equivalent(original, passes=(FoldArithmeticPass(),))


def test_passes_are_idempotent_and_do_not_depend_on_target_codegen(monkeypatch):
    from malbolge.compiler import py2mg

    original = compile_python_to_semantic_ir("n=getchar()\nprint((n*255)+0,7*9,1<2)\n")
    def forbidden(*args, **kwargs):
        pytest.fail("an arithmetic pass invoked target code generation")
    monkeypatch.setattr(py2mg, "compile_python_to_mg", forbidden)
    monkeypatch.setattr(py2mg._DirectCompiler, "compile", forbidden)
    result = transformed(original)
    assert print_semantic(transformed(result)) == print_semantic(result)


MANIFEST = json.loads((ROOT / "benchmarks" / "manifest.json").read_text())
WORKLOADS = [(program, workload) for program in MANIFEST["programs"]
             for workload in program["workloads"]]


@pytest.mark.parametrize("program,workload", WORKLOADS,
                         ids=[f"{program['id']}-{workload['id']}" for program, workload in WORKLOADS])
def test_all_fixed_benchmark_oracles_before_after(program, workload):
    original = compile_python_to_semantic_ir((ROOT / "benchmarks" / program["path"]).read_text())
    data = workload["stdin"].encode()
    result = equivalent(original, data)
    assert run_semantic(result, data).output == workload["stdout"].encode()
