"""The semantic oracle is tested without using either source frontend."""
import pytest

pytest.importorskip("xdsl")

from xdsl.dialects.builtin import ModuleOp, i32
from xdsl.ir import Block
from xdsl.traits import Pure
from xdsl.utils.exceptions import VerifyException

from malbolge.compiler.ir.semantic import (
    MOD, MAX_WORD, WORD, BinaryOp, BoolOp, BreakOp, CallOp, CompareOp,
    ConstOp, ContinueOp, ForOp, FuncOp, GetCharOp, IfExprOp, IfOp, LoadOp,
    PrintLiteralOp, PrintWordOp, ProgramOp, PutCharOp, ReadIntOp, ReturnOp,
    SemanticIRError, StoreOp, UnaryOp, UnboundNameOp, WhileOp, WordType, YieldOp,
    parse_semantic, print_semantic, verify_semantic,
)
from malbolge.compiler.ir.interpreter import run_semantic


def module(ops, *, globals=(), locals=(), functions=()):
    return ModuleOp([ProgramOp(globals, [*functions, FuncOp("main", [], locals, ops,
                                                         returns="void", globals=globals)])])


def constant_region(number):
    value = ConstOp(number)
    return [value, YieldOp(value)]


@pytest.mark.parametrize("kind,left,right,expected", [
    ("add", MAX_WORD, 1, 0), ("sub", 0, 1, MAX_WORD),
    ("mul", MAX_WORD, MAX_WORD, 1), ("floordiv", MAX_WORD, 10, MAX_WORD // 10),
    ("mod", MAX_WORD, 10, MAX_WORD % 10),
])
def test_unsigned_word_edges(kind, left, right, expected):
    a, b = ConstOp(left), ConstOp(right)
    result = BinaryOp(kind, a, b)
    output = run_semantic(module([a, b, result, PrintWordOp(result)]))
    assert output.output == str(expected).encode()
    assert output.status == "completed"


def test_types_and_roundtrip_preserve_executable_structure():
    cond = ConstOp(1)
    choice = IfExprOp(cond, constant_region(MAX_WORD), constant_region(0))
    source = module([cond, choice, PrintWordOp(choice)])
    serialized = print_semantic(source)
    assert "pysem.if_expr" in serialized
    assert "pysem.word" in serialized
    recovered = parse_semantic(serialized)
    assert print_semantic(recovered) == serialized
    assert run_semantic(recovered) == run_semantic(source)


@pytest.mark.parametrize("kind,first,expected", [("and", 0, b"0"), ("or", 9, b"9")])
def test_lazy_boolean_does_not_run_unselected_input(kind, first, expected):
    read = ReadIntOp("unreached")
    result = BoolOp(kind, [constant_region(first), [read, YieldOp(read)]])
    actual = run_semantic(module([result, PrintWordOp(result)]), b"invalid\n")
    assert actual.output == expected
    assert actual.input_consumed == 0


def test_compare_captures_middle_once_and_short_circuits_later_input():
    reads = [GetCharOp() for _ in range(3)]
    comparison = CompareOp(["lt", "lt"], [[value, YieldOp(value)] for value in reads])
    actual = run_semantic(module([comparison, PrintWordOp(comparison)]), b"321")
    assert actual.output == b"0"
    assert actual.input_consumed == 2
    reads = [GetCharOp() for _ in range(3)]
    comparison = CompareOp(["lt", "lt"], [[value, YieldOp(value)] for value in reads])
    actual = run_semantic(module([comparison, PrintWordOp(comparison)]), b"123")
    assert actual.output == b"1"
    assert actual.input_consumed == 3


def test_selected_expression_keeps_preexisting_ssa_capture():
    initial, update = ConstOp(7), ConstOp(9)
    function = FuncOp("change", [], [], [update, StoreOp("x", update, "global"), ReturnOp(update)],
                      globals=["x"])
    captured, call = LoadOp("x", "global"), CallOp("change", [])
    result = BinaryOp("add", captured, call)
    program = module([initial, StoreOp("x", initial, "global"), captured, call, result, PrintWordOp(result)],
                     globals=["x"], functions=[function])
    actual = run_semantic(program)
    assert actual.output == b"16"
    assert actual.globals == {"x": 9}


def test_function_block_arguments_recursion_and_call_budget():
    block = Block(arg_types=[WORD])
    n = block.args[0]
    zero, one = ConstOp(0), ConstOp(1)
    less = CompareOp(["eq"], [[YieldOp(n)], [zero, YieldOp(zero)]])
    prev = BinaryOp("sub", n, one)
    recur = CallOp("count", [prev])
    result = BinaryOp("add", recur, one)
    block.add_ops([one, less, IfOp(less, [ReturnOp(one)]), prev, recur, result, ReturnOp(result)])
    function = FuncOp("count", ["n"], [], block)
    five = ConstOp(5)
    call = CallOp("count", [five])
    program = module([five, call, PrintWordOp(call)], functions=[function])
    assert run_semantic(program).output == b"6"
    assert run_semantic(program, max_calls=3).status == "call_budget"
    assert run_semantic(program, max_call_depth=3).status == "call_depth_budget"


@pytest.mark.parametrize("step,start,stop,sentinel,expected", [
    (1, 0, 3, False, b"012"), (-1, 2, 0, True, b"210"),
    (MOD, 1, 4, False, b"1"), (-MOD, 3, 0, True, b"3"),
    (1, MAX_WORD - 1, MAX_WORD, False, str(MAX_WORD - 1).encode()),
])
def test_range_hidden_iterator_bounds_and_nonwrapping_step(step, start, stop, sentinel, expected):
    a, b, replace = ConstOp(start), ConstOp(stop), ConstOp(42)
    visible = LoadOp("i")
    loop = ForOp("i", a, b, step, [visible, PrintWordOp(visible), StoreOp("i", replace)], stop_sentinel=sentinel)
    assert run_semantic(module([a, b, replace, loop], locals=["i"])).output == expected


def test_empty_range_preserves_visible_slot_and_continue_updates_iterator():
    initial, start, stop = ConstOp(9), ConstOp(0), ConstOp(0)
    visible = LoadOp("i")
    empty = ForOp("i", start, stop, 1, [])
    actual = run_semantic(module([initial, StoreOp("i", initial), start, stop, empty, visible, PrintWordOp(visible)], locals=["i"]))
    assert actual.output == b"9"
    start, stop = ConstOp(0), ConstOp(3)
    value = LoadOp("i")
    loop = ForOp("i", start, stop, 1, [value, PrintWordOp(value), ContinueOp(), PrintLiteralOp("bad")])
    assert run_semantic(module([start, stop, loop], locals=["i"])).output == b"012"


def test_while_reevaluates_condition_and_break_exits_inner_loop_only():
    char = GetCharOp()
    condition = [char, YieldOp(char)]
    loop = WhileOp(condition, [PrintLiteralOp("x"), BreakOp(), PrintLiteralOp("bad")])
    actual = run_semantic(module([loop, PrintLiteralOp("done")]), b"12")
    assert actual.output == b"xdone"
    assert actual.input_consumed == 1


@pytest.mark.parametrize("data,expected", [
    (b"0\n", b"0"), (b" +00042 \r\n", b"42"), (b"3486784400", b"3486784400"),
    (b"", b"error\n"), (b" \n", b"error\n"), (b"+ 1\n", b"error\n"),
    (b"1 2\n", b"error\n"), (b"3486784401\n", b"error\n"),
    (b"-1\n", b"error\n"), (b"1_0\n", b"error\n"), (b"++1\n", b"error\n"),
])
def test_decimal_input_contract(data, expected):
    read = ReadIntOp("prompt:")
    result = run_semantic(module([read, PrintWordOp(read)]), data)
    assert result.output == b"prompt:" + expected
    assert result.status == ("runtime_error" if expected == b"error\n" else "completed")


@pytest.mark.parametrize("kind", ["floordiv", "mod"])
def test_runtime_error_unwinds_callers_and_preserves_prior_output(kind):
    one, zero = ConstOp(1), ConstOp(0)
    fail = BinaryOp(kind, one, zero)
    function = FuncOp("bad", [], [], [PrintLiteralOp("before:"), one, zero, fail, ReturnOp(fail)])
    call = CallOp("bad", [])
    result = run_semantic(module([call, PrintLiteralOp("never")], functions=[function]))
    assert result.output == b"before:error\n"
    assert result.status == "runtime_error"


def test_raw_io_modulo_byte_and_eof_sentinel():
    a, b, large = GetCharOp(), GetCharOp(), ConstOp(321)
    actual = run_semantic(module([a, PutCharOp(a), b, PrintWordOp(b), large, PutCharOp(large)]), b"\xff")
    assert actual.output == b"\xff59049A"


def test_budget_empty_loops_input_scanning_and_output():
    infinite = WhileOp(constant_region(1), [])
    result = run_semantic(module([infinite]), max_operations=10)
    assert result.status == "operation_budget"
    assert result.operations == 10
    read = ReadIntOp()
    result = run_semantic(module([read]), b" " * 100, max_operations=5)
    assert result.status == "operation_budget"
    assert result.input_consumed == 4
    assert run_semantic(module([PrintLiteralOp("hello")]), max_output=2).output == b"he"
    assert run_semantic(module([PrintLiteralOp("hello")]), max_output=2).status == "output_budget"


@pytest.mark.parametrize("make", [
    lambda: module([ConstOp(MOD)]),
    lambda: module([ConstOp(-1)]),
    lambda: module([LoadOp("absent")]),
    lambda: module([BreakOp()]),
    lambda: module([ContinueOp()]),
    lambda: module([CallOp("absent", [])]),
    lambda: module([PrintLiteralOp("\u0100")]),
    lambda: module([ReadIntOp("\u0100")]),
    lambda: module([UnboundNameOp("x + sideeffect()")]),
    lambda: module([BoolOp("and", [constant_region(1)])]),
    lambda: module([CompareOp(["is"], [constant_region(1), constant_region(2)])]),
    lambda: module([BoolOp("and", [[ConstOp(1)], constant_region(2)])]),
])
def test_invalid_semantic_constructs(make):
    with pytest.raises(SemanticIRError):
        verify_semantic(make())


def test_reject_typed_mutation():
    value = ConstOp(1)
    value.result._type = i32
    with pytest.raises(SemanticIRError):
        verify_semantic(module([value]))
    with pytest.raises(VerifyException, match="20 trits"):
        WordType(10)


def test_no_ssa_forward_sibling_or_cross_function_capture():
    later = ConstOp(7)
    with pytest.raises(SemanticIRError, match="lexical scope"):
        verify_semantic(module([PrintWordOp(later), later]))
    first = ConstOp(7)
    invalid = BoolOp("and", [[first, YieldOp(first)], [YieldOp(first)]])
    with pytest.raises(SemanticIRError, match="lexical scope"):
        verify_semantic(module([invalid]))
    external = ConstOp(7)
    other = FuncOp("other", [], [], [ReturnOp(external)])
    with pytest.raises(SemanticIRError, match="lexical scope"):
        verify_semantic(module([external], functions=[other]))


def test_no_lazy_expression_store_or_nested_region_argument():
    value = ConstOp(1)
    invalid = BoolOp("and", [[value, StoreOp("x", value), YieldOp(value)], constant_region(2)])
    with pytest.raises(SemanticIRError):
        verify_semantic(module([invalid], locals=["x"]))
    block = Block(arg_types=[WORD])
    block.add_op(YieldOp(block.args[0]))
    invalid = BoolOp("and", [block, constant_region(2)])
    with pytest.raises(SemanticIRError, match="block arguments"):
        verify_semantic(module([invalid]))


def test_return_contract_and_void_calls():
    bad = FuncOp("bad", [], [], [], returns="word")
    with pytest.raises(SemanticIRError, match="fallthrough"):
        verify_semantic(module([], functions=[bad]))
    void = FuncOp("void", [], [], [ReturnOp()], returns="void")
    with pytest.raises(SemanticIRError, match="word-returning"):
        verify_semantic(module([CallOp("void", [])], functions=[void]))
    void = FuncOp("void", [], [], [PrintLiteralOp("ok"), ReturnOp()], returns="void")
    assert run_semantic(module([CallOp("void", [], returns=False)], functions=[void])).output == b"ok"


def test_global_write_requires_explicit_declaration():
    value = ConstOp(1)
    function = FuncOp("bad", [], [], [value, StoreOp("x", value, "global")], returns="void")
    with pytest.raises(SemanticIRError, match="declaration"):
        verify_semantic(module([], globals=["x"], functions=[function]))


def test_effectful_operations_do_not_advertise_purity():
    value = ConstOp(1)
    ops = [LoadOp("x"), StoreOp("x", value), BinaryOp("floordiv", value, value),
           BinaryOp("mod", value, value), CallOp("f", []), GetCharOp(),
           ReadIntOp(), PutCharOp(value), PrintWordOp(value), PrintLiteralOp("x")]
    assert all(not op.has_trait(Pure) for op in ops)


def test_unbound_name_traps_are_explicit_and_lazy():
    trap = UnboundNameOp("missing")
    lazy = BoolOp("and", [constant_region(0), [trap, YieldOp(trap)]])
    program = module([lazy, PrintWordOp(lazy)])
    assert run_semantic(parse_semantic(print_semantic(program))).output == b"0"
    assert not trap.has_trait(Pure)
    with pytest.raises(SemanticIRError, match="unresolved source name"):
        run_semantic(module([UnboundNameOp("missing")]))


def test_invalid_call_arity_and_slot_scope_are_rejected():
    block = Block(arg_types=[WORD])
    block.add_op(ReturnOp(block.args[0]))
    function = FuncOp("identity", ["x"], [], block)
    with pytest.raises(SemanticIRError, match="argument count"):
        verify_semantic(module([CallOp("identity", [])], functions=[function]))
    with pytest.raises(SemanticIRError, match="scope"):
        verify_semantic(module([LoadOp("x", "ambient")], locals=["x"]))


def test_global_initialization_and_local_storage_are_distinct():
    global_value = LoadOp("x", "global")
    assert run_semantic(module([global_value, PrintWordOp(global_value)], globals=["x"])).output == b"0"
    with pytest.raises(SemanticIRError, match="uninitialized local"):
        run_semantic(module([LoadOp("x")], locals=["x"]))


def test_invalid_range_step_and_sentinel_are_rejected():
    for step, sentinel in [(0, False), (1, True)]:
        a, b = ConstOp(0), ConstOp(1)
        with pytest.raises(SemanticIRError, match="range"):
            verify_semantic(module([a, b, ForOp("i", a, b, step, [], stop_sentinel=sentinel)], locals=["i"]))


def test_unreachable_word_return_in_empty_loop_does_not_change_void_contract():
    zero, value = ConstOp(0), ConstOp(42)
    loop = ForOp("i", zero, zero, 1, [value, ReturnOp(value)])
    function = FuncOp("void", [], ["i"], [zero, loop], returns="void")
    assert run_semantic(module([CallOp("void", [], returns=False)], functions=[function])).status == "completed"


def test_unary_operations_and_if_expression_select_exactly_one_side():
    truth = ConstOp(0)
    negate = UnaryOp("not", truth)
    read = GetCharOp()
    conditional = IfExprOp(negate, [read, YieldOp(read)], constant_region(99))
    positive = UnaryOp("pos", conditional)
    assert run_semantic(module([truth, negate, conditional, positive, PutCharOp(positive)]), b"A").output == b"A"


def test_expression_condition_values_do_not_escape_into_loop_body():
    condition_value = ConstOp(1)
    invalid = WhileOp([condition_value, YieldOp(condition_value)], [PrintWordOp(condition_value), BreakOp()])
    with pytest.raises(SemanticIRError, match="lexical scope"):
        verify_semantic(module([invalid]))
