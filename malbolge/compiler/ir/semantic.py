"""Structured Python-subset semantics, before any target-specific lowering.

Expression results are SSA words; source variables remain explicit mutable
slots. Lazy expressions own ordered regions, so side effects and single
operand evaluation are represented in the IR rather than hidden in source.
No effectful operation advertises purity, and this layer performs no rewrites.
"""
from __future__ import annotations

import io
import re
from collections.abc import Iterable, Sequence

from . import require_ir_support

require_ir_support()

from xdsl.context import Context
from xdsl.dialects.builtin import ArrayAttr, Builtin, IntAttr, ModuleOp, StringAttr
from xdsl.ir import Block, Dialect, Operation, ParametrizedAttribute, Region, SSAValue, TypeAttribute
from xdsl.irdl import (IRDLOperation, irdl_attr_definition, irdl_op_definition,
                       operand_def, opt_operand_def, opt_result_def, prop_def,
                       region_def, result_def, traits_def, var_operand_def,
                       var_region_def)
from xdsl.parser import Parser
from xdsl.printer import Printer
from xdsl.traits import IsTerminator, NoTerminator
from xdsl.utils.exceptions import ParseError, VerifyException

MOD = 3 ** 20
MAX_WORD = MOD - 1
EOF_WORD = 59049


class SemanticIRError(ValueError):
    """Invalid semantic IR structure, scope, type, or control flow."""


@irdl_attr_definition
class WordType(ParametrizedAttribute, TypeAttribute):
    name = "pysem.word"
    width: IntAttr

    def __init__(self, width: int = 20):
        super().__init__(IntAttr(width))

    def verify(self):
        if self.width.data != 20:
            raise VerifyException("semantic words must have exactly 20 trits")


WORD = WordType()


def _strings(values: Iterable[str]) -> ArrayAttr[StringAttr]:
    return ArrayAttr(StringAttr(value) for value in values)


def strings(values: ArrayAttr[StringAttr]) -> tuple[str, ...]:
    return tuple(value.data for value in values)


def region(value: Region | Block | Iterable[Operation]) -> Region:
    if isinstance(value, Region):
        return value
    return Region(value if isinstance(value, Block) else Block(value))


@irdl_op_definition
class ProgramOp(IRDLOperation):
    name = "pysem.program"
    globals = prop_def(ArrayAttr[StringAttr])
    entry = prop_def(StringAttr)
    body = region_def("single_block")
    traits = traits_def(NoTerminator())

    def __init__(self, globals: Sequence[str], functions: Iterable[Operation], entry: str = "main"):
        super().__init__(properties={"globals": _strings(globals), "entry": StringAttr(entry)},
                         regions=[region(functions)])


@irdl_op_definition
class FuncOp(IRDLOperation):
    name = "pysem.func"
    sym_name = prop_def(StringAttr)
    parameters = prop_def(ArrayAttr[StringAttr])
    locals = prop_def(ArrayAttr[StringAttr])
    globals = prop_def(ArrayAttr[StringAttr])
    returns = prop_def(StringAttr)
    body = region_def("single_block")
    traits = traits_def(NoTerminator())

    def __init__(self, name: str, parameters: Sequence[str], locals: Sequence[str],
                 ops: Block | Iterable[Operation], returns: str = "word", globals: Sequence[str] = ()):
        body = ops if isinstance(ops, Block) else Block(ops, arg_types=[WORD] * len(parameters))
        super().__init__(properties={"sym_name": StringAttr(name), "parameters": _strings(parameters),
                                    "locals": _strings(locals), "globals": _strings(globals),
                                    "returns": StringAttr(returns)}, regions=[Region(body)])


@irdl_op_definition
class ConstOp(IRDLOperation):
    name = "pysem.const"
    value = prop_def(IntAttr)
    result = result_def(WordType)

    def __init__(self, value: int):
        super().__init__(properties={"value": IntAttr(value)}, result_types=[WORD])


@irdl_op_definition
class LoadOp(IRDLOperation):
    name = "pysem.load"
    slot = prop_def(StringAttr)
    scope = prop_def(StringAttr)
    result = result_def(WordType)

    def __init__(self, name: str, scope: str = "local"):
        super().__init__(properties={"slot": StringAttr(name), "scope": StringAttr(scope)}, result_types=[WORD])


