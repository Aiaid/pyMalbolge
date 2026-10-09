"""Python subset to the high-level, executable semantic dialect.

This frontend never invokes the direct compiler or constructs target code.  It
reuses its *AST-only* definite-assignment/name checks, and the shared syntax
normalizer, so source diagnostics remain consistent with the established subset.
Arithmetic and control flow are retained as semantic operations; no optimization
or target representation is selected here.
"""

from __future__ import annotations

import ast

from . import require_ir_support

require_ir_support()

from xdsl.dialects.builtin import FileLineColLoc, IntAttr, ModuleOp, StringAttr
from xdsl.ir import Block, Operation, SSAValue

from ..py2mg import MOD, RESERVED_FUNCS, _BUILTINS, _DirectCompiler, Py2MgError
from ..python_normalize import _exits, bind_call_arguments, normalize_tree
from .semantic import (
    WORD, BinaryOp, BoolOp, BreakOp, CallOp, CompareOp, ConstOp, ContinueOp,
    ForOp, FuncOp, GetCharOp, IfExprOp, IfOp, LoadOp, PrintLiteralOp,
    PrintWordOp, ProgramOp, PutCharOp, ReadIntOp, ReturnOp, StoreOp,
    UnaryOp, UnboundNameOp, WhileOp, YieldOp, verify_semantic,
)


class SemanticFrontendError(Py2MgError):
    """Unsupported Python input, with its original source location."""


class _Analysis:
    """An intentionally small adapter containing no code-generation state.

    These methods inspect Python ASTs only.  In particular, this is neither a
    subclass nor an instance of the target compiler: its initializer, compile,
    expression lowering and target emitters are never called.
    """

    _compiling_helper = False
    _check_name = _DirectCompiler._check_name
    _collect_assigned = staticmethod(_DirectCompiler._collect_assigned)
    _global_decls_in = staticmethod(_DirectCompiler._global_decls_in)
    _check_definite_assignment = _DirectCompiler._check_definite_assignment
    _da_stmts = _DirectCompiler._da_stmts
    _da_stmt = _DirectCompiler._da_stmt
    _da_terminates = _DirectCompiler._da_terminates
    _da_reads = _DirectCompiler._da_reads
    _da_name = _DirectCompiler._da_name
    _static_bool = _DirectCompiler._static_bool
    _range_args = _DirectCompiler._range_args
    _signed_literal = staticmethod(_DirectCompiler._signed_literal)
    _literal_range_nonempty = staticmethod(_DirectCompiler._literal_range_nonempty)
    _fold = _DirectCompiler._fold
    _fold_ord = _DirectCompiler._fold_ord

    def __init__(self, source: str):
        self.source = source
        self._fdefs = {}

    def err(self, message: str, node: ast.AST):
        return SemanticFrontendError(message, node, self.source)


_BINARY = {ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul",
           ast.FloorDiv: "floordiv", ast.Mod: "mod"}
_COMPARE = {ast.Lt: "lt", ast.LtE: "le", ast.Gt: "gt", ast.GtE: "ge",
            ast.Eq: "eq", ast.NotEq: "ne"}


