"""Semantic A/B checks for slot propagation and effect-preserving DCE."""
import json
from pathlib import Path
import sys

import pytest

if sys.version_info < (3, 10):
    pytest.skip("optional semantic IR requires Python 3.10+", allow_module_level=True)
pytest.importorskip("xdsl")

from xdsl.dialects.builtin import ModuleOp

from malbolge.compiler.ir.dataflow_passes import (
    ConstantPropagationPass, EliminatePureComputationPass,
)
from malbolge.compiler.ir.frontend import SemanticFrontendError, compile_python_to_semantic_ir
from malbolge.compiler.ir.interpreter import run_semantic
from malbolge.compiler.ir.semantic import (
    MAX_WORD, BinaryOp, BoolOp, CallOp, CompareOp, ConstOp, FuncOp, GetCharOp,
    IfExprOp, LoadOp, PrintWordOp, ProgramOp, PutCharOp, ReadIntOp, ReturnOp,
    SemanticIRError, StoreOp, UnboundNameOp, YieldOp,
    create_semantic_context, print_semantic, verify_semantic,
)


def observation(module, data=b""):
    result = run_semantic(module, data)
    assert result.status in ("completed", "runtime_error")
    return (result.output, result.globals, result.return_value, result.status,
            result.error, result.input_consumed, result.calls)


def apply(module, *passes):
    current = module.clone()
    verify_semantic(current)
    for selected in passes:
        selected.apply(create_semantic_context(), current)
        verify_semantic(current)
    return current


def ab(source, data=b"", passes=None):
    original = compile_python_to_semantic_ir(source)
    selected = passes or (ConstantPropagationPass(), EliminatePureComputationPass())
    transformed = apply(original, *selected)
    assert observation(transformed, data) == observation(original, data)
    return original, transformed


def manual(ops, *, globals=(), locals=(), functions=()):
    entry = FuncOp("main", [], locals, ops, returns="void", globals=globals)
    return ModuleOp([ProgramOp(globals, [*functions, entry])])


def region(value):
    op = ConstOp(value)
    return [op, YieldOp(op)]


def test_propagate_straight_line_ring_values_and_preserve_locations():
    before, after = ab(f"x={MAX_WORD}\ny=x+1\nz=y-1\nprint(z)\n")
    loads = [op for op in before.walk() if isinstance(op, LoadOp)]
    assert len(loads) == 3
    assert not any(isinstance(op, LoadOp) for op in after.walk())
    locations = [op.location for op in after.walk() if isinstance(op, ConstOp)]
    assert all(op.location in locations for op in loads)
    assert sum(isinstance(op, StoreOp) for op in before.walk()) == sum(isinstance(op, StoreOp) for op in after.walk())


def test_global_fact_invalidated_by_call_but_prior_ssa_capture_survives():
    _, after = ab("""x=65
def change():
    global x
    x=66
    return 0
y=x+change()
putchar(y)
putchar(x)
""")
    remaining = [op for op in after.walk() if isinstance(op, LoadOp)]
    # The call result stays unknown (there is no interprocedural evaluation),
    # but the pre-call x read is still replaced by its captured constant.
    assert [(op.scope.data, op.slot.data) for op in remaining] == [("global", "y"), ("global", "x")]
    assert run_semantic(after).output == b"AB"


def test_calls_preserve_caller_local_facts_and_parameter_slots_start_unknown():
    _, after = ab("""x=0
def change():
    global x
    x=77
    return 0
def local(value):
    fixed=65
    change()
    return fixed+value
putchar(local(1))
""")
    loads = [op.slot.data for op in after.walk() if isinstance(op, LoadOp)]
    assert "fixed" not in loads
    assert "value" in loads


def test_all_function_globals_start_unknown_even_entry_globals():
    read = LoadOp("x", "global")
    original = manual([read, PrintWordOp(read)], globals=["x"])
    after = apply(original, ConstantPropagationPass())
    assert any(isinstance(op, LoadOp) for op in after.walk())
    assert observation(after) == observation(original)


@pytest.mark.parametrize("data", [b"\0", b"A"])
@pytest.mark.parametrize("second", [65, 66])
def test_branch_join_only_retains_equal_slot_values(data, second):
    source = f"if getchar():\n    x=65\nelse:\n    x={second}\nputchar(x)\n"
    _, after = ab(source, data)
    assert any(isinstance(op, LoadOp) for op in after.walk()) == (second != 65)


def test_terminal_branch_does_not_invent_a_continuing_fact():
    for data in (b"\0", b"A"):
        ab("""def f():
    x=65
    if getchar():
        x=66
        return x
    putchar(x)
    return 0
f()
""", data)


def test_repeated_conditions_kill_written_facts_before_first_rewrite():
    _, after = ab("x=0\nwhile x<3:\n    putchar(x+65)\n    x+=1\nputchar(x+65)\n")
    assert run_semantic(after).output == b"ABCD"
    assert any(isinstance(op, LoadOp) and op.slot.data == "x" for op in after.walk())