@irdl_op_definition
class UnboundNameOp(IRDLOperation):
    """Explicit lookup trap retained in statically unreachable source arms.

    Source definite-assignment checks reject reachable occurrences. Keeping a
    trap operation represents the unreachable expression without inventing a
    variable slot or permitting an invalid SSA reference.
    """
    name = "pysem.unbound_name"
    symbol = prop_def(StringAttr)
    result = result_def(WordType)

    def __init__(self, name: str):
        super().__init__(properties={"symbol": StringAttr(name)}, result_types=[WORD])


@irdl_op_definition
class StoreOp(IRDLOperation):
    name = "pysem.store"
    slot = prop_def(StringAttr)
    scope = prop_def(StringAttr)
    value = operand_def(WordType)

    def __init__(self, name: str, value: SSAValue | Operation, scope: str = "local"):
        super().__init__(operands=[value], properties={"slot": StringAttr(name), "scope": StringAttr(scope)})


@irdl_op_definition
class BinaryOp(IRDLOperation):
    name = "pysem.binary"
    kind = prop_def(StringAttr)
    lhs = operand_def(WordType)
    rhs = operand_def(WordType)
    result = result_def(WordType)

    def __init__(self, kind: str, lhs: SSAValue | Operation, rhs: SSAValue | Operation):
        super().__init__(operands=[lhs, rhs], properties={"kind": StringAttr(kind)}, result_types=[WORD])


@irdl_op_definition
class UnaryOp(IRDLOperation):
    name = "pysem.unary"
    kind = prop_def(StringAttr)
    value = operand_def(WordType)
    result = result_def(WordType)

    def __init__(self, kind: str, value: SSAValue | Operation):
        super().__init__(operands=[value], properties={"kind": StringAttr(kind)}, result_types=[WORD])


@irdl_op_definition
class YieldOp(IRDLOperation):
    name = "pysem.yield"
    value = operand_def(WordType)
    traits = traits_def(IsTerminator())

    def __init__(self, value: SSAValue | Operation):
        super().__init__(operands=[value])


@irdl_op_definition
class BoolOp(IRDLOperation):
    name = "pysem.bool"
    kind = prop_def(StringAttr)
    values = var_region_def("single_block")
    result = result_def(WordType)

    def __init__(self, kind: str, regions: Sequence[Region | Block | Iterable[Operation]]):
        super().__init__(properties={"kind": StringAttr(kind)}, regions=[[region(r) for r in regions]], result_types=[WORD])


@irdl_op_definition
class CompareOp(IRDLOperation):
    name = "pysem.compare"
    kinds = prop_def(ArrayAttr[StringAttr])
    values = var_region_def("single_block")
    result = result_def(WordType)

    def __init__(self, kinds: Sequence[str], regions: Sequence[Region | Block | Iterable[Operation]]):
        super().__init__(properties={"kinds": _strings(kinds)}, regions=[[region(r) for r in regions]], result_types=[WORD])


@irdl_op_definition
class IfExprOp(IRDLOperation):
    name = "pysem.if_expr"
    condition = operand_def(WordType)
    then_region = region_def("single_block")
    else_region = region_def("single_block")
    result = result_def(WordType)

    def __init__(self, condition: SSAValue | Operation, then_region, else_region):
        super().__init__(operands=[condition], regions=[region(then_region), region(else_region)], result_types=[WORD])


@irdl_op_definition
class IfOp(IRDLOperation):
    name = "pysem.if"
    condition = operand_def(WordType)
    then_region = region_def("single_block")
    else_region = region_def("single_block")
    traits = traits_def(NoTerminator())

    def __init__(self, condition: SSAValue | Operation, then_region, else_region=()):
        super().__init__(operands=[condition], regions=[region(then_region), region(else_region)])


@irdl_op_definition
class WhileOp(IRDLOperation):
    name = "pysem.while"
    condition = region_def("single_block")
    body = region_def("single_block")
    traits = traits_def(NoTerminator())

    def __init__(self, condition, body):
        super().__init__(regions=[region(condition), region(body)])


@irdl_op_definition
class ForOp(IRDLOperation):
    name = "pysem.for"
    target = prop_def(StringAttr)
    scope = prop_def(StringAttr)
    start = operand_def(WordType)
    stop = operand_def(WordType)
    step = prop_def(IntAttr)
    stop_sentinel = prop_def(IntAttr)
    body = region_def("single_block")
    traits = traits_def(NoTerminator())

    def __init__(self, target: str, start: SSAValue | Operation, stop: SSAValue | Operation,
                 step: int, body, scope: str = "local", stop_sentinel: bool = False):
        super().__init__(operands=[start, stop], properties={"target": StringAttr(target), "scope": StringAttr(scope),
            "step": IntAttr(step), "stop_sentinel": IntAttr(int(stop_sentinel))}, regions=[region(body)])


