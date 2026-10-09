"""Graph proofs and observable parity for arithmetic emission hints."""

import json
from pathlib import Path
import sys

import pytest

if sys.version_info < (3, 10):
    pytest.skip("optional semantic IR requires Python 3.10+", allow_module_level=True)
pytest.importorskip("xdsl")

from xdsl.context import Context
from xdsl.dialects.builtin import IntAttr, ModuleOp, StringAttr, UnitAttr

from malbolge.compiler.ir.arithmetic_passes import LowerConstantMultiplyPass
from malbolge.compiler.ir.expression_passes import (
    INLINE_ARITHMETIC_ATTR, MAX_INLINE_ARITHMETIC_DEPTH, InlinePureArithmeticPass,
    inline_arithmetic_candidates, verified_inline_arithmetic_hints,
)
from malbolge.compiler.ir.frontend import compile_python_to_semantic_ir
from malbolge.compiler.ir.interpreter import run_semantic
from malbolge.compiler.ir.semantic import (
    BinaryOp, BoolOp, CallOp, ConstOp, FuncOp, GetCharOp, IfExprOp, LoadOp,
    PrintLiteralOp, PrintWordOp, ProgramOp, ReturnOp, StoreOp, UnaryOp,
    YieldOp, get_program, parse_semantic, print_semantic, verify_semantic,
)


ROOT = Path(__file__).resolve().parents[1]


def module(ops, *, globals=(), locals=(), functions=()):
    return ModuleOp([ProgramOp(globals, [*functions, FuncOp(
        "main", [], locals, ops, returns="void", globals=globals)])])


def mark(original, data=b""):
    verify_semantic(original)
    before = run_semantic(original, data)
    operations = list(original.walk())
    operands = [tuple(operation.operands) for operation in operations]
    locations = [operation.location for operation in operations]
    InlinePureArithmeticPass().apply(Context(), original)
    verify_semantic(original)
    assert list(original.walk()) == operations
    assert [tuple(operation.operands) for operation in operations] == operands
    assert [operation.location for operation in operations] == locations
    # Markers do not even change oracle operation counts or call budgets.
    assert run_semantic(original, data) == before
    text = print_semantic(original)
    InlinePureArithmeticPass().apply(Context(), original)
    assert print_semantic(original) == text
    replay = parse_semantic(text)
    assert print_semantic(replay) == text
    assert run_semantic(replay, data) == before
    return original


@pytest.mark.parametrize("producer_kind", ["add", "sub"])
@pytest.mark.parametrize("consumer_kind", ["add", "sub"])
@pytest.mark.parametrize("operand_index", [0, 1])
def test_only_adjacent_single_use_add_sub_producers_are_marked(producer_kind, consumer_kind, operand_index):
    read, one = GetCharOp(), ConstOp(1)
    producer = BinaryOp(producer_kind, read, one)
    operands = [producer, read] if operand_index == 0 else [read, producer]
    consumer = BinaryOp(consumer_kind, *operands)
    original = module([read, one, producer, consumer, PrintWordOp(consumer)])
    assert inline_arithmetic_candidates(original) == frozenset([producer])
    assert not verified_inline_arithmetic_hints(original)
    mark(original, b"A")
    assert verified_inline_arithmetic_hints(original) == frozenset([producer])
    assert isinstance(producer.attributes[INLINE_ARITHMETIC_ATTR], UnitAttr)
    assert INLINE_ARITHMETIC_ATTR not in consumer.attributes


def test_multiple_operand_occurrences_count_as_multiple_uses():
    read = GetCharOp()
    producer = BinaryOp("add", read, read)
    consumer = BinaryOp("add", producer, producer)
    original = module([read, producer, consumer, PrintWordOp(consumer)])
    assert producer.result.uses.get_length() == 2
    mark(original, b"A")
    assert not inline_arithmetic_candidates(original)
    assert not verified_inline_arithmetic_hints(original)


def test_an_additional_later_use_keeps_the_producer_materialized():
    read, one = GetCharOp(), ConstOp(1)
    producer = BinaryOp("add", read, one)
    consumer = BinaryOp("sub", producer, one)
    original = module([read, one, producer, consumer, PrintWordOp(consumer), PrintWordOp(producer)])
    mark(original, b"A")
    assert not verified_inline_arithmetic_hints(original)


@pytest.mark.parametrize("intervening", ["read", "constant", "print", "store", "call"])
def test_any_intervening_operation_blocks_inlining(intervening):
    read, one = GetCharOp(), ConstOp(1)
    producer = BinaryOp("add", read, one)
    consumer = BinaryOp("add", producer, read)
    functions = []
    if intervening == "read":
        middle = GetCharOp()
    elif intervening == "constant":
        middle = ConstOp(0)
    elif intervening == "print":
        middle = PrintLiteralOp("effect")
    elif intervening == "store":
        middle = StoreOp("x", one, "global")
    else:
        value = ConstOp(0)
        functions = [FuncOp("touch", [], [], [PrintLiteralOp("call"), value, ReturnOp(value)])]
        middle = CallOp("touch", [])
    original = module([read, one, producer, middle, consumer, PrintWordOp(consumer)],
                      globals=["x"], functions=functions)
    mark(original, b"AB")
    assert not verified_inline_arithmetic_hints(original)


