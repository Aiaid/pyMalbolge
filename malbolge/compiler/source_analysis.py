"""Shared AST-only source checks for the direct and semantic frontends.

No code generation or optional IR dependencies belong here. Supports the base
Python 3.8 toolchain; TargetWhile is a dependency-free AST contract.
"""

import ast

from .target_ast import TargetWhile

MOD = 3 ** 20  # Malbolge20 value ring, 3486784401

# Reserved (uppercased) function names, mirroring py2c.
RESERVED_FUNCS = {
    "MAIN", "PUTCHAR", "GETCHAR", "ZZMUL", "ZZDIV", "ZZMOD",
    "INT", "INPUT", "ZZREADINT", "ZZPRINTINT",
}

C_KEYWORDS = {
    "int", "bool", "true", "false", "if", "else", "while",
    "return", "static", "main", "putchar", "getchar",
}

# Names intercepted by builtin call dispatch cannot name user functions.
_BUILTINS = {"putchar", "getchar", "ord", "chr", "print", "range", "int", "input"}


class Py2MgError(Exception):
    """Raised for unsupported or invalid Python input (with source location)."""

    def __init__(self, message, node=None, source=None):
        self.message = message
        self.lineno = getattr(node, "lineno", None)
        self.col = getattr(node, "col_offset", None)
        self.snippet = None
        if source is not None and self.lineno is not None:
            lines = source.splitlines()
            if 1 <= self.lineno <= len(lines):
                self.snippet = lines[self.lineno - 1]
        super().__init__(self._render())

    def _render(self):
        head = "compile error"
        if self.lineno is not None:
            head += " (line {})".format(self.lineno)
        out = "{}: {}".format(head, self.message)
        if self.snippet is not None:
            out += "\n    " + self.snippet.strip()
        return out


# Preserve the public exception's qualified name for existing callers/pickles.
Py2MgError.__module__ = "malbolge.compiler.py2mg"