@irdl_op_definition
class BreakOp(IRDLOperation):
    name = "pysem.break"


@irdl_op_definition
class ContinueOp(IRDLOperation):
    name = "pysem.continue"


@irdl_op_definition
class ReturnOp(IRDLOperation):
    name = "pysem.return"
    value = opt_operand_def(WordType)

    def __init__(self, value: SSAValue | Operation | None = None):
        super().__init__(operands=[value])


@irdl_op_definition
class CallOp(IRDLOperation):
    name = "pysem.call"
    callee = prop_def(StringAttr)
    arguments = var_operand_def(WordType)
    result = opt_result_def(WordType)

    def __init__(self, callee: str, args: Sequence[SSAValue | Operation], returns: bool = True):
        super().__init__(operands=[args], properties={"callee": StringAttr(callee)}, result_types=[WORD if returns else None])


@irdl_op_definition
class GetCharOp(IRDLOperation):
    name = "pysem.getchar"
    result = result_def(WordType)

    def __init__(self):
        super().__init__(result_types=[WORD])


@irdl_op_definition
class PutCharOp(IRDLOperation):
    name = "pysem.putchar"
    value = operand_def(WordType)

    def __init__(self, value: SSAValue | Operation):
        super().__init__(operands=[value])


@irdl_op_definition
class PrintLiteralOp(IRDLOperation):
    name = "pysem.print_literal"
    text = prop_def(StringAttr)

    def __init__(self, text: str):
        super().__init__(properties={"text": StringAttr(text)})


@irdl_op_definition
class PrintWordOp(IRDLOperation):
    name = "pysem.print_word"
    value = operand_def(WordType)

    def __init__(self, value: SSAValue | Operation):
        super().__init__(operands=[value])


@irdl_op_definition
class ReadIntOp(IRDLOperation):
    name = "pysem.read_int"
    prompt = prop_def(StringAttr)
    result = result_def(WordType)

    def __init__(self, prompt: str = ""):
        super().__init__(properties={"prompt": StringAttr(prompt)}, result_types=[WORD])


_OPS = [ProgramOp, FuncOp, ConstOp, LoadOp, UnboundNameOp, StoreOp, BinaryOp, UnaryOp, YieldOp,
        BoolOp, CompareOp, IfExprOp, IfOp, WhileOp, ForOp, BreakOp, ContinueOp,
        ReturnOp, CallOp, GetCharOp, PutCharOp, PrintLiteralOp, PrintWordOp, ReadIntOp]
Semantic = Dialect("pysem", _OPS, [WordType])
_EXPRESSIONS = (ConstOp, LoadOp, UnboundNameOp, BinaryOp, UnaryOp, BoolOp, CompareOp, IfExprOp, CallOp, GetCharOp, ReadIntOp)
_BODY_OPS = _EXPRESSIONS + (StoreOp, IfOp, WhileOp, ForOp, BreakOp, ContinueOp, ReturnOp, PutCharOp, PrintLiteralOp, PrintWordOp)
_COMPARISONS = frozenset(("lt", "le", "gt", "ge", "eq", "ne"))


def create_semantic_context() -> Context:
    context = Context()
    context.load_dialect(Builtin)
    context.load_dialect(Semantic)
    return context


def get_program(module: ModuleOp | ProgramOp) -> ProgramOp:
    if isinstance(module, ProgramOp):
        return module
    ops = tuple(module.body.block.ops)
    if len(ops) != 1 or not isinstance(ops[0], ProgramOp):
        raise SemanticIRError("semantic module must contain exactly one pysem.program")
    return ops[0]


def _names(values: ArrayAttr[StringAttr], description: str) -> set[str]:
    names = strings(values)
    if len(set(names)) != len(names):
        raise SemanticIRError(f"duplicate {description} name")
    if any(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name) is None for name in names):
        raise SemanticIRError(f"invalid {description} name")
    return set(names)


def _constant(value: SSAValue) -> int | None:
    op = value.owner
    if isinstance(op, ConstOp):
        return op.value.data
    if isinstance(op, UnaryOp):
        inner = _constant(op.value)
        if inner is not None:
            return int(not inner) if op.kind.data == "not" else inner
    return None


