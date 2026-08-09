"""py2mg -- a *direct* Python-subset -> ``.mg`` backend.

This is an alternative front-end to the existing two-step ``py2c`` (Python ->
Nagoya C subset) + ``c2mg`` (C subset -> ``.mg``) path.  It walks the Python
AST and emits ``.mg`` pseudo-instructions directly, skipping the C layer.

Why bypass C (see ``docs/findings.md``):

* The C subset forces three-address expansion, ``bool`` avoidance and identifier
  mangling that all inflate the generated code.
* ``c2mg`` (faithful to the reference) hard-codes ``is_recursive = True`` for
  *every* function and shares one global temporary pool, so every function --
  even leaf helpers and ``main`` -- pays full push/pop stack protection, and an
  intermediate held in a temporary across two sibling recursive calls can be
  clobbered (the A2 double-recursion bug).

What this backend changes (and *only* this -- it reuses c2mg's proven codegen
primitives verbatim for arithmetic, comparison and the call ABI, so the
generated programs compute identical results):

1. **Per-function temporaries.**  Every temporary is declared as a ``VAR`` inside
   its owning ``DEF`` (mg2mc scopes local ``VAR`` names per routine, so two
   routines' temporaries never share a cell).  A non-recursive callee therefore
   cannot clobber its caller's temporaries.
2. **Real recursion analysis.**  A function is protected only when it can reach
   itself in the call graph.  Non-recursive functions (the common case, incl.
   ``main`` and the injected ``zzmul``/``zzdiv``/``zzmod`` helpers) emit *zero*
   push/pop protection.
3. **Precise cross-call protection.**  For a recursive function, entry/exit
   push/pop covers its non-static locals *and* exactly those temporaries that
   are live across a ``CALL`` -- so a naturally-nested ``fib(n-1)+fib(n-2)`` is
   correct without any three-address rewrite (the A2 bug is fixed at the
   mechanism level, not merely side-stepped).

The public entry point is :func:`compile_python_to_mg`.

Language subset (int arithmetic, ``while``, ``if``/``elif``/``else``,
``for``-``range``, chained comparison, boolean ops, functions incl. recursion,
``putchar``/``getchar``) plus batch-one syntactic sugar:

* ``print(...)`` of *compile-time constants only* -- string/int literals,
  foldable int expressions, and all-constant f-strings.  Each argument is
  rendered (ints as unsigned mod-3**20 decimal, strings verbatim), joined by
  ``sep`` and terminated by ``end`` (both constant strings), and emitted byte by
  byte.  A runtime (variable) argument is rejected with a line number pointing
  at ``putchar`` -- variable printing is a v2 feature.
* ``ord('c')`` folds a one-character string literal to its codepoint.
* Conditional expressions ``a if c else b`` materialise into a temp filled by
  whichever branch the condition selects (lazy: only the taken arm runs).
* Augmented assignment ``+= -= *= //= %=`` (``**=`` unsupported).  The
  multiply/divide/modulo helpers stay lazily injected.
* ``break``/``continue`` for the innermost ``while``/``for``-``range`` loop,
  lowered via per-loop ``BRK``/``SKP`` flag variables.  The guard that
  suppresses the rest of a body after a break/continue always SWITCHes on a
  fresh, normalised ``skip == 0`` comparison -- never on the raw flag cell --
  so the A3 self-modification trap never arises (findings.md A3).

Known v0 limitations (documented in ``docs/design/py2mg-backend.md``):

* ``and``/``or`` are evaluated non-short-circuit (both sides always run).  This
  differs from Python only when an operand has side effects; the pure-Python
  subset's boolean operands in practice are comparisons of pure values.
* ``while``/``for``-``else`` are unsupported.
"""

import ast

from . import c2mg
from .c2mg import (
    Variable, Block, Func, Generator,
    INT, BOOL, ARG,
    RETURN_VALUE, MAIN_FUNCTION,
    VAR_STACK_TOP, VAR_STACK_TOP_VAL,
)

__all__ = ["compile_python_to_mg", "Py2MgError"]

MOD = 3 ** 20  # Malbolge20 value ring, 3486784401

# Reserved (uppercased) function names, mirroring py2c.
RESERVED_FUNCS = {"MAIN", "PUTCHAR", "GETCHAR", "ZZMUL", "ZZDIV", "ZZMOD"}

C_KEYWORDS = {
    "int", "bool", "true", "false", "if", "else", "while",
    "return", "static", "main", "putchar", "getchar",
}

# Injected integer helpers, expressed in the same Python subset this backend
# compiles.  They use only +, -, comparisons, while and if, so they compile
# through the ordinary path and (being non-recursive) get no frame protection.
# Algorithms are the exact ones py2c injects as C (validated against Python
# semantics), transcribed to Python.
HELPER_SRC = {
    "ZZMUL": (
        "def zzmul(a, b):\n"
        "    result = 0\n"
        "    rem = b\n"
        "    cnt = 32\n"
        "    while cnt != 0:\n"
        "        cnt = cnt - 1\n"
        "        p = 1\n"
        "        ash = a\n"
        "        j = 0\n"
        "        while j != cnt:\n"
        "            p = p + p\n"
        "            ash = ash + ash\n"
        "            j = j + 1\n"
        "        if rem >= p:\n"
        "            rem = rem - p\n"
        "            result = result + ash\n"
        "    return result\n"
    ),
    "ZZDIV": (
        "def zzdiv(a, b):\n"
        "    q = 0\n"
        "    rem = a\n"
        "    if b != 0:\n"
        "        while b <= rem:\n"
        "            bsh = b\n"
        "            p = 1\n"
        "            while bsh <= rem - bsh:\n"
        "                bsh = bsh + bsh\n"
        "                p = p + p\n"
        "            rem = rem - bsh\n"
        "            q = q + p\n"
        "    return q\n"
    ),
    "ZZMOD": (
        "def zzmod(a, b):\n"
        "    rem = a\n"
        "    if b != 0:\n"
        "        while b <= rem:\n"
        "            bsh = b\n"
        "            while bsh <= rem - bsh:\n"
        "                bsh = bsh + bsh\n"
        "            rem = rem - bsh\n"
        "    return rem\n"
    ),
}

_OP_HELPER = {ast.Mult: "ZZMUL", ast.FloorDiv: "ZZDIV", ast.Mod: "ZZMOD"}

