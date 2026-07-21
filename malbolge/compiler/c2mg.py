"""c2mg -- port of ``ref/nagoya-highlevel`` (the "Nagoya high-level" flex/bison
C-subset compiler) into pure Python, emitting ``.mg`` pseudo-instruction text
for the Malbolge20 toolchain.

This is a *bug-for-bug faithful* transliteration of the C++ reference
(``parser.yy`` + ``Variable/Array/Ident/Instruction/Block/Func/Generator``).
It reproduces the reference's quirks exactly rather than fixing them.  The
sharp edges that shape this layer (all verified against the compiled reference
binary ``ref/nagoya-highlevel/parser``):

* **Identifier mangling is ``"u_" + name`` (lowercase).**  Function names are
  additionally upper-cased (``upper_ident``), so ``main`` -> ``MAIN``.

* **``std::map`` iteration order is ascending lexicographic key order.**  Every
  global-variable ``VAR`` line, ``PROTO`` line and ``DEF..END`` routine is
  emitted in sorted-by-name order; a function's own locals are pushed in
  forward-sorted order and popped in reverse-sorted order.  ``flags`` keep
  insertion order.

* **``CON0`` / ``CON1`` / ``CON2`` are never declared as ``VAR``** -- they are
  bare references the downstream ``.mg`` -> ``.mc`` stage materialises.

* **Every function is treated as recursive.**  ``check_recursive_call`` computes
  real reachability and then throws it away, hard-coding ``is_recursive=True``
  for every function, so all non-static/non-temporary locals get push/pop stack
  protection and every ``CALL`` site is wrapped with a ``RETURN_ADDR`` push/pop.

* **The shared global temporary pool causes the recursion-corruption bug.**
  ``get_temporary_variable`` always inserts into the *global* variable map (one
  shared FIFO free-list), and the push/pop protection explicitly *excludes*
  temporaries -- so an intermediate result held in a temp across two sibling
  recursive calls can be clobbered.  ``fib(4)`` comes out wrong; that is a sign
  of fidelity, not a bug here.

* **``bool`` storage is effectively broken.**  Constants are cached by *value*
  (``CONST_<n>``) ignoring type, and ``P20``/``P21``/``P12`` pre-seed the cache
  with ``INT``-typed entries whose values collide with ``FALSE_VAL``/
  ``TRUE_VAL``.  A ``bool`` local's mandatory entry-init ``copy`` pulls the
  ``INT``-typed ``CONST_0`` and raises "Type mismatch".  (This is why the sister
  ``py2c`` front-end never emits ``bool``/``true``/``false``.)

* **Operator precedence is *standard*.**  Despite a superficially ambiguous
  ``expression: expression OP expression`` grammar, the Bison precedence
  declarations resolve every conflict the usual way: ``!`` / ``++`` / ``--``
  tightest, then ``+ -``, then ``< > <= >=``, then ``== !=``, then ``&&``, then
  ``||``, then assignment (right-assoc, lowest).  So ``a < b && c`` parses as
  ``(a < b) && c``.  (An earlier investigation claimed "no precedence"; that was
  an artifact of the pervasive bool/const Type-mismatch bug muddying every
  bool-typed probe.  Confirmed against ``parser.output`` states 116/119/125 and
  the live binary.)

* **Assembly order:** global ``VAR`` lines (sorted) -> ``FLAG`` lines (insertion
  order) -> ``PROTO`` lines (sorted) come first; then all ``DEF..END`` routines
  (sorted).  Routine bodies are *generated first* internally so that temporaries
  and constants created during generation are captured in the global ``VAR``
  list.

Public entry point: :func:`compile_c_to_mg`.
"""

__all__ = ["compile_c_to_mg", "C2MgError"]

# --- constants (from define.h) ---------------------------------------------
TRUE_VAL = 3486784399
FALSE_VAL = 3486784398
VAR_STACK_TOP = "STACK_TOP"
VAR_STACK_TOP_VAL = 3486784381
MAIN_FUNCTION = "MAIN"
PUTCHAR_FUNCTION = "PUTCHAR"
GETCHAR_FUNCTION = "GETCHAR"
RETURN_ADDR = "RETURN_ADDR"
RETURN_VALUE = "RETURN_VALUE"
VAR_UNINITIALIZED = 4000000000
MOD1 = 3486784401  # 3**20

INT = "INT"
BOOL = "BOOL"


def ARG(i):
    return "ARG" + str(i)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class C2MgError(Exception):
    """Raised for invalid input to the C-subset compiler.

    Carries the (best-effort) source line and offending token, and renders a
    message shaped like the reference parser's stderr.
    """

    def __init__(self, message, lineno=None, token=None):
        self.message = message
        self.lineno = lineno
        self.token = token
        super().__init__(self._render())

    def _render(self):
        parts = [self.message]
        if self.lineno is not None:
            parts.append("Line：{}".format(self.lineno))
        if self.token is not None:
            parts.append("Token：{}".format(self.token))
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Data classes (Variable / Array / Ident)
# ---------------------------------------------------------------------------
class Variable:
    __slots__ = ("type", "name", "init_val",
                 "is_temporary", "is_using", "is_static")

    def __init__(self, type, name, init_val=0):
        self.type = type
        self.name = name
        self.init_val = init_val
        self.is_temporary = False
        self.is_using = False
        self.is_static = False


class Array:
    __slots__ = ("type", "name", "array_top_addr", "array_size")

    def __init__(self, type, name, array_size):
        self.type = type
        self.name = name
        self.array_top_addr = None
        self.array_size = array_size


class Ident:
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name

    def to_string(self):
        return "u_" + self.name


# ---------------------------------------------------------------------------
# Instruction (INS_TYPE tagged record)
# ---------------------------------------------------------------------------
class Instruction:
    __slots__ = ("type", "var", "flag", "function", "repeat_count",
                 "block", "if_block", "else_block", "case0", "case1", "case2")

    def __init__(self, type):
        self.type = type
        self.var = None
        self.flag = None
        self.function = None
        self.repeat_count = None
        self.block = None
        self.if_block = None
        self.else_block = None
        self.case0 = None
        self.case1 = None
        self.case2 = None

    @staticmethod
    def ROT(v):
        i = Instruction("ROT"); i.var = v; return i

    @staticmethod
    def OPR(v):
        i = Instruction("OPR"); i.var = v; return i

    @staticmethod
    def IND_OPR(v):
        i = Instruction("IND_OPR"); i.var = v; return i

    @staticmethod
    def SET(flag):
        i = Instruction("SET"); i.flag = flag; return i

    @staticmethod
    def RESET(flag):
        i = Instruction("RESET"); i.flag = flag; return i

    @staticmethod
    def REPEAT(n, block):
        i = Instruction("REPEAT"); i.repeat_count = n; i.block = block; return i

    @staticmethod
    def IF(flag, if_block, else_block):
        i = Instruction("IF"); i.flag = flag
        i.if_block = if_block; i.else_block = else_block; return i

    @staticmethod
    def SWITCH(v, case0, case1, case2):
        i = Instruction("SWITCH"); i.var = v
        i.case0 = case0; i.case1 = case1; i.case2 = case2; return i

    @staticmethod
    def CALL(f):
        i = Instruction("CALL"); i.function = f; return i

    @staticmethod
    def INPUT():
        return Instruction("INPUT")

    @staticmethod
    def OUTPUT():
        return Instruction("OUTPUT")

    @staticmethod
    def RETURN(f):
        i = Instruction("RETURN"); i.function = f; return i

    @staticmethod
    def BREAK():
        return Instruction("BREAK")


