"""
py2c -- transpile a subset of Python into the "Nagoya high-level C" subset
that ``ref/nagoya-highlevel/parser`` accepts, as the front-end of the
Python -> Malbolge20 pipeline.

The target C subset is small and has several sharp edges that shape every
decision in this module (all verified experimentally against the reference
parser):

* Identifiers must match ``[a-zA-Z][0-9a-zA-Z_]*`` -- a leading underscore is
  rejected by the scanner.  Every helper/temporary we emit therefore starts
  with a letter (``zz`` prefix).
* Function names are upper-cased by the parser, so ``zzmul`` and ``ZZMUL``
  collide, ``main``/``putchar``/``getchar`` are reserved, and two Python
  functions whose names upper-case to the same string collide.
* ``true`` / ``false`` literals are broken: the internal constants ``P20`` /
  ``P21`` are pre-created with the *same numeric values* as ``FALSE_VAL`` /
  ``TRUE_VAL`` but with type ``INT``, and the constant cache is keyed by value,
  so a ``bool`` literal comes back typed ``INT`` and any assignment to a
  ``bool`` variable raises "Type mismatch".  We therefore never emit ``bool``,
  ``true`` or ``false`` and never store a comparison/logical result into a
  variable.  Booleans live as ``int`` 0/1 materialised through control flow.
* The grammar has **no operator precedence**: ``a < b && c`` parses as
  ``a < (b && c)``.  We defuse this completely by lowering every expression to
  three-address form -- each emitted statement contains at most one binary
  operator whose operands are a bare variable or an integer literal.
* There is no ``*`` / ``/`` / ``%`` operator and no ``break`` / ``continue`` /
  ``goto``.  Multiplication, floor-division and modulo are provided as helper
  functions injected on demand; loops are expressed purely through a
  recomputed ``while`` condition.
* Declarations may only be initialised with a literal, and local declarations
  must precede statements, so we declare every local/temporary up front and
  perform all initialisation with runtime assignments.

The public entry point is :func:`compile_python_to_c`.
"""

import ast

__all__ = ["compile_python_to_c", "CompileError"]

# Malbolge20 works in the ring of integers modulo 3**20.
MOD = 3 ** 20  # 3486784401

# Names the reference parser reserves (compared after upper-casing) plus the
# helpers we inject.  A user function may not upper-case to any of these.
RESERVED_FUNCS = {"MAIN", "PUTCHAR", "GETCHAR", "ZZMUL", "ZZDIV", "ZZMOD"}

# Names `_call()` special-cases at every call site, before it ever consults
# `self.functions`.  A user-defined function with one of these names could be
# registered but never successfully called, so they're reserved at
# definition time instead (see defects.md B3-B6).
BUILTIN_CALL_NAMES = {"putchar", "getchar", "ord", "chr", "print", "range"}

# C keywords / builtins in the subset; a Python variable may not be named one
# of these (they are legal Python identifiers but illegal here).
C_KEYWORDS = {
    "int", "bool", "true", "false", "if", "else", "while",
    "return", "static", "main", "putchar", "getchar",
}

# ---------------------------------------------------------------------------
# Injected helper functions (emitted only when the corresponding operator is
# actually used).  Algorithms validated exhaustively against Python semantics.
# ---------------------------------------------------------------------------

# result = a * b  (mod 3**20), binary "double-and-add": O(32) additions.
HELPER_MUL = """\
int zzmul(int a, int b){
  int result; int rem; int cnt; int p; int ash; int j;
  result = 0; rem = b; cnt = 32;
  while(cnt != 0){
    cnt = cnt - 1;
    p = 1; ash = a; j = 0;
    while(j != cnt){ p = p + p; ash = ash + ash; j = j + 1; }
    if(rem >= p){ rem = rem - p; result = result + ash; }
  }
  return result;
}
"""

# q = a // b  (floor division of non-negative integers), long division.
# Returns 0 when b == 0 so the program cannot hang on a divide-by-zero loop.
HELPER_DIV = """\
int zzdiv(int a, int b){
  int q; int rem; int bsh; int p;
  q = 0; rem = a;
  if(b != 0){
    while(b <= rem){
      bsh = b; p = 1;
      while(bsh <= (rem - bsh)){ bsh = bsh + bsh; p = p + p; }
      rem = rem - bsh; q = q + p;
    }
  }
  return q;
}
"""

# r = a % b  (remainder of non-negative integers), long division.
HELPER_MOD = """\
int zzmod(int a, int b){
  int rem; int bsh;
  rem = a;
  if(b != 0){
    while(b <= rem){
      bsh = b;
      while(bsh <= (rem - bsh)){ bsh = bsh + bsh; }
      rem = rem - bsh;
    }
  }
  return rem;
}
"""

HELPERS = {"zzmul": HELPER_MUL, "zzdiv": HELPER_DIV, "zzmod": HELPER_MOD}


class CompileError(Exception):
    """Raised for unsupported or invalid Python input.

    Carries the offending source line/column and a rendered snippet so the CLI
    can print a friendly diagnostic.
    """

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
        parts = []
        if self.lineno is not None:
            parts.append("line {}".format(self.lineno))
        head = "compile error"
        if parts:
            head += " (" + ", ".join(parts) + ")"
        out = "{}: {}".format(head, self.message)
        if self.snippet is not None:
            out += "\n    " + self.snippet.strip()
            if self.col is not None:
                caret_pad = len(self.snippet) - len(self.snippet.lstrip())
                out += "\n    " + " " * max(0, self.col - caret_pad) + "^"
        return out