class _Frontend(_Analysis):
    def __init__(self, source: str):
        super().__init__(source)
        self.functions: dict[str, ast.FunctionDef] = {}
        self.returns: dict[str, str] = {}
        self.global_names: list[str] = []
        self.module_bindings: set[str] = set()
        self.global_bindings: set[str] = set()
        self.local_names: set[str] = set()
        self.global_decls: set[str] = set()
        self.is_entry = False
        self.loop_depth = 0

    def located(self, op: Operation, node: ast.AST) -> Operation:
        op.location = FileLineColLoc(StringAttr("<python-subset>"),
                                    IntAttr(getattr(node, "lineno", 1)),
                                    IntAttr(getattr(node, "col_offset", 0) + 1))
        return op

    def emit(self, ops: list[Operation], op: Operation, node: ast.AST):
        ops.append(self.located(op, node))
        return op.results[0] if op.results else None

    def scope(self, name: str, node: ast.AST) -> str:
        self._check_name(name, node)
        if not self.is_entry and name in self.local_names:
            return "local"
        if name in self.global_names:
            return "global"
        raise self.err("name {!r} is not defined".format(name), node)

    def compile(self) -> ModuleOp:
        try:
            # ast.parse omits CPython's symbol-table checks, e.g. global after
            # use, duplicate parameters, and module-level return/break.
            compile(self.source, "<python-subset>", "exec")
            tree = ast.parse(self.source)
        except SyntaxError as exc:
            node = ast.Constant(value=None)
            node.lineno, node.col_offset = exc.lineno or 1, (exc.offset or 1) - 1
            raise self.err("Python syntax error: {}".format(exc.msg), node) from None
        tree = normalize_tree(tree, error=self.err)
        body = []
        for index, stmt in enumerate(tree.body):
            if isinstance(stmt, ast.FunctionDef):
                self.register(stmt)
            elif index == 0 and self.is_docstring(stmt):
                continue
            elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
                raise self.err("'import' is unsupported", stmt)
            elif isinstance(stmt, ast.ClassDef):
                raise self.err("class definitions are unsupported", stmt)
            else:
                body.append(stmt)

        self.global_names = self.assigned(body, set(), set())
        self.module_bindings = set(self._collect_assigned(body, set(), set()))
        self.global_bindings = set(self.module_bindings)
        # A declaration is not a binding.  Include function global *writes*,
        # while a declaration without any assignment remains an undefined name.
        for definition in self.functions.values():
            declared = self._global_decls_in(definition.body)
            for name in self.assigned(definition.body, set(), set()):
                if name in declared and name not in self.global_names:
                    self.global_names.append(name)
            self.global_bindings.update(declared & set(
                self._collect_assigned(definition.body, set(), set())))
        functions = [self.function(node) for node in self.functions.values()]
        self.is_entry, self.local_names, self.global_decls = True, set(), set()
        self.validate_shapes(body)
        self._check_definite_assignment(body, set(), set(self.global_names))
        self.check_constant_arithmetic(body)
        entry_ops = self.statements(body)
        entry_ops.append(ReturnOp())
        entry_name = "mbentry"
        while entry_name.upper() in self._fdefs:
            entry_name += "x"
        functions.append(FuncOp(entry_name, [], [], entry_ops, returns="void",
                                globals=self.global_names))
        module = ModuleOp([ProgramOp(self.global_names, functions, entry=entry_name)])
        verify_semantic(module)
        return module

    @staticmethod
    def is_docstring(node: ast.AST) -> bool:
        return (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str))

    def assigned(self, body, parameters, globals):
        names = self._collect_assigned(body, parameters, globals)
        # Even a bare annotation makes a name local in Python, though it does
        # not establish a value for definite-assignment purposes.
        for stmt in body:
            if isinstance(stmt, ast.FunctionDef):
                continue
            for node in ast.walk(stmt):
                if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    name = node.target.id
                    if name not in names and name not in parameters and name not in globals:
                        names.append(name)
        return names

    def validate_shapes(self, nodes):
        """Reject unsupported constructs before downstream name diagnostics.

        Otherwise a nested definition/with/try or walrus can hide its own
        unsupported binding, making the later read incorrectly blame a name.
        Type annotations are deliberately ignored, as required by the subset.
        """
        frontend = self
        statements = (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Expr, ast.If,
                      ast.While, ast.For, ast.Return, ast.Break, ast.Continue,
                      ast.Global, ast.Pass)
        expressions = (ast.Constant, ast.Name, ast.BinOp, ast.UnaryOp, ast.BoolOp,
                       ast.Compare, ast.IfExp, ast.Call, ast.JoinedStr,
                       ast.FormattedValue, ast.Starred)

        class Shapes(ast.NodeVisitor):
            def generic_visit(self, node):
                if isinstance(node, ast.stmt) and not isinstance(node, statements):
                    if isinstance(node, ast.FunctionDef):
                        raise frontend.err("nested function definitions are unsupported", node)
                    raise frontend.err("unsupported statement: {}".format(type(node).__name__), node)
                if isinstance(node, ast.expr) and not isinstance(node, expressions):
                    raise frontend.err("unsupported expression: {}".format(type(node).__name__), node)
                super().generic_visit(node)

            def visit_AnnAssign(self, node):
                self.visit(node.target)
                if node.value is not None:
                    self.visit(node.value)

            def visit_Call(self, node):
                if not isinstance(node.func, ast.Name):
                    raise frontend.err("only direct function calls are supported", node)
                self.generic_visit(node)

        visitor = Shapes()
        for node in nodes:
            visitor.visit(node)

    def register(self, node: ast.FunctionDef):
        if node.decorator_list:
            raise self.err("function decorators are unsupported", node)
        name = self._check_name(node.name, node)
        if name in _BUILTINS:
            raise self.err("function name {!r} collides with a builtin".format(name), node)
        upper = name.upper()
        if upper == "MAIN":
            raise self.err("define top-level code directly, not a main() function", node)
        if upper in RESERVED_FUNCS:
            raise self.err("function name {!r} is reserved".format(name), node)
        if upper in self._fdefs:
            raise self.err("function {!r} collides with {!r} (names are case-insensitive "
                           "in the backend)".format(name, self._fdefs[upper].name), node)
        args = node.args
        if (args.vararg or args.kwarg or args.kwonlyargs or args.posonlyargs
                or args.defaults or any(args.kw_defaults)):
            raise self.err("only simple positional parameters are supported", node)
        for parameter in args.args:
            self._check_name(parameter.arg, parameter)
        self._fdefs[upper] = node
        self.functions[name] = node
        outcomes = _exits(node.body)
        self.returns[name] = ("maybe" if "value" in outcomes else "void") \
            if outcomes & {"none", "fallthrough"} else "word"

    def function(self, node: ast.FunctionDef) -> FuncOp:
        params = [param.arg for param in node.args.args]
        self.global_decls = self._global_decls_in(node.body)
        for name in sorted(self.global_decls):
            self._check_name(name, node)
        locals = params + self.assigned(node.body, set(params), self.global_decls)
        self.local_names, self.is_entry = set(locals), False
        # A local assignment shadows a module name throughout the function.
        # Implicit global reads retain the existing frontend's module-binding
        # boundary. A different function's `global x; x = ...` reserves storage
        # but does not make x implicitly visible here; an explicit declaration
        # is needed unless module-level code binds the name.
        external = (self.module_bindings - self.local_names) | set(params)
        external |= self.global_decls
        body = list(node.body)
        if body and self.is_docstring(body[0]):
            body = body[1:]
        self.validate_shapes(body)
        self._check_definite_assignment(body, external, self.local_names)
        self.check_constant_arithmetic(body)
        block = Block(arg_types=[WORD] * len(params))
        for name, arg in zip(params, block.args):
            block.add_op(self.located(StoreOp(name, arg, scope="local"), node))
        block.add_ops(self.statements(body))
        if _exits(body) & {"none", "fallthrough"}:
            block.add_op(self.located(ReturnOp(), node))
        return self.located(FuncOp(node.name, params, locals, block,
                                   returns=self.returns[node.name],
                                   globals=sorted(self.global_decls & set(self.global_names))), node)

    def check_constant_arithmetic(self, nodes):
        """Preserve source diagnostics without rewriting any semantic ops.

        The direct frontend diagnoses zero divisors only when its operands are
        known constants.  Its static statement/boolean reachability rules also
        decide which source expressions receive that diagnostic.  Keep this
        check separate from IR construction: valid constants, arithmetic and
        even statically dead regions still become ordinary semantic operations.
        """
        for node in nodes:
            if isinstance(node, ast.If):
                known = self._static_bool(node.test)
                if known is not None:
                    self.check_constant_arithmetic(node.body if known else node.orelse)
                else:
                    self.diagnostic_value(node.test, condition=True)
                    self.check_constant_arithmetic(node.body)
                    self.check_constant_arithmetic(node.orelse)
            elif isinstance(node, ast.While):
                known = self._static_bool(node.test)
                if known is not False:
                    if known is not True:
                        self.diagnostic_value(node.test, condition=True)
                    self.check_constant_arithmetic(node.body)
            elif isinstance(node, ast.For):
                if (isinstance(node.iter, ast.Call) and isinstance(node.iter.func, ast.Name)
                        and node.iter.func.id == "range"):
                    start, stop, _ = self._range_args(node.iter)
                    self.diagnostic_value(start)
                    literal_stop = self._signed_literal(stop)
                    if literal_stop is None or literal_stop >= 0:
                        self.diagnostic_value(stop)
                # The established compiler checks a range body even if its
                # literal bounds happen to describe an empty range.
                self.check_constant_arithmetic(node.body)
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign,
                                   ast.Expr, ast.Return)):
                if node.value is not None:
                    self.diagnostic_value(node.value)
            if self._da_terminates([node]):
                break

    def diagnostic_value(self, node: ast.expr, *, condition=False):
        """Return a legacy-known word for diagnostics only, never an IR value."""
        if isinstance(node, ast.BoolOp):
            remaining = iter(node.values)
            first = next(remaining)
            if condition:
                known = self._static_bool(first)
                while known is not None:
                    decisive = not known if isinstance(node.op, ast.And) else known
                    if decisive:
                        self.diagnostic_value(first, condition=True)
                        return None
                    following = next(remaining, None)
                    if following is None:
                        self.diagnostic_value(first, condition=True)
                        return None
                    first, known = following, self._static_bool(following)
                self.diagnostic_value(first, condition=True)
                for operand in remaining:
                    self.diagnostic_value(operand, condition=True)
                return None
            value = self.diagnostic_value(first)
            for operand in remaining:
                if value is not None:
                    decisive = value == 0 if isinstance(node.op, ast.And) else value != 0
                    if decisive:
                        return value
                    value = self.diagnostic_value(operand)
                else:
                    # Once the prefix is dynamic, the established frontend
                    # checks all subsequent lazy regions, even a later 0/1.
                    self.diagnostic_value(operand)
            return value
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, bool)) and node.value >= 0:
                return int(node.value) % MOD
            return None
        if isinstance(node, ast.BinOp):
            left = self.diagnostic_value(node.left)
            right = self.diagnostic_value(node.right)
            if left is not None and right is not None and type(node.op) in _BINARY:
                return self._fold(node.op, left, right, node)
            # These identities describe the legacy diagnostic result only;
            # the semantic BinaryOp and all operand effects are still emitted.
            if isinstance(node.op, ast.Mod) and right == 1:
                return 0
            if isinstance(node.op, ast.Mult) and (left == 0 or right == 0):
                return 0
            return None
        if isinstance(node, ast.UnaryOp):
            value = self.diagnostic_value(node.operand,
                                          condition=isinstance(node.op, ast.Not))
            return value if isinstance(node.op, ast.UAdd) else None
        if isinstance(node, ast.Compare):
            for operand in [node.left, *node.comparators]:
                self.diagnostic_value(operand)
            return None
        if isinstance(node, ast.IfExp):
            self.diagnostic_value(node.test, condition=True)
            # The current source contract checks both arms; it does not fold
            # an if-expression's literal condition during source diagnostics.
            self.diagnostic_value(node.body)
            self.diagnostic_value(node.orelse)
            return None
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "ord":
                return self._fold_ord(node)
            for argument in node.args:
                self.diagnostic_value(argument)
            for keyword in node.keywords:
                self.diagnostic_value(keyword.value)
        return None

    def statements(self, nodes) -> list[Operation]:
        ops: list[Operation] = []
        for node in nodes:
            self.statement(node, ops)
        return ops

    def statement(self, node: ast.stmt, ops: list[Operation]):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    raise self.err("unsupported assignment target: {} (only simple names)"
                                   .format(type(target).__name__), node)
            value = self.expression(node.value, ops)
            for target in node.targets:
                self.emit(ops, StoreOp(target.id, value, scope=self.scope(target.id, target)), node)
        elif isinstance(node, ast.AnnAssign):
            if not isinstance(node.target, ast.Name):
                raise self.err("unsupported annotated assignment target", node)
            self._check_name(node.target.id, node)
            if node.value is not None:
                value = self.expression(node.value, ops)
                self.emit(ops, StoreOp(node.target.id, value,
                                      scope=self.scope(node.target.id, node)), node)
        elif isinstance(node, ast.AugAssign):
            if not isinstance(node.target, ast.Name):
                raise self.err("augmented assignment is only supported on simple names", node)
            kind = self.binary_kind(node.op, node, augmented=True)
            scope = self.scope(node.target.id, node)
            previous = self.emit(ops, LoadOp(node.target.id, scope=scope), node)
            right = self.expression(node.value, ops)
            value = self.emit(ops, BinaryOp(kind, previous, right), node)
            self.emit(ops, StoreOp(node.target.id, value, scope=scope), node)
        elif isinstance(node, ast.Expr):
            value = node.value
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
                if value.func.id == "print":
                    self.print_call(value, ops)
                    return
                if value.func.id == "putchar":
                    if len(value.args) != 1 or value.keywords:
                        raise self.err("putchar() takes exactly one argument", value)
                    arg = self.expression(value.args[0], ops)
                    self.emit(ops, PutCharOp(arg), node)
                    return
                if value.func.id in self.functions:
                    self.call(value, ops, discarded=True)
                    return
            self.expression(value, ops)
        elif isinstance(node, ast.If):
            condition = self.expression(node.test, ops)
            self.emit(ops, IfOp(condition, self.statements(node.body),
                                self.statements(node.orelse)), node)
        elif isinstance(node, ast.While):
            if node.orelse:
                raise self.err("while...else is unsupported", node)
            condition = self.expression_region(node.test)
            self.loop_depth += 1
            body = self.statements(node.body)
            self.loop_depth -= 1
            self.emit(ops, WhileOp(condition, body), node)
        elif isinstance(node, ast.For):
            self.for_loop(node, ops)
        elif isinstance(node, ast.Return):
            if self.is_entry:
                raise self.err("'return' outside function", node)
            value = None if node.value is None or (isinstance(node.value, ast.Constant)
                       and node.value.value is None) else self.expression(node.value, ops)
            self.emit(ops, ReturnOp(value), node)
        elif isinstance(node, ast.Break):
            if not self.loop_depth:
                raise self.err("'break' outside loop", node)
            self.emit(ops, BreakOp(), node)
        elif isinstance(node, ast.Continue):
            if not self.loop_depth:
                raise self.err("'continue' outside loop", node)
            self.emit(ops, ContinueOp(), node)
        elif isinstance(node, ast.Global):
            if self.is_entry:
                raise self.err("'global' outside function", node)
            for name in node.names:
                self._check_name(name, node)
        elif isinstance(node, ast.Pass):
            return
        elif isinstance(node, ast.FunctionDef):
            raise self.err("nested function definitions are unsupported", node)
        else:
            raise self.err("unsupported statement: {}".format(type(node).__name__), node)

    def for_loop(self, node: ast.For, ops: list[Operation]):
        if node.orelse:
            raise self.err("for...else is unsupported", node)
        if not isinstance(node.target, ast.Name):
            raise self.err("for-loop target must be a simple name", node)
        if not (isinstance(node.iter, ast.Call) and isinstance(node.iter.func, ast.Name)
                and node.iter.func.id == "range"):
            raise self.err("only 'for <name> in range(...)' is supported", node)
        if node.iter.keywords:
            raise self.err("range() does not support keyword arguments", node.iter)
        start, stop, step = self._range_args(node.iter)
        first, last = self._signed_literal(start), self._signed_literal(stop)
        if first is not None and first < 0:
            raise self.err("range() cannot yield negative integers", start)
        if step < 0 and last is not None and last < -1:
            raise self.err("descending range() supports non-negative bounds or stop=-1", stop)
        # Start and stop are captured once, in source order, outside the loop.
        start_value = self.expression(start, ops)
        sentinel = step < 0 and last == -1
        if last is not None and last < 0:
            stop_value = self.emit(ops, ConstOp(0), stop)
        else:
            stop_value = self.expression(stop, ops)
        self.loop_depth += 1
        body = self.statements(node.body)
        self.loop_depth -= 1
        self.emit(ops, ForOp(node.target.id, start_value, stop_value, step, body,
                            scope=self.scope(node.target.id, node),
                            stop_sentinel=sentinel), node)

    def binary_kind(self, op, node, augmented=False):
        if isinstance(op, ast.Div):
            raise self.err("true division '{}' is unsupported; use floor division '{}'"
                           .format("/=" if augmented else "/", "//=" if augmented else "//"), node)
        if type(op) not in _BINARY:
            raise self.err("unsupported {} operator: {}".format(
                "augmented" if augmented else "binary", type(op).__name__), node)
        return _BINARY[type(op)]

    def expression_region(self, node: ast.expr) -> list[Operation]:
        ops: list[Operation] = []
        value = self.expression(node, ops)
        self.emit(ops, YieldOp(value), node)
        return ops

    def expression(self, node: ast.expr, ops: list[Operation]) -> SSAValue:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, bool)):
                if node.value < 0:
                    raise self.err("negative integer literal is unsupported", node)
                return self.emit(ops, ConstOp(int(node.value) % MOD), node)
            if isinstance(node.value, str):
                raise self.err("string literals are unsupported (use ord('c'))", node)
            if isinstance(node.value, float):
                raise self.err("floating-point values are unsupported", node)
            raise self.err("unsupported constant: {!r}".format(node.value), node)
        if isinstance(node, ast.Name):
            if self.is_unbound(node.id):
                # Source definite assignment has already rejected reachable
                # unknown names. Preserve the accepted dead read explicitly,
                # so editing the IR to reach it traps instead of reading zero.
                self._check_name(node.id, node)
                return self.emit(ops, UnboundNameOp(node.id), node)
            if node.id in self.global_decls and node.id not in self.global_bindings:
                raise self.err("name {!r} is not defined".format(node.id), node)
            return self.emit(ops, LoadOp(node.id, scope=self.scope(node.id, node)), node)
        if isinstance(node, ast.BinOp):
            kind = self.binary_kind(node.op, node)
            left = self.expression(node.left, ops)
            right = self.expression(node.right, ops)
            return self.emit(ops, BinaryOp(kind, left, right), node)
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.USub):
                raise self.err("unary minus is unsupported (the value ring has no negatives)", node)
            if isinstance(node.op, ast.Invert):
                raise self.err("bitwise '~' is unsupported", node)
            kind = "not" if isinstance(node.op, ast.Not) else "pos"
            value = self.expression(node.operand, ops)
            return self.emit(ops, UnaryOp(kind, value), node)
        if isinstance(node, ast.BoolOp):
            regions = [self.expression_region(value) for value in node.values]
            return self.emit(ops, BoolOp("and" if isinstance(node.op, ast.And) else "or",
                                         regions), node)
        if isinstance(node, ast.Compare):
            for op in node.ops:
                if type(op) not in _COMPARE:
                    raise self.err("comparison operator {} is unsupported".format(type(op).__name__), node)
            regions = [self.expression_region(value) for value in [node.left, *node.comparators]]
            return self.emit(ops, CompareOp([_COMPARE[type(op)] for op in node.ops], regions), node)
        if isinstance(node, ast.IfExp):
            condition = self.expression(node.test, ops)
            return self.emit(ops, IfExprOp(condition, self.expression_region(node.body),
                                         self.expression_region(node.orelse)), node)
        if isinstance(node, ast.Call):
            return self.call(node, ops)
        if isinstance(node, ast.JoinedStr):
            raise self.err("f-strings are only supported as print() arguments", node)
        raise self.err("unsupported expression: {}".format(type(node).__name__), node)

    def is_unbound(self, name: str) -> bool:
        return (name not in self.global_names and name not in self.local_names
                and name not in self.global_decls and name not in _BUILTINS
                and name.upper() not in self._fdefs)

    def call(self, node: ast.Call, ops: list[Operation], discarded=False):
        if not isinstance(node.func, ast.Name):
            raise self.err("only direct function calls are supported", node)
        name = node.func.id
        if name.lower().startswith("zz"):
            raise self.err("function name {!r} is reserved ('zz' prefix is internal)".format(name), node)
        if name == "getchar":
            if node.args or node.keywords:
                raise self.err("getchar() takes no arguments", node)
            return self.emit(ops, GetCharOp(), node)
        if name == "ord":
            if len(node.args) != 1 or node.keywords:
                raise self.err("ord() takes exactly one argument", node)
            arg = node.args[0]
            if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                raise self.err("ord() argument must be a single-character string literal", node)
            if len(arg.value) != 1:
                raise self.err("ord() expects a single character", node)
            return self.emit(ops, ConstOp(ord(arg.value) % MOD), node)
        if name == "int":
            return self.read_int(node, ops)
        messages = {
            "input": "input() is only supported as int(input())",
            "putchar": "putchar() returns nothing and cannot be used as a value",
            "print": "print(...) returns None and cannot be used as a value",
            "chr": "chr() is unsupported; emit characters with putchar(codepoint)",
            "range": "range() is only valid in a 'for' loop header",
        }
        if name in messages:
            raise self.err(messages[name], node)
        if name not in self.functions:
            if self.is_unbound(name):
                self._check_name(name, node)
                # Resolving the callee precedes evaluation of its arguments.
                return self.emit(ops, UnboundNameOp(name), node)
            raise self.err("call to undefined function {!r}".format(name), node)
        if not discarded and self.returns[name] != "word":
            raise self.err("function {!r} may return None; its result cannot be used as an integer"
                           .format(name), node)
        params = [param.arg for param in self.functions[name].args.args]
        expressions, indices = bind_call_arguments(node, params, error=self.err)
        values = [self.expression(expr, ops) for expr in expressions]
        arguments = [None] * len(params)
        for index, value in zip(indices, values):
            arguments[index] = value
        return self.emit(ops, CallOp(name, arguments, returns=not discarded), node)

    def byte_text(self, text: str, node: ast.AST) -> str:
        for char in text:
            if ord(char) > 255:
                raise self.err("print() cannot emit character {!r} (codepoint {} > 255); "
                               "output is byte-oriented".format(char, ord(char)), node)
        return text

    def read_int(self, node: ast.Call, ops: list[Operation]):
        if len(node.args) != 1 or node.keywords:
            raise self.err("only int(input()) is supported", node)
        inp = node.args[0]
        if not (isinstance(inp, ast.Call) and isinstance(inp.func, ast.Name)
                and inp.func.id == "input"):
            raise self.err("only int(input()) is supported", node)
        if inp.keywords or len(inp.args) > 1:
            raise self.err("input() accepts at most one literal prompt", inp)
        prompt = ""
        if inp.args:
            arg = inp.args[0]
            if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                raise self.err("input() prompt must be a string literal", arg)
            prompt = self.byte_text(arg.value, arg)
        return self.emit(ops, ReadIntOp(prompt=prompt), node)

    def print_call(self, node: ast.Call, ops: list[Operation]):
        keywords = {"sep": " ", "end": "\n"}
        seen = set()
        for keyword in node.keywords:
            if keyword.arg is None:
                raise self.err("print() does not support ** keyword unpacking", node)
            if keyword.arg in seen:
                raise self.err("print() received duplicate keyword argument {!r}"
                               .format(keyword.arg), keyword.value)
            if keyword.arg not in keywords:
                raise self.err("print() only supports the 'sep' and 'end' keyword arguments, "
                               "not {!r}".format(keyword.arg), node)
            value = keyword.value
            if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
                raise self.err("print() {}= must be a constant string literal"
                               .format(keyword.arg), value)
            keywords[keyword.arg] = self.byte_text(value.value, value)
            seen.add(keyword.arg)
        parts = []
        # All argument effects precede this print's first byte; immutable SSA
        # results also capture globals before a later argument can mutate them.
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                parts.append(self.byte_text(arg.value, arg))
            else:
                parts.append(self.expression(arg, ops))
        for index, part in enumerate(parts):
            if index:
                self.emit(ops, PrintLiteralOp(keywords["sep"]), node)
            self.emit(ops, PrintLiteralOp(part) if isinstance(part, str) else PrintWordOp(part), node)
        self.emit(ops, PrintLiteralOp(keywords["end"]), node)


def compile_python_to_semantic_ir(source: str) -> ModuleOp:
    """Build verified high-level IR directly from the documented Python subset."""
    return _Frontend(source).compile()


__all__ = ["SemanticFrontendError", "compile_python_to_semantic_ir"]