def test_for_target_and_nested_loop_writes_are_not_treated_invariant():
    ab("""i=99
fixed=65
for i in range(3):
    j=0
    while j<2:
        j+=1
        if j==1:
            continue
        putchar(fixed+i)
    if i==1:
        break
putchar(i+65)
""")


def test_call_in_loop_condition_invalidates_globals_for_body_and_after_loop():
    _, after = ab("""x=0
def advance():
    global x
    x+=1
    return x<3
while advance():
    putchar(64+x)
putchar(64+x)
""")
    assert run_semantic(after).output == b"ABC"


@pytest.mark.parametrize("expression", [
    "getchar() and change()", "getchar() or change()",
    "0 < getchar() < change()", "change() if getchar() else 0",
])
@pytest.mark.parametrize("data", [b"\0", b"\1"])
def test_conditional_calls_join_global_effects(expression, data):
    source = f"""x=65
def change():
    global x
    x=66
    return 2
value={expression}
putchar(x)
"""
    _, after = ab(source, data)
    assert any(isinstance(op, LoadOp) and op.slot.data == "x" for op in after.walk())


@pytest.mark.parametrize("expression", ["0 and change()", "1 or change()", "2 < 1 < change()", "0 if 1 else change()"])
def test_statically_skipped_calls_preserve_global_facts(expression):
    source = f"""x=65
def change():
    global x
    x=66
    return 2
value={expression}
putchar(x)
"""
    _, after = ab(source)
    assert not any(isinstance(op, LoadOp) and op.slot.data == "x" for op in after.walk())


@pytest.mark.parametrize("expression", ["getchar() and 0", "getchar() or 7", "getchar() < 0 < 0"])
@pytest.mark.parametrize("data", [b"\0", b"\1"])
def test_selected_boolean_words_and_compare_results_are_not_overstated(expression, data):
    ab(f"x={expression}\nprint(x)\n", data)


def test_dce_erases_only_unused_pure_arithmetic_and_preserves_operand_input():
    _, after = ab("getchar()+1\n2*3\nputchar(65)\n", b"Z", passes=(EliminatePureComputationPass(),))
    assert not any(isinstance(op, BinaryOp) for op in after.walk())
    assert sum(isinstance(op, GetCharOp) for op in after.walk()) == 1


def test_dce_keeps_calls_decimal_input_raw_input_and_global_stores():
    _, after = ab("""x=1
def f():
    global x
    x=2
    return 7
f()
getchar()
int(input())
""", b"A7\n", passes=(EliminatePureComputationPass(),))
    assert any(isinstance(op, CallOp) for op in after.walk())
    assert any(isinstance(op, ReadIntOp) for op in after.walk())
    assert sum(isinstance(op, StoreOp) for op in after.walk()) == 2


def test_dce_keeps_uninitialized_load_and_trap_errors():
    original = manual([LoadOp("x")], locals=["x"])
    after = apply(original, EliminatePureComputationPass(), ConstantPropagationPass())
    for item in (original, after):
        with pytest.raises(SemanticIRError, match="uninitialized local"):
            run_semantic(item)
    trap = UnboundNameOp("missing")
    lazy = BoolOp("and", [region(0), [trap, YieldOp(trap)]])
    after = apply(manual([lazy]), EliminatePureComputationPass())
    assert any(isinstance(op, UnboundNameOp) for op in after.walk())
    assert run_semantic(after).output == b""


@pytest.mark.parametrize("kind", ["floordiv", "mod"])
@pytest.mark.parametrize("denominator", ["getchar()", "0", "3486784400+1"])
def test_dce_keeps_zero_or_unknown_checked_divisors(kind, denominator):
    left = ConstOp(7)
    if denominator == "getchar()":
        right, prefix = GetCharOp(), []
    elif denominator == "0":
        right, prefix = ConstOp(0), []
    else:
        a, b = ConstOp(MAX_WORD), ConstOp(1)
        right, prefix = BinaryOp("add", a, b), [a, b]
    checked = BinaryOp(kind, left, right)
    original = manual([left, *prefix, right, checked])
    after = apply(original, EliminatePureComputationPass())
    assert any(isinstance(op, BinaryOp) and op.kind.data == kind for op in after.walk())
    assert observation(original, b"\0") == observation(after, b"\0")
    assert observation(original, b"\1") == observation(after, b"\1")


@pytest.mark.parametrize("kind", ["floordiv", "mod"])
def test_dce_can_remove_checked_operation_with_proven_nonzero_ring_divisor(kind):
    left, zero, one = GetCharOp(), ConstOp(0), ConstOp(1)
    denominator = BinaryOp("sub", zero, one)
    unused = BinaryOp(kind, left, denominator)
    original = manual([left, zero, one, denominator, unused])
    after = apply(original, EliminatePureComputationPass())
    assert [op.name for op in after.body.block.first_op.body.block.first_op.body.block.ops] == ["pysem.getchar"]
    assert observation(original, b"A") == observation(after, b"A")