class SourceAnalysis:
    """AST analysis mixin, independent of either frontend's generation state.

    Consumers provide ``err(message, node)`` and an uppercase-name ``_fdefs``
    mapping. ``_compiling_helper`` permits internal names only during helper
    compilation. Definite-assignment entry initializes its own loop-exit stack.
    This mixin deliberately has no initializer or code-generation hooks.
    """

    _compiling_helper = False

    def _check_name(self, name, node):
        if not name or not (name[0].isalpha() and name.isascii()):
            raise self.err(
                "identifier {!r} is not a valid identifier".format(name), node)
        if not all(c.isalnum() or c == "_" for c in name) or not name.isascii():
            raise self.err(
                "identifier {!r} has unsupported characters".format(name), node)
        if name.lower().startswith("zz") and not self._compiling_helper:
            raise self.err(
                "identifier {!r} is reserved ('zz' prefix is internal)".format(
                    name), node)
        if name in C_KEYWORDS or name.lower() in {"int", "input"}:
            raise self.err(
                "identifier {!r} collides with a reserved word".format(name),
                node)
        return name

    @staticmethod
    def _collect_assigned(stmts, params, gset):
        found = []
        seen = set()

        def add(name):
            if name not in seen and name not in params and name not in gset:
                seen.add(name)
                found.append(name)

        class V(ast.NodeVisitor):
            def visit_Assign(self, n):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        add(t.id)
                self.generic_visit(n)

            def visit_AnnAssign(self, n):
                # A bare annotation (`x: int` with no value) does NOT bind the
                # name in CPython -- only annotate-with-value does.
                if n.value is not None and isinstance(n.target, ast.Name):
                    add(n.target.id)
                self.generic_visit(n)

            def visit_AugAssign(self, n):
                if isinstance(n.target, ast.Name):
                    add(n.target.id)
                self.generic_visit(n)

            def visit_For(self, n):
                if isinstance(n.target, ast.Name):
                    add(n.target.id)
                self.generic_visit(n)

            def visit_FunctionDef(self, n):
                pass

        v = V()
        for s in stmts:
            v.visit(s)
        return found

    @staticmethod
    def _global_decls_in(stmts):
        names = set()
        for s in ast.walk(ast.Module(body=list(stmts), type_ignores=[])):
            if isinstance(s, ast.Global):
                names.update(s.names)
        return names

    def _check_definite_assignment(self, stmts, external, all_assigned):
        self._da_exit_stack = []
        self._da_stmts(stmts, set(), external, all_assigned)

    def _da_stmts(self, stmts, bound, external, all_assigned):
        bound = set(bound)
        for s in stmts:
            bound = self._da_stmt(s, bound, external, all_assigned)
            if self._da_terminates([s]):
                break
        return bound

    def _da_stmt(self, s, bound, external, all_assigned):
        if isinstance(s, TargetWhile):
            condition_bound = self._da_stmts(s.condition_prelude, bound, external, all_assigned)
            self._da_reads(s.test, condition_bound, external, all_assigned)
            known = self._static_bool(s.test)
            if known is False:
                return condition_bound
            exits = []
            self._da_exit_stack.append(exits)
            self._da_stmts(s.body, condition_bound, external, all_assigned)
            self._da_exit_stack.pop()
            breaks = [state for kind, state in exits if kind == "break"]
            if known is True and breaks:
                return set.intersection(*breaks)
            return condition_bound
        if isinstance(s, ast.Assign):
            for target in s.targets:
                if not isinstance(target, ast.Name):
                    raise self.err(
                        "unsupported assignment target: {} (only simple names)"
                        .format(type(target).__name__), s)
            self._da_reads(s.value, bound, external, all_assigned)
            for t in s.targets:
                if isinstance(t, ast.Name):
                    bound.add(t.id)
            return bound
        if isinstance(s, ast.AnnAssign):
            if s.value is not None:
                self._da_reads(s.value, bound, external, all_assigned)
                if isinstance(s.target, ast.Name):
                    bound.add(s.target.id)
            return bound  # bare annotation does not bind
        if isinstance(s, ast.AugAssign):
            if isinstance(s.target, ast.Name):
                self._da_name(s.target, bound, external, all_assigned)  # read
            self._da_reads(s.value, bound, external, all_assigned)
            if isinstance(s.target, ast.Name):
                bound.add(s.target.id)
            return bound
        if isinstance(s, ast.Expr):
            self._da_reads(s.value, bound, external, all_assigned)
            return bound
        if isinstance(s, ast.If):
            self._da_reads(s.test, bound, external, all_assigned)
            folded = self._static_bool(s.test)
            if folded is not None:
                return self._da_stmts(s.body if folded else s.orelse,
                                      bound, external, all_assigned)
            b1 = self._da_stmts(s.body, bound, external, all_assigned)
            b2 = self._da_stmts(s.orelse, bound, external, all_assigned)
            t1 = self._da_terminates(s.body)
            t2 = self._da_terminates(s.orelse)
            if t1 and t2:
                return bound
            if t1:
                return b2
            if t2:
                return b1
            return bound | (b1 & b2)
        if isinstance(s, ast.While):
            self._da_reads(s.test, bound, external, all_assigned)
            if self._static_bool(s.test) is False:
                return bound
            exits = []
            self._da_exit_stack.append(exits)
            self._da_stmts(s.body, bound, external, all_assigned)
            self._da_exit_stack.pop()
            breaks = [state for kind, state in exits if kind == "break"]
            if self._static_bool(s.test) is True and breaks:
                return set.intersection(*breaks)
            return bound  # the body may run zero times
        if isinstance(s, ast.For):
            if (isinstance(s.iter, ast.Call) and isinstance(s.iter.func, ast.Name)
                    and s.iter.func.id == "range"):
                start, stop, step = self._range_args(s.iter)
                first = self._signed_literal(start)
                last = self._signed_literal(stop)
                if first is not None and first < 0:
                    raise self.err("range() cannot yield negative integers", start)
                if step < 0 and last is not None and last < -1:
                    raise self.err(
                        "descending range() supports non-negative bounds or stop=-1",
                        stop)
            self._da_reads(s.iter, bound, external, all_assigned)
            body_bound = set(bound)
            if isinstance(s.target, ast.Name):
                body_bound.add(s.target.id)
            exits = []
            self._da_exit_stack.append(exits)
            end_bound = self._da_stmts(s.body, body_bound, external, all_assigned)
            self._da_exit_stack.pop()
            if self._literal_range_nonempty(s.iter):
                return set.intersection(end_bound, *(state for _, state in exits))
            return bound  # range may be empty; target not bound afterwards
        if isinstance(s, (ast.Break, ast.Continue)):
            if self._da_exit_stack:
                kind = "break" if isinstance(s, ast.Break) else "continue"
                self._da_exit_stack[-1].append((kind, set(bound)))
            return bound
        if isinstance(s, ast.Return):
            if s.value is not None:
                self._da_reads(s.value, bound, external, all_assigned)
            return bound
        return bound  # Pass / Global / (rejected elsewhere) -- no reads

    def _da_terminates(self, stmts):
        if not stmts:
            return False
        last = stmts[-1]
        if isinstance(last, (ast.Return, ast.Break, ast.Continue)):
            return True
        if isinstance(last, ast.If):
            known = self._static_bool(last.test)
            if known is not None:
                return self._da_terminates(last.body if known else last.orelse)
            if last.orelse:
                return (self._da_terminates(last.body)
                        and self._da_terminates(last.orelse))
        return False

    def _da_reads(self, expr, bound, external, all_assigned):
        if isinstance(expr, ast.Name) and isinstance(expr.ctx, ast.Load):
            self._da_name(expr, bound, external, all_assigned)
            return
        if isinstance(expr, ast.BoolOp):
            for operand in expr.values:
                self._da_reads(operand, bound, external, all_assigned)
                known = self._static_bool(operand)
                if known is not None and (
                        (isinstance(expr.op, ast.And) and not known)
                        or (isinstance(expr.op, ast.Or) and known)):
                    break
            return
        if isinstance(expr, ast.IfExp):
            self._da_reads(expr.test, bound, external, all_assigned)
            known = self._static_bool(expr.test)
            if known is not None:
                self._da_reads(expr.body if known else expr.orelse,
                               bound, external, all_assigned)
                return
        for child in ast.iter_child_nodes(expr):
            self._da_reads(child, bound, external, all_assigned)

    def _da_name(self, name_node, bound, external, all_assigned):
        name = name_node.id
        if name in bound or name in external:
            return
        if name.upper() in self._fdefs or name in _BUILTINS:
            return  # function reference / builtin used as a callee
        if name in all_assigned:
            raise self.err(
                "name {!r} may be used before assignment".format(name),
                name_node)
        raise self.err("name {!r} is not defined".format(name), name_node)

    def _static_bool(self, node):
        """Constant-fold a boolean condition to True/False, else None."""
        if isinstance(node, ast.Constant):
            v = node.value
            if isinstance(v, bool):
                return v
            if isinstance(v, int):
                return v % MOD != 0
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            value = self._static_bool(node.operand)
            return None if value is None else not value
        if isinstance(node, ast.BoolOp):
            result = None
            for operand in node.values:
                result = self._static_bool(operand)
                if result is None:
                    return None
                if isinstance(node.op, ast.And) and not result:
                    return False
                if isinstance(node.op, ast.Or) and result:
                    return True
            return result
        return None

    def _range_args(self, call):
        n = len(call.args)
        if n == 0 or n > 3:
            raise self.err("range() takes 1 to 3 arguments", call)
        if n == 1:
            return ast.Constant(value=0), call.args[0], 1
        start = call.args[0]
        stop = call.args[1]
        step = 1
        if n == 3:
            s = call.args[2]
            step = self._signed_literal(s)
            if step is None:
                raise self.err(
                    "range() step must be a nonzero integer literal", s)
            if step == 0:
                raise self.err(
                    "range() step must be nonzero", s)
        return start, stop, step

    @staticmethod
    def _signed_literal(node):
        try:
            value = ast.literal_eval(node)
        except (TypeError, ValueError, SyntaxError):
            return None
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return None

    @staticmethod
    def _literal_range_nonempty(call):
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                and call.func.id == "range" and not call.keywords):
            return False
        try:
            args = [ast.literal_eval(arg) for arg in call.args]
            if not all(isinstance(arg, int) for arg in args):
                return False
            args = [value % MOD if index < 2 and value >= 0 else value
                    for index, value in enumerate(args)]
            iterator = range(*args)
            return (iterator.start < iterator.stop if iterator.step > 0
                    else iterator.start > iterator.stop)
        except (TypeError, ValueError, SyntaxError):
            return False

    def _fold(self, op, a, b, node):
        if isinstance(op, ast.Add):
            return (a + b) % MOD
        if isinstance(op, ast.Sub):
            return (a - b) % MOD
        if isinstance(op, ast.Mult):
            return (a * b) % MOD
        if isinstance(op, ast.FloorDiv):
            if b == 0:
                raise self.err("integer division or modulo by zero", node)
            return (a // b) % MOD
        if isinstance(op, ast.Mod):
            if b == 0:
                raise self.err("integer division or modulo by zero", node)
            return (a % b) % MOD
        raise self.err(
            "unsupported binary operator: {}".format(type(op).__name__), node)

    def _fold_ord(self, node):
        if len(node.args) != 1 or node.keywords:
            raise self.err("ord() takes exactly one argument", node)
        arg = node.args[0]
        if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
            raise self.err(
                "ord() argument must be a single-character string literal",
                node)
        if len(arg.value) != 1:
            raise self.err(
                "ord() expects a single character, got {!r}".format(arg.value),
                node)
        return ord(arg.value) % MOD
