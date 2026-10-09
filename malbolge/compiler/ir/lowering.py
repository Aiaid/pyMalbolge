"""Authoritative semantic-IR adapter to the existing direct target backend.

The generated Python AST is a compatibility representation, reconstructed
entirely from verified operations. No original source, cached AST, or LAL text
is consulted. It is executable as ordinary Python in the nonnegative,
nonoverflowing domain, but the target backend supplies word-ring arithmetic,
byte I/O, and checked runtime-error propagation; use the semantic interpreter
as the complete executable specification.

Loads and effectful producers are captured once in fresh temporaries. Pure
ConstOps remain literal AST constants, preserving the old backend's literal
range/condition analyses. Known literal truth through unary/boolean operations
is retained when spelling guards; producer statements still execute in order.
Slots are distinct from SSA temporaries. Globals
start at zero as specified by the semantic dialect; locals are never given
artificial initial values.

For a verified word-returning function, an unreachable ``return 0`` tail (and
zero spelling for unreachable void returns) preserves its verified contract
through the old backend's more conservative AST analysis. This is an adapter
representation detail, not a new source-language return value or IR rewrite.
"""

from __future__ import annotations

import ast

from . import require_ir_support

require_ir_support()

from xdsl.dialects.builtin import ModuleOp
from xdsl.ir import Block, SSAValue

from .semantic import (
    BinaryOp, BoolOp, BreakOp, CallOp, CompareOp, ConstOp, ContinueOp,
    ForOp, FuncOp, GetCharOp, IfExprOp, IfOp, LoadOp, PrintLiteralOp,
    PrintWordOp, ProgramOp, PutCharOp, ReadIntOp, ReturnOp, SemanticIRError,
    StoreOp, UnaryOp, UnboundNameOp, WhileOp, YieldOp, get_program, strings, verify_semantic,
)


class SemanticLoweringError(SemanticIRError):
    """Verified semantic IR cannot be represented by the compatibility backend."""


_BINARY = {"add": ast.Add, "sub": ast.Sub, "mul": ast.Mult,
           "floordiv": ast.FloorDiv, "mod": ast.Mod}
_COMPARE = {"lt": ast.Lt, "le": ast.LtE, "gt": ast.Gt,
            "ge": ast.GtE, "eq": ast.Eq, "ne": ast.NotEq}


def _name(name: str) -> ast.Name:
    return ast.Name(id=name, ctx=ast.Load())


def _assign(name: str, value: ast.expr) -> ast.Assign:
    return ast.Assign(targets=[ast.Name(id=name, ctx=ast.Store())], value=value)


def _call(name: str, args: list[ast.expr], *, keywords=()) -> ast.Call:
    return ast.Call(func=_name(name), args=args, keywords=list(keywords))


def _body(statements: list[ast.stmt]) -> list[ast.stmt]:
    return statements or [ast.Pass()]


def _word_boolean(condition: ast.expr) -> ast.IfExp:
    # pysem booleans are integer words, including when subsequently printed.
    return ast.IfExp(test=condition, body=ast.Constant(value=1), orelse=ast.Constant(value=0))