# ---------------------------------------------------------------------------
# Generator (text emitter, mirrors Generator.cc)
# ---------------------------------------------------------------------------
class Generator:
    def __init__(self):
        self.code = []
        self.tab_count = 0

    def _line(self, s):
        self.code.append(s + "\n")

    def add_spaces(self):
        self.code.append(" " * (2 * self.tab_count))
        return self

    def var(self, name, init_val):
        self.add_spaces()
        self._line("VAR " + name + "=" + str(init_val))
        return self

    def flag(self, name):
        self._line("FLAG " + name + " = FALSE")
        return self

    def proto(self, name):
        self.add_spaces()
        self._line("PROTO " + name)
        return self

    def routine(self, name):
        self.add_spaces()
        self._line("DEF " + name)
        return self

    def end(self):
        self.add_spaces()
        self._line("END")
        return self

    def rot(self, v):
        self.add_spaces()
        self._line("ROT " + (v.name if isinstance(v, Variable) else v))
        return self

    def opr(self, v):
        self.add_spaces()
        self._line("OPR " + (v.name if isinstance(v, Variable) else v))
        return self

    def ind_opr(self, v):
        self.add_spaces()
        self._line("IND_OPR " + (v.name if isinstance(v, Variable) else v))
        return self

    def set(self, name):
        self.add_spaces()
        self._line("SET " + name)
        return self

    def reset(self, name):
        self.add_spaces()
        self._line("RESET " + name)
        return self

    def repeat(self, n):
        self.add_spaces()
        self._line("REPEAT " + n)
        return self

    def if_(self, name):
        self.add_spaces()
        self._line("IF " + name)
        return self

    def else_(self):
        self.add_spaces()
        self._line("ELSE")
        return self

    def switch_(self, v):
        self.add_spaces()
        self._line("SWITCH " + (v.name if isinstance(v, Variable) else v))
        return self

    def case0(self):
        self.add_spaces()
        self._line("CASE0")
        return self

    def case1(self):
        self.add_spaces()
        self._line("CASE1")
        return self

    def case2(self):
        self.add_spaces()
        self._line("CASE2")
        return self

    def call(self, f):
        self.add_spaces()
        self._line("CALL " + (f.name if isinstance(f, Func) else f))
        return self

    def indent(self):
        self.tab_count += 1
        return self

    def outdent(self):
        self.tab_count -= 1
        return self

    def input(self):
        self.add_spaces()
        self._line("INPUT")
        return self

    def output(self):
        self.add_spaces()
        self._line("OUTPUT")
        return self

    def break_(self):
        self.add_spaces()
        self._line("BREAK")
        return self

    def func_return(self):
        self.add_spaces()
        self._line("RETURN")
        return self

    def text(self):
        return "".join(self.code)


# ---------------------------------------------------------------------------
# Block (instruction container + code generation)
# ---------------------------------------------------------------------------
class Block:
    def __init__(self, ctx):
        self.ctx = ctx
        self.instructions = []

    def add_instruction(self, inst):
        self.instructions.append(inst)
        return self

    def rot(self, v):
        return self.add_instruction(Instruction.ROT(v))

    def opr(self, v):
        return self.add_instruction(Instruction.OPR(v))

    def set(self, flag):
        return self.add_instruction(Instruction.SET(flag))

    def reset(self, flag):
        return self.add_instruction(Instruction.RESET(flag))

    def ind_opr(self, v):
        return self.add_instruction(Instruction.IND_OPR(v))

    def call(self, f):
        return self.add_instruction(Instruction.CALL(f))

    def repeat(self, n, block):
        return self.add_instruction(Instruction.REPEAT(str(n), block))

    def repeat_inf(self, block):
        return self.add_instruction(Instruction.REPEAT("INF", block))

    def if_(self, flag, if_block, else_block):
        return self.add_instruction(Instruction.IF(flag, if_block, else_block))

    def switch_(self, var, case0, case1, case2):
        return self.add_instruction(Instruction.SWITCH(var, case0, case1, case2))

    def input(self):
        return self.add_instruction(Instruction.INPUT())

    def output(self):
        return self.add_instruction(Instruction.OUTPUT())

    def break_(self):
        return self.add_instruction(Instruction.BREAK())

    def func_return(self, f):
        return self.add_instruction(Instruction.RETURN(f))

    def reset_to_con0(self, v):
        return self.reset_to_con1(v).opr(v)

    def reset_to_con1(self, v):
        return self.rot(self.ctx.CON1).opr(v).opr(v)

    def reset_to_con2(self, v):
        return self.reset_to_con1(v).rot(self.ctx.CON2).opr(v)

    def generate(self, g):
        ctx = self.ctx
        for inst in self.instructions:
            t = inst.type
            if t == "ROT":
                g.rot(inst.var)
            elif t == "OPR":
                g.opr(inst.var)
            elif t == "IND_OPR":
                g.ind_opr(inst.var)
            elif t == "SET":
                g.set(inst.flag)
            elif t == "RESET":
                g.reset(inst.flag)
            elif t == "REPEAT":
                g.repeat(inst.repeat_count).indent()
                inst.block.generate(g)
                g.outdent().end()
            elif t == "RETURN":
                inst.function.finalize_block.generate(g)
                g.func_return()
            elif t == "INPUT":
                g.input()
            elif t == "OUTPUT":
                g.output()
            elif t == "BREAK":
                g.break_()
            elif t == "IF":
                g.if_(inst.flag).indent()
                inst.if_block.generate(g)
                g.outdent().else_().indent()
                inst.else_block.generate(g)
                g.outdent().end()
            elif t == "SWITCH":
                g.switch_(inst.var).indent().case0().indent()
                inst.case0.generate(g)
                g.outdent().case1().indent()
                inst.case1.generate(g)
                g.outdent().case2().indent()
                inst.case2.generate(g)
                g.outdent().outdent().end()
            elif t == "CALL":
                f = inst.function
                v = Variable(INT, RETURN_ADDR + "@" + f.name)
                if f.is_recursive:
                    b = Block(ctx)
                    ctx.push_stack(b, v)
                    b.generate(g)
                g.call(f)
                if f.is_recursive:
                    b = Block(ctx)
                    ctx.pop_stack(b, v)
                    b.generate(g)


