"""Explicit Python-shaped target IR passed directly to the legacy MG backend.

Unlike source Python, this contract records generated local storage and a loop
condition's ordered prelude. Neither fact can be recovered safely from names or
an unparse/parse round trip. The module has no xDSL dependency and supports the
base Python 3.8 toolchain.
"""

import ast
from collections.abc import Mapping
from copy import deepcopy


class TargetASTError(ValueError):
    """Malformed target metadata or unsupported structured-loop prelude."""

    def __init__(self, message, node=None):
        self.node = node
        self.lineno = getattr(node, "lineno", None)
        self.col = getattr(node, "col_offset", None)
        super().__init__(message)


class _TargetNode:
    def __reduce__(self):
        # Python 3.13's AST reduction calls the constructor with one positional
        # None per field. Our constructors have explicit metadata arguments and
        # defaults, so reconstruct empty nodes and restore the complete state.
        # Keeping state separate also preserves shared references during copy.
        return type(self), (), self.__dict__


class TargetAST(_TargetNode, ast.Module):
    """A module with explicit generated-local names, keyed by function name."""

    def __init__(self, body=(), *, generated_locals=None, type_ignores=()):
        super().__init__(body=list(body), type_ignores=list(type_ignores))
        self.generated_locals = {} if generated_locals is None else deepcopy(generated_locals)


class TargetWhile(_TargetNode, ast.While):
    """Run condition_prelude before every test, then execute the original body."""

    _fields = ("condition_prelude", "test", "body", "orelse")
    if hasattr(ast.While, "_field_types"):
        # CPython uses this schema to initialize fields starting with 3.13.
        _field_types = dict(ast.While._field_types, condition_prelude=list[ast.stmt])

    def __init__(self, test=None, body=(), *, condition_prelude=(), orelse=()):
        super().__init__(test=test, body=list(body), orelse=list(orelse),
                         condition_prelude=list(condition_prelude))


def _function_bindings(function):
    assigned, globals_ = set(), set()

    class Bindings(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            pass

        def visit_Assign(self, node):
            for target in node.targets:
                assigned.update(part.id for part in ast.walk(target)
                                if isinstance(part, ast.Name) and isinstance(part.ctx, ast.Store))
            self.generic_visit(node)

        def visit_AnnAssign(self, node):
            if node.value is not None and isinstance(node.target, ast.Name):
                assigned.add(node.target.id)
            self.generic_visit(node)

        def visit_AugAssign(self, node):
            if isinstance(node.target, ast.Name):
                assigned.add(node.target.id)
            self.generic_visit(node)

        def visit_For(self, node):
            if isinstance(node.target, ast.Name):
                assigned.add(node.target.id)
            self.generic_visit(node)

        def visit_Global(self, node):
            globals_.update(node.names)

    visitor = Bindings()
    for statement in function.body:
        visitor.visit(statement)
    parameters = {parameter.arg for parameter in
                  (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)}
    if function.args.vararg is not None:
        parameters.add(function.args.vararg.arg)
    if function.args.kwarg is not None:
        parameters.add(function.args.kwarg.arg)
    return assigned - globals_ - parameters, globals_, parameters


def validate_target_ast(tree):
    """Validate metadata ownership; ordinary source/DA checks still run later."""
    if not isinstance(tree, TargetAST):
        raise TargetASTError("structured target compilation requires a TargetAST module", tree)
    if not isinstance(tree.generated_locals, Mapping):
        raise TargetASTError("generated_locals must map function names to local-name collections", tree)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    for function_name, names in tree.generated_locals.items():
        if not isinstance(function_name, str) or function_name not in functions:
            raise TargetASTError("generated_locals names an undefined function {!r}".format(function_name), tree)
        function = functions[function_name]
        if not isinstance(names, (set, frozenset, list, tuple)) or any(
                not isinstance(name, str) for name in names):
            raise TargetASTError("generated locals must be an explicit collection of names", function)
        locals_, globals_, parameters = _function_bindings(function)
        for name in names:
            if name in parameters:
                raise TargetASTError("parameter {!r} cannot be declared a generated local".format(name), function)
            if name in globals_:
                raise TargetASTError("global {!r} cannot be declared a generated local".format(name), function)
            if name not in locals_:
                raise TargetASTError("generated local {!r} is not assigned in function {!r}"
                                     .format(name, function_name), function)
    allowed = (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Expr, ast.If, ast.Pass)
    for node in ast.walk(tree):
        if not isinstance(node, TargetWhile):
            continue
        if not isinstance(node.condition_prelude, list):
            raise TargetASTError("condition_prelude must be a list of statements", node)
        if node.orelse:
            raise TargetASTError("while/else is unsupported", node)
        for statement in node.condition_prelude:
            if not isinstance(statement, ast.stmt):
                raise TargetASTError("condition_prelude must contain statements", node)
            for part in ast.walk(statement):
                if isinstance(part, ast.stmt) and not isinstance(part, allowed):
                    raise TargetASTError("unsupported condition prelude statement: {}"
                                         .format(type(part).__name__), part)
    return tree


def to_legacy_ast(tree):
    """Return an equivalent plain AST for validation, display, or ablation.

    This is an explicit structural conversion, never a text round trip. A loop
    prelude is placed before its guard on every iteration. The generated local
    metadata remains on the caller's TargetAST and is intentionally absent from
    this ordinary Python view.
    """
    validate_target_ast(tree)

    class Legacy(ast.NodeTransformer):
        def visit_TargetAST(self, node):
            return ast.Module(body=[self.visit(statement) for statement in node.body],
                              type_ignores=node.type_ignores)

        def visit_TargetWhile(self, node):
            node = self.generic_visit(node)
            if not node.condition_prelude:
                return ast.copy_location(ast.While(test=node.test, body=node.body,
                                                  orelse=node.orelse), node)
            guard = ast.copy_location(ast.If(
                test=ast.UnaryOp(op=ast.Not(), operand=node.test),
                body=[ast.Break()], orelse=[]), node)
            return ast.copy_location(ast.While(test=ast.Constant(value=1),
                body=node.condition_prelude + [guard] + node.body, orelse=[]), node)

    return ast.fix_missing_locations(Legacy().visit(deepcopy(tree)))


__all__ = ["TargetAST", "TargetWhile", "TargetASTError", "validate_target_ast", "to_legacy_ast"]