@pytest.mark.parametrize("kind", ["mul", "floordiv", "mod"])
def test_non_add_sub_producer_or_consumer_is_never_marked(kind):
    for kind_on_producer in (False, True):
        read, one = GetCharOp(), ConstOp(1)
        producer = BinaryOp(kind if kind_on_producer else "add", read, one)
        consumer = BinaryOp("add" if kind_on_producer else kind, producer, one)
        original = module([read, one, producer, consumer, PrintWordOp(consumer)])
        mark(original, b"A")
        assert not verified_inline_arithmetic_hints(original)


def test_unary_consumer_is_not_an_arithmetic_chain_consumer():
    read, one = GetCharOp(), ConstOp(1)
    producer = BinaryOp("add", read, one)
    consumer = UnaryOp("pos", producer)
    original = module([read, one, producer, consumer, PrintWordOp(consumer)])
    mark(original, b"A")
    assert not verified_inline_arithmetic_hints(original)


def test_parent_value_used_only_in_lazy_region_does_not_cross_the_boundary():
    read, one = GetCharOp(), ConstOp(1)
    producer = BinaryOp("add", read, one)
    inner = BinaryOp("add", producer, one)
    other = ConstOp(0)
    choice = IfExprOp(one, [inner, YieldOp(inner)], [other, YieldOp(other)])
    original = module([read, one, producer, choice, PrintWordOp(choice)])
    mark(original, b"A")
    assert producer.result.uses.get_length() == 1
    assert not verified_inline_arithmetic_hints(original)


def test_adjacent_chain_inside_a_lazy_region_stays_in_that_region():
    read, captured, first = GetCharOp(), ConstOp(1), ConstOp(1)
    producer = BinaryOp("add", read, captured)
    consumer = BinaryOp("add", producer, captured)
    boolean = BoolOp("and", [[first, YieldOp(first)],
                              [read, producer, consumer, YieldOp(consumer)]])
    original = module([captured, boolean, PrintWordOp(boolean)])
    mark(original, b"A")
    assert verified_inline_arithmetic_hints(original) == frozenset([producer])
    assert producer.parent is consumer.parent is boolean.values[1].block


def test_adjacent_chains_in_loops_keep_repeated_input_and_bound_values():
    # Source variable loads may intervene; chain expansion is the intended
    # producer of immediately adjacent operations.
    original = compile_python_to_semantic_ir("for i in range(3):\n    print(getchar()*3)\n")
    LowerConstantMultiplyPass().apply(Context(), original)
    mark(original, b"ABC")
    assert len(verified_inline_arithmetic_hints(original)) == 1
    assert run_semantic(original, b"ABC").output == b"195\n198\n201\n"


@pytest.mark.parametrize("attribute", [IntAttr(0), IntAttr(1), StringAttr("unit"), StringAttr("")])
def test_wrong_attribute_type_is_not_a_verified_hint(attribute):
    read = GetCharOp()
    producer = BinaryOp("add", read, read)
    consumer = BinaryOp("add", producer, read)
    original = module([read, producer, consumer, PrintWordOp(consumer)])
    producer.attributes[INLINE_ARITHMETIC_ATTR] = attribute
    assert inline_arithmetic_candidates(original) == frozenset([producer])
    assert not verified_inline_arithmetic_hints(original)
    mark(original, b"A")
    assert verified_inline_arithmetic_hints(original) == frozenset([producer])


def test_malicious_marker_on_effect_or_nonadjacent_operation_is_ignored_and_removed():
    read = GetCharOp()
    producer = BinaryOp("add", read, read)
    middle = GetCharOp()
    consumer = BinaryOp("add", producer, read)
    original = module([read, producer, middle, consumer, PrintWordOp(consumer)])
    for operation in (read, producer, middle, consumer):
        operation.attributes[INLINE_ARITHMETIC_ATTR] = UnitAttr()
    assert not verified_inline_arithmetic_hints(original)
    mark(original, b"AB")
    assert all(INLINE_ARITHMETIC_ATTR not in operation.attributes for operation in original.walk())