# ---------------------------------------------------------------------------
# Func
# ---------------------------------------------------------------------------
class Func:
    def __init__(self, ctx, return_type, name):
        self.ctx = ctx
        self.name = name
        self.return_type = return_type
        self.variables = {}   # name -> Variable
        self.arrays = {}      # name -> Array
        self.args = []        # list of (type, mangled_name)
        self.block = None
        self.finalize_block = Block(ctx)
        self.callees = []
        self.is_recursive = False
        self.is_implemented = False

    def generate(self, g):
        ctx = self.ctx
        g.routine(self.name).indent()
        initialize_block = Block(ctx)

        # array allocation (forward sorted)
        for key in sorted(self.arrays):
            v = self.arrays[key]
            ctx.push_stack(initialize_block, v.array_top_addr)
            ctx.move_stack_top(initialize_block, v.array_size)
            ctx.copy(initialize_block, ctx.stack_top, v.array_top_addr)

        # PUSH (forward sorted): emit VAR line + push protection
        for key in sorted(self.variables):
            v = self.variables[key]
            g.var(v.name, v.init_val)
            if self.is_recursive and not v.is_static and not v.is_temporary:
                ctx.push_stack(initialize_block, v)

        # POP prep (reverse sorted)
        for key in sorted(self.variables, reverse=True):
            v = self.variables[key]
            if self.is_recursive and not v.is_static and not v.is_temporary:
                ctx.pop_stack(self.finalize_block, v)

        # array free prep (reverse sorted)
        for key in sorted(self.arrays, reverse=True):
            v = self.arrays[key]
            ctx.move_stack_top(self.finalize_block, (-1) * v.array_size)
            ctx.pop_stack(self.finalize_block, v.array_top_addr)

        initialize_block.generate(g)
        if self.block is not None:
            self.block.generate(g)
        g.outdent()
        g.end()


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------
KEYWORDS = {
    "int": "INT", "bool": "BOOL", "true": "TRUE", "false": "FALSE",
    "if": "IF", "else": "ELSE", "static": "STATIC", "return": "RETURN",
    "while": "WHILE",
}

TWO_CHAR = {
    "++": "INC", "--": "DEC", "&&": "AND", "||": "OR", "==": "EQ",
    "!=": "NEQ", "<=": "LTE", ">=": "GTE", "+=": "PLUS_ASSIGN",
    "-=": "MINUS_ASSIGN",
}

ONE_CHAR = {
    "=": "ASSIGN", ";": "SEMICORON", ",": "COMMA", "(": "LPAREN",
    ")": "RPAREN", "{": "LBRACE", "}": "RBRACE", "[": "LBRACKET",
    "]": "RBRACKET", "+": "PLUS", "-": "MINUS", "<": "LT", ">": "GT",
    "!": "NOT",
}


class Token:
    __slots__ = ("kind", "value", "lineno")

    def __init__(self, kind, value, lineno):
        self.kind = kind
        self.value = value
        self.lineno = lineno

    def text(self):
        if self.kind == "NUMBER":
            return str(self.value)
        if self.kind == "IDENT":
            return self.value
        if self.kind == "EOF":
            return ""
        return self.value if isinstance(self.value, str) else str(self.value)


def tokenize(src):
    """Mirror scanner.ll (flex maximal-munch, rule order).

    Returns (tokens, warnings).  Unmatched characters produce a warning and are
    skipped (non-fatal), exactly like the reference's catch-all rule.
    """
    tokens = []
    warnings = []
    i = 0
    n = len(src)
    lineno = 1
    while i < n:
        c = src[i]
        # whitespace [ \t\n]
        if c in " \t\n":
            if c == "\n":
                lineno += 1
            i += 1
            continue
        # comments
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            # //[^\n]*  -- skip to end of line
            j = i + 2
            while j < n and src[j] != "\n":
                j += 1
            i = j
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            # \/\*.*\*\/  -- greedy, does NOT cross newline: match to the LAST
            # "*/" on the current line.
            eol = src.find("\n", i)
            line_end = eol if eol != -1 else n
            close = src.rfind("*/", i + 2, line_end)
            if close != -1:
                i = close + 2
                continue
            # unclosed on this line: '/' falls through to catch-all
            warnings.append("cannot handle such characters: " + c)
            i += 1
            continue
        # identifier / keyword (longest run, then keyword check)
        if c.isalpha():
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] == "_"):
                # only ASCII letters/digits/underscore per [0-9a-zA-Z_]
                ch = src[j]
                if ch == "_" or ("0" <= ch <= "9") or ("a" <= ch <= "z") or ("A" <= ch <= "Z"):
                    j += 1
                else:
                    break
            word = src[i:j]
            i = j
            if word in KEYWORDS:
                tokens.append(Token(KEYWORDS[word], word, lineno))
            else:
                tokens.append(Token("IDENT", word, lineno))
            continue
        # number [0-9]|[1-9][0-9]*
        if "0" <= c <= "9":
            if c == "0":
                tokens.append(Token("NUMBER", 0, lineno))
                i += 1
            else:
                j = i + 1
                while j < n and "0" <= src[j] <= "9":
                    j += 1
                tokens.append(Token("NUMBER", int(src[i:j]), lineno))
                i = j
            continue
        # char literal '.'  (quote, one non-newline char, quote)
        if c == "'" and i + 2 < n and src[i + 1] != "\n" and src[i + 2] == "'":
            tokens.append(Token("NUMBER", ord(src[i + 1]), lineno))
            i += 3
            continue
        # two-char operators
        if i + 1 < n:
            pair = src[i:i + 2]
            if pair in TWO_CHAR:
                tokens.append(Token(TWO_CHAR[pair], pair, lineno))
                i += 2
                continue
        # one-char operators / punctuation
        if c in ONE_CHAR:
            tokens.append(Token(ONE_CHAR[c], c, lineno))
            i += 1
            continue
        # catch-all
        warnings.append("cannot handle such characters: " + c)
        i += 1
    tokens.append(Token("EOF", "", lineno))
    return tokens, warnings