def _outcomes(block: Block) -> set[str]:
    outcomes = {"fallthrough"}
    for op in block.ops:
        if "fallthrough" not in outcomes:
            break
        current = {"fallthrough"}
        if isinstance(op, ReturnOp):
            current = {"none" if op.value is None else "word"}
        elif isinstance(op, BreakOp):
            current = {"break"}
        elif isinstance(op, ContinueOp):
            current = {"continue"}
        elif isinstance(op, IfOp):
            value = _constant(op.condition)
            current = set()
            if value is None or value:
                current |= _outcomes(op.then_region.block)
            if value is None or not value:
                current |= _outcomes(op.else_region.block)
        elif isinstance(op, (WhileOp, ForOp)):
            inner = _outcomes(op.body.block)
            current = inner & {"word", "none"}
            if isinstance(op, WhileOp):
                term = op.condition.block.last_op
                truth = _constant(term.value) if isinstance(term, YieldOp) else None
                if truth == 0:
                    current = {"fallthrough"}
                elif truth is None or "break" in inner:
                    current.add("fallthrough")
            else:
                start, stop = _constant(op.start), _constant(op.stop)
                if op.stop_sentinel.data:
                    stop = -1
                known_nonempty = (start is not None and stop is not None and
                                  (start < stop if op.step.data > 0 else start > stop))
                if start is not None and stop is not None and not known_nonempty:
                    current = {"fallthrough"}
                if not known_nonempty or inner & {"fallthrough", "break", "continue"}:
                    current.add("fallthrough")
        outcomes = (outcomes - {"fallthrough"}) | current
    return outcomes