# Names special-cased in a Call position; a user function may not take one of
# these (its calls would be intercepted by the builtin dispatch -- py2c defect
# D13/B3-B6).  putchar/getchar are additionally caught by C_KEYWORDS.
_BUILTINS = {"putchar", "getchar", "ord", "chr", "print", "range"}


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


class _DirectCompiler(c2mg.Compiler):
    """Drives c2mg's codegen primitives from the Python AST.

    Reuses c2mg.Compiler's arithmetic/comparison/stack helpers unchanged; the
    temporary allocator and frame policy are overridden below.
    """

    def __init__(self, source):
        # Empty token list: we never use the C parser, only the codegen state
        # (constant cache pre-seed, CON0/1/2, global maps, etc.).
        super().__init__([])
        self.source = source

        # Per-function compile state.
        self._func = None            # current Func (also set during generate)
        self._is_main = False
        self._params = set()
        self._locals = set()
        self._globals_decl = set()
        self._module_globals = set()
        self._live = []              # temporaries held across a sub-lowering
        self._loops = []             # stack of enclosing loops that own flags
        self._active_loop = None     # innermost flag-owning loop (guard target)

        self._fdefs = {}             # UPPER name -> ast.FunctionDef
        self._pynames = {}           # UPPER name -> original Python name
        self._pending_helpers = []   # injected helpers awaiting compilation

    # -- diagnostics --------------------------------------------------------
    def err(self, msg, node):
        return Py2MgError(msg, node, self.source)

    # -- per-function temporaries (override c2mg's shared global pool) -------
    def get_temporary_variable(self, type=INT):
        f = self._func
        fl = f._free_temps
        if fl:
            v = fl.pop(0)
            v.is_using = True
            v.type = type
            return v
        name = "TMP" + str(f._temp_id)
        f._temp_id += 1
        v = Variable(type, name)
        v.is_temporary = True
        v.is_using = True
        f.variables[name] = v
        return v

    def release_temporary_variable(self, v):
        if not v.is_using:
            raise Py2MgError("internal: temporary released twice: " + v.name)
        v.is_using = False
        self._func._free_temps.append(v)

    # -- real recursion analysis (override c2mg's hard-coded True) ----------
    def check_recursive_call(self):
        graph = {name: set() for name in self.functions}
        for name, f in self.functions.items():
            for callee in f.callees:
                graph[name].add(callee.name)
        for name, f in self.functions.items():
            f.is_recursive = self._reaches_self(name, graph)

    @staticmethod
    def _reaches_self(start, graph):
        seen = set()
        stack = list(graph.get(start, ()))
        while stack:
            x = stack.pop()
            if x == start:
                return True
            if x in seen:
                continue
            seen.add(x)
            stack.extend(graph.get(x, ()))
        return False

    # -- value helpers ------------------------------------------------------
    def _as_var(self, val, type=INT):
        """Materialise an int literal as a constant Variable; pass Variables."""
        if isinstance(val, int):
            return self.get_const_variable(type, val % MOD)
        return val

    @staticmethod
    def _is_temp(val):
        return isinstance(val, Variable) and val.is_temporary and val.is_using

    def _release_if_temp(self, val):
        if self._is_temp(val):
            self.release_temporary_variable(val)

    def _reacquire(self, v):
        """Take ownership back of a temp that c2mg's ``_logical_and`` /
        ``_logical_or`` already released, so our own release discipline (a
        condition temp is always live when returned) stays consistent."""
        if isinstance(v, Variable) and v.is_temporary and not v.is_using:
            try:
                self._func._free_temps.remove(v)
            except ValueError:
                pass
            v.is_using = True
        return v

    def _stable_operand(self, val):
        """Hand a comparison primitive a value it may freely consume.

        c2mg's ``lt``/``eq`` release the temporaries they receive (and may reuse
        that cell as their result), so passing a shared/held temporary directly
        would corrupt it.  Literals become constants; a live temporary is copied
        into a throw-away the primitive can own; a plain variable is passed as-is
        (the primitive copies it internally)."""
        if isinstance(val, int):
            return self.get_const_variable(INT, val % MOD)
        if self._is_temp(val):
            t = self.get_temporary_variable(INT)
            self.copy(self.current_block, val, t)
            return t
        return val

    # =======================================================================
    # Expression lowering.  Returns int (folded literal) or a Variable (INT).
    # =======================================================================
    def lower(self, node):
        if isinstance(node, ast.Constant):
            return self._const(node)
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                return self._resolve_name(node)
            raise self.err("unsupported name context", node)
        if isinstance(node, ast.BinOp):
            return self._arith(node)
        if isinstance(node, ast.UnaryOp):
            return self._unary(node)
        if isinstance(node, (ast.BoolOp, ast.Compare)):
            return self._bool_as_int(node)
        if isinstance(node, ast.IfExp):
            return self._cond_expr(node)
        if isinstance(node, ast.Call):
            return self._call_value(node)
        if isinstance(node, ast.JoinedStr):
            raise self.err(
                "f-strings are only supported as print() arguments", node)
        raise self.err(
            "unsupported expression: {}".format(type(node).__name__), node)

    def _cond_expr(self, node):
        """Lower ``a if c else b`` into a temp filled by whichever branch the
        condition selects.  Only the selected branch's code runs (lazy: each
        branch is a separate SWITCH case), so side effects fire exactly like
        CPython's short-circuit conditional expression."""
        cond = self._lower_cond(node.test)
        r = self.get_temporary_variable(INT)
        # Keep cond and r live across each branch so a recursive callee inside a
        # branch protects their cells (cross-call temp tracking).
        pushed = []
        if self._is_temp(cond):
            self._live.append(cond)
            pushed.append(cond)
        self._live.append(r)
        pushed.append(r)
        saved = self.current_block
        then_blk = Block(self)
        self.current_block = then_blk
        self._store_into(self.lower(node.body), r)
        else_blk = Block(self)
        self.current_block = else_blk
        self._store_into(self.lower(node.orelse), r)
        self.current_block = saved
        for _ in pushed:
            self._live.pop()
        # SWITCH low trit: CASE0 (cond false) -> else, CASE1 (cond true) -> then.
        self.current_block.switch_(cond, else_blk, then_blk, Block(self))
        self._release_if_temp(cond)
        return r

    def _store_into(self, val, r):
        """Copy an int literal or Variable ``val`` into temp ``r``."""
        if val is r:
            return
        self.copy(self.current_block, self._as_var(val), r)
        self._release_if_temp(val)

    def _const(self, node):
        v = node.value
        if isinstance(v, bool):
            return 1 if v else 0
        if isinstance(v, int):
            if v < 0:
                raise self.err(
                    "negative integer literal is unsupported (values are mod "
                    "3**20 with no negatives)", node)
            return v % MOD
        if isinstance(v, str):
            raise self.err(
                "string literals are unsupported (use ord('c'))", node)
        if isinstance(v, float):
            raise self.err("floating-point values are unsupported", node)
        raise self.err("unsupported constant: {!r}".format(v), node)

    def _unary(self, node):
        op = node.op
        if isinstance(op, ast.USub):
            raise self.err(
                "unary minus is unsupported (the value ring has no negatives)",
                node)
        if isinstance(op, ast.UAdd):
            return self.lower(node.operand)
        if isinstance(op, ast.Not):
            return self._bool_as_int(node)
        if isinstance(op, ast.Invert):
            raise self.err("bitwise '~' is unsupported", node)
        raise self.err(
            "unsupported unary operator: {}".format(type(op).__name__), node)

    def _arith(self, node):
        op = node.op
        if isinstance(op, ast.Div):
            raise self.err(
                "true division '/' is unsupported; use floor division '//'",
                node)
        left = self.lower(node.left)
        right = self._lower_protecting(node.right, left)
        if isinstance(left, int) and isinstance(right, int):
            return self._fold(op, left, right, node)
        lv = self._as_var(left)
        rv = self._as_var(right)
        if isinstance(op, ast.Add):
            return self._add_expr(lv, rv)
        if isinstance(op, ast.Sub):
            return self._sub_expr(lv, rv)
        if type(op) in _OP_HELPER:
            f = self._ensure_helper(_OP_HELPER[type(op)])
            self._func.callees.append(f)
            return self._do_call(f, [lv, rv], node)
        raise self.err(
            "unsupported binary operator: {}".format(type(op).__name__), node)

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

    def _lower_protecting(self, node, held):
        """Lower `node` while keeping temporary `held` marked live across it."""
        push = self._is_temp(held)
        if push:
            self._live.append(held)
        try:
            return self.lower(node)
        finally:
            if push:
                self._live.pop()

    # -- calls --------------------------------------------------------------
    def _call_value(self, node):
        fname = self._callee_name(node)
        if fname == "putchar":
            raise self.err(
                "putchar() returns nothing and cannot be used as a value", node)
        if fname == "getchar":
            if node.args or node.keywords:
                raise self.err("getchar() takes no arguments", node)
            return self._getchar()
        if fname == "ord":
            return self._fold_ord(node)
        if fname == "chr":
            raise self.err(
                "chr() is unsupported; emit characters with putchar(codepoint)",
                node)
        if fname == "print":
            raise self.err(
                "print(...) returns None and cannot be used as a value", node)
        if fname == "range":
            raise self.err("range() is only valid in a 'for' loop header", node)
        upper = fname.upper()
        if upper not in self._fdefs:
            raise self.err(
                "call to undefined function {!r}".format(fname), node)
        if node.keywords:
            raise self.err("keyword arguments are unsupported", node)
        f = self.functions[upper]
        fdef = self._fdefs[upper]
        nparams = len(fdef.args.args)
        if len(node.args) != nparams:
            raise self.err(
                "{}() takes {} argument(s) but {} given".format(
                    fname, nparams, len(node.args)), node)
        self._func.callees.append(f)
        argvals = self._lower_args(node.args)
        return self._do_call(f, argvals, node)

    def _lower_args(self, arg_nodes):
        """Lower argument expressions, keeping earlier temp results live."""
        vals = []
        pushed = 0
        for an in arg_nodes:
            v = self.lower(an)
            vals.append(v)
            if self._is_temp(v):
                self._live.append(v)
                pushed += 1
        for _ in range(pushed):
            self._live.pop()
        return vals

    def _do_call(self, f, argvals, node):
        block = self.current_block
        for i, av in enumerate(argvals):
            self.copy(block, self._as_var(av),
                      Variable(INT, ARG(i) + "@" + f.name))
        # Record temporaries live across this call so the (recursive) function
        # protects exactly them.
        held = [v for v in self._live if self._is_temp(v)]
        self._func._cross_call_temps.update(held)
        block.call(f)
        for av in argvals:
            self._release_if_temp(av)
        ret = Variable(INT, RETURN_VALUE + "@" + f.name)
        t = self.get_temporary_variable(INT)
        self.copy(block, ret, t)
        return t

    def _callee_name(self, node):
        if not isinstance(node.func, ast.Name):
            raise self.err(
                "only direct function calls are supported", node)
        return node.func.id

    def _getchar(self):
        block = self.current_block
        ret_val = self.get_temporary_variable(INT)
        z = self.get_temporary_variable(INT)
        (block.rot(self.CON1).opr(z).opr(z).opr(ret_val).opr(ret_val)
              .input().opr(z).opr(ret_val))
        self.release_temporary_variable(z)
        return ret_val

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

    # =======================================================================
    # Boolean lowering.
    #   _lower_cond(node)  -> a BOOL temporary suitable for SWITCH.
    #   _bool_as_int(node) -> an INT temporary holding 0 or 1 (value context).
    # =======================================================================
    def _lower_cond(self, node):
        if isinstance(node, ast.Compare):
            return self._compare_cond(node)
        if isinstance(node, ast.BoolOp):
            return self._boolop_cond(node)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return self.not_(self.current_block, self._lower_cond(node.operand))
        if isinstance(node, ast.Constant):
            zero = self.get_const_variable(INT, 0)
            true_b = self.eq(self.current_block, zero, zero)  # always true
            if self._const(node):
                return true_b
            return self.not_(self.current_block, true_b)
        # truthiness of an integer expression: (x != 0)
        v = self._as_var(self.lower(node))
        return self.not_(
            self.current_block,
            self.eq(self.current_block, v, self.get_const_variable(INT, 0)))

    def _compare_cond(self, node):
        for op in node.ops:
            if type(op) not in _CMP:
                raise self.err(
                    "comparison operator {} is unsupported".format(
                        type(op).__name__), node)
        # Lower every operand once (calls with side effects run once), keeping
        # earlier temp operands live across later lowering.
        vals = []
        pushed = 0
        first = self.lower(node.left)
        vals.append(first)
        if self._is_temp(first):
            self._live.append(first)
            pushed += 1
        for c in node.comparators:
            v = self.lower(c)
            vals.append(v)
            if self._is_temp(v):
                self._live.append(v)
                pushed += 1
        for _ in range(pushed):
            self._live.pop()
        res = None
        for i, op in enumerate(node.ops):
            b = self._single_cmp(vals[i], op, vals[i + 1])
            if res is None:
                res = b
            else:
                res = self._reacquire(self._logical_and(res, b))
        for v in vals:
            self._release_if_temp(v)
        return res

    def _single_cmp(self, lval, op, rval):
        cb = self.current_block
        lv = self._stable_operand(lval)
        rv = self._stable_operand(rval)
        if isinstance(op, ast.Lt):
            return self.lt(cb, lv, rv, False)
        if isinstance(op, ast.LtE):
            return self.lt(cb, lv, rv, True)
        if isinstance(op, ast.Gt):
            return self.lt(cb, rv, lv, False)
        if isinstance(op, ast.GtE):
            return self.lt(cb, rv, lv, True)
        if isinstance(op, ast.Eq):
            return self.eq(cb, lv, rv)
        if isinstance(op, ast.NotEq):
            return self.not_(cb, self.eq(cb, lv, rv))
        raise Py2MgError("unsupported comparison")

    def _boolop_cond(self, node):
        res = None
        for v in node.values:
            protect = res is not None and self._is_temp(res)
            if protect:
                self._live.append(res)
            b = self._lower_cond(v)
            if protect:
                self._live.pop()
            if res is None:
                res = b
            elif isinstance(node.op, ast.And):
                res = self._reacquire(self._logical_and(res, b))
            else:
                res = self._reacquire(self._logical_or(res, b))
        return res

    def _bool_as_int(self, node):
        b = self._lower_cond(node)
        r = self.get_temporary_variable(INT)
        case0 = Block(self)
        self.copy(case0, self.get_const_variable(INT, 0), r)
        case1 = Block(self)
        self.copy(case1, self.get_const_variable(INT, 1), r)
        self.current_block.switch_(b, case0, case1, Block(self))
        self._release_if_temp(b)
        return r

    # =======================================================================
    # Statement compilation.
    # =======================================================================
    def _compile_body(self, stmts):
        for s in stmts:
            self._stmt(s)

    def _stmt(self, node):
        method = getattr(self, "_stmt_" + type(node).__name__, None)
        if method is None:
            raise self.err(
                "unsupported statement: {}".format(type(node).__name__), node)
        method(node)

    def _compile_into_block(self, stmts):
        blk = Block(self)
        saved = self.current_block
        self.current_block = blk
        self._compile_body(stmts)
        self.current_block = saved
        return blk

    # -- name binding / resolution ------------------------------------------
    def _check_name(self, name, node):
        if not name or not (name[0].isalpha() and name.isascii()):
            raise self.err(
                "identifier {!r} is not a valid identifier".format(name), node)
        if not all(c.isalnum() or c == "_" for c in name) or not name.isascii():
            raise self.err(
                "identifier {!r} has unsupported characters".format(name), node)
        if name.lower().startswith("zz"):
            raise self.err(
                "identifier {!r} is reserved ('zz' prefix is internal)".format(
                    name), node)
        if name in C_KEYWORDS:
            raise self.err(
                "identifier {!r} collides with a reserved word".format(name),
                node)
        return name

    def _resolve_name(self, node):
        name = self._check_name(node.id, node)
        mangled = "u_" + name
        if self._is_main:
            v = self.global_variables.get(mangled)
            if v is None:
                raise self.err("name {!r} is not defined".format(name), node)
            return v
        if name in self._params or name in self._locals:
            return self._func.variables[mangled]
        if name in self._globals_decl or name in self._module_globals:
            v = self.global_variables.get(mangled)
            if v is None:
                raise self.err("name {!r} is not defined".format(name), node)
            return v
        raise self.err("name {!r} is not defined".format(name), node)

    def _target_var(self, name, node):
        """Resolve (creating a module global if needed) an assignment target."""
        self._check_name(name, node)
        mangled = "u_" + name
        if self._is_main or name in self._globals_decl:
            v = self.global_variables.get(mangled)
            if v is None:
                v = Variable(INT, mangled)
                self.global_variables[mangled] = v
            return v
        if name in self._params or name in self._locals:
            return self._func.variables[mangled]
        if name in self._module_globals:
            return self.global_variables["u_" + name]
        # first assignment to a fresh local
        v = self._func.variables.get(mangled)
        if v is None:
            v = Variable(INT, mangled)
            self._func.variables[mangled] = v
            self._locals.add(name)
        return v

    def _store(self, val, z):
        if isinstance(val, int):
            self.copy(self.current_block, self.get_const_variable(INT, val), z)
            return
        if val is z:
            return
        self.copy(self.current_block, val, z)
        self._release_if_temp(val)

    def _stmt_Assign(self, node):
        names = []
        for t in node.targets:
            if not isinstance(t, ast.Name):
                raise self.err(
                    "unsupported assignment target: {} (only simple names)"
                    .format(type(t).__name__), node)
            names.append(t.id)
        zs = [self._target_var(n, node) for n in names]
        val = self.lower(node.value)
        self._store(val, zs[0])
        for z in zs[1:]:
            if z is not zs[0]:
                self.copy(self.current_block, zs[0], z)

    def _stmt_AnnAssign(self, node):
        if not isinstance(node.target, ast.Name):
            raise self.err("unsupported annotated assignment target", node)
        z = self._target_var(node.target.id, node)
        if node.value is None:
            return
        self._store(self.lower(node.value), z)

    def _stmt_AugAssign(self, node):
        if not isinstance(node.target, ast.Name):
            raise self.err(
                "augmented assignment is only supported on simple names", node)
        z = self._target_var(node.target.id, node)
        op = node.op
        if isinstance(op, ast.Div):
            raise self.err(
                "true division '/=' is unsupported; use '//='", node)
        val = self.lower(node.value)
        if isinstance(op, ast.Add):
            self.add(self.current_block, z, self._as_var(val))
            self._release_if_temp(val)
        elif isinstance(op, ast.Sub):
            self.sub(self.current_block, z, self._as_var(val))
            self._release_if_temp(val)
        elif type(op) in _OP_HELPER:
            f = self._ensure_helper(_OP_HELPER[type(op)])
            self._func.callees.append(f)
            t = self._do_call(f, [z, self._as_var(val)], node)
            self.copy(self.current_block, t, z)
            self.release_temporary_variable(t)
        else:
            raise self.err(
                "unsupported augmented operator: {}".format(
                    type(op).__name__), node)

    def _stmt_Expr(self, node):
        value = node.value
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) \
                and value.func.id == "putchar":
            if len(value.args) != 1 or value.keywords:
                raise self.err("putchar() takes exactly one argument", node)
            arg = self._as_var(self.lower(value.args[0]))
            (self.current_block.rot(self.CON2).opr(arg)
                 .rot(self.CON2).opr(arg).output())
            return
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) \
                and value.func.id == "print":
            self._emit_print(value, node)
            return
        if isinstance(value, ast.Constant):
            return  # bare literal / docstring
        result = self.lower(value)
        self._release_if_temp(result)

    # -- print() and f-strings (compile-time constant rendering) ------------
    def _putbyte(self, cp):
        """Emit a single output byte for codepoint ``cp`` (assumed 0..255)."""
        argv = self.get_const_variable(INT, cp)
        (self.current_block.rot(self.CON2).opr(argv)
             .rot(self.CON2).opr(argv).output())

    def _emit_print(self, call, node):
        sep = " "
        end = "\n"
        for kw in call.keywords:
            if kw.arg == "sep":
                sep = self._const_str_kwarg(kw, "sep")
            elif kw.arg == "end":
                end = self._const_str_kwarg(kw, "end")
            elif kw.arg is None:
                raise self.err(
                    "print() does not support ** keyword unpacking", node)
            else:
                raise self.err(
                    "print() only supports the 'sep' and 'end' keyword "
                    "arguments, not {!r}".format(kw.arg), node)
        parts = [self._render_print_arg(a) for a in call.args]
        text = sep.join(parts) + end
        for ch in text:
            cp = ord(ch)
            if cp > 255:
                raise self.err(
                    "print() cannot emit character {!r} (codepoint {} > 255); "
                    "output is byte-oriented".format(ch, cp), node)
            self._putbyte(cp)

    def _const_str_kwarg(self, kw, name):
        v = kw.value
        if isinstance(v, ast.Constant) and isinstance(v.value, str):
            return v.value
        raise self.err(
            "print() {}= must be a constant string literal".format(name),
            kw.value)

    def _render_print_arg(self, node):
        """Render a print() argument to the text it contributes.  Only
        compile-time constants are accepted; a runtime value is rejected with
        a line number (variable printing is a v2 feature)."""
        if isinstance(node, ast.JoinedStr):
            return self._render_fstring(node)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        folded = self._fold_int_const(node)
        if folded is None:
            raise self.err(
                "print() only accepts compile-time constants (string/int "
                "literals, foldable int expressions, all-constant f-strings); "
                "use putchar(codepoint) for runtime values -- variable "
                "printing is a v2 feature", node)
        return str(folded)

    def _render_fstring(self, node):
        out = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                out.append(part.value)
            elif isinstance(part, ast.FormattedValue):
                if part.conversion is not None and part.conversion != -1:
                    raise self.err(
                        "f-string conversions (!s/!r/!a) are unsupported", node)
                if part.format_spec is not None:
                    raise self.err(
                        "f-string format specifiers (:...) are unsupported",
                        node)
                out.append(self._render_print_arg(part.value))
            else:
                raise self.err("unsupported f-string component", node)
        return "".join(out)

    def _fold_int_const(self, node):
        """Purely constant-fold ``node`` to an int in ``[0, MOD)`` or return
        None if it is not a compile-time integer constant.  Emits no code."""
        if isinstance(node, ast.Constant):
            v = node.value
            if isinstance(v, bool):
                return 1 if v else 0
            if isinstance(v, int):
                if v < 0:
                    raise self.err(
                        "negative integer literal is unsupported (values are "
                        "mod 3**20 with no negatives)", node)
                return v % MOD
            return None
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.UAdd):
                return self._fold_int_const(node.operand)
            if isinstance(node.op, ast.USub):
                raise self.err(
                    "unary minus is unsupported (the value ring has no "
                    "negatives)", node)
            return None
        if isinstance(node, ast.BinOp):
            left = self._fold_int_const(node.left)
            right = self._fold_int_const(node.right)
            if left is None or right is None:
                return None
            return self._fold(node.op, left, right, node)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "ord":
            return self._fold_ord(node)
        return None

    def _stmt_If(self, node):
        folded = self._static_bool(node.test)
        if folded is True:
            self._compile_seq_inline(node.body)
            return
        if folded is False:
            self._compile_seq_inline(node.orelse)
            return
        cond = self._lower_cond(node.test)
        then_block = self._compile_stmt_block(node.body)
        else_block = self._compile_stmt_block(node.orelse)
        # SWITCH on the low trit: CASE0 (false) -> else, CASE1 (true) -> then.
        self.current_block.switch_(cond, else_block, then_block, Block(self))
        self._release_if_temp(cond)

    # -- statement-sequence compilation with break/continue guarding --------
    def _compile_seq_inline(self, stmts):
        """Compile a sequence into the *current* block, honouring break/continue
        guarding when inside a flag-owning loop."""
        if self._active_loop is not None:
            self._compile_loop_seq(stmts)
        else:
            self._compile_body(stmts)

    def _compile_stmt_block(self, stmts):
        """Compile a nested sequence into a fresh Block (guard-aware)."""
        blk = Block(self)
        saved = self.current_block
        self.current_block = blk
        self._compile_seq_inline(stmts)
        self.current_block = saved
        return blk

    def _compile_loop_seq(self, stmts):
        """Compile a loop-body sequence: once a statement that may set the
        current loop's break/continue flag is emitted, wrap every following
        sibling in ``if not skip`` so their side effects are suppressed after a
        break/continue.  The guard SWITCHes on a *fresh, normalised* ``skip==0``
        comparison, never on the raw flag cell -- so the A3 self-modification
        trap (SWITCH on an OPR-written cell inside a loop) never arises."""
        n = len(stmts)
        for i, s in enumerate(stmts):
            self._stmt(s)
            if i + 1 < n and self._contains_loop_control(s):
                rest = stmts[i + 1:]
                skip = self._active_loop["skip"]
                guard = self._flag_is_zero(skip)   # BOOL: skip == 0
                rest_block = self._compile_loop_body(rest)
                # CASE0 (skip != 0) -> drop rest; CASE1 (skip == 0) -> run rest.
                self.current_block.switch_(
                    guard, Block(self), rest_block, Block(self))
                self._release_if_temp(guard)
                return

    def _compile_loop_body(self, stmts):
        blk = Block(self)
        saved = self.current_block
        self.current_block = blk
        self._compile_loop_seq(stmts)
        self.current_block = saved
        return blk

    def _contains_loop_control(self, node):
        """True if ``node`` can ``break``/``continue`` the *enclosing* loop --
        i.e. it holds a Break/Continue not buried inside a nested loop or def."""
        if isinstance(node, (ast.For, ast.While, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            return False
        if isinstance(node, (ast.Break, ast.Continue)):
            return True
        for child in ast.iter_child_nodes(node):
            if self._contains_loop_control(child):
                return True
        return False

    def _loop_has_control(self, body):
        return any(self._contains_loop_control(s) for s in body)

    # -- loop control flag helpers ------------------------------------------
    def _new_loop_flags(self):
        """Allocate a matched ``BRK<n>``/``SKP<n>`` flag pair for one loop."""
        f = self._func
        n = f._flag_id
        f._flag_id += 1
        brk = Variable(INT, "BRK" + str(n))
        skip = Variable(INT, "SKP" + str(n))
        f.variables[brk.name] = brk
        f.variables[skip.name] = skip
        return brk, skip

    def _set_flag(self, block, var, val):
        self.copy(block, self.get_const_variable(INT, val), var)

    def _flag_is_zero(self, var):
        """A fresh, SWITCH-normalised BOOL that is true iff ``var == 0``."""
        return self.eq(self.current_block, var,
                       self.get_const_variable(INT, 0))

    def _emit_break_check(self, block, brk):
        """After a loop body, break out of the REPEAT when ``brk != 0``."""
        guard = self.eq(block, brk, self.get_const_variable(INT, 0))
        # CASE0 (brk != 0) -> BREAK the loop; CASE1 (brk == 0) -> keep looping.
        block.switch_(guard, Block(self).break_(), Block(self), Block(self))
        self._release_if_temp(guard)

    def _stmt_While(self, node):
        if node.orelse:
            raise self.err("while/else is unsupported", node)
        folded = self._static_bool(node.test)
        if folded is False:
            return
        if not self._loop_has_control(node.body):
            prev = self._active_loop
            self._active_loop = None
            try:
                if folded is True:
                    body = self._compile_into_block(node.body)
                    self.current_block.repeat_inf(body)
                    return
                inner = Block(self)
                saved = self.current_block
                self.current_block = inner
                cond = self._lower_cond(node.test)
                body = self._compile_into_block(node.body)
                inner.switch_(cond, Block(self).break_(), body, Block(self))
                self._release_if_temp(cond)
                self.current_block = saved
                self.current_block.repeat_inf(inner)
            finally:
                self._active_loop = prev
            return
        # break/continue present: lower via per-loop flags.
        brk, skip = self._new_loop_flags()
        self._set_flag(self.current_block, brk, 0)
        loop = {"brk": brk, "skip": skip}
        prev = self._active_loop
        self._loops.append(loop)
        self._active_loop = loop
        try:
            inner = Block(self)
            saved = self.current_block
            self.current_block = inner
            self._set_flag(inner, skip, 0)       # top of each iteration
            if folded is True:
                self._compile_loop_seq(node.body)
            else:
                cond = self._lower_cond(node.test)
                body = self._compile_loop_body(node.body)
                inner.switch_(cond, Block(self).break_(), body, Block(self))
                self._release_if_temp(cond)
            self._emit_break_check(inner, brk)
            self.current_block = saved
            self.current_block.repeat_inf(inner)
        finally:
            self._loops.pop()
            self._active_loop = prev

    def _stmt_For(self, node):
        if node.orelse:
            raise self.err("for/else is unsupported", node)
        if not isinstance(node.target, ast.Name):
            raise self.err(
                "for loops must iterate a single variable over range(...)",
                node)
        it = node.iter
        if not (isinstance(it, ast.Call) and isinstance(it.func, ast.Name)
                and it.func.id == "range"):
            raise self.err(
                "for loops must iterate over range(...)", node)
        if it.keywords:
            raise self.err("range() does not take keyword arguments", node)
        start, stop, step = self._range_args(it)
        var = self._target_var(node.target.id, node)
        self._store(self.lower(start), var)
        bound = self._as_var(self.lower(stop))
        stepc = self.get_const_variable(INT, step % MOD)
        if not self._loop_has_control(node.body):
            prev = self._active_loop
            self._active_loop = None
            try:
                inner = Block(self)
                saved = self.current_block
                self.current_block = inner
                cond = self.lt(inner, var, bound, False)     # var < bound
                body = self._compile_into_block(node.body)
                self.add(body, var, stepc)
                inner.switch_(cond, Block(self).break_(), body, Block(self))
                self._release_if_temp(cond)
                self.current_block = saved
                self.current_block.repeat_inf(inner)
                self._release_if_temp(bound)
            finally:
                self._active_loop = prev
            return
        # break/continue present: lower via per-loop flags.  The range step is
        # appended after the (guarded) body, outside the guard, so ``continue``
        # still advances the loop variable.
        brk, skip = self._new_loop_flags()
        self._set_flag(self.current_block, brk, 0)
        loop = {"brk": brk, "skip": skip}
        prev = self._active_loop
        self._loops.append(loop)
        self._active_loop = loop
        try:
            inner = Block(self)
            saved = self.current_block
            self.current_block = inner
            self._set_flag(inner, skip, 0)       # top of each iteration
            cond = self.lt(inner, var, bound, False)     # var < bound
            body = self._compile_loop_body(node.body)
            self.add(body, var, stepc)
            inner.switch_(cond, Block(self).break_(), body, Block(self))
            self._release_if_temp(cond)
            self._emit_break_check(inner, brk)
            self.current_block = saved
            self.current_block.repeat_inf(inner)
            self._release_if_temp(bound)
        finally:
            self._loops.pop()
            self._active_loop = prev

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
            if not (isinstance(s, ast.Constant) and isinstance(s.value, int)
                    and not isinstance(s.value, bool)):
                raise self.err(
                    "range() step must be a positive integer literal", s)
            if s.value <= 0:
                raise self.err(
                    "range() step must be positive (no descending ranges)", s)
            step = s.value
        return start, stop, step

    def _stmt_Return(self, node):
        if self._is_main:
            raise self.err("'return' outside function", node)
        if node.value is None:
            val = 0
        else:
            val = self.lower(node.value)
        self.copy(self.current_block, self._as_var(val),
                  Variable(INT, RETURN_VALUE))
        self._release_if_temp(val)
        self.current_block.func_return(self._func)

    def _stmt_Pass(self, node):
        pass

    def _stmt_Global(self, node):
        if self._is_main:
            raise self.err("'global' outside function", node)
        for name in node.names:
            self._check_name(name, node)
            self._globals_decl.add(name)

    def _stmt_Break(self, node):
        if not self._loops:
            raise self.err("'break' outside loop", node)
        loop = self._loops[-1]
        # Break sets both flags: skip suppresses the rest of the body this
        # iteration; brk makes the post-body check exit the REPEAT.
        self._set_flag(self.current_block, loop["brk"], 1)
        self._set_flag(self.current_block, loop["skip"], 1)

    def _stmt_Continue(self, node):
        if not self._loops:
            raise self.err("'continue' outside loop", node)
        loop = self._loops[-1]
        # Continue only suppresses the rest of the body; the loop keeps running
        # (and, for for-range, the step still fires -- it is emitted outside the
        # guard).
        self._set_flag(self.current_block, loop["skip"], 1)

    def _stmt_FunctionDef(self, node):
        raise self.err("nested function definitions are unsupported", node)

    def _static_bool(self, node):
        """Constant-fold a boolean condition to True/False, else None."""
        if isinstance(node, ast.Constant):
            v = node.value
            if isinstance(v, bool):
                return v
            if isinstance(v, int):
                return v != 0
        return None

    # =======================================================================
    # Scope pre-scan (mirrors py2c's collectors).
    # =======================================================================
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

    # -- definite-assignment analysis (rejects use-before-assignment) -------
    # A simple flow-sensitive pass mirroring CPython's rule: a name read must be
    # bound on *every* path reaching the read.  Fixes py2c defects D6-D9 (reads
    # of never-/conditionally-/annotation-only-bound names, uninitialised
    # augmented assignment) with an accurate original-source line number.
    def _check_definite_assignment(self, stmts, external, all_assigned):
        self._da_stmts(stmts, set(), external, all_assigned)

    def _da_stmts(self, stmts, bound, external, all_assigned):
        bound = set(bound)
        for s in stmts:
            bound = self._da_stmt(s, bound, external, all_assigned)
        return bound

    def _da_stmt(self, s, bound, external, all_assigned):
        if isinstance(s, ast.Assign):
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
            self._da_stmts(s.body, bound, external, all_assigned)
            return bound  # the body may run zero times
        if isinstance(s, ast.For):
            self._da_reads(s.iter, bound, external, all_assigned)
            body_bound = set(bound)
            if isinstance(s.target, ast.Name):
                body_bound.add(s.target.id)
            self._da_stmts(s.body, body_bound, external, all_assigned)
            return bound  # range may be empty; target not bound afterwards
        if isinstance(s, ast.Return):
            if s.value is not None:
                self._da_reads(s.value, bound, external, all_assigned)
            return bound
        return bound  # Pass / Global / (rejected elsewhere) -- no reads

    @staticmethod
    def _da_terminates(stmts):
        if not stmts:
            return False
        last = stmts[-1]
        if isinstance(last, (ast.Return, ast.Break, ast.Continue)):
            return True
        if isinstance(last, ast.If) and last.orelse:
            return (_DirectCompiler._da_terminates(last.body)
                    and _DirectCompiler._da_terminates(last.orelse))
        return False

    def _da_reads(self, expr, bound, external, all_assigned):
        for n in ast.walk(expr):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                self._da_name(n, bound, external, all_assigned)

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

    @staticmethod
    def _global_decls_in(stmts):
        names = set()
        for s in ast.walk(ast.Module(body=list(stmts), type_ignores=[])):
            if isinstance(s, ast.Global):
                names.update(s.names)
        return names

    # =======================================================================
    # Per-function compilation.
    # =======================================================================
    def _new_func(self, upper):
        f = Func(self, INT, upper)
        f._temp_id = 0
        f._flag_id = 0
        f._free_temps = []
        f._cross_call_temps = set()
        self.functions[upper] = f
        return f

    def _compile_user_function(self, upper):
        fdef = self._fdefs[upper]
        f = self.functions[upper]
        args = fdef.args.args
        if fdef.args.vararg or fdef.args.kwarg or fdef.args.kwonlyargs \
                or fdef.args.posonlyargs or fdef.args.defaults \
                or (fdef.args.kw_defaults and any(fdef.args.kw_defaults)):
            raise self.err(
                "only simple positional parameters are supported", fdef)
        params = [a.arg for a in args]
        for p in params:
            self._check_name(p, fdef)

        self._func = f
        self._is_main = False
        self._params = set(params)
        self._globals_decl = self._global_decls_in(fdef.body)
        # `global x` naming a parameter is a SyntaxError in CPython.
        clash = self._params & self._globals_decl
        if clash:
            raise self.err(
                "name {!r} is parameter and global".format(sorted(clash)[0]),
                fdef)
        self._locals = set(self._collect_assigned(
            fdef.body, self._params, self._globals_decl))
        self._live = []
        self._loops = []
        self._active_loop = None

        # Reject use-before-assignment before emitting anything.
        external = self._params | self._globals_decl | self._module_globals
        self._check_definite_assignment(fdef.body, external, self._locals)

        for p in params:
            f.variables["u_" + p] = Variable(INT, "u_" + p)
        for name in self._locals:
            f.variables.setdefault("u_" + name, Variable(INT, "u_" + name))

        f.block = Block(self)
        self.current_block = f.block

        # Zero-init non-static locals at entry (each activation starts fresh;
        # required for recursion correctness).
        for key in sorted(f.variables):
            v = f.variables[key]
            if not v.is_static and not v.is_temporary:
                self.copy(self.current_block, self.get_const_variable(INT, 0), v)
        # ARGi -> parameter local.
        for i, p in enumerate(params):
            argname = ARG(i)
            v1 = Variable(INT, argname)
            v1.is_static = True
            f.variables[argname] = v1
            self.copy(self.current_block, v1, f.variables["u_" + p])
        rv = Variable(INT, RETURN_VALUE)
        rv.is_static = True
        f.variables[RETURN_VALUE] = rv

        self._compile_body(fdef.body)

        if not (fdef.body and isinstance(fdef.body[-1], ast.Return)):
            # implicit `return 0`
            self.copy(self.current_block, self.get_const_variable(INT, 0),
                      Variable(INT, RETURN_VALUE))
            self.current_block.func_return(f)

    def _compile_main(self, module_body):
        f = self._new_func(MAIN_FUNCTION)
        self._func = f
        self._is_main = True
        self._params = set()
        self._globals_decl = set()
        self._locals = set()
        self._live = []
        self._loops = []
        self._active_loop = None
        # In main, module-level names are its own sequential locals -- reading
        # one before its first assignment is a NameError in CPython.
        self._check_definite_assignment(module_body, set(), self._module_globals)
        f.block = Block(self)
        self.current_block = f.block
        self._compile_body(module_body)

    # =======================================================================
    # Generation.
    # =======================================================================
    def _generate_function(self, f, g):
        self._func = f
        init_block = Block(self)
        f.finalize_block = Block(self)
        if f.is_recursive:
            protected = []
            for key in sorted(f.variables):
                v = f.variables[key]
                if not v.is_static and not v.is_temporary:
                    protected.append(v)
            for v in sorted(f._cross_call_temps, key=lambda x: x.name):
                protected.append(v)
            # Fresh scratch names for the push/pop machinery, so they can never
            # alias a protected cell.
            f._free_temps = []
            for v in protected:
                self.push_stack(init_block, v)
            for v in reversed(protected):
                self.pop_stack(f.finalize_block, v)

        g.routine(f.name).indent()
        for key in sorted(f.variables):
            v = f.variables[key]
            g.var(v.name, v.init_val)
        init_block.generate(g)
        if f.block is not None:
            f.block.generate(g)
        g.outdent()
        g.end()

    def _generate_program(self):
        # Generate routine bodies first so temporaries, constants and flags they
        # create during generation are captured by the header emission below
        # (mirrors c2mg.parse_program).
        gg = Generator()
        for name in sorted(self.functions):
            self._generate_function(self.functions[name], gg)

        g = Generator()
        for name in sorted(self.global_variables):
            v = self.global_variables[name]
            g.var(v.name, v.init_val)
        for flag in self.flags:
            g.flag(flag)
        for name in sorted(self.functions):
            g.proto(name)
        return g.text() + gg.text()

    # =======================================================================
    # Driver.
    # =======================================================================
    def compile(self):
        try:
            tree = ast.parse(self.source)
        except SyntaxError as e:
            node = ast.Constant(value=None)
            node.lineno = e.lineno or 1
            node.col_offset = (e.offset or 1) - 1
            raise Py2MgError(
                "Python syntax error: {}".format(e.msg), node, self.source)

        module_body = []
        for stmt in tree.body:
            if isinstance(stmt, ast.FunctionDef):
                self._register_function(stmt)
            elif isinstance(stmt, ast.Expr) and isinstance(
                    stmt.value, ast.Constant) and isinstance(
                    stmt.value.value, str):
                continue  # module docstring
            elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
                raise self.err("'import' is unsupported", stmt)
            elif isinstance(stmt, ast.ClassDef):
                raise self.err("class definitions are unsupported", stmt)
            else:
                module_body.append(stmt)

        if "MAIN" in self._fdefs:
            raise self.err(
                "define top-level code directly, not a main() function",
                self._fdefs["MAIN"])

        # stack pointer global.
        self.stack_top = Variable(INT, VAR_STACK_TOP)
        self.global_variables[VAR_STACK_TOP] = self.stack_top
        self.stack_top.init_val = VAR_STACK_TOP_VAL

        # module-level globals.
        self._module_globals = set(self._collect_assigned(module_body, set(),
                                                          set()))
        for name in self._module_globals:
            self.global_variables.setdefault("u_" + name,
                                             Variable(INT, "u_" + name))

        # Compile user functions, then main; either may lazily inject
        # arithmetic helpers (only when a runtime *, // or % is actually
        # emitted -- a constant-folded one injects nothing).  Then drain the
        # pending helper worklist.
        for upper in sorted(self._fdefs):
            self._compile_user_function(upper)
        self._compile_main(module_body)
        while self._pending_helpers:
            self._compile_user_function(self._pending_helpers.pop())

        self.check_recursive_call()
        return self._generate_program()

    def _register_function(self, node):
        if node.decorator_list:
            raise self.err(
                "function decorators are unsupported", node)
        name = self._check_name(node.name, node)
        if name in _BUILTINS:
            raise self.err(
                "function name {!r} collides with a builtin; calls to it would "
                "be intercepted (rename the function)".format(name), node)
        upper = name.upper()
        if upper in RESERVED_FUNCS or upper in ("MAIN",):
            if upper != "MAIN":
                raise self.err(
                    "function name {!r} is reserved".format(name), node)
        if upper in self._fdefs:
            raise self.err(
                "function {!r} collides with {!r} (names are case-insensitive "
                "in the backend)".format(name, self._pynames.get(upper, name)),
                node)
        self._fdefs[upper] = node
        self._pynames[upper] = name
        self._new_func(upper)

    def _ensure_helper(self, upper):
        """Register an arithmetic helper (ZZMUL/ZZDIV/ZZMOD) on first real use.

        Injecting lazily -- only when a runtime multiply/divide/modulo is
        actually emitted -- means a constant-folded ``9 * 7`` pulls in nothing,
        matching the C backend (whose folded operators never reference a
        helper)."""
        if upper not in self._fdefs:
            hdef = ast.parse(HELPER_SRC[upper]).body[0]
            self._fdefs[upper] = hdef
            self._pynames[upper] = hdef.name
            self._new_func(upper)
            self._pending_helpers.append(upper)
        return self.functions[upper]


def compile_python_to_mg(source):
    """Compile a subset of Python `source` directly to ``.mg`` text.

    Returns the generated ``.mg`` string.  Raises :class:`Py2MgError` (carrying
    a source line and snippet) for unsupported or invalid input.
    """
    return _DirectCompiler(source).compile()


_CMP = {ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq}