# ---------------------------------------------------------------------------
# The compiler / parser (holds all "global" state from parser.yy's %code)
# ---------------------------------------------------------------------------
class Compiler:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

        self.functions = {}          # name -> Func
        self.global_variables = {}   # name -> Variable
        self.global_arrays = {}      # name -> Array
        self.flags = []              # list of flag names (insertion order)

        self.blocks = []
        self.current_block = None

        self.CON0 = Variable(INT, "CON0")
        self.CON1 = Variable(INT, "CON1")
        self.CON2 = Variable(INT, "CON2")

        self.current_func = None
        self.decl_type = None
        self.decl_static = False
        self.variable_collection = self.global_variables
        self.array_collection = self.global_arrays

        self.stack_top_init_val = VAR_STACK_TOP_VAL

        self.temporary_variable_id = 0
        self.free_temporary_variables = []  # FIFO free-list

        self.stack_top = None

        # pre-seed the constant cache (order matters: these fix CONST_* types
        # to INT for the rest of the compile).
        self.P20 = self.get_const_variable(INT, 3486784398)
        self.P21 = self.get_const_variable(INT, 3486784399)
        self.P12 = self.get_const_variable(INT, 1743392201)

    # -- token stream helpers ------------------------------------------------
    def peek(self, k=0):
        idx = self.pos + k
        if idx >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[idx]

    def cur(self):
        return self.tokens[self.pos]

    def advance(self):
        tok = self.tokens[self.pos]
        if self.pos < len(self.tokens) - 1:
            self.pos += 1
        return tok

    def at(self, kind):
        return self.cur().kind == kind

    def expect(self, kind):
        tok = self.cur()
        if tok.kind != kind:
            self.syntax_error("syntax error")
        return self.advance()

    def syntax_error(self, msg):
        tok = self.cur()
        raise C2MgError(msg, lineno=tok.lineno, token=tok.text())

    def throw_syntax_error(self, msg):
        # semantic error thrown from an action; report at the current token.
        tok = self.cur()
        raise C2MgError(msg, lineno=tok.lineno, token=tok.text())

    # -- block stack ---------------------------------------------------------
    def Block(self):
        return Block(self)

    def add_block(self):
        self.current_block = Block(self)
        self.blocks.append(self.current_block)

    def pop_block(self):
        self.blocks.pop()
        if not self.blocks:
            self.current_block = None
        else:
            self.current_block = self.blocks[-1]

    # -- temporaries ---------------------------------------------------------
    def get_temporary_variable(self, type):
        ftv = self.free_temporary_variables
        if len(ftv) > 0:
            v = ftv.pop(0)
            v.is_using = True
            v.type = type
            return v
        name = "TEMP" + str(self.temporary_variable_id)
        self.temporary_variable_id += 1
        v = Variable(type, name)
        v.is_temporary = True
        v.is_using = True
        self.global_variables[name] = v
        return v

    def release_temporary_variable(self, v):
        if not v.is_using:
            self.throw_syntax_error(
                "Temporary variable '" + v.name + "' is already released.")
        v.is_using = False
        self.free_temporary_variables.append(v)

    # -- recursion analysis (result discarded; always True) ------------------
    def mark_callee(self, f, checked):
        for callee in f.callees:
            if not checked.get(callee, False):
                checked[callee] = True
                self.mark_callee(callee, checked)

    def check_recursive_call(self):
        for name in sorted(self.functions):
            f = self.functions[name]
            checked = {}
            for name2 in self.functions:
                checked[self.functions[name2]] = False
            self.mark_callee(f, checked)
            f.is_recursive = True  # hard-coded, real result discarded

    # -- constants -----------------------------------------------------------
    def get_const_variable(self, type, num):
        if num >= 0:
            name = "CONST_" + str(num)
        else:
            name = "CONST_minus_" + str(-num)
        if name not in self.global_variables:
            v = Variable(type, name)
            v.init_val = num if num >= 0 else MOD1 + num
            self.global_variables[name] = v
        return self.global_variables[name]

    def get_flags(self, n):
        size = len(self.flags)
        if n > size:
            for k in range(size, n):
                self.flags.append("TEMP_FLAG" + str(k))
        return self.flags

    # -- type checks ---------------------------------------------------------
    def checkBool(self, v):
        if v.type != BOOL:
            self.throw_syntax_error("Only bool expression can be used.")

    def checkInt(self, v):
        if v.type != INT:
            self.throw_syntax_error("Only int expression can be used.")

    def checkBool_array(self, arr):
        if arr.type != BOOL:
            self.throw_syntax_error("Only bool expression can be used.")

    def checkInt_array(self, arr):
        if arr.type != INT:
            self.throw_syntax_error("Only int expression can be used.")

    # -- symbol lookup -------------------------------------------------------
    def search_variable_from_collection(self, collection, name):
        if name in collection:
            return collection[name]
        elif collection is not self.global_variables:
            return self.search_variable_from_collection(self.global_variables, name)
        else:
            self.throw_syntax_error("'" + name + "' is not defined.")

    def search_array_from_collection(self, collection, name):
        if name in collection:
            return collection[name]
        elif collection is not self.global_arrays:
            return self.search_array_from_collection(self.global_arrays, name)
        else:
            self.throw_syntax_error("'" + name + "' is not defined.")

    def get_variable(self, name):
        return self.search_variable_from_collection(self.variable_collection, name)

    def get_array(self, name):
        return self.search_array_from_collection(self.array_collection, name)

    # -- codegen helpers (transliterated from parser.yy) ---------------------
    def copy(self, block, x, y):
        if x.type != y.type:
            self.throw_syntax_error("Type mismatch")
        z = self.get_temporary_variable(INT)
        (block.rot(self.CON1).opr(z).opr(z).opr(y).opr(y).rot(self.CON2)
              .opr(x).rot(self.CON2).opr(x).opr(z).opr(y))
        self.release_temporary_variable(z)

    def copy_to_temporary(self, block, v):
        if v.is_temporary:
            return v
        else:
            t = self.get_temporary_variable(v.type)
            self.copy(block, v, t)
            return t

    def inc(self, block, v):
        flgs = self.get_flags(1)
        f = flgs[0]
        y = self.get_const_variable(INT, 3486784398)
        z = self.get_const_variable(INT, 0)
        block.set(f)
        inner = (self.Block().if_(
                    f,
                    (self.Block().rot(self.CON2).opr(v).opr(z).opr(y).opr(v).opr(z).opr(y)
                        .switch_(y, self.Block(), self.Block().reset(f), self.Block())),
                    self.Block()
                 ).rot(self.CON1).opr(z).rot(v))
        block.repeat(20, inner).rot(self.CON1).opr(y)

    def inc2(self, block, v):
        flgs = self.get_flags(1)
        f = flgs[0]
        y = self.get_const_variable(INT, 3486784398)
        z = self.get_const_variable(INT, 0)
        block.set(f)
        (block.rot(self.CON2).opr(v).rot(self.CON2).opr(v).opr(z).opr(y).opr(v).rot(self.CON2).opr(v)
              .switch_(y, self.Block().reset(f), self.Block(), self.Block())
              .rot(self.CON1).opr(z).rot(v))
        inner = (self.Block().if_(
                    f,
                    (self.Block().rot(self.CON2).opr(v).opr(z).opr(y).opr(v).opr(z).opr(y)
                        .switch_(y, self.Block(), self.Block().reset(f), self.Block())),
                    self.Block()
                 ).rot(self.CON1).opr(z).rot(v))
        block.repeat(19, inner).rot(self.CON1).opr(y)

    def dec(self, block, v):
        flgs = self.get_flags(1)
        f = flgs[0]
        y = self.get_const_variable(INT, 3486784398)
        z = self.get_const_variable(INT, 0)
        block.set(f)
        inner = (self.Block().if_(
                    f,
                    (self.Block().rot(self.CON2).opr(v).rot(self.CON2).opr(v).opr(z).opr(y).opr(v).rot(self.CON2).opr(v)
                        .switch_(y, self.Block(), self.Block().reset(f), self.Block())),
                    self.Block()
                 ).rot(self.CON1).opr(z).rot(v))
        block.repeat(20, inner).rot(self.CON1).opr(y)

    def dec2(self, block, v):
        flgs = self.get_flags(1)
        f = flgs[0]
        y = self.get_const_variable(INT, 3486784398)
        z = self.get_const_variable(INT, 0)
        block.set(f)
        (block.rot(self.CON2).opr(v).opr(z).opr(y).opr(v).opr(z).opr(y)
              .switch_(y, self.Block().reset(f), self.Block(), self.Block())
              .rot(self.CON1).opr(z).rot(v))
        inner = (self.Block().if_(
                    f,
                    (self.Block().rot(self.CON2).opr(v).rot(self.CON2).opr(v).opr(z).opr(y).opr(v).rot(self.CON2).opr(v)
                        .switch_(y, self.Block(), self.Block().reset(f), self.Block())),
                    self.Block()
                 ).rot(self.CON1).opr(z).rot(v))
        block.repeat(19, inner).rot(self.CON1).opr(y)

    def reset_to_con1(self, block, v):
        # helper mirrored so sum/carry can use it inline
        return block.reset_to_con1(v)

    def sum(self, block, x, y):
        temp = self.get_temporary_variable(INT)
        block.reset_to_con1(temp)
        (block.rot(self.CON2).opr(x).opr(temp).opr(temp).rot(self.CON0).opr(x)
              .rot(self.CON2).opr(temp).rot(self.CON2).opr(y).rot(self.CON2).opr(y)
              .opr(x).opr(y).opr(temp).opr(x))
        self.release_temporary_variable(temp)

    def carry(self, block, x, y):
        temp = self.get_temporary_variable(INT)
        block.reset_to_con1(temp)
        (block.rot(self.CON2).opr(x).rot(self.CON2).opr(x).opr(temp).opr(y)
              .opr(temp).opr(y).rot(self.CON0).opr(y).opr(y))
        self.release_temporary_variable(temp)

    def add(self, block, x, _y):
        c = self.copy_to_temporary(block, _y)
        inner_block = self.Block()
        c2 = self.get_temporary_variable(INT)
        reset = self.get_const_variable(INT, 2905653667)
        self.copy(inner_block, c, c2)
        self.carry(inner_block, x, c)
        (inner_block.rot(self.CON2).opr(reset).opr(c).rot(self.CON2).opr(c)
                    .rot(self.CON2).opr(reset))
        self.sum(inner_block, x, c2)
        inner_block.rot(x).rot(reset)
        block.repeat(20, inner_block)

    def invert(self, block, x):
        y = self.get_const_variable(INT, 0)
        (block.rot(self.CON2).opr(x).opr(y).opr(y).opr(x).rot(self.CON2).opr(x)
              .rot(self.CON1).opr(y))
        self.inc(block, x)

    def sub(self, block, x, _y):
        y = self.copy_to_temporary(block, _y)
        self.invert(block, y)
        self.add(block, x, y)

    def not_(self, block, x):
        self.checkBool(x)
        y = self.get_temporary_variable(BOOL)
        block.reset_to_con1(y)
        block.rot(self.CON2).opr(x).rot(self.CON2).opr(x).opr(y)
        return y

    def lt(self, block, _x, _y, with_equal):
        self.checkInt(_x)
        self.checkInt(_y)
        x = self.copy_to_temporary(block, _x)
        y = self.copy_to_temporary(block, _y)
        temp = self.get_temporary_variable(INT)
        block.reset_to_con2(temp)
        (block.rot(self.CON2).opr(x).opr(temp).opr(x).opr(temp).opr(y)
              .rot(self.CON2).opr(y).opr(x).rot(self.CON2).opr(y).opr(x))
        self.release_temporary_variable(y)
        self.release_temporary_variable(temp)
        res = self.get_temporary_variable(BOOL)
        if with_equal:
            block.reset_to_con2(res).rot(self.CON0).opr(self.P12).opr(res)
        else:
            block.reset_to_con1(res).rot(self.CON0).opr(self.P21).opr(res)
        inner_block = self.Block()
        x2 = self.get_temporary_variable(INT)
        self.copy(inner_block, x, x2)
        (inner_block.rot(self.CON2).opr(x2).opr(res).opr(x2).opr(res).opr(x2).opr(res))
        inner_block.rot(x)
        block.repeat(20, inner_block)
        self.release_temporary_variable(x)
        self.release_temporary_variable(x2)
        return res

    def eq(self, block, _x, _y):
        self.checkInt(_x)
        self.checkInt(_y)
        x = self.copy_to_temporary(block, _x)
        y = self.copy_to_temporary(block, _y)
        temp = self.get_temporary_variable(INT)
        block.reset_to_con2(temp)
        (block.rot(self.CON2).opr(x).opr(temp).opr(x).opr(temp).opr(y).opr(x).opr(x))
        self.release_temporary_variable(y)
        self.release_temporary_variable(temp)
        res = self.get_temporary_variable(BOOL)
        block.reset_to_con2(res).rot(self.CON0).opr(self.P12).opr(res)
        inner_block = self.Block()
        (inner_block.rot(self.CON2).opr(x).rot(self.CON2).opr(x).opr(res))
        inner_block.rot(x)
        inner_block.switch_(res, self.Block().break_(), self.Block(), self.Block())
        block.repeat(20, inner_block)
        self.release_temporary_variable(x)
        return res

    def push_stack(self, block, x):
        self.dec2(block, self.stack_top)
        z = self.get_temporary_variable(INT)
        (block.rot(self.CON1).opr(z).opr(z).ind_opr(self.stack_top).ind_opr(self.stack_top)
              .rot(self.CON2).opr(x).rot(self.CON2).opr(x).opr(z).ind_opr(self.stack_top))
        self.release_temporary_variable(z)

    def pop_stack(self, block, y):
        z = self.get_temporary_variable(INT)
        (block.rot(self.CON1).opr(z).opr(z).opr(y).opr(y).rot(self.CON2)
              .ind_opr(self.stack_top).rot(self.CON2).ind_opr(self.stack_top).opr(z).opr(y))
        self.release_temporary_variable(z)
        self.inc2(block, self.stack_top)

    def move_stack_top(self, block, n):
        if n != 0:
            if 0 < n <= 2:
                for _ in range(n):
                    self.dec2(block, self.stack_top)
            elif -2 <= n < 0:
                for _ in range(-n):
                    self.inc2(block, self.stack_top)
            else:
                self.add(block, self.stack_top,
                         self.get_const_variable(INT, (-2) * n))

    def get_absolute_address(self, block, x, n):
        addr = self.get_temporary_variable(INT)
        self.copy(block, n, addr)
        self.add(block, addr, n)
        self.add(block, addr, x.array_top_addr)
        return addr

    def copy_from_array(self, block, x, n, y):
        if x.type != y.type:
            self.throw_syntax_error("Type mismatch")
        addr = self.get_absolute_address(block, x, n)
        z = self.get_temporary_variable(x.type)
        (block.rot(self.CON1).opr(z).opr(z).opr(y).opr(y).rot(self.CON2)
              .ind_opr(addr).rot(self.CON2).ind_opr(addr).opr(z).opr(y))
        self.release_temporary_variable(z)
        self.release_temporary_variable(addr)

    def copy_to_array(self, block, x, n, y):
        if x.type != y.type:
            self.throw_syntax_error("Type mismatch")
        addr = self.get_absolute_address(block, x, n)
        z = self.get_temporary_variable(x.type)
        (block.rot(self.CON1).opr(z).opr(z).ind_opr(addr).ind_opr(addr)
              .rot(self.CON2).opr(y).rot(self.CON2).opr(y).opr(z).ind_opr(addr))
        self.release_temporary_variable(z)
        self.release_temporary_variable(addr)

    # -----------------------------------------------------------------------
    # Parser  (recursive descent; actions mirror the Bison reductions)
    # -----------------------------------------------------------------------
    def parse_program(self):
        # program: {stack_top init} decl_list {finalize}
        self.stack_top = Variable(INT, VAR_STACK_TOP)
        self.global_variables[VAR_STACK_TOP] = self.stack_top

        self.parse_decl_list()
        self.expect("EOF")

        # finalize
        self.stack_top.init_val = self.stack_top_init_val
        self.check_recursive_call()

        gg = Generator()
        for name in sorted(self.functions):
            self.functions[name].generate(gg)

        g = Generator()
        for name in sorted(self.global_variables):
            v = self.global_variables[name]
            g.var(v.name, v.init_val)
        for flag in self.flags:
            g.flag(flag)
        for name in sorted(self.functions):
            g.proto(self.functions[name].name)

        return g.text() + gg.text()

    def parse_decl_list(self):
        while not self.at("EOF"):
            self.parse_decl()

    def parse_type(self):
        if self.at("INT"):
            self.advance()
            return INT
        if self.at("BOOL"):
            self.advance()
            return BOOL
        self.syntax_error("syntax error")

    def parse_type_decl(self):
        # type_decl: type | STATIC type
        if self.at("STATIC"):
            self.advance()
            t = self.parse_type()
            self.decl_static = True
            self.decl_type = t
            return t
        else:
            t = self.parse_type()
            self.decl_static = False
            self.decl_type = t
            return t

    def parse_decl(self):
        # var_decl | func_decl | proto_decl -- all start with type_decl
        if not (self.at("INT") or self.at("BOOL") or self.at("STATIC")):
            self.syntax_error("syntax error")
        ret_type = self.parse_type_decl()
        # after type_decl comes IDENT
        if not self.at("IDENT"):
            self.syntax_error("syntax error")
        if self.peek(1).kind == "LPAREN":
            self.parse_func_or_proto(ret_type)
        else:
            self.parse_var_init_list()
            self.expect("SEMICORON")

    # -- function / prototype -----------------------------------------------
    def parse_dummy_arg_list_wrapper(self):
        if self.at("RPAREN"):
            return []
        return self.parse_dummy_arg_list()

    def parse_dummy_arg_list(self):
        args = [self.parse_dummy_arg()]
        while self.at("COMMA"):
            self.advance()
            args.append(self.parse_dummy_arg())
        return args

    def parse_dummy_arg(self):
        t = self.parse_type()
        if not self.at("IDENT"):
            self.syntax_error("syntax error")
        name = self.advance().value
        return (t, Ident(name).to_string())

    def parse_func_or_proto(self, ret_type):
        name_tok = self.advance()  # IDENT
        upper = name_tok.value.upper()
        self.expect("LPAREN")
        args = self.parse_dummy_arg_list_wrapper()
        self.expect("RPAREN")

        if self.at("SEMICORON"):
            # proto_decl
            self.advance()
            if upper in self.functions:
                self.throw_syntax_error("'" + upper + "' is already defined.")
            f = Func(self, ret_type, upper)
            f.args = args
            self.functions[upper] = f
            return

        # func_decl: expect LBRACE
        self.expect("LBRACE")
        if upper in self.functions:
            f = self.functions[upper]
            if f.is_implemented:
                self.throw_syntax_error("'" + upper + "' is already defined.")
            else:
                if len(f.args) != len(args):
                    self.throw_syntax_error("Argument does not match prototype.")
                for k in range(len(args)):
                    if f.args[k][0] != args[k][0] or f.args[k][1] != args[k][1]:
                        self.throw_syntax_error("Argument does not match prototype.")
        else:
            f = Func(self, ret_type, upper)
            self.functions[upper] = f

        self.current_func = f
        f.args = args
        f.is_implemented = True
        self.variable_collection = f.variables
        self.array_collection = f.arrays

        # var_decl_list
        while self.at("INT") or self.at("BOOL") or self.at("STATIC"):
            self.parse_type_decl()
            self.parse_var_init_list()
            self.expect("SEMICORON")

        # mid-action after var_decl_list
        self.add_block()
        f.block = self.current_block

        for (typ, varname) in args:
            f.variables[varname] = Variable(typ, varname)

        # local variable init copies (sorted iteration of variables)
        for key in sorted(f.variables):
            v = f.variables[key]
            if not v.is_static and v.init_val != VAR_UNINITIALIZED:
                self.copy(self.current_block,
                          self.get_const_variable(v.type, v.init_val), v)

        # ARGi setup (declaration order)
        i = 0
        for (typ, varname) in args:
            argname = ARG(i)
            i += 1
            v1 = Variable(typ, argname)
            v1.is_static = True
            f.variables[argname] = v1
            v2 = f.variables[varname]
            self.copy(self.current_block, v1, v2)

        return_val = Variable(f.return_type, RETURN_VALUE)
        return_val.is_static = True
        f.variables[RETURN_VALUE] = return_val

        # statement_list
        self.parse_statement_list()
        self.expect("RBRACE")

        # restore scope
        self.variable_collection = self.global_variables
        self.array_collection = self.global_arrays
        self.current_func = None
        # pop the function body block
        self.pop_block()

    # -- variable declarations ----------------------------------------------
    def parse_var_init_list(self):
        self.parse_var_init()
        while self.at("COMMA"):
            self.advance()
            self.parse_var_init()

    def parse_var_init(self):
        # var_init: several forms starting with escaped_ident
        if not self.at("IDENT"):
            self.syntax_error("syntax error")
        # array declaration: escaped_ident LBRACKET NUMBER RBRACKET
        if self.peek(1).kind == "LBRACKET":
            ident = Ident(self.advance().value)
            self.expect("LBRACKET")
            if not self.at("NUMBER"):
                self.syntax_error("syntax error")
            size = self.advance().value
            self.expect("RBRACKET")
            self._declare_array(ident, size)
            return
        # scalar declaration (possibly with initializer)
        v = self._declare_var()
        if self.at("ASSIGN"):
            self.advance()
            if self.at("MINUS"):
                self.advance()
                if not self.at("NUMBER"):
                    self.syntax_error("syntax error")
                num = self.advance().value
                v.init_val = MOD1 - num
            elif self.at("NUMBER"):
                v.init_val = self.advance().value
            elif self.at("TRUE"):
                self.advance()
                v.init_val = TRUE_VAL
            elif self.at("FALSE"):
                self.advance()
                v.init_val = FALSE_VAL
            else:
                self.syntax_error("syntax error")

    def _declare_var(self):
        ident = Ident(self.advance().value)
        name = ident.to_string()
        if name in self.variable_collection:
            self.throw_syntax_error("'" + ident.name + "' is already defined.")
        v = Variable(self.decl_type, name)
        v.is_static = self.decl_static
        self.variable_collection[name] = v
        return v

    def _declare_array(self, ident, size):
        name = ident.to_string()
        if self.decl_static:
            self.throw_syntax_error("Static array is not supported.")
        if name in self.array_collection:
            self.throw_syntax_error("'" + ident.name + "' is already defined.")
        arr = Array(self.decl_type, name, size)
        if self.array_collection is self.global_arrays:
            self.stack_top_init_val -= size * 2
            v = Variable(INT, name, self.stack_top_init_val)
        else:
            v = Variable(INT, name)
        v.is_static = True
        arr.array_top_addr = v
        self.array_collection[name] = arr
        self.variable_collection[name] = v

    # -- statements ----------------------------------------------------------
    def parse_statement_list(self):
        while not self.at("RBRACE") and not self.at("EOF"):
            self.parse_statement()

    def parse_statement(self):
        k = self.cur().kind
        if k == "SEMICORON":
            self.advance()
            return
        if k == "IF":
            self.parse_if_statement()
            return
        if k == "WHILE":
            self.parse_while_statement()
            return
        if k == "RETURN":
            self.parse_return_statement()
            return
        # expression SEMICORON
        result = self.parse_expression()
        self.expect("SEMICORON")
        if result.is_temporary:
            self.release_temporary_variable(result)

    def parse_block(self):
        # block: LBRACE statement_list RBRACE | null statement
        if self.at("LBRACE"):
            self.advance()
            self.add_block()
            self.parse_statement_list()
            self.expect("RBRACE")
            blk = self.current_block
            self.pop_block()
            return blk
        else:
            self.add_block()
            self.parse_statement()
            blk = self.current_block
            self.pop_block()
            return blk

    def parse_if_statement(self):
        self.expect("IF")
        self.expect("LPAREN")
        cond = self.parse_expression()
        self.expect("RPAREN")
        self.checkBool(cond)
        then_block = self.parse_block()
        if self.at("ELSE"):
            self.advance()
            else_block = self.parse_block()
        else:
            else_block = self.Block()
        # switch_(cond, else, then, empty)
        self.current_block.switch_(cond, else_block, then_block, self.Block())

    def parse_while_statement(self):
        self.expect("WHILE")
        self.add_block()   # condition codegen goes into the while-block
        self.expect("LPAREN")
        cond = self.parse_expression()
        self.checkBool(cond)
        self.expect("RPAREN")
        body = self.parse_block()
        inner_block = self.current_block
        self.pop_block()
        inner_block.switch_(cond, self.Block().break_(), body, self.Block())
        self.current_block.repeat_inf(inner_block)

    def parse_return_statement(self):
        self.expect("RETURN")
        val = self.parse_expression()
        self.expect("SEMICORON")
        v = Variable(self.current_func.return_type, RETURN_VALUE)
        self.copy(self.current_block, val, v)
        self.current_block.func_return(self.current_func)

    # -- expressions (precedence climbing) ----------------------------------
    def parse_expression(self):
        return self.parse_assign()

    def _is_array_assign_ahead(self):
        # current token is IDENT, peek(1) is LBRACKET; scan for matching
        # RBRACKET and check whether the token after it is ASSIGN.
        depth = 0
        idx = self.pos + 1  # at LBRACKET
        n = len(self.tokens)
        while idx < n:
            kind = self.tokens[idx].kind
            if kind == "LBRACKET":
                depth += 1
            elif kind == "RBRACKET":
                depth -= 1
                if depth == 0:
                    after = self.tokens[idx + 1].kind if idx + 1 < n else "EOF"
                    return after == "ASSIGN"
            elif kind == "EOF":
                return False
            idx += 1
        return False

    def parse_assign(self):
        tok = self.cur()
        if tok.kind == "IDENT":
            nxt = self.peek(1).kind
            if nxt == "ASSIGN":
                ident = Ident(self.advance().value)
                self.advance()  # '='
                rhs = self.parse_assign()
                z = self.get_variable(ident.to_string())
                if z is not rhs:
                    self.copy(self.current_block, rhs, z)
                return z
            if nxt == "PLUS_ASSIGN":
                ident = Ident(self.advance().value)
                self.advance()
                rhs = self.parse_assign()
                z = self.get_variable(ident.to_string())
                self.add(self.current_block, z, rhs)
                return z
            if nxt == "MINUS_ASSIGN":
                ident = Ident(self.advance().value)
                self.advance()
                rhs = self.parse_assign()
                z = self.get_variable(ident.to_string())
                self.sub(self.current_block, z, rhs)
                return z
            if nxt == "LBRACKET" and self._is_array_assign_ahead():
                ident = Ident(self.advance().value)
                self.expect("LBRACKET")
                index = self.parse_expression()
                self.expect("RBRACKET")
                self.expect("ASSIGN")
                rhs = self.parse_assign()
                z = self.get_array(ident.to_string())
                self.copy_to_array(self.current_block, z, index, rhs)
                return rhs
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while self.at("OR"):
            self.advance()
            right = self.parse_and()
            left = self._logical_or(left, right)
        return left

    def parse_and(self):
        left = self.parse_eq()
        while self.at("AND"):
            self.advance()
            right = self.parse_eq()
            left = self._logical_and(left, right)
        return left

    def parse_eq(self):
        left = self.parse_rel()
        while self.at("EQ") or self.at("NEQ"):
            op = self.advance().kind
            right = self.parse_rel()
            if op == "EQ":
                self.checkInt(left)
                self.checkInt(right)
                left = self.eq(self.current_block, left, right)
            else:  # NEQ
                self.checkInt(left)
                self.checkInt(right)
                left = self.not_(self.current_block,
                                 self.eq(self.current_block, left, right))
        return left

    def parse_rel(self):
        left = self.parse_add()
        while self.cur().kind in ("LT", "GT", "LTE", "GTE"):
            op = self.advance().kind
            right = self.parse_add()
            if op == "LT":
                left = self.lt(self.current_block, left, right, False)
            elif op == "LTE":
                left = self.lt(self.current_block, left, right, True)
            elif op == "GT":
                left = self.lt(self.current_block, right, left, False)
            else:  # GTE
                left = self.lt(self.current_block, right, left, True)
        return left

    def parse_add(self):
        left = self.parse_unary()
        while self.at("PLUS") or self.at("MINUS"):
            op = self.advance().kind
            right = self.parse_unary()
            if op == "PLUS":
                left = self._add_expr(left, right)
            else:
                left = self._sub_expr(left, right)
        return left

    # -- binary-op actions (mirror the Bison rule bodies) --------------------
    def _add_expr(self, x, y):
        self.checkInt(x)
        self.checkInt(y)
        if not x.is_temporary:
            if y.is_temporary:
                x, y = y, x
            else:
                t = self.get_temporary_variable(INT)
                self.copy(self.current_block, x, t)
                x = t
        self.add(self.current_block, x, y)
        if y.is_temporary:
            self.release_temporary_variable(y)
        return x

    def _sub_expr(self, x, y):
        self.checkInt(x)
        self.checkInt(y)
        if not x.is_temporary:
            t = self.get_temporary_variable(INT)
            self.copy(self.current_block, x, t)
            x = t
        if not y.is_temporary:
            t = self.get_temporary_variable(INT)
            self.copy(self.current_block, y, t)
            y = t
        self.sub(self.current_block, x, y)
        return x

    def _logical_and(self, _x, y):
        self.checkBool(_x)
        self.checkBool(y)
        if not _x.is_temporary:
            if y.is_temporary:
                _x, y = y, _x
                x = _x
            else:
                x = self.get_temporary_variable(BOOL)
                self.copy(self.current_block, _x, x)
        else:
            x = _x
        (self.current_block.rot(self.CON2).opr(y).opr(x).rot(self.CON0).opr(y).opr(x))
        (self.current_block.rot(self.CON0).opr(self.P21).opr(y)
             .rot(self.CON0).opr(self.P12).opr(y))
        if _x.is_temporary:
            self.release_temporary_variable(_x)
        if y.is_temporary:
            self.release_temporary_variable(y)
        return x

    def _logical_or(self, _x, y):
        self.checkBool(_x)
        self.checkBool(y)
        if not _x.is_temporary:
            if y.is_temporary:
                _x, y = y, _x
                x = _x
            else:
                x = self.get_temporary_variable(BOOL)
                self.copy(self.current_block, _x, x)
        else:
            x = _x
        t = self.get_temporary_variable(BOOL)
        (self.current_block.rot(self.CON1).opr(t).opr(t).rot(self.CON2).opr(t))
        (self.current_block.rot(self.CON2).opr(y).opr(t).opr(x).rot(self.CON1).opr(t).opr(x))
        (self.current_block.rot(self.CON2).opr(y))
        if _x.is_temporary:
            self.release_temporary_variable(_x)
        if y.is_temporary:
            self.release_temporary_variable(y)
        return x

    # -- unary / postfix / primary ------------------------------------------
    def parse_unary(self):
        k = self.cur().kind
        if k == "INC":
            self.advance()
            if not self.at("IDENT"):
                self.syntax_error("syntax error")
            ident = Ident(self.advance().value)
            if self.at("LBRACKET"):
                self.advance()
                index = self.parse_expression()
                self.expect("RBRACKET")
                arr = self.get_array(ident.to_string())
                self.checkInt_array(arr)
                z = self.get_temporary_variable(INT)
                self.copy_from_array(self.current_block, arr, index, z)
                self.inc(self.current_block, z)
                self.copy_to_array(self.current_block, arr, index, z)
                return z
            else:
                v = self.get_variable(ident.to_string())
                self.checkInt(v)
                self.inc(self.current_block, v)
                return v
        if k == "DEC":
            self.advance()
            if not self.at("IDENT"):
                self.syntax_error("syntax error")
            ident = Ident(self.advance().value)
            if self.at("LBRACKET"):
                self.advance()
                index = self.parse_expression()
                self.expect("RBRACKET")
                arr = self.get_array(ident.to_string())
                self.checkInt_array(arr)
                z = self.get_temporary_variable(INT)
                self.copy_from_array(self.current_block, arr, index, z)
                self.dec(self.current_block, z)
                self.copy_to_array(self.current_block, arr, index, z)
                return z
            else:
                v = self.get_variable(ident.to_string())
                self.checkInt(v)
                self.dec(self.current_block, v)
                return v
        if k == "NOT":
            self.advance()
            operand = self.parse_unary()
            res = self.not_(self.current_block, operand)
            if operand.is_temporary:
                self.release_temporary_variable(operand)
            return res
        return self.parse_primary()

    def parse_primary(self):
        tok = self.cur()
        k = tok.kind
        if k == "LPAREN":
            self.advance()
            inner = self.parse_expression()
            self.expect("RPAREN")
            return inner
        if k == "NUMBER":
            self.advance()
            return self.get_const_variable(INT, tok.value)
        if k == "MINUS":
            self.advance()
            if not self.at("NUMBER"):
                self.syntax_error("syntax error")
            num = self.advance().value
            return self.get_const_variable(INT, MOD1 - num)
        if k == "TRUE":
            self.advance()
            return self.get_const_variable(BOOL, TRUE_VAL)
        if k == "FALSE":
            self.advance()
            return self.get_const_variable(BOOL, FALSE_VAL)
        if k == "IDENT":
            nxt = self.peek(1).kind
            if nxt == "LPAREN":
                return self.parse_func_call()
            # escaped_ident forms
            ident = Ident(self.advance().value)
            if self.at("LBRACKET"):
                self.advance()
                index = self.parse_expression()
                self.expect("RBRACKET")
                if self.at("INC"):
                    self.advance()
                    return self._post_inc_array(ident, index)
                if self.at("DEC"):
                    self.advance()
                    return self._post_dec_array(ident, index)
                # scalar_variable: array element rvalue
                v = self.get_array(ident.to_string())
                z = self.get_temporary_variable(v.type)
                self.copy_from_array(self.current_block, v, index, z)
                return z
            if self.at("INC"):
                self.advance()
                return self._post_inc(ident)
            if self.at("DEC"):
                self.advance()
                return self._post_dec(ident)
            # plain scalar variable
            return self.get_variable(ident.to_string())
        self.syntax_error("syntax error")

    def _post_inc(self, ident):
        v = self.get_variable(ident.to_string())
        self.checkInt(v)
        t = self.get_temporary_variable(INT)
        self.copy(self.current_block, v, t)
        self.inc(self.current_block, v)
        return t

    def _post_dec(self, ident):
        v = self.get_variable(ident.to_string())
        self.checkInt(v)
        t = self.get_temporary_variable(INT)
        self.copy(self.current_block, v, t)
        self.dec(self.current_block, v)
        return t

    def _post_inc_array(self, ident, index):
        arr = self.get_array(ident.to_string())
        self.checkInt_array(arr)
        z = self.get_temporary_variable(INT)
        self.copy_from_array(self.current_block, arr, index, z)
        t = self.get_temporary_variable(INT)
        self.copy(self.current_block, z, t)
        self.inc(self.current_block, z)
        self.copy_to_array(self.current_block, arr, index, z)
        return t

    def _post_dec_array(self, ident, index):
        arr = self.get_array(ident.to_string())
        self.checkInt_array(arr)
        z = self.get_temporary_variable(INT)
        self.copy_from_array(self.current_block, arr, index, z)
        t = self.get_temporary_variable(INT)
        self.copy(self.current_block, z, t)
        self.dec(self.current_block, z)
        self.copy_to_array(self.current_block, arr, index, z)
        return t

    def parse_func_call(self):
        name_tok = self.advance()  # IDENT
        upper = name_tok.value.upper()
        self.expect("LPAREN")
        args = self.parse_expression_list_wrapper()
        self.expect("RPAREN")

        if upper == MAIN_FUNCTION:
            self.throw_syntax_error("Can not call 'main'")
        elif upper == PUTCHAR_FUNCTION:
            if len(args) != 1:
                self.throw_syntax_error("Argument size missmatch")
            arg = args[0]
            if arg.type != INT:
                self.throw_syntax_error("Argument type missmatch")
            (self.current_block.rot(self.CON2).opr(arg).rot(self.CON2).opr(arg).output())
            return self.CON0
        elif upper == GETCHAR_FUNCTION:
            if len(args) != 0:
                self.throw_syntax_error("Argument size missmatch")
            ret_val = self.get_temporary_variable(INT)
            z = self.get_temporary_variable(INT)
            (self.current_block.rot(self.CON1).opr(z).opr(z).opr(ret_val).opr(ret_val)
                 .input().opr(z).opr(ret_val))
            self.release_temporary_variable(z)
            return ret_val
        else:
            if upper not in self.functions:
                self.throw_syntax_error("Undefined function '" + upper + "'")
            f = self.functions[upper]
            self.current_func.callees.append(f)
            if len(f.args) != len(args):
                self.throw_syntax_error("Argument size missmatch")
            i = 0
            for arg in args:
                if arg.type != f.args[i][0]:
                    self.throw_syntax_error("Argument type missmatch")
                self.copy(self.current_block, arg,
                          Variable(arg.type, ARG(i) + "@" + f.name))
                i += 1
            self.current_block.call(f)
            ret = Variable(f.return_type, RETURN_VALUE + "@" + f.name)
            t = self.get_temporary_variable(ret.type)
            self.copy(self.current_block, ret, t)
            return t

    def parse_expression_list_wrapper(self):
        if self.at("RPAREN"):
            return []
        return self.parse_expression_list()

    def parse_expression_list(self):
        args = [self.parse_expression()]
        while self.at("COMMA"):
            self.advance()
            args.append(self.parse_expression())
        return args


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def compile_c_to_mg(c_source):
    """Compile *c_source* (Nagoya high-level C subset) to ``.mg`` text.

    Returns the generated ``.mg`` string.  Raises :class:`C2MgError` on
    invalid input (with a best-effort line number and offending token).
    """
    tokens, warnings = tokenize(c_source)
    compiler = Compiler(tokens)
    compiler.warnings = warnings
    return compiler.parse_program()