def verify_semantic(module: ModuleOp | ProgramOp) -> None:
    """Verify types, lexical SSA dominance, symbols, lazy regions and contracts.

    Names are explicit slots, not SSA source variables. Definite assignment of
    source slots remains the frontend's source diagnostic responsibility.
    """
    try:
        module.verify()
        program = get_program(module)
        global_names = _names(program.globals, "global")
        if program.body.block.args:
            raise SemanticIRError("program body cannot have block arguments")
        functions: dict[str, FuncOp] = {}
        for func in program.body.block.ops:
            if not isinstance(func, FuncOp):
                raise SemanticIRError("program body may only contain functions")
            name = func.sym_name.data
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name) is None or name in functions:
                raise SemanticIRError("invalid or duplicate function name")
            functions[name] = func
        if program.entry.data not in functions:
            raise SemanticIRError("program entry function is undefined")
        if functions[program.entry.data].parameters:
            raise SemanticIRError("program entry function must have no parameters")

        for func in functions.values():
            params = _names(func.parameters, "parameter")
            local_names = _names(func.locals, "local") | params
            declared_globals = _names(func.globals, "function global")
            if local_names & declared_globals or not declared_globals <= global_names:
                raise SemanticIRError("function local/global declarations conflict or name undefined globals")
            if len(func.body.block.args) != len(params) or any(arg.type != WORD for arg in func.body.block.args):
                raise SemanticIRError("function arguments must match word parameter signature")
            if func.returns.data not in ("word", "void", "maybe"):
                raise SemanticIRError("invalid function return contract")

            def slot(name: str, scope: str, *, writing: bool = False):
                if scope not in ("local", "global"):
                    raise SemanticIRError("slot scope must be local or global")
                if name not in (local_names if scope == "local" else global_names):
                    raise SemanticIRError(f"undefined {scope} slot {name!r}")
                if writing and scope == "global" and name not in declared_globals:
                    raise SemanticIRError(f"global store {name!r} lacks function global declaration")

            def check(block: Block, inherited: set[SSAValue], *, expression: bool = False,
                      loop_depth: int = 0, function_body: bool = False):
                if block.args and not function_body:
                    raise SemanticIRError("nested semantic regions cannot have block arguments")
                available = set(inherited) | set(block.args)
                ops = tuple(block.ops)
                if expression and (not ops or not isinstance(ops[-1], YieldOp)):
                    raise SemanticIRError("expression region must end in pysem.yield")
                for index, op in enumerate(ops):
                    allowed = _EXPRESSIONS + (YieldOp,) if expression else _BODY_OPS
                    if not isinstance(op, allowed):
                        raise SemanticIRError(f"{op.name} is not allowed in this semantic region")
                    if isinstance(op, YieldOp) and index != len(ops) - 1:
                        raise SemanticIRError("yield must be last in an expression region")
                    if any(value not in available for value in op.operands):
                        raise SemanticIRError("SSA operand is not defined in its lexical scope before use")
                    if any(value.type != WORD for value in (*op.operands, *op.results)):
                        raise SemanticIRError("all semantic values must have word<20> type")
                    if isinstance(op, ConstOp) and not 0 <= op.value.data < MOD:
                        raise SemanticIRError("constant is outside the unsigned word ring")
                    if isinstance(op, UnboundNameOp) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", op.symbol.data) is None:
                        raise SemanticIRError("unbound name trap needs a valid source identifier")
                    if isinstance(op, (LoadOp, StoreOp)):
                        slot(op.slot.data, op.scope.data, writing=isinstance(op, StoreOp))
                    if isinstance(op, BinaryOp) and op.kind.data not in ("add", "sub", "mul", "floordiv", "mod"):
                        raise SemanticIRError("invalid binary operation")
                    if isinstance(op, UnaryOp) and op.kind.data not in ("not", "pos"):
                        raise SemanticIRError("invalid unary operation")
                    if isinstance(op, CallOp):
                        callee = functions.get(op.callee.data)
                        if callee is None or len(op.arguments) != len(callee.parameters):
                            raise SemanticIRError("undefined call or wrong argument count")
                        if op.result is not None and callee.returns.data != "word":
                            raise SemanticIRError("call result requires a word-returning function")
                        if expression and op.result is None:
                            raise SemanticIRError("void call cannot occur in an expression region")
                    if isinstance(op, (PrintLiteralOp, ReadIntOp)):
                        value = op.text.data if isinstance(op, PrintLiteralOp) else op.prompt.data
                        if any(ord(char) > 255 for char in value):
                            raise SemanticIRError("literal output must contain only byte codepoints")
                    if isinstance(op, BoolOp):
                        if op.kind.data not in ("and", "or") or len(op.values) < 2:
                            raise SemanticIRError("boolean expression needs a valid kind and at least two regions")
                        for nested in op.values:
                            check(nested.block, available, expression=True)
                    elif isinstance(op, CompareOp):
                        if not len(op.kinds) or len(op.values) != len(op.kinds) + 1 or not set(strings(op.kinds)) <= _COMPARISONS:
                            raise SemanticIRError("comparison needs one more operand region than valid comparison kinds")
                        for nested in op.values:
                            check(nested.block, available, expression=True)
                    elif isinstance(op, (IfOp, IfExprOp)):
                        for nested in (op.then_region, op.else_region):
                            check(nested.block, available, expression=isinstance(op, IfExprOp), loop_depth=loop_depth)
                    elif isinstance(op, WhileOp):
                        check(op.condition.block, available, expression=True)
                        check(op.body.block, available, loop_depth=loop_depth + 1)
                    elif isinstance(op, ForOp):
                        slot(op.target.data, op.scope.data, writing=True)
                        if not op.step.data or op.stop_sentinel.data not in (0, 1) or (op.stop_sentinel.data and op.step.data >= 0):
                            raise SemanticIRError("range needs nonzero step and descending-only stop sentinel")
                        check(op.body.block, available, loop_depth=loop_depth + 1)
                    elif isinstance(op, (BreakOp, ContinueOp)) and not loop_depth:
                        raise SemanticIRError("loop control outside a loop")
                    available.update(op.results)

            check(func.body.block, set(), function_body=True)
            outcomes = _outcomes(func.body.block)
            if func.returns.data == "word" and outcomes & {"none", "fallthrough"}:
                raise SemanticIRError("word-returning function has reachable None or fallthrough")
            if func.returns.data == "void" and "word" in outcomes:
                raise SemanticIRError("void function has a reachable word return")
    except SemanticIRError:
        raise
    except (VerifyException, ValueError, TypeError) as exc:
        raise SemanticIRError(f"invalid semantic IR: {exc}") from exc


def print_semantic(module: ModuleOp) -> str:
    verify_semantic(module)
    stream = io.StringIO()
    Printer(stream=stream, print_debuginfo=True).print_op(module)
    return stream.getvalue() + "\n"


def parse_semantic(source: str) -> ModuleOp:
    try:
        module = Parser(create_semantic_context(), source).parse_module()
    except (ParseError, VerifyException, ValueError) as exc:
        raise SemanticIRError(f"invalid textual semantic IR: {exc}") from exc
    verify_semantic(module)
    return module


__all__ = [op.__name__ for op in _OPS] + ["WordType", "WORD", "Semantic", "SemanticIRError", "MOD", "MAX_WORD", "EOF_WORD",
    "strings", "region", "get_program", "create_semantic_context", "verify_semantic", "print_semantic", "parse_semantic"]