def test_dce_removes_pure_unused_regions_but_keeps_effectful_comparison():
    pure = CompareOp(["lt"], [region(1), region(2)])
    choose = IfExprOp(ConstOp(1), region(3), region(4))
    # The explicit condition producer must also be a block operation.
    condition = choose.condition.owner
    char = GetCharOp()
    effectful = CompareOp(["lt"], [[char, YieldOp(char)], region(100)])
    original = manual([pure, condition, choose, effectful])
    after = apply(original, EliminatePureComputationPass())
    assert sum(isinstance(op, CompareOp) for op in after.walk()) == 1
    assert not any(isinstance(op, IfExprOp) for op in after.walk())
    assert observation(original, b"A") == observation(after, b"A")


@pytest.mark.parametrize("limit", [0, 1, 3, 8, 20])
@pytest.mark.parametrize("pass_class", [ConstantPropagationPass, EliminatePureComputationPass])
def test_bounded_partial_work_is_deterministic_and_semantics_preserving(limit, pass_class):
    source = "x=65\ny=x+1\nwhile x<68:\n    x+=1\n    y+=1\nputchar(y)\n"
    original = compile_python_to_semantic_ir(source)
    first, second = apply(original, pass_class(limit)), apply(original, pass_class(limit))
    assert print_semantic(first) == print_semantic(second)
    assert observation(first) == observation(original)
    if limit == 0:
        assert print_semantic(first) == print_semantic(original)


@pytest.mark.parametrize("limit", [-1, True, 0.5])
def test_invalid_work_budgets_rejected(limit):
    module = compile_python_to_semantic_ir("pass")
    with pytest.raises(ValueError, match="nonnegative integer"):
        ConstantPropagationPass(limit).apply(create_semantic_context(), module)


def corpus():
    root = Path(__file__).resolve().parents[1] / "benchmarks"
    manifest = json.loads((root / "manifest.json").read_text())
    return [(program["id"] + "/" + work["id"], (root / program["path"]).read_text(),
             work["stdin"].encode(), work["stdout"].encode())
            for program in manifest["programs"] for work in program["workloads"]]


_CORPUS = corpus()


@pytest.mark.parametrize("name,source,data,expected", _CORPUS, ids=[case[0] for case in _CORPUS])
@pytest.mark.parametrize("passes", [(ConstantPropagationPass(),), (EliminatePureComputationPass(),),
                                    (ConstantPropagationPass(), EliminatePureComputationPass())],
                         ids=["propagation", "dce", "combined"])
def test_fixed_workload_oracle_ab(name, source, data, expected, passes):
    assert len(_CORPUS) == 32
    before, after = ab(source, data, passes=passes)
    assert run_semantic(before, data).output == expected
    assert run_semantic(after, data).output == expected


def test_deep_ssa_constant_chain_uses_bounded_iterative_analysis():
    read, one = GetCharOp(), ConstOp(1)
    operations = [read, one]
    denominator = one
    for _ in range(2000):
        denominator = BinaryOp("add", denominator, one)
        operations.append(denominator)
    operations.append(BinaryOp("floordiv", read, denominator))
    before = manual(operations)
    after = apply(before, EliminatePureComputationPass())
    assert not any(isinstance(op, BinaryOp) for op in after.walk())
    assert observation(before, b"A") == observation(after, b"A")


def test_optimizers_do_not_hide_live_name_traps_or_source_zero_divisor_errors():
    before = manual([UnboundNameOp("missing")])
    after = apply(before, ConstantPropagationPass(), EliminatePureComputationPass())
    with pytest.raises(SemanticIRError, match="unresolved source name"):
        run_semantic(after)
    with pytest.raises(SemanticFrontendError, match="zero"):
        compile_python_to_semantic_ir("x=1//0\n")


@pytest.mark.parametrize("data", [b"\0", b"\1"])
def test_interoperation_with_arithmetic_and_control_passes_preserves_errors_and_io(data):
    from malbolge.compiler.ir.arithmetic_passes import (
        FoldArithmeticPass, SimplifyArithmeticPass, SimplifyControlPass,
        LowerConstantMultiplyPass,
    )
    passes = (ConstantPropagationPass(), FoldArithmeticPass(), SimplifyArithmeticPass(),
              SimplifyControlPass(), LowerConstantMultiplyPass(), EliminatePureComputationPass())
    for source in [
        "x=getchar()\ny=(x//x)*0\nprint(y)\n",
        "x=0\ny=(0 and getchar())+x\nprint(y)\n",
        "x=7\ny=x*17\nprint(y)\n",
        "x=1\nwhile x<4:\n    print(x)\n    x+=1\n",
    ]:
        ab(source, data, passes=passes)