@pytest.mark.parametrize("mutation", ["extra_use", "intervening_effect", "consumer_kind"])
def test_graph_mutation_invalidates_the_old_hint_before_pass_reruns(mutation):
    read = GetCharOp()
    producer = BinaryOp("add", read, read)
    consumer = BinaryOp("add", producer, read)
    output = PrintWordOp(consumer)
    original = module([read, producer, consumer, output])
    mark(original, b"AB")
    assert verified_inline_arithmetic_hints(original) == frozenset([producer])
    if mutation == "extra_use":
        output.operands = (producer.result,)
    elif mutation == "intervening_effect":
        consumer.parent.insert_op_before(GetCharOp(), consumer)
    else:
        consumer.properties["kind"] = StringAttr("mul")
    verify_semantic(original)
    assert isinstance(producer.attributes[INLINE_ARITHMETIC_ATTR], UnitAttr)
    assert not verified_inline_arithmetic_hints(original)
    InlinePureArithmeticPass().apply(Context(), original)
    assert INLINE_ARITHMETIC_ATTR not in producer.attributes


def test_work_cap_is_conservative_and_does_not_trust_unvisited_markers():
    read = GetCharOp()
    producer = BinaryOp("add", read, read)
    consumer = BinaryOp("add", producer, read)
    original = module([read, producer, consumer, PrintWordOp(consumer)])
    producer.attributes[INLINE_ARITHMETIC_ATTR] = UnitAttr()
    before = print_semantic(original)
    InlinePureArithmeticPass(max_operations=0).apply(Context(), original)
    assert print_semantic(original) == before
    assert not inline_arithmetic_candidates(original, max_operations=0)
    assert not verified_inline_arithmetic_hints(original, max_operations=0)
    limit = list(original.walk()).index(producer) + 1
    assert verified_inline_arithmetic_hints(original, max_operations=limit) == frozenset([producer])
    for invalid in (-1, True, None, 2.5):
        with pytest.raises(ValueError, match="nonnegative integer"):
            inline_arithmetic_candidates(original, max_operations=invalid)
        with pytest.raises(ValueError, match="nonnegative integer"):
            InlinePureArithmeticPass(max_operations=invalid).apply(Context(), original)


def test_program_and_module_helpers_return_the_same_operations():
    original = compile_python_to_semantic_ir("print(getchar()*3)\n")
    LowerConstantMultiplyPass().apply(Context(), original)
    mark(original, b"A")
    assert verified_inline_arithmetic_hints(original) == verified_inline_arithmetic_hints(get_program(original))


def test_thousands_of_adjacent_nodes_keep_expression_depth_bounded():
    read, one = GetCharOp(), ConstOp(1)
    operations = [read, one]
    previous = read.result
    chain = []
    for _ in range(2000):
        binary = BinaryOp("add", previous, one)
        binary.attributes[INLINE_ARITHMETIC_ATTR] = UnitAttr()  # forged blanket hints
        chain.append(binary)
        operations.append(binary)
        previous = binary.result
    original = module([*operations, PrintWordOp(previous)])
    verify_semantic(original)
    candidates = inline_arithmetic_candidates(original)
    eligible = len(chain) - 1  # the last result feeds output, not arithmetic
    assert len(candidates) == eligible - eligible // (MAX_INLINE_ARITHMETIC_DEPTH + 1)
    assert verified_inline_arithmetic_hints(original) == candidates
    InlinePureArithmeticPass().apply(Context(), original)
    verify_semantic(original)
    depth = {}
    for binary in chain:
        if binary in candidates:
            depth[binary] = 1 + max(depth.get(value.owner, 0) for value in binary.operands)
        else:
            depth[binary] = 0
            assert INLINE_ARITHMETIC_ATTR not in binary.attributes
    assert max(depth.values()) == MAX_INLINE_ARITHMETIC_DEPTH
    assert run_semantic(original, b"A").output == b"2065"


@pytest.mark.parametrize("source,data", [
    ("print((1//getchar())*3)\n", b"\0"),
    ("print(int(input('N:'))*3)\n", b"bad\n"),
    ("g=1\ndef touch():\n    global g\n    g=7\n    putchar(65)\n    return 3\n"
     "print(g,touch()*3,g)\n", b""),
])
def test_markers_preserve_checked_errors_input_consumption_and_global_capture(source, data):
    original = compile_python_to_semantic_ir(source)
    LowerConstantMultiplyPass().apply(Context(), original)
    mark(original, data)


MANIFEST = json.loads((ROOT / "benchmarks" / "manifest.json").read_text())
WORKLOADS = [(program, workload) for program in MANIFEST["programs"]
             for workload in program["workloads"]]


@pytest.mark.parametrize("program,workload", WORKLOADS,
                         ids=[f"{program['id']}-{workload['id']}" for program, workload in WORKLOADS])
def test_fixed_workloads_keep_identical_semantic_execution(program, workload):
    original = compile_python_to_semantic_ir((ROOT / "benchmarks" / program["path"]).read_text())
    LowerConstantMultiplyPass().apply(Context(), original)
    mark(original, workload["stdin"].encode())
    assert run_semantic(original, workload["stdin"]).output == workload["stdout"].encode()