class _Lowerer:
    def __init__(self, program: ProgramOp):
        self.program = program
        self.functions = list(program.body.block.ops)
        source_names = list(strings(program.globals))
        for func in self.functions:
            source_names.extend((func.sym_name.data, *strings(func.locals), *strings(func.parameters)))
        source_names.extend(op.symbol.data for op in program.walk() if isinstance(op, UnboundNameOp))
        self.prefix = "mbir"
        while any(name.lower().startswith(self.prefix) for name in source_names):
            self.prefix += "x"
        self.function_names = {
            func.sym_name.data: f"{self.prefix}f{index}"
            for index, func in enumerate(self.functions)
        }
        self.global_names = {
            name: f"{self.prefix}g{index}" for index, name in enumerate(strings(program.globals))
        }
        self.local_names: dict[str, str] = {}
        self.values: dict[SSAValue, str | int] = {}
        self.truths: dict[SSAValue, bool] = {}
        self.counter = 0
        self.returns_word = False

    def fresh(self) -> str:
        name = f"{self.prefix}t{self.counter}"
        self.counter += 1
        return name

    def value(self, value: SSAValue) -> ast.expr:
        try:
            stored = self.values[value]
        except KeyError as exc:
            raise SemanticLoweringError("SSA value has no preceding lowered producer") from exc
        return ast.Constant(value=stored) if isinstance(stored, int) else _name(stored)

    def slot(self, name: str, scope: str) -> str:
        names = self.global_names if scope == "global" else self.local_names
        try:
            return names[name]
        except KeyError as exc:
            raise SemanticLoweringError(f"undefined {scope} slot {name!r}") from exc

    def condition(self, value: SSAValue) -> ast.expr:
        known = self.truths.get(value)
        return ast.Constant(value=int(known)) if known is not None else self.value(value)

    def capture(self, result: SSAValue, expression: ast.expr) -> ast.Assign:
        name = self.fresh()
        self.values[result] = name
        return _assign(name, expression)

    def expression_region(self, block: Block) -> tuple[list[ast.stmt], ast.expr]:
        operations = list(block.ops)
        terminator = operations.pop()
        if not isinstance(terminator, YieldOp):
            raise SemanticLoweringError("expression region lacks its final yield")
        statements = self.operations(operations)
        return statements, self.value(terminator.value)

    def boolean(self, op: BoolOp) -> list[ast.stmt]:
        name = self.fresh()
        self.values[op.result] = name
        first, value = self.expression_region(op.values[0].block)
        def remaining(index: int, previous: SSAValue) -> list[ast.stmt]:
            if index == len(op.values):
                return []
            body, selected = self.expression_region(op.values[index].block)
            body.append(_assign(name, selected))
            body.extend(remaining(index + 1, op.values[index].block.last_op.value))
            condition = self.condition(previous)
            if op.kind.data == "or":
                condition = ast.UnaryOp(op=ast.Not(), operand=condition)
            return [ast.If(test=condition, body=body, orelse=[])]

        # Use each already-captured operand as its guard. Literal guards stay
        # literal, so known-dead name traps remain dead to source validation.
        statements = first + [_assign(name, value)] + remaining(1, op.values[0].block.last_op.value)
        for region in op.values:
            known = self.truths.get(region.block.last_op.value)
            if known is None:
                break
            if (op.kind.data == "and" and not known) or (op.kind.data == "or" and known):
                self.truths[op.result] = known
                break
        else:
            self.truths[op.result] = known
        return statements

    def comparison(self, op: CompareOp) -> list[ast.stmt]:
        name = self.fresh()
        self.values[op.result] = name
        kinds = strings(op.kinds)
        first, left = self.expression_region(op.values[0].block)

        def pair(index: int, previous: ast.expr) -> list[ast.stmt]:
            body, right = self.expression_region(op.values[index + 1].block)
            body.append(_assign(name, _word_boolean(ast.Compare(
                left=previous, ops=[_COMPARE[kinds[index]]()], comparators=[right]))))
            if index + 1 < len(kinds):
                # Nested guards retain the dominance of the captured middle
                # operand for both Python and the direct backend's analysis.
                body.append(ast.If(test=_name(name), body=pair(index + 1, right), orelse=[]))
            return body

        return first + pair(0, left)

    def operations(self, operations) -> list[ast.stmt]:
        statements: list[ast.stmt] = []
        for op in operations:
            if isinstance(op, ConstOp):
                self.values[op.result] = op.value.data
                self.truths[op.result] = bool(op.value.data)
            elif isinstance(op, LoadOp):
                statements.append(self.capture(op.result, _name(self.slot(op.slot.data, op.scope.data))))
            elif isinstance(op, UnboundNameOp):
                statements.append(self.capture(op.result, _name(op.symbol.data)))
            elif isinstance(op, StoreOp):
                statements.append(_assign(self.slot(op.slot.data, op.scope.data), self.value(op.value)))
            elif isinstance(op, BinaryOp):
                right = self.value(op.rhs)
                if op.kind.data in ("floordiv", "mod") and isinstance(right, ast.Constant) and right.value == 0:
                    # Source diagnostics already ran before IR construction.
                    # A manually constructed/edited zero-divisor operation is
                    # a checked runtime error in the IR, not a compiler error.
                    divisor = self.fresh()
                    statements.append(_assign(divisor, right))
                    right = _name(divisor)
                statements.append(self.capture(op.result, ast.BinOp(
                    left=self.value(op.lhs), op=_BINARY[op.kind.data](), right=right)))
            elif isinstance(op, UnaryOp):
                operator = ast.Not() if op.kind.data == "not" else ast.UAdd()
                expression = ast.UnaryOp(op=operator, operand=self.value(op.value))
                if op.kind.data == "not":
                    expression = _word_boolean(expression)
                statements.append(self.capture(op.result, expression))
                known = self.truths.get(op.value)
                if known is not None:
                    self.truths[op.result] = not known if op.kind.data == "not" else known
            elif isinstance(op, BoolOp):
                statements.extend(self.boolean(op))
            elif isinstance(op, CompareOp):
                statements.extend(self.comparison(op))
            elif isinstance(op, IfExprOp):
                name = self.fresh()
                self.values[op.result] = name
                then, first = self.expression_region(op.then_region.block)
                otherwise, second = self.expression_region(op.else_region.block)
                statements.append(ast.If(test=self.condition(op.condition),
                    body=then + [_assign(name, first)], orelse=otherwise + [_assign(name, second)]))
            elif isinstance(op, IfOp):
                statements.append(ast.If(test=self.condition(op.condition),
                    body=_body(self.operations(op.then_region.block.ops)),
                    orelse=self.operations(op.else_region.block.ops)))
            elif isinstance(op, WhileOp):
                prelude, condition = self.expression_region(op.condition.block)
                condition = self.condition(op.condition.block.last_op.value)
                body = self.operations(op.body.block.ops)
                if prelude:
                    body = prelude + [ast.If(
                        test=ast.UnaryOp(op=ast.Not(), operand=condition),
                        body=[ast.Break()], orelse=[])] + body
                    condition = ast.Constant(value=1)
                statements.append(ast.While(test=condition, body=_body(body), orelse=[]))
            elif isinstance(op, ForOp):
                stop = ast.Constant(value=-1) if op.stop_sentinel.data else self.value(op.stop)
                iterator = _call("range", [self.value(op.start), stop, ast.Constant(value=op.step.data)])
                statements.append(ast.For(
                    target=ast.Name(id=self.slot(op.target.data, op.scope.data), ctx=ast.Store()),
                    iter=iterator, body=_body(self.operations(op.body.block.ops)), orelse=[]))
            elif isinstance(op, BreakOp):
                statements.append(ast.Break())
            elif isinstance(op, ContinueOp):
                statements.append(ast.Continue())
            elif isinstance(op, ReturnOp):
                value = self.value(op.value) if op.value is not None else (
                    ast.Constant(value=0) if self.returns_word else None)
                statements.append(ast.Return(value=value))
            elif isinstance(op, CallOp):
                expression = _call(self.function_names[op.callee.data],
                                   [self.value(value) for value in op.arguments])
                statements.append(self.capture(op.result, expression) if op.result is not None
                                  else ast.Expr(value=expression))
            elif isinstance(op, GetCharOp):
                statements.append(self.capture(op.result, _call("getchar", [])))
            elif isinstance(op, ReadIntOp):
                read = _call("input", [ast.Constant(value=op.prompt.data)])
                statements.append(self.capture(op.result, _call("int", [read])))
            elif isinstance(op, PutCharOp):
                statements.append(ast.Expr(value=_call("putchar", [self.value(op.value)])))
            elif isinstance(op, (PrintWordOp, PrintLiteralOp)):
                value = self.value(op.value) if isinstance(op, PrintWordOp) else ast.Constant(value=op.text.data)
                statements.append(ast.Expr(value=_call("print", [value],
                    keywords=[ast.keyword(arg="end", value=ast.Constant(value=""))])))
            else:
                raise SemanticLoweringError(f"unsupported semantic operation {op.name!r}")
        return statements

    def function(self, func: FuncOp, index: int) -> ast.FunctionDef:
        locals_ = list(strings(func.locals))
        for parameter in strings(func.parameters):
            if parameter not in locals_:
                locals_.append(parameter)
        self.local_names = {name: f"{self.prefix}l{index}_{position}" for position, name in enumerate(locals_)}
        parameters = []
        for position, value in enumerate(func.body.block.args):
            name = f"{self.prefix}a{index}_{position}"
            self.values[value] = name
            parameters.append(ast.arg(arg=name))
        self.returns_word = func.returns.data == "word"
        body = []
        globals_ = [self.global_names[name] for name in strings(func.globals)]
        if globals_:
            body.append(ast.Global(names=globals_))
        body.extend(self.operations(func.body.block.ops))
        if self.returns_word:
            # verify_semantic established this tail is unreachable. Retaining
            # an explicit scalar tail satisfies legacy AST contract analysis.
            body.append(ast.Return(value=ast.Constant(value=0)))
        return ast.FunctionDef(name=self.function_names[func.sym_name.data],
            args=ast.arguments(posonlyargs=[], args=parameters, vararg=None,
                               kwonlyargs=[], kw_defaults=[], kwarg=None, defaults=[]),
            body=_body(body), decorator_list=[])

    def lower(self) -> ast.Module:
        body: list[ast.stmt] = [
            _assign(name, ast.Constant(value=0)) for name in self.global_names.values()
        ]
        body.extend(self.function(func, index) for index, func in enumerate(self.functions))
        body.append(ast.Expr(value=_call(self.function_names[self.program.entry.data], [])))
        return ast.fix_missing_locations(ast.Module(body=body, type_ignores=[]))


def lower_semantic_to_python_ast(module: ModuleOp | ProgramOp) -> ast.Module:
    """Reconstruct a fresh backend-compatible AST from verified IR alone."""
    verify_semantic(module)
    return _Lowerer(get_program(module)).lower()


def lower_semantic_to_python(module: ModuleOp | ProgramOp) -> str:
    """Serialize the authoritative generated AST for inspection/compilation."""
    return ast.unparse(lower_semantic_to_python_ast(module)) + "\n"


def lower_semantic_to_mg(module: ModuleOp | ProgramOp) -> str:
    """Use the existing direct compiler on the newly reconstructed AST text."""
    from ..py2mg import Py2MgError, compile_python_to_mg

    source = lower_semantic_to_python(module)
    try:
        return compile_python_to_mg(source)
    except Py2MgError as exc:
        raise SemanticLoweringError(f"semantic IR compatibility lowering failed: {exc}") from exc


__all__ = ["SemanticLoweringError", "lower_semantic_to_python_ast",
           "lower_semantic_to_python", "lower_semantic_to_mg"]