def _operand(x):
    """Render a lowered value (int literal or C variable name) as C text."""
    if isinstance(x, int):
        return str(x % MOD)
    return x


class _Compiler:
    def __init__(self, source):
        self.source = source
        self.functions = {}          # python name -> ast.FunctionDef
        self.func_c_names = {}        # python name -> emitted C name
        self.used_helpers = set()     # subset of {"zzmul","zzdiv","zzmod"}
        self.global_names = []        # module-level variable names, in order
        self._global_seen = set()
        self.module_globals = set()   # names assigned anywhere at module
                                       # level (prescanned before any
                                       # function/main is compiled)

        # Per-function emission state (reset in _compile_function).
        self.buf = None               # list[str] of body lines (indented)
        self.indent = 0
        self.tmp_id = 0
        self.temps = None             # set of temp names declared this function
        self.locals = None            # set of local names for current function
        self.params = None            # set of parameter names (declared in sig)
        self.globals_in_scope = None  # names bound to module scope in this func
        self.in_main = False          # compiling the synthetic main()?
        self.bound = None             # names definitely assigned so far, in
                                       # actual compile order, in the current
                                       # function/main (definite-assignment
                                       # tracking; see _is_bound)
        self.loop_stack = []          # stack of (skip_var, break_var) pairs,
                                       # innermost loop last; entries are
                                       # (None, None) for loops that don't use
                                       # break/continue (see
                                       # _body_has_break_continue)
        self.current_skip = None      # skip-flag variable name of the
                                       # innermost loop whose body statements
                                       # are being emitted right now (None if
                                       # not inside a break/continue-bearing
                                       # loop) -- consulted by _compile_body
                                       # to guard every statement so a
                                       # break/continue can "skip" the rest
                                       # of the current iteration without a
                                       # real break/continue/goto in the
                                       # target C subset.

    # -- diagnostics --------------------------------------------------------
    def err(self, msg, node):
        return CompileError(msg, node, self.source)

    # -- low-level emission -------------------------------------------------
    def emit(self, text):
        self.buf.append("  " * self.indent + text)

    def newtmp(self):
        name = "zzt{}".format(self.tmp_id)
        self.tmp_id += 1
        self.temps.add(name)
        return name

    def use_helper(self, name):
        self.used_helpers.add(name)

    # -- name validation ----------------------------------------------------
    def check_var_name(self, name, node):
        if not name or not (name[0].isalpha() and name.isascii()):
            raise self.err(
                "identifier {!r} is not a valid C identifier".format(name), node)
        if not all(c.isalnum() or c == "_" for c in name) or not name.isascii():
            raise self.err(
                "identifier {!r} contains characters unsupported by the C "
                "backend".format(name), node)
        if name.lower().startswith("zz"):
            raise self.err(
                "identifier {!r} is reserved (names starting with 'zz' are "
                "used internally by the compiler)".format(name), node)
        if name in C_KEYWORDS:
            raise self.err(
                "identifier {!r} collides with a C keyword in the target "
                "backend".format(name), node)
        return name

    def check_func_name(self, name, node):
        self.check_var_name(name, node)
        if name in BUILTIN_CALL_NAMES:
            raise self.err(
                "function name {!r} is reserved (it is a built-in the "
                "compiler special-cases at call sites)".format(name), node)
        upper = name.upper()
        if upper in RESERVED_FUNCS:
            raise self.err(
                "function name {!r} is reserved (it upper-cases to {!r}, which "
                "the backend reserves)".format(name, upper), node)
        return name

    # -- scope classification ----------------------------------------------
    def is_global(self, name):
        """True if `name` refers to a module-level variable in current scope."""
        if self.in_main:
            return True  # every variable bound in main() is a module global
        if self.locals is not None:
            if name in self.locals:
                return False
            if self.globals_in_scope is not None and name in self.globals_in_scope:
                return True
            # read-only reference to a module global from inside a function
            return name in self._global_seen
        return True  # module level: everything is global

    def add_global(self, name):
        if name not in self._global_seen:
            self._global_seen.add(name)
            self.global_names.append(name)

    # -- definite-assignment tracking ---------------------------------------
    def _is_bound(self, name):
        """True if a read of `name` here is guaranteed to see a value.

        `self.bound` tracks names assigned so far in the *actual* compile
        order of the current function/main (params seeded up front, then
        updated as `_bind_target`/`global` statements are processed while
        `_compile_body` walks statements in source order) -- so a read is
        rejected unless something textually earlier already assigned it.

        User functions additionally accept any name assigned anywhere at
        module level (`self.module_globals`), even without a `global`
        declaration: real Python resolves a bare global read at call time,
        long after module-level code has run, and py2c has no way to reason
        about call-time ordering statically, so this is intentionally
        permissive.  The synthesized main() IS the module-level code, so it
        gets no such fallback -- reading a module global there before its
        own assignment is exactly the use-before-assignment bug we reject.
        """
        if name in self.bound:
            return True
        if not self.in_main and name in self.module_globals:
            return True
        return False

    # =======================================================================
    # Expression lowering.  Returns either an int (a folded literal, reduced
    # mod 3**20) or a str (a bare C variable name).  Any intermediate
    # computation is emitted as three-address statements.
    # =======================================================================
    def lower(self, node):
        if isinstance(node, ast.Constant):
            return self._const(node)
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                name = self.check_var_name(node.id, node)
                if not self._is_bound(name):
                    raise self.err(
                        "name {!r} is used before it is assigned".format(
                            name), node)
                return name
            raise self.err("unsupported name context", node)
        if isinstance(node, ast.BinOp):
            return self._binop(node)
        if isinstance(node, ast.UnaryOp):
            return self._unaryop(node)
        if isinstance(node, ast.BoolOp):
            return self._materialize_cond(node)
        if isinstance(node, ast.Compare):
            return self._materialize_cond(node)
        if isinstance(node, ast.Call):
            return self._call(node)
        if isinstance(node, ast.IfExp):
            return self._ifexp(node)
        raise self.err(
            "unsupported expression: {}".format(type(node).__name__), node)

    def _ifexp(self, node):
        """`a if c else b` -- materialise into a temp via real if/else so
        only the selected branch's side effects (e.g. function calls) run;
        this is lazy evaluation, unlike a plain ternary value lookup."""
        flag = self._materialize_cond(node.test)
        result = self.newtmp()
        self.emit("if({} != 0){{".format(flag))
        self.indent += 1
        self._assign_into(result, node.body)
        self.indent -= 1
        self.emit("} else {")
        self.indent += 1
        self._assign_into(result, node.orelse)
        self.indent -= 1
        self.emit("}")
        return result

    def _const(self, node):
        v = node.value
        if isinstance(v, bool):
            return 1 if v else 0
        if isinstance(v, int):
            if v < 0:
                raise self.err(
                    "negative integer literal is unsupported: the Malbolge20 "
                    "value ring has no negatives (values are mod 3**20)", node)
            return v % MOD
        if isinstance(v, str):
            raise self.err(
                "string literals are unsupported (only single characters via "
                "ord('c') are allowed)", node)
        if isinstance(v, float):
            raise self.err("floating-point values are unsupported", node)
        raise self.err(
            "unsupported constant: {!r}".format(v), node)

    def _binop(self, node):
        op = node.op
        if isinstance(op, ast.Div):
            raise self.err(
                "true division '/' is unsupported; use floor division '//' "
                "(all values are non-negative integers mod 3**20)", node)
        left = self.lower(node.left)
        right = self.lower(node.right)
        # constant folding
        if isinstance(left, int) and isinstance(right, int):
            folded = self._fold(op, left, right, node)
            if folded is not None:
                return folded
        return self._binop_emit(op, left, right, node)

    def _fold(self, op, a, b, node):
        if isinstance(op, ast.Add):
            return (a + b) % MOD
        if isinstance(op, ast.Sub):
            return (a - b) % MOD  # Python % is non-negative: matches mod ring
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

    def _binop_emit(self, op, left, right, node, dest=None):
        d = dest if dest is not None else self.newtmp()
        lo, ro = _operand(left), _operand(right)
        if isinstance(op, ast.Add):
            self.emit("{} = {} + {};".format(d, lo, ro))
        elif isinstance(op, ast.Sub):
            self.emit("{} = {} - {};".format(d, lo, ro))
        elif isinstance(op, ast.Mult):
            self.use_helper("zzmul")
            self.emit("{} = zzmul({}, {});".format(d, lo, ro))
        elif isinstance(op, ast.FloorDiv):
            self.use_helper("zzdiv")
            self.emit("{} = zzdiv({}, {});".format(d, lo, ro))
        elif isinstance(op, ast.Mod):
            self.use_helper("zzmod")
            self.emit("{} = zzmod({}, {});".format(d, lo, ro))
        else:
            raise self.err(
                "unsupported binary operator: {}".format(type(op).__name__),
                node)
        return d

    def _unaryop(self, node):
        op = node.op
        if isinstance(op, ast.USub):
            raise self.err(
                "unary minus is unsupported: the value ring has no negatives "
                "(3 - 5 wraps to a large positive value, x < 0 is always "
                "false)", node)
        if isinstance(op, ast.UAdd):
            return self.lower(node.operand)
        if isinstance(op, ast.Not):
            return self._materialize_cond(node)
        if isinstance(op, ast.Invert):
            raise self.err("bitwise '~' is unsupported", node)
        raise self.err(
            "unsupported unary operator: {}".format(type(op).__name__), node)

    def _call(self, node):
        fname = self._callee_name(node)
        if fname == "putchar":
            raise self.err(
                "putchar() returns nothing and cannot be used as a value", node)
        if fname == "getchar":
            if node.args or node.keywords:
                raise self.err("getchar() takes no arguments", node)
            d = self.newtmp()
            self.emit("{} = getchar();".format(d))
            return d
        if fname == "ord":
            return self._fold_ord(node)
        if fname == "chr":
            raise self.err(
                "chr() is unsupported; emit characters with putchar(codepoint)",
                node)
        if fname == "print":
            raise self.err(
                "print() is only supported as a top-level statement with "
                "compile-time constant arguments; it cannot be used as a "
                "value (use putchar(codepoint) to emit output)", node)
        if fname == "range":
            raise self.err("range() is only valid in a 'for' loop header", node)
        # user function
        if fname not in self.functions:
            raise self.err("call to undefined function {!r}".format(fname), node)
        if node.keywords:
            raise self.err(
                "keyword arguments are unsupported; pass arguments positionally",
                node)
        fn = self.functions[fname]
        nparams = len(fn.args.args)
        if len(node.args) != nparams:
            raise self.err(
                "{}() takes {} argument(s) but {} given".format(
                    fname, nparams, len(node.args)), node)
        args = [_operand(self.lower(a)) for a in node.args]
        d = self.newtmp()
        self.emit("{} = {}({});".format(
            d, self.func_c_names[fname], ", ".join(args)))
        return d

    def _callee_name(self, node):
        if not isinstance(node.func, ast.Name):
            raise self.err(
                "only direct function calls are supported (no methods or "
                "computed callees)", node)
        return node.func.id

    def _fold_ord(self, node):
        if len(node.args) != 1 or node.keywords:
            raise self.err("ord() takes exactly one argument", node)
        arg = node.args[0]
        if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
            raise self.err(
                "ord() argument must be a single-character string literal "
                "(evaluated at compile time)", node)
        if len(arg.value) != 1:
            raise self.err(
                "ord() expects a single character, got {!r}".format(arg.value),
                node)
        return ord(arg.value) % MOD

    # =======================================================================
    # Condition lowering.  Every boolean is materialised as an int variable
    # holding 0 or 1, computed through control flow -- never stored as a
    # comparison result (which the backend rejects).  Returns the flag var
    # name (a str).
    # =======================================================================
    def _materialize_cond(self, node):
        flag = self.newtmp()
        self._cond_into(node, flag)
        return flag

    def _cond_into(self, node, flag):
        if isinstance(node, ast.Compare):
            self._cmp_into(node, flag)
        elif isinstance(node, ast.BoolOp):
            self._boolop_into(node, flag)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            inner = self._materialize_cond(node.operand)
            self.emit("{} = 1;".format(flag))
            self.emit("if({} != 0){{".format(inner))
            self.indent += 1
            self.emit("{} = 0;".format(flag))
            self.indent -= 1
            self.emit("}")
        elif isinstance(node, ast.Constant):
            val = self._const(node)
            self.emit("{} = {};".format(flag, 1 if val else 0))
        else:
            # truthiness of an arbitrary integer expression: flag = (x != 0)
            val = _operand(self.lower(node))
            self.emit("{} = 0;".format(flag))
            self.emit("if({} != 0){{".format(val))
            self.indent += 1
            self.emit("{} = 1;".format(flag))
            self.indent -= 1
            self.emit("}")

    _CMP_OP = {
        ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=",
        ast.Eq: "==", ast.NotEq: "!=",
    }

    def _cmp_into(self, node, flag):
        for op in node.ops:
            if type(op) not in self._CMP_OP:
                raise self.err(
                    "comparison operator {} is unsupported".format(
                        type(op).__name__), node)
        # Lower every operand once (so calls with side effects run once), then
        # AND the pairwise comparisons together for chained comparisons.
        operands = [_operand(self.lower(node.left))]
        for c in node.comparators:
            operands.append(_operand(self.lower(c)))
        if len(node.ops) == 1:
            self._single_cmp_into(operands[0], node.ops[0], operands[1], flag)
            return
        # chained: a < b < c  ==>  (a<b) && (b<c)
        self.emit("{} = 0;".format(flag))
        self._chain_cmp(operands, node.ops, 0, flag)

    def _chain_cmp(self, operands, ops, i, flag):
        # emits: if(operands[i] op operands[i+1]){ <rest or flag=1> }
        self.emit("if({} {} {}){{".format(
            operands[i], self._CMP_OP[type(ops[i])], operands[i + 1]))
        self.indent += 1
        if i + 1 == len(ops):
            self.emit("{} = 1;".format(flag))
        else:
            self._chain_cmp(operands, ops, i + 1, flag)
        self.indent -= 1
        self.emit("}")

    def _single_cmp_into(self, left, op, right, flag):
        self.emit("{} = 0;".format(flag))
        self.emit("if({} {} {}){{".format(left, self._CMP_OP[type(op)], right))
        self.indent += 1
        self.emit("{} = 1;".format(flag))
        self.indent -= 1
        self.emit("}")

    def _boolop_into(self, node, flag):
        if isinstance(node.op, ast.And):
            self.emit("{} = 0;".format(flag))
            self._and_chain(node.values, 0, flag)
        else:  # Or -- short-circuit
            self.emit("{} = 0;".format(flag))
            self._or_chain(node.values, 0, flag)

    def _and_chain(self, values, i, flag):
        sub = self._materialize_cond(values[i])
        self.emit("if({} != 0){{".format(sub))
        self.indent += 1
        if i + 1 == len(values):
            self.emit("{} = 1;".format(flag))
        else:
            self._and_chain(values, i + 1, flag)
        self.indent -= 1
        self.emit("}")

    def _or_chain(self, values, i, flag):
        sub = self._materialize_cond(values[i])
        self.emit("if({} != 0){{".format(sub))
        self.indent += 1
        self.emit("{} = 1;".format(flag))
        self.indent -= 1
        if i + 1 == len(values):
            self.emit("}")
        else:
            self.emit("} else {")
            self.indent += 1
            self._or_chain(values, i + 1, flag)
            self.indent -= 1
            self.emit("}")

    # =======================================================================
    # Statement compilation.
    # =======================================================================
    def compile_stmt(self, node):
        method = getattr(self, "_stmt_" + type(node).__name__, None)
        if method is None:
            raise self.err(
                "unsupported statement: {}".format(type(node).__name__), node)
        method(node)

    def _bind_target(self, name, node):
        """Record `name` as an assignment target in the current scope."""
        self.check_var_name(name, node)
        if self.in_main or self.locals is None:
            self.add_global(name)
        elif self.globals_in_scope is not None and name in self.globals_in_scope:
            self.add_global(name)
        elif self.params is not None and name in self.params:
            pass  # already declared in the function signature
        else:
            self.locals.add(name)
        self.bound.add(name)

    def _assign_into(self, target_name, value_node):
        """Compute value_node directly into an existing variable target_name."""
        if isinstance(value_node, ast.BinOp) and not isinstance(
                value_node.op, ast.Div):
            left = self.lower(value_node.left)
            right = self.lower(value_node.right)
            if isinstance(left, int) and isinstance(right, int):
                folded = self._fold(value_node.op, left, right, value_node)
                if folded is not None:
                    self.emit("{} = {};".format(target_name, folded))
                    return
            self._binop_emit(value_node.op, left, right, value_node,
                             dest=target_name)
            return
        if isinstance(value_node, (ast.Compare, ast.BoolOp)) or (
                isinstance(value_node, ast.UnaryOp)
                and isinstance(value_node.op, ast.Not)):
            self._cond_into(value_node, target_name)
            return
        val = _operand(self.lower(value_node))
        self.emit("{} = {};".format(target_name, val))

    def _stmt_Assign(self, node):
        if len(node.targets) != 1 and any(
                not isinstance(t, ast.Name) for t in node.targets):
            raise self.err(
                "only simple name targets are supported in assignment", node)
        names = []
        for t in node.targets:
            if not isinstance(t, ast.Name):
                raise self.err(
                    "unsupported assignment target: {} (tuple/attribute/"
                    "subscript assignment is not supported)".format(
                        type(t).__name__), node)
            names.append(t.id)
        for name in names:
            self._bind_target(name, node)
        # a = b = expr : compute once into the first, copy to the rest.
        self._assign_into(names[0], node.value)
        for name in names[1:]:
            self.emit("{} = {};".format(name, names[0]))

    def _stmt_AnnAssign(self, node):
        if node.value is None:
            # bare annotation (`x: int`, no value) has no runtime effect in
            # CPython: it records the annotation but does NOT bind the name
            # (a subsequent read is a NameError). Validate the identifier
            # shape but do not bind it -- a later read falls through to the
            # normal use-before-assignment check.
            if isinstance(node.target, ast.Name):
                self.check_var_name(node.target.id, node)
            return
        if not isinstance(node.target, ast.Name):
            raise self.err("unsupported annotated assignment target", node)
        self._bind_target(node.target.id, node)
        self._assign_into(node.target.id, node.value)

    def _stmt_AugAssign(self, node):
        if not isinstance(node.target, ast.Name):
            raise self.err(
                "augmented assignment is only supported on simple names", node)
        name = node.target.id
        self.check_var_name(name, node)
        # x must already be bound: `x += 1` reads the current value of x
        # before writing the new one, so an unbound x is a use-before-
        # assignment error, not an implicit declaration.
        if not self._is_bound(name):
            raise self.err(
                "name {!r} is used before it is assigned (augmented "
                "assignment reads the current value before writing the "
                "new one)".format(name), node)
        self._bind_target(name, node)
        op = node.op
        if isinstance(op, ast.Div):
            raise self.err(
                "true division '/=' is unsupported; use floor division '//='",
                node)
        val = self.lower(node.value)
        if isinstance(op, ast.Add):
            self.emit("{} += {};".format(name, _operand(val)))
        elif isinstance(op, ast.Sub):
            self.emit("{} -= {};".format(name, _operand(val)))
        elif isinstance(op, (ast.Mult, ast.FloorDiv, ast.Mod)):
            self._binop_emit(op, name, val, node, dest=name)
        else:
            raise self.err(
                "unsupported augmented operator: {}".format(
                    type(op).__name__), node)

    def _stmt_Expr(self, node):
        value = node.value
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            if value.func.id == "putchar":
                if len(value.args) != 1 or value.keywords:
                    raise self.err("putchar() takes exactly one argument", node)
                arg = _operand(self.lower(value.args[0]))
                self.emit("putchar({});".format(arg))
                return
            if value.func.id == "print":
                self._stmt_print(node, value)
                return
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            # A bare string-literal statement is only tolerated as a
            # docstring, and only in the first statement of a module/
            # function body -- that case is stripped out before compilation
            # ever reaches _stmt_Expr (see _compile_function/compile()), so
            # any bare string Expr that gets here is *not* in docstring
            # position and is rejected exactly like any other string
            # literal.
            raise self.err(
                "string literals are unsupported (only single characters "
                "via ord('c') are allowed); a bare string literal is only "
                "accepted as a docstring, and only as the first statement "
                "of a module or function body", node)
        if isinstance(value, ast.Constant):
            # bare non-string literal: no effect (matches CPython evaluating
            # and discarding an expression statement).
            return
        # Any other expression statement: evaluate for side effects, discard.
        self.lower(value)

    # -- print() ------------------------------------------------------------
    # print() only accepts compile-time constant arguments: string literals,
    # f-strings whose every part is itself constant, and int expressions the
    # existing constant folder (_fold/_binop) can reduce to a literal. Every
    # accepted call is rendered once, at compile time, into a fixed sequence
    # of putchar() calls -- there is no runtime formatting support (that is
    # deferred to a v2 decimal print()).
    def _check_bytes_range(self, text, node):
        for ch in text:
            cp = ord(ch)
            if cp > 255:
                raise self.err(
                    "character {!r} (U+{:04X}) cannot be emitted by "
                    "putchar(), which only supports codepoints 0-255"
                    .format(ch, cp), node)

    def _print_render_arg(self, arg):
        """Render one print()/f-string part to a compile-time Python str."""
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            self._check_bytes_range(arg.value, arg)
            return arg.value
        if isinstance(arg, ast.JoinedStr):
            return self._render_fstring(arg)
        value = self.lower(arg)
        if not isinstance(value, int):
            raise self.err(
                "print() only accepts compile-time constant arguments "
                "(string literals, f-strings with constant parts, or "
                "int expressions the compiler can fold); use "
                "putchar(codepoint) for runtime values (decimal print() "
                "of runtime values is planned for a future version)", arg)
        return str(value % MOD)

    def _render_fstring(self, node):
        out = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                self._check_bytes_range(part.value, part)
                out.append(part.value)
            elif isinstance(part, ast.FormattedValue):
                if part.conversion != -1:
                    raise self.err(
                        "f-string conversion specifiers (!r/!s/!a) are "
                        "unsupported", part)
                if part.format_spec is not None:
                    raise self.err(
                        "f-string format specifiers are unsupported", part)
                out.append(self._print_render_arg(part.value))
            else:
                raise self.err(
                    "unsupported f-string part: {}".format(
                        type(part).__name__), part)
        return "".join(out)

    def _stmt_print(self, node, call):
        sep, end = " ", "\n"
        seen_kw = set()
        for kw in call.keywords:
            if kw.arg is None or kw.arg not in ("sep", "end") \
                    or kw.arg in seen_kw:
                raise self.err(
                    "print() only supports the 'sep' and 'end' keyword "
                    "arguments, each a compile-time constant string "
                    "literal", node)
            seen_kw.add(kw.arg)
            if not (isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, str)):
                raise self.err(
                    "print()'s {!r} argument must be a compile-time "
                    "constant string literal".format(kw.arg), kw.value)
            self._check_bytes_range(kw.value.value, kw.value)
            if kw.arg == "sep":
                sep = kw.value.value
            else:
                end = kw.value.value
        parts = [self._print_render_arg(a) for a in call.args]
        text = sep.join(parts) + end
        for ch in text:
            self.emit("putchar({});".format(ord(ch)))

    def _stmt_If(self, node):
        flag = self._materialize_cond(node.test)
        self.emit("if({} != 0){{".format(flag))
        self.indent += 1
        self._compile_body(node.body)
        self.indent -= 1
        if node.orelse:
            self.emit("} else {")
            self.indent += 1
            self._compile_body(node.orelse)
            self.indent -= 1
        self.emit("}")

    def _stmt_While(self, node):
        if node.orelse:
            raise self.err("while/else is unsupported", node)
        # Recompute the condition into the same flag before the loop and at the
        # end of the body (the C subset has no break/continue/goto).
        has_bc = self._body_has_break_continue(node.body)
        skip = brk = None
        if has_bc:
            skip = self.newtmp()
            brk = self.newtmp()
            self.emit("{} = 0;".format(brk))
        flag = self.newtmp()
        self._cond_into(node.test, flag)
        self.emit("while({} != 0){{".format(flag))
        self.indent += 1
        if has_bc:
            self.emit("{} = 0;".format(skip))
        self._compile_loop_body(node.body, skip, brk)
        self._cond_into(node.test, flag)
        if has_bc:
            # break forces the loop to end regardless of what the (still
            # correctly recomputed) condition says.
            self.emit("if({} != 0){{".format(brk))
            self.indent += 1
            self.emit("{} = 0;".format(flag))
            self.indent -= 1
            self.emit("}")
        self.indent -= 1
        self.emit("}")

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
                "for loops must iterate over range(...); other iterables are "
                "unsupported", node)
        if it.keywords:
            raise self.err("range() does not take keyword arguments", node)
        start, stop, step = self._range_args(it)
        var = node.target.id
        self._bind_target(var, node)
        # i = start
        self._assign_into(var, start)
        # bound = stop (evaluate once)
        bound = _operand(self.lower(stop))
        has_bc = self._body_has_break_continue(node.body)
        skip = brk = None
        if has_bc:
            skip = self.newtmp()
            brk = self.newtmp()
            self.emit("{} = 0;".format(brk))
        flag = self.newtmp()
        self._single_cmp_into(var, ast.Lt(), bound, flag)
        self.emit("while({} != 0){{".format(flag))
        self.indent += 1
        if has_bc:
            self.emit("{} = 0;".format(skip))
        self._compile_loop_body(node.body, skip, brk)
        # `continue` still advances the loop variable (it only skips the
        # rest of the body); `break` must not, so the increment is guarded
        # by the break flag alone, not the skip flag.
        if has_bc:
            self.emit("if({} == 0){{".format(brk))
            self.indent += 1
            self.emit("{} += {};".format(var, step))
            self.indent -= 1
            self.emit("}")
        else:
            self.emit("{} += {};".format(var, step))
        self._single_cmp_into(var, ast.Lt(), bound, flag)
        if has_bc:
            self.emit("if({} != 0){{".format(brk))
            self.indent += 1
            self.emit("{} = 0;".format(flag))
            self.indent -= 1
            self.emit("}")
        self.indent -= 1
        self.emit("}")

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
                    "range() step must be positive (the value ring has no "
                    "negatives, so descending ranges are unsupported)", s)
            step = s.value
        return start, stop, step

    def _stmt_Return(self, node):
        if self.in_main:
            raise self.err("'return' outside function", node)
        if node.value is None:
            self.emit("return 0;")
            return
        val = _operand(self.lower(node.value))
        self.emit("return {};".format(val))

    def _stmt_Pass(self, node):
        pass

    def _stmt_Global(self, node):
        if self.globals_in_scope is None:
            raise self.err("'global' outside function", node)
        for name in node.names:
            self.check_var_name(name, node)
            if self.params is not None and name in self.params:
                raise self.err(
                    "name {!r} is parameter and global".format(name), node)
            self.globals_in_scope.add(name)
            self.bound.add(name)

    def _stmt_Break(self, node):
        if not self.loop_stack:
            raise self.err("'break' outside loop", node)
        skip, brk = self.loop_stack[-1]
        # break both abandons the rest of this iteration (skip) and marks
        # the loop itself for termination (brk); see _stmt_While/_stmt_For.
        self.emit("{} = 1;".format(skip))
        self.emit("{} = 1;".format(brk))

    def _stmt_Continue(self, node):
        if not self.loop_stack:
            raise self.err("'continue' outside loop", node)
        skip, _brk = self.loop_stack[-1]
        self.emit("{} = 1;".format(skip))

    def _stmt_FunctionDef(self, node):
        raise self.err(
            "nested function definitions are unsupported", node)

    def _body_has_break_continue(self, stmts):
        """True if `stmts` contains a break/continue that targets *this*
        loop -- i.e. one not nested inside a deeper loop or function def
        (those own their own break/continue, or reject it themselves)."""
        found = []

        class V(ast.NodeVisitor):
            def visit_Break(self, n):
                found.append(True)

            def visit_Continue(self, n):
                found.append(True)

            def visit_While(self, n):
                pass  # a nested loop's break/continue targets it, not us

            def visit_For(self, n):
                pass

            def visit_FunctionDef(self, n):
                pass  # unreachable in practice (nested defs are rejected)

        v = V()
        for s in stmts:
            v.visit(s)
            if found:
                return True
        return bool(found)

    def _compile_loop_body(self, stmts, skip, brk):
        """Compile a while/for body under the given (skip, break) flags.

        `skip`/`brk` are None when the loop has no break/continue at all, in
        which case this is exactly the old unguarded _compile_body."""
        self.loop_stack.append((skip, brk))
        prev_skip = self.current_skip
        self.current_skip = skip
        try:
            self._compile_body(stmts)
        finally:
            self.current_skip = prev_skip
            self.loop_stack.pop()

    def _compile_body(self, stmts):
        for s in stmts:
            if self.current_skip is not None:
                # Once break/continue sets the skip flag, every later
                # statement in this iteration (at this nesting level, and
                # recursively inside any if/elif/else nested in it) must be
                # a no-op -- the target C subset has no break/continue/goto
                # to jump past them directly.
                self.emit("if({} == 0){{".format(self.current_skip))
                self.indent += 1
                self.compile_stmt(s)
                self.indent -= 1
                self.emit("}")
            else:
                self.compile_stmt(s)

    # =======================================================================
    # Top-level driver.
    # =======================================================================
    def _collect_locals(self, stmts, params, gset):
        """Names assigned anywhere in a function body (minus params/globals)."""
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
                # A bare annotation (`x: int`, no value) does not bind the
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
                pass  # don't descend into nested defs (rejected elsewhere)

        v = V()
        for s in stmts:
            v.visit(s)
        return found

    def _global_decls_in(self, stmts):
        names = set()
        for s in ast.walk(ast.Module(body=stmts, type_ignores=[])):
            if isinstance(s, ast.Global):
                names.update(s.names)
        return names

    def _compile_function(self, node, c_name, is_main):
        params = [a.arg for a in node.args.args]
        if node.args.vararg or node.args.kwarg or node.args.kwonlyargs \
                or node.args.posonlyargs or node.args.defaults \
                or node.args.kw_defaults and any(node.args.kw_defaults):
            raise self.err(
                "only simple positional parameters are supported (no *args, "
                "**kwargs, defaults or keyword-only parameters)", node)
        for p in params:
            self.check_var_name(p, node)

        self.buf = []
        self.indent = 1
        self.tmp_id = 0
        self.temps = set()
        self.in_main = is_main
        self.params = set(params)
        self.bound = set(params)
        gset = self._global_decls_in(node.body)
        self.globals_in_scope = set(gset)
        self.locals = set()
        self.loop_stack = []
        self.current_skip = None
        # Pre-seed declared locals so ordering of first-use doesn't matter.
        # In main() every assigned name is a module global, not a local.
        if not is_main:
            for name in self._collect_locals(node.body, set(params), gset):
                self.locals.add(name)

        body = node.body
        if not is_main and body and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            # Function docstring: only the literal first statement of a real
            # (user-written) function body is tolerated bare -- main()'s
            # body is a compiler-synthesized list of module-level
            # statements, not a real function body, so it never gets this
            # treatment here (the true module docstring, if any, was
            # already stripped out of it by compile() before module_body
            # was ever assembled).
            body = body[1:]
        self._compile_body(body)

        # Assemble: signature, declarations (locals + temps), body.
        decl_names = []
        for name in sorted(self.locals):
            decl_names.append(name)
        for name in sorted(self.temps, key=lambda s: int(s[3:])):
            decl_names.append(name)

        sig_params = ", ".join("int {}".format(p) for p in params)
        lines = ["int {}({}){{".format(c_name, sig_params)]
        for name in decl_names:
            lines.append("  int {};".format(name))
        lines.extend(self.buf)
        lines.append("}")

        # reset scope state
        self.locals = None
        self.params = None
        self.globals_in_scope = None
        self.in_main = False
        self.bound = None
        self.loop_stack = []
        self.current_skip = None
        return "\n".join(lines)

    def compile(self):
        try:
            tree = ast.parse(self.source)
        except SyntaxError as e:
            node = ast.Constant(value=None)
            node.lineno = e.lineno or 1
            node.col_offset = (e.offset or 1) - 1
            raise CompileError(
                "Python syntax error: {}".format(e.msg), node, self.source)

        module_body = []
        for i, stmt in enumerate(tree.body):
            if isinstance(stmt, ast.FunctionDef):
                self._register_function(stmt)
            elif i == 0 and isinstance(stmt, ast.Expr) and isinstance(
                    stmt.value, ast.Constant) and isinstance(
                    stmt.value.value, str):
                # Module docstring: only recognised as the literal first
                # statement of the file (matches CPython); a bare string
                # statement anywhere else is just a rejected string literal
                # expression (see _stmt_Expr), same as inside a function.
                continue
            elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
                raise self.err("'import' is unsupported", stmt)
            elif isinstance(stmt, ast.ClassDef):
                raise self.err("class definitions are unsupported", stmt)
            else:
                module_body.append(stmt)

        if "main" in self.functions:
            raise self.err(
                "define top-level code directly, not a main() function "
                "(the compiler generates main from module-level statements)",
                self.functions["main"])

        # Prescan module-level assignment targets so user functions can
        # freely read a module global without a `global` declaration (see
        # _is_bound); must happen before any function/main is compiled.
        self.module_globals = set(self._collect_locals(module_body, set(), set()))

        # Compile user functions.
        func_chunks = []
        for name, fn in self.functions.items():
            func_chunks.append(
                self._compile_function(fn, self.func_c_names[name], False))

        # Compile module-level code as main().
        main_fn = ast.FunctionDef(
            name="main", args=ast.arguments(
                posonlyargs=[], args=[], vararg=None, kwonlyargs=[],
                kw_defaults=[], kwarg=None, defaults=[]),
            body=module_body or [ast.Pass()], decorator_list=[], returns=None)
        ast.fix_missing_locations(main_fn)
        main_chunk = self._compile_function(main_fn, "main", True)

        # Assemble the final translation unit.
        out = []
        # Injected helpers first (only those used).
        for hname in ("zzmul", "zzdiv", "zzmod"):
            if hname in self.used_helpers:
                out.append(HELPERS[hname].rstrip())
        # Forward prototypes for every user function, so calls resolve
        # regardless of definition order (the backend rejects calls to a
        # not-yet-seen function) and mutual recursion works.
        if self.functions:
            protos = []
            for name, fn in self.functions.items():
                params = ", ".join(
                    "int {}".format(a.arg) for a in fn.args.args)
                protos.append("int {}({});".format(
                    self.func_c_names[name], params))
            out.append("\n".join(protos))
        # Global variable declarations (no initialiser: the subset only allows
        # literal initialisers, and every value is assigned at runtime inside
        # main, so functions reading a global resolve it from global scope).
        for name in self.global_names:
            out.append("int {};".format(name))
        for chunk in func_chunks:
            out.append(chunk)
        out.append(main_chunk)
        return "\n\n".join(out) + "\n"

    def _register_function(self, node):
        if node.decorator_list:
            raise self.err(
                "decorators are unsupported", node.decorator_list[0])
        name = node.name
        if name in self.functions:
            raise self.err(
                "function {!r} is already defined".format(name), node)
        self.check_func_name(name, node)
        upper = name.upper()
        for other in self.func_c_names:
            if other.upper() == upper:
                raise self.err(
                    "function {!r} collides with {!r} (function names are "
                    "case-insensitive in the target backend)".format(
                        name, other), node)
        self.functions[name] = node
        self.func_c_names[name] = name


def compile_python_to_c(source):
    """Transpile a subset of Python `source` into Nagoya high-level C.

    Returns the generated C source as a string.  Raises :class:`CompileError`
    (carrying line/column and a source snippet) for unsupported or invalid
    input.
    """
    return _Compiler(source).compile()
