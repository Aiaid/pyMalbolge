"""
malbolge.compiler.mg2mc -- pure-Python port of the Nagoya ``.mg`` (control-bearing
pseudo-instruction sequence) -> ``.mc`` (Low-Level-Assembly, LAL) translator.

This is a faithful, deterministic re-implementation of the C++/flex/bison tool at
``ref/nagoya-ternary/`` (MIT licensed).  The reference tool has two independent
code-generation switches, each with two deterministic settings, and all four
combinations are available here through ``translate_mg_to_mc``'s keyword arguments:

* ``op_style="cluster"`` (``-c``, the default) emits OUTPUT/INPUT/SET/RESET as
  shared cluster modules; ``op_style="inline"`` (``-i``) expands them in place.
* ``jmp_style="main"`` (``-m``, the default) makes continuous ROT/OPR calls return
  to the main control flow first; ``jmp_style="direct"`` (``-d``) jumps straight to
  the next module.

What is *not* ported is the reference tool's default, seed-dependent behaviour: with
neither ``-c`` nor ``-i`` (resp. neither ``-m`` nor ``-d``) upstream mixes the two
styles per decision point via ``std::mt19937``, and ``Option.use_op_block`` /
``Option.back_to_main`` still raise ``RuntimeError`` on those branches.  Every style
selectable here is deterministic and independent of the ``-s`` seed.  The default
``translate_mg_to_mc(mg)`` reproduces ``parser -m -c -s 1 <file>`` byte for byte.

The single intentional behavioural change over the upstream tool: upstream prints
every syntax/semantic error to stderr and *always* exits 0 (``main.cc`` never checks
``parser.parse()``'s return value), and a ``PROTO`` without a matching ``DEF`` even
SIGSEGVs.  Here every such error is raised as :class:`Mg2McError` (carrying a source
line number where one is available) instead.  Non-fatal lexer events -- an unknown
character such as a bare ``#`` on its own line -- are still skipped silently, exactly
as upstream's ``scanner.ll`` ``.`` rule does, so fragment files like
``runtime/mg/primitives/*.mg`` still translate to the same boilerplate.

    from malbolge.compiler.mg2mc import translate_mg_to_mc, Mg2McError
    mc = translate_mg_to_mc("DEF MAIN\n  OUTPUT\nEND\n")
    mc = translate_mg_to_mc(mg, op_style="inline", jmp_style="direct")
"""

from __future__ import annotations

import enum
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class Mg2McError(Exception):
    """Raised on any ``.mg`` syntax or semantic error.

    ``line`` is the 1-based source line number where the error was detected, or
    ``None`` when it is only known at generation time (e.g. an undefined
    forward-referenced variable).
    """

    def __init__(self, message: str, line: Optional[int] = None):
        self.line = line
        if line is not None:
            super().__init__("%s (line %d)" % (message, line))
        else:
            super().__init__(message)


# ---------------------------------------------------------------------------
# define.h constants
# ---------------------------------------------------------------------------

def LABEL_OPR(var):      return "OPR_" + var
def LABEL_ROT(var):      return "ROT_" + var
def LABEL_DJMP(var):     return "DJMP_" + var
def LABEL_IND_OPR(var):  return "IND_OPR_" + var
def LABEL_REV_OPR(var):  return "REV_OPR_" + var
def LABEL_END_REV(var):  return "END_REV_" + var
def LABEL_SET(flag):     return "SET_" + flag
def LABEL_RESET(flag):   return "RESET_" + flag

FLAG_JMP = "FLAG_JMP"
FLAG_REV_OPR_ROT = "FLAG_REV_OPR_ROT"
FLAG_REV_IND_OPR = "FLAG_REV_IND_OPR"
LABEL_REV_IND_OPR = "REV_IND_OPR"
LABEL_RETURN = "RETURN"
LABEL_OUTPUT = "L_OUTPUT"
LABEL_INPUT = "L_INPUT"
FLAG_ON = 0
FLAG_OFF = 1
FLAG_CASE0 = "FLAG_CASE0"
FLAG_CASE1 = "FLAG_CASE1"
FLAG_CASE2 = "FLAG_CASE2"
INF_EXPR = -1
CON0_VAL = 0
CON1_VAL = 1743392200
CON2_VAL = 3486784400
FUNC_RETURN_ADDR = "RETURN_ADDR"
GLOBAL_ROUTINE = "GLOBAL"
MAIN_ROUTINE = "MAIN"


class INS_TYPE(enum.Enum):
    IF_BRANCH = 1
    IF_BRANCH_ASSIGNED = 2
    NEXT = 3
    SKIP = 4
    END = 5
    INPUT = 6
    REV_INPUT = 7
    OUTPUT = 8
    REV_OUTPUT = 9
    DUP = 10
    LABEL = 11
    JMP = 12
    REV_JMP = 13
    VAR = 14
    UNIT_CALL = 15


# ---------------------------------------------------------------------------
# raw/ind-opr.h and raw/djmp.h -- emitted verbatim (byte-exact, self-contained)
# ---------------------------------------------------------------------------

RAW_IND_OPR_FLAGS = "\n# IND_OPR用フラグ\nFLAG 1/2, FLAG_REV_IND_OPR\nFLAG 0/2, FLAG_I0\nFLAG 0/2, FLAG_I1\nFLAG 0/2, FLAG_I2\nFLAG 0/2, FLAG_I3\nFLAG 0/2, FLAG_I4\nFLAG 1/9, FLAG_I5\nFLAG 1/5, FLAG_I6\n"
RAW_IND_OPR_UNIT = "\n# IND_OPRユニット\nUNIT{\n66: DUP\nIND_OPR:\n67: MOV_D #(9)\nUNIT2_1:\n68: NOOP\n69: NOOP\n70: NOOP\n71: OPR #(9)\nUNIT2_2:\n72: NOOP\n73: NOOP\nUNIT2_3:\n74: MOV_D #(5)\n75: NOOP\n76: MOV_D # 36にジャンプ　(6)\nUNIT2_4:\n77: NOOP\n78: NOOP\n79: NOOP\n80: NOOP\n81: NOOP\n82: MOV_D # (68)\nUNIT2_5:\n83: MOV_D # (5)\nUNIT2_6:\n84: JMP\n}\n"
RAW_IND_OPR_REV = "\n#IND_OPRの復元\n########################\nREV_IND_OPR:\n  NEXT FLAG_I5\nMID_L0:\n  UNIT2_1 # 67番地のMOV_D\n  DUP\n  DUP\n  DUP\nMID_L1:\n  UNIT2_2 # 71番地のOPR\n  DUP\nMID_L2:\n  UNIT2_3\n  MID_L3 # 74番地のMOV_D\nMID_L3:\n  DUP\nMID_L4:\n  MID_L5 # 76番地のMOV_D\nMID_L5:\n  DUP\n  DUP\n  DUP\n  DUP\n  DUP\nMID_L6:\n  UNIT2_5 # 82番地のMOV_D\n  MID_L7 # 83番地のMOV_D\nMID_L7:\n  SKIP MID_L8\n\n#76番地の初期化時に利用\nMID_L4_2:\n  UNIT2_4 # 76番地のMOV_D\n  DUP\n  DUP\n  DUP\n  DUP\n  DUP\nMID_L6_2:\n  UNIT2_5 # 82番地のMOV_D\n  MID_L7_2 # 83番地のMOV_D\nMID_L7_2:\n  SKIP MID_L8\n\n# 83番地の初期化時に利用\nMID_L7_3:\n  UNIT2_6 # 83番地のMOD_D\n\n\nMID_L8:\n  IF FLAG_I0\n  BRANCH L_0XXXX\nL_1XXXX:\n  NEXT FLAG_I1\n  IF FLAG_I1\n  BRANCH L_11XXX\nL_10XXX:\n  IF FLAG_I2\n  BRANCH L_100XX\nL_101XX:\n  IF FLAG_I3\n  BRANCH L_1010X\nL_1011X:\n  NEXT FLAG_I0\n  NEXT FLAG_I3\n  IF FLAG_I4\n  BRANCH MID_L6\n  NEXT FLAG_I3\n  IF FLAG_I1\n  BRANCH MID_L7_3\n\nL_11XXX:\n  IF FLAG_I2\n  BRANCH L_110XX\n  JMP MID_L9\n\nL_110XX:\n  IF FLAG_I0\n  BRANCH MID_L7_3\n\nL_1010X:\n  NEXT FLAG_I4\n  IF FLAG_I4\n  BRANCH MID_L4_2\n  NEXT FLAG_I3\n  IF FLAG_I0\n  BRANCH MID_L4_2\n\nL_100XX:\n  IF FLAG_I3\n  BRANCH L_1000X\nL_1001X:\n  NEXT FLAG_I4\n  IF FLAG_I4\n  BRANCH MID_L4_2\n  IF FLAG_I1\n  BRANCH MID_L4_2\n\nL_1000X:\n  NEXT FLAG_I0\n  NEXT FLAG_I4\n  IF FLAG_I4\n  BRANCH MID_L2\n  NEXT FLAG_I2\n  NEXT FLAG_I3\n  IF FLAG_I4\n  BRANCH MID_L2\n\nL_0XXXX:\n  NEXT FLAG_I1\n  IF FLAG_I1\n  BRANCH L_01XXX\nL_00XXX:\n  IF FLAG_I2\n  BRANCH L_000XX\nL_001XX:\n  IF FLAG_I3\n  BRANCH L_0010X\nL_0011X:\n  NEXT FLAG_I0\n  IF FLAG_I4\n  BRANCH MID_L0\n  IF FLAG_I1\n  BRANCH MID_L0\n\nL_01XXX:\n  IF FLAG_I2\n  BRANCH L_010XX\nL_011XX:\n  IF FLAG_I3\n  BRANCH L_0110X\nL_0111X:\n  NEXT FLAG_I0\n  IF FLAG_I4\n  BRANCH MID_L1\n  NEXT FLAG_I0\n  NEXT FLAG_I1\n  NEXT FLAG_I3\n  NEXT FLAG_JMP\n  IF FLAG_JMP\n  BRANCH MID_L1\n\nL_010XX:\n  IF FLAG_I3\n  BRANCH L_0100X\nL_0101X:\n  IF FLAG_I4\n  BRANCH L_01010\n  NEXT FLAG_I0\n  IF FLAG_I3\n  BRANCH MID_L1\n\nL_01010:\n  NEXT FLAG_I1\n  NEXT FLAG_I4\n  NEXT FLAG_JMP\n  IF FLAG_JMP\n  BRANCH MID_L1\n\nL_0100X:\n  NEXT FLAG_I0\n  IF FLAG_I4\n  BRANCH MID_L1\n  NEXT FLAG_I2\n  NEXT FLAG_JMP\n  IF FLAG_JMP\n  BRANCH MID_L1\n\nL_0110X:\n  NEXT FLAG_I0\n  IF FLAG_I4\n  BRANCH MID_L1\n  NEXT FLAG_I1\n  NEXT FLAG_I2\n  NEXT FLAG_JMP\n  IF FLAG_JMP\n  BRANCH MID_L1\n\nL_0010X:\n  NEXT FLAG_I0\n  NEXT FLAG_I2\n  IF FLAG_I4\n  BRANCH MID_L1\n  NEXT FLAG_I2\n  NEXT FLAG_JMP\n  IF FLAG_JMP\n  BRANCH MID_L0\n\nL_000XX:\n  IF FLAG_I3\n  BRANCH L_0000X\nL_0001X:\n  NEXT FLAG_I0\n  NEXT FLAG_I1\n  IF FLAG_I4\n  BRANCH MID_L0\n  NEXT FLAG_I1\n  NEXT FLAG_JMP\n  IF FLAG_JMP\n  BRANCH MID_L0\n\nL_0000X:\n  NEXT FLAG_I3\n  NEXT FLAG_I4\n  IF FLAG_I4\n  BRANCH MID_L0\n  NEXT FLAG_I3\n  NEXT FLAG_JMP\n  IF FLAG_JMP\nBRANCH MID_L0\n\nMID_L9:\n  REV JMP\n  NEXT FLAG_I0\n  NEXT FLAG_I2\n\n  IF FLAG_I5\n  BRANCH MID_L10\n  NEXT FLAG_JMP\n  IF FLAG_JMP\n  BRANCH MID_L6\n\nMID_L10:\n  IF FLAG_I6\n  BRANCH MID_L11\n  NEXT FLAG_JMP\n  IF FLAG_JMP\n  BRANCH MID_L6\n\nMID_L11:\n  NEXT FLAG_I0\n  NEXT FLAG_I1\n  NEXT FLAG_I2\n########################\n"
RAW_DJMP_UNIT = "\nUNIT{\n59:DUP\nDJMP:\n60:MOV_D #(2)\nREV_DJMP:\n61:JMP\n}\n"


# ---------------------------------------------------------------------------
# Radix.cc -- base conversion (only Radix::to(string, p) is used by the parser)
# ---------------------------------------------------------------------------

_RADIX_DIGITS = "0123456789ABCDEF"
_RADIX_INDEX = {c: i for i, c in enumerate(_RADIX_DIGITS)}


def radix_to_int(text: str, base: int) -> int:
    """Port of ``Radix::to(const std::string& t, int p)``: interpret ``text`` as a
    base-``base`` number left-to-right via ``sm = sm*base + digit``.

    Like the upstream tool this does *not* validate that each digit is < base
    (upstream's ``39t`` silently evaluates to ``3*3+9 == 18``); callers that need a
    stricter check do it before calling here.
    """
    sm = _RADIX_INDEX[text[0]]
    for i in range(1, len(text)):
        sm = sm * base + _RADIX_INDEX[text[i]]
    return sm


# ---------------------------------------------------------------------------
# Instruction.cc
# ---------------------------------------------------------------------------

class Instruction:
    __slots__ = (
        "routine", "type", "label", "flag", "move_to", "next_cluster_branch",
        "varname", "varval", "unit", "unit_arg",
    )

    def __init__(self, type=None):
        self.routine = None
        self.type = type
        self.label = ""
        self.flag = ""
        self.move_to = None
        self.next_cluster_branch = None
        self.varname = ""
        self.varval = ""
        self.unit = ""
        self.unit_arg = ""

    @staticmethod
    def IF_BRANCH(flag):
        p = Instruction(INS_TYPE.IF_BRANCH)
        p.flag = flag
        return p

    @staticmethod
    def IF_BRANCH_ASSIGNED(flag, branch=None):
        p = Instruction(INS_TYPE.IF_BRANCH_ASSIGNED)
        p.flag = flag
        p.move_to = branch
        return p

    @staticmethod
    def NEXT(flag):
        p = Instruction(INS_TYPE.NEXT)
        p.flag = flag
        return p

    @staticmethod
    def SKIP(label):
        p = Instruction(INS_TYPE.SKIP)
        p.move_to = label
        return p

    @staticmethod
    def LABEL(label):
        p = Instruction(INS_TYPE.LABEL)
        p.label = label
        return p

    @staticmethod
    def JMP(jmp):
        p = Instruction(INS_TYPE.JMP)
        p.move_to = jmp
        return p

    @staticmethod
    def REV_JMP():
        return Instruction(INS_TYPE.REV_JMP)

    @staticmethod
    def INPUT():
        return Instruction(INS_TYPE.INPUT)

    @staticmethod
    def REV_INPUT():
        return Instruction(INS_TYPE.REV_INPUT)

    @staticmethod
    def OUTPUT():
        return Instruction(INS_TYPE.OUTPUT)

    @staticmethod
    def REV_OUTPUT():
        return Instruction(INS_TYPE.REV_OUTPUT)

    @staticmethod
    def DUP():
        return Instruction(INS_TYPE.DUP)

    @staticmethod
    def END():
        return Instruction(INS_TYPE.END)

    @staticmethod
    def VAR(name, val):
        ins = Instruction(INS_TYPE.VAR)
        ins.varname = name
        ins.varval = str(val)
        return ins

    @staticmethod
    def UNIT_CALL(unitname, arg=""):
        ins = Instruction(INS_TYPE.UNIT_CALL)
        ins.unit = unitname
        ins.unit_arg = arg
        return ins


# ---------------------------------------------------------------------------
# Generator.cc -- string emission (tab_count starts at 1; add_spaces = 2*tab)
# ---------------------------------------------------------------------------

class Generator:
    def __init__(self):
        self.tab_count = 1
        self._parts: List[str] = []

    def _w(self, s):
        self._parts.append(s)

    def _spaces(self):
        self._w("  " * self.tab_count)
        return self

    def program_start_to(self, entry):
        self._w("PROGRAM_START_TO ENTRY@" + entry)
        return self.ln()

    def routine_start(self, name):
        self._w("ROUTINE " + name + "{")
        return self.ln()

    def routine_end(self):
        self._w("}")
        return self

    def flag(self, name, val):
        self._w("FLAG " + str(val) + "/2, " + name)
        return self.ln()

    def label(self, name):
        self._w(name + ":")
        return self.ln()

    def djmp(self, varname):
        self.label(LABEL_DJMP(varname))._spaces()
        self._w("DJMP " + varname)
        return self.ln()

    def opr(self, varname):
        self.label(LABEL_OPR(varname))._spaces()
        self._w("OPR " + varname)
        return self.ln()

    def rot(self, varname):
        self.label(LABEL_ROT(varname)).next(FLAG_REV_OPR_ROT)._spaces()
        self._w("ROT")
        return self.ln()

    def ind_opr(self, varname):
        self.label(LABEL_IND_OPR(varname)).next(FLAG_REV_IND_OPR)._spaces()
        self._w("IND_OPR " + varname)
        return self.ln()

    def rev_opr(self):
        self._spaces()
        self._w("REV OPR")
        return self.ln()

    def rev_rot(self):
        self._spaces()
        self._w("REV ROT")
        return self.ln()

    def dup(self):
        self._spaces()
        self._w("DUP")
        return self.ln()

    def end(self):
        self._spaces()
        self._w("END")
        return self.ln()

    def skip(self, labelname):
        self._spaces()
        self._w("SKIP " + labelname)
        return self.ln()

    def var(self, varname, val):
        self._w(varname + ":" + str(val))
        return self.ln()

    def if_branch(self, flag, branch):
        self._spaces()
        self._w("IF " + flag)
        self.ln()._spaces()
        self._w("BRANCH " + branch)
        return self.ln()

    def next(self, flag):
        self._spaces()
        self._w("NEXT " + flag)
        return self.ln()

    def output(self):
        self._spaces()
        self._w("OUTPUT")
        return self.ln()

    def input(self):
        self._spaces()
        self._w("INPUT")
        return self.ln()

    def rev_output(self):
        self._spaces()
        self._w("REV OUTPUT")
        return self.ln()

    def rev_input(self):
        self._spaces()
        self._w("REV INPUT")
        return self.ln()

    def jmp(self, jmp):
        self._spaces()
        self._w("JMP " + jmp)
        return self.ln()

    def rev_jmp(self):
        self._spaces()
        self._w("REV JMP")
        return self.ln()

    def ln(self):
        self._w("\n")
        return self

    def raw(self, s):
        self._w(s)
        return self

    def unit_call(self, unit, unit_arg):
        self._spaces()
        self._w(unit)
        if len(unit_arg) > 0:
            self._w(" " + unit_arg)
        self._w("\n")
        return self

    def output_code(self) -> str:
        # Mirrors ``std::cout << code.str() << std::endl;`` -- one trailing newline.
        return "".join(self._parts) + "\n"


# ---------------------------------------------------------------------------
# Variable.cc
# ---------------------------------------------------------------------------

class Variable:
    __slots__ = ("name", "routine", "init_val", "is_defined")

    def __init__(self, name, init_val, routine):
        self.name = name
        self.init_val = str(init_val)
        self.routine = routine
        self.is_defined = True


# ---------------------------------------------------------------------------
# Routine.cc
# ---------------------------------------------------------------------------

class Routine:
    def __init__(self, program, name):
        self.program = program
        self.name = name
        ins = Instruction.LABEL("ENTRY")
        ins.routine = self
        self._entry_label = ins

        self.blocks: List["CodeBlock"] = []
        self._current_block: Optional["CodeBlock"] = None
        self.temporary_variables: List[Variable] = []
        self.main_block: Optional["CodeBlock"] = None

        self.num_of_repeat_nested = 0
        # variables: name -> Variable, insertion order preserved; iterated sorted.
        self.variables: Dict[str, Variable] = {}

        self.var_cluster_branches: Dict[str, List[Instruction]] = {}
        self.output_cluster_branches: List[Instruction] = []
        self.input_cluster_branches: List[Instruction] = []
        self.set_cluster_branches: Dict[str, List[Instruction]] = {}
        self.reset_cluster_branches: Dict[str, List[Instruction]] = {}
        self.switch_branches: Dict[str, List[Instruction]] = {}

        self.labels: Dict[str, Instruction] = {}
        self.is_using_ind_opr: Dict[str, bool] = {}

        self.is_implemented = False
        self.VAR_RETURN_ADDR: Optional[Variable] = None

        if name != MAIN_ROUTINE and name != GLOBAL_ROUTINE:
            self.VAR_RETURN_ADDR = self.add_var(FUNC_RETURN_ADDR, 0)

    def add_var(self, name, val) -> Variable:
        vars_ = self.variables
        if name in vars_:
            var = vars_[name]
            if var.is_defined:
                raise Mg2McError("Variable '" + name + "' is already defined.",
                                 self.program.current_line)
            else:
                var.init_val = str(val)
                var.is_defined = True
                return var
        inst = Instruction.LABEL(name)
        inst.routine = self
        self.labels[name] = inst
        v = Variable(name, val, self)
        vars_[name] = v
        return v

    def current_block(self):
        return self._current_block

    def add_block(self):
        block = CodeBlock(self.program, self)
        if not self.blocks:
            self.main_block = block
        self.blocks.append(block)
        self._current_block = block

    def pop_block(self):
        block = self.blocks.pop()
        if not self.blocks:
            self._current_block = None
        else:
            self._current_block = self.blocks[-1]
        return block

    def entry_label(self):
        return self._entry_label

    def get_temporary_variables(self, n):
        size = len(self.temporary_variables)
        if n > size:
            for i in range(size, n):
                v = "TEMP" + str(i)
                self.temporary_variables.append(self.add_var(v, 0))
        return self.temporary_variables

    def end(self):
        end = Instruction.END()
        end.routine = self
        self.main_block.add_main_instruction(end)

    # -- get_move_to_label -------------------------------------------------
    def get_move_to_label(self, ins):
        move_to = ins.move_to
        if not move_to or move_to.routine is None:
            raise Mg2McError(
                "A Instruction is not assigned to a Routine. Something wrong.")
        label = move_to.label
        if move_to.routine is not self:
            label += "@" + move_to.routine.name
        return label

    # -- generate ----------------------------------------------------------
    def generate(self, g: Generator):
        if self.main_block is None:
            # Declared via PROTO but never defined via DEF: upstream dereferences a
            # null main_block and SIGSEGVs.  Raise a clear error instead.
            raise Mg2McError(
                "Routine '" + self.name +
                "' is declared (PROTO) but never defined (DEF).")

        g.routine_start(self.name).label(self.entry_label().label)

        use_ind_opr = len(self.program.ind_opr_branches) > 0
        if use_ind_opr and self.name == MAIN_ROUTINE:
            g.if_branch(FLAG_REV_IND_OPR, LABEL_REV_IND_OPR).next(FLAG_REV_IND_OPR)

        self.generate_instructions(g, self.main_block.main_instructions)

        for varname in sorted(self.variables.keys()):
            var = self.variables[varname]
            if not var.is_defined:
                raise Mg2McError(
                    "Variable '" + varname + "@" + var.routine.name +
                    "' is not defined.")
            init_val = var.init_val
            var_cluster_branches = self.var_cluster_branches.get(varname, [])
            switch_branches = self.switch_branches.get(varname, [])
            using_ind_opr = self.is_using_ind_opr.get(varname, False)
            using_djmp = self.program.is_using_djmp
            label_rev_opr = LABEL_REV_OPR(varname)
            label_end_rev = LABEL_END_REV(varname)

            if using_ind_opr:
                g.ind_opr(varname)
            if using_djmp:
                g.djmp(varname)
            if len(var_cluster_branches) > 0:
                g.opr(varname).rot(varname)

            g.var(varname, init_val)

            if len(switch_branches) > 0:
                label_set_case0 = "L_" + varname + "_SET_CASE0"
                label_set_case1 = "L_" + varname + "_SET_CASE1"
                label_set_case2 = "L_" + varname + "_SET_CASE2"
                label_switch_branches = "L_" + varname + "_SWITCH_BRANCHES"
                g.skip(label_set_case2).skip(label_set_case1).skip(label_set_case0)
                g.label(label_set_case0).next(FLAG_CASE0).skip(label_switch_branches)
                g.label(label_set_case1).next(FLAG_CASE1).skip(label_switch_branches)
                g.label(label_set_case2).next(FLAG_CASE2).skip(label_switch_branches)
                g.label(label_switch_branches)
                self.generate_instructions(g, switch_branches)
                g.next(FLAG_CASE2)

            if len(var_cluster_branches) > 0:
                (g.if_branch(FLAG_REV_OPR_ROT, label_rev_opr).rev_rot()
                  .skip(label_end_rev)
                  .label(label_rev_opr).rev_opr().next(FLAG_REV_OPR_ROT)
                  .label(label_end_rev))
                self.generate_branches(g, var_cluster_branches)

        if len(self.output_cluster_branches) > 0:
            g.label(LABEL_OUTPUT).output().dup().rev_output()
            self.generate_branches(g, self.output_cluster_branches)
        if len(self.input_cluster_branches) > 0:
            g.label(LABEL_INPUT).input().dup().rev_input()
            self.generate_branches(g, self.input_cluster_branches)
        for flagname in sorted(self.set_cluster_branches.keys()):
            g.label(LABEL_SET(flagname)).if_branch(flagname, LABEL_SET(flagname))
            self.generate_branches(g, self.set_cluster_branches[flagname])
        for flagname in sorted(self.reset_cluster_branches.keys()):
            (g.label(LABEL_RESET(flagname))
              .if_branch(flagname, LABEL_RESET(flagname)).next(flagname))
            self.generate_branches(g, self.reset_cluster_branches[flagname])

        if use_ind_opr and self.name == MAIN_ROUTINE:
            g.raw(RAW_IND_OPR_REV)
            self.generate_branches(g, self.program.ind_opr_branches)

        g.routine_end()

    def generate_instructions(self, g, instructions):
        for ins in instructions:
            if ins.label != "":
                g.label(ins.label)
            t = ins.type
            if t == INS_TYPE.IF_BRANCH or t == INS_TYPE.IF_BRANCH_ASSIGNED:
                g.if_branch(ins.flag, self.get_move_to_label(ins))
            elif t == INS_TYPE.NEXT:
                g.next(ins.flag)
            elif t == INS_TYPE.END:
                g.end()
            elif t == INS_TYPE.INPUT:
                g.input()
            elif t == INS_TYPE.REV_INPUT:
                g.rev_input()
            elif t == INS_TYPE.OUTPUT:
                g.output()
            elif t == INS_TYPE.REV_OUTPUT:
                g.rev_output()
            elif t == INS_TYPE.DUP:
                g.dup()
            elif t == INS_TYPE.JMP:
                g.jmp(self.get_move_to_label(ins))
            elif t == INS_TYPE.REV_JMP:
                g.rev_jmp()
            elif t == INS_TYPE.SKIP:
                g.skip(self.get_move_to_label(ins))
            elif t == INS_TYPE.VAR:
                g.var(ins.varname, ins.varval)
            elif t == INS_TYPE.UNIT_CALL:
                g.unit_call(ins.unit, ins.unit_arg)
            elif t == INS_TYPE.LABEL:
                pass

    def generate_branches(self, g, branches):
        for ins in branches:
            flag = ins.flag
            if ins.next_cluster_branch is None:
                g.if_branch(flag, self.get_move_to_label(ins))
                g.next(flag)
            else:
                next_flag = ins.next_cluster_branch.flag
                g.next(next_flag)
                g.if_branch(flag, self.get_move_to_label(ins))
                g.next(flag)
                g.next(next_flag)


# ---------------------------------------------------------------------------
# CodeBlock.cc
# ---------------------------------------------------------------------------

class CodeBlock:
    def __init__(self, program, routine):
        self.program = program
        self.routine = routine
        self.last_instructions: List[Instruction] = []
        self.last_cluster_branches: List[Instruction] = []
        self.main_instructions: List[Instruction] = []
        self.break_instructions: List[List[Instruction]] = []

    def merge_block(self, block):
        self.last_instructions = block.last_instructions
        self.last_cluster_branches = block.last_cluster_branches
        if len(self.break_instructions) < len(block.break_instructions):
            while len(self.break_instructions) < len(block.break_instructions):
                self.break_instructions.append([])
        for i, instructions in enumerate(block.break_instructions):
            self.break_instructions[i].extend(instructions)
        self.main_instructions.extend(block.main_instructions)

    def rot(self, var):
        self.rot_opr(var, LABEL_ROT(var.name))

    def opr(self, var):
        self.rot_opr(var, LABEL_OPR(var.name))

    def djmp(self, var):
        self.add_main_instruction(Instruction.NEXT(FLAG_JMP))
        label = Instruction.LABEL(LABEL_DJMP(var.name))
        label.routine = self.routine
        if_branch = Instruction.IF_BRANCH_ASSIGNED(FLAG_JMP, label)
        if_branch.routine = self.routine
        self.cut_branch_chain()
        self.add_main_instruction(if_branch)

    def rot_opr(self, var, label):
        rt = var.routine
        self.add_cluster_branch(
            rt.var_cluster_branches.setdefault(var.name, []), label, rt)

    def ind_opr(self, var):
        routine = var.routine
        self.add_cluster_branch(
            self.program.ind_opr_branches, LABEL_IND_OPR(var.name), routine)
        routine.is_using_ind_opr[var.name] = True

    def add_cluster_branch(self, target_cluster_branches, label, routine=None):
        if routine is None:
            routine = self.routine
        labels = self.routine.labels
        if label not in labels:
            p = Instruction.LABEL(label)
            p.routine = routine
            labels[label] = p
        op = Instruction.IF_BRANCH(self.program.create_branch_flag())
        op.label = label
        op.routine = routine
        target_cluster_branches.append(op)

        if len(self.last_cluster_branches) == 0:
            flag_on = Instruction.NEXT(op.flag)
            self.add_main_instruction(flag_on)
            self.last_instructions = [flag_on]
        else:
            for it in self.last_cluster_branches:
                it.next_cluster_branch = op
        self.last_cluster_branches = [op]
        self.jump_to(op)

    def add_main_instruction(self, inst):
        for last in self.last_instructions:
            if last.type == INS_TYPE.IF_BRANCH:
                last.move_to = inst
                if inst.label == "":
                    inst.label = self.program.get_next("LABEL")
                last.type = INS_TYPE.IF_BRANCH_ASSIGNED
        inst.routine = self.routine
        self.main_instructions.append(inst)

    def jump_to(self, inst):
        self.jump_to_next()
        for last in self.last_instructions:
            last.type = INS_TYPE.IF_BRANCH_ASSIGNED
            last.move_to = inst
        self.last_instructions = [inst]

    def jump_to_next(self):
        flag = False
        lst: List[Instruction] = []
        back_to_main = self.program.option.back_to_main()

        next_ins = Instruction.NEXT(FLAG_JMP)
        next_ins.routine = self.routine

        for last in self.last_instructions:
            if last.type != INS_TYPE.IF_BRANCH:
                flag = True
            else:
                if back_to_main:
                    next_ins.label = self.program.get_next("JMP_BACK")
                    last.type = INS_TYPE.IF_BRANCH_ASSIGNED
                    last.move_to = next_ins
                else:
                    lst.append(last)
        if (len(self.last_instructions) == 0) or flag or back_to_main:
            self.add_main_instruction(next_ins)
            jmp = Instruction.IF_BRANCH(FLAG_JMP)
            self.add_main_instruction(jmp)
            lst = [jmp]
        self.last_instructions = lst

    def cut_branch_chain(self):
        self.last_instructions = []
        self.last_cluster_branches = []

    def output(self):
        if self.program.option.use_op_block():
            return self.add_cluster_branch(
                self.routine.output_cluster_branches, LABEL_OUTPUT)
        else:
            self.add_main_instruction(Instruction.OUTPUT())
            self.add_main_instruction(Instruction.DUP())
            rev = Instruction.REV_OUTPUT()
            self.add_main_instruction(rev)
            self.last_instructions = [rev]

    def input(self):
        if self.program.option.use_op_block():
            return self.add_cluster_branch(
                self.routine.input_cluster_branches, LABEL_INPUT)
        else:
            self.add_main_instruction(Instruction.INPUT())
            self.add_main_instruction(Instruction.DUP())
            rev = Instruction.REV_INPUT()
            self.add_main_instruction(rev)
            self.last_instructions = [rev]

    def set(self, flag):
        if self.program.option.use_op_block():
            self.add_cluster_branch(
                self.routine.set_cluster_branches.setdefault(flag, []),
                LABEL_SET(flag))
        else:
            label = self.program.get_next("SET")
            if_branch = Instruction.IF_BRANCH_ASSIGNED(flag, None)
            if_branch.label = label
            if_branch.move_to = if_branch
            self.add_main_instruction(if_branch)
            self.last_instructions = [if_branch]

    def reset(self, flag):
        if self.program.option.use_op_block():
            self.add_cluster_branch(
                self.routine.reset_cluster_branches.setdefault(flag, []),
                LABEL_RESET(flag))
        else:
            if_branch = Instruction.IF_BRANCH_ASSIGNED(flag, None)
            if_branch.label = self.program.get_next("RESET")
            if_branch.move_to = if_branch
            self.add_main_instruction(if_branch)
            next_ins = Instruction.NEXT(flag)
            self.add_main_instruction(next_ins)
            self.last_instructions = [next_ins]

    def end(self):
        end = Instruction.END()
        end.label = LABEL_RETURN
        self.add_main_instruction(end)
        self.last_instructions = [end]

    def next(self, flagname):
        inst = Instruction.NEXT(flagname)
        self.add_main_instruction(inst)
        self.last_instructions = [inst]

    def repeat_break(self, num):
        routine = self.routine
        if num > routine.num_of_repeat_nested:
            raise Mg2McError("There is no 'REPEAT' to break",
                             self.program.current_line)
        self.jump_to_next()
        for last in self.last_instructions:
            if len(self.break_instructions) < num:
                while len(self.break_instructions) < num:
                    self.break_instructions.append([])
            self.break_instructions[num - 1].append(last)
        self.cut_branch_chain()

    def if_statement(self, if_flag, if_block, else_block):
        else_label = Instruction.LABEL(self.program.get_next("ELSE"))
        end_label = Instruction.LABEL(self.program.get_next("IFEND"))

        next_ins = Instruction.NEXT(if_flag)
        next_ins.label = self.program.get_next("IF")
        self.add_main_instruction(next_ins)

        if_branch = Instruction.IF_BRANCH_ASSIGNED(if_flag, else_label)
        self.add_main_instruction(if_branch)
        self.merge_block(if_block)
        self.jump_to(end_label)
        # (upstream stores last_if_instructions but never reads it again)

        self.last_instructions = []
        last_if_cluster_branches = self.last_cluster_branches
        self.add_main_instruction(else_label)
        self.merge_block(else_block)

        self.add_main_instruction(end_label)
        self.last_instructions = [end_label]
        # std::list::merge on pointer values only affects order, never membership;
        # order of last_cluster_branches never reaches the output, so extend.
        self.last_cluster_branches = self.last_cluster_branches + list(
            last_if_cluster_branches)

    def repeat(self, repeat_num, block):
        rep_labelname = self.program.get_next("REPEAT")
        repeat_label = Instruction.LABEL(rep_labelname)
        repeat_end_label = Instruction.LABEL(self.program.get_next("REPEATEND"))
        block_start_label = Instruction.LABEL(rep_labelname + "_BLOCK_START")

        if repeat_num != INF_EXPR:
            flags: List[str] = []
            while repeat_num > 0:
                bit = repeat_num % 2
                repeat_num = repeat_num >> 1
                counter_flag = self.program.get_next(rep_labelname + "_COUNTER")
                self.program.add_flag(counter_flag, FLAG_OFF)
                flags.append(counter_flag)
                bit = 1 - bit
                if bit == FLAG_ON:
                    self.set(counter_flag)
                else:
                    self.reset(counter_flag)
            self.add_main_instruction(repeat_label)
            for i in range(len(flags)):
                if_branch = Instruction.IF_BRANCH_ASSIGNED(flags[i], block_start_label)
                self.add_main_instruction(if_branch)
            self.jump_to(repeat_end_label)
        else:
            self.add_main_instruction(repeat_label)

        if len(block.break_instructions) > 0:
            for last in block.break_instructions[0]:
                last.type = INS_TYPE.IF_BRANCH_ASSIGNED
                last.move_to = repeat_end_label
            block.break_instructions.pop(0)
        self.add_main_instruction(block_start_label)
        self.merge_block(block)

        self.jump_to(repeat_label)
        self.cut_branch_chain()
        self.add_main_instruction(repeat_end_label)

    def switch_statement(self, var, case0_block, case1_block, case2_block):
        varname = var.name
        switch_name = self.program.get_next("SWITCH_" + varname)
        routine = var.routine
        labels = routine.labels
        var_label_inst = labels[varname]
        self.program.add_flag(switch_name, 1)
        switch_start_label_name = switch_name + "_START"
        next_ins = Instruction.NEXT(switch_name)
        next_ins.label = switch_start_label_name
        self.add_main_instruction(next_ins)
        jmp = Instruction.JMP(var_label_inst)
        self.add_main_instruction(jmp)
        self.last_instructions = []
        case0_label_name = switch_name + "_CASE0"
        case1_label_name = switch_name + "_CASE1"
        case2_label_name = switch_name + "_CASE2"
        switch_end_label = Instruction.LABEL(switch_name + "_END")
        case2 = Instruction.LABEL(case2_label_name)
        case1 = Instruction.LABEL(case1_label_name)
        case0 = Instruction.LABEL(case0_label_name)
        case1.label = case1_label_name
        self.add_main_instruction(case0)
        self.add_main_instruction(Instruction.REV_JMP())
        self.add_main_instruction(Instruction.IF_BRANCH_ASSIGNED(FLAG_CASE0, case1))
        self.merge_block(case0_block)
        self.jump_to(switch_end_label)

        self.add_main_instruction(case1)
        self.add_main_instruction(Instruction.NEXT(FLAG_CASE0))
        self.add_main_instruction(Instruction.IF_BRANCH_ASSIGNED(FLAG_CASE1, case2))
        self.merge_block(case1_block)
        self.jump_to(switch_end_label)

        self.add_main_instruction(case2)
        self.add_main_instruction(Instruction.NEXT(FLAG_CASE1))
        self.add_main_instruction(Instruction.NEXT(FLAG_CASE2))
        self.merge_block(case2_block)

        self.add_main_instruction(switch_end_label)

        routine.switch_branches.setdefault(varname, []).append(
            Instruction.IF_BRANCH_ASSIGNED(switch_name, case0))
        routine.switch_branches[varname].append(Instruction.NEXT(switch_name))

    def call(self, name):
        program = self.program
        if name not in program.routines:
            raise Mg2McError("Undefined routine : " + name,
                             self.program.current_line)
        target_routine = program.routines[name]
        temps = self.routine.get_temporary_variables(1)
        return_to_addr_str = program.get_next("RETURN_TO_ADDR")
        return_to_str = program.get_next("RETURN_TO")
        return_to_addr = self.routine.add_var(return_to_addr_str, return_to_str)
        z = temps[0]
        self.rot(program.VAR_CON1)
        self.opr(z)
        self.opr(z)
        self.opr(target_routine.VAR_RETURN_ADDR)
        self.opr(target_routine.VAR_RETURN_ADDR)
        self.rot(program.VAR_CON2)
        self.opr(return_to_addr)
        self.rot(program.VAR_CON2)
        self.opr(return_to_addr)
        self.opr(z)
        self.opr(target_routine.VAR_RETURN_ADDR)

        entry_ins = target_routine.entry_label()
        self.jump_to(entry_ins)

        self.cut_branch_chain()
        call_inst = Instruction.UNIT_CALL("REV_DJMP")
        call_inst.label = return_to_str
        self.add_main_instruction(call_inst)

    def func_return(self):
        if self.routine.name == MAIN_ROUTINE:
            self.add_main_instruction(Instruction.END())
        else:
            self.program.is_using_djmp = True
            self.djmp(self.routine.VAR_RETURN_ADDR)

    def flip(self, name):
        self.add_main_instruction(Instruction.NEXT(name))


# ---------------------------------------------------------------------------
# Option.cc
# ---------------------------------------------------------------------------

OP_STYLES = ("cluster", "inline")
JMP_STYLES = ("main", "direct")


class Option:
    """The reference tool's Option singleton, driven by a code-generation style.

    ``Option.h`` initialises all four fields to ``true``; each of ``main.cc``'s
    getopt cases clears exactly one of them, and this constructor does the same:

        op_style="cluster"  ->  -c  ->  op_inline    = False
        op_style="inline"   ->  -i  ->  op_block     = False
        jmp_style="main"    ->  -m  ->  jmp_directly = False
        jmp_style="direct"  ->  -d  ->  jmp_main     = False

    Either way one of the two fields each decision method inspects is False, so
    the method takes a deterministic branch and never reaches ``get_rand()``
    (``std::mt19937``); the ``-s`` seed is irrelevant for all four styles.  The
    rand branches are kept as guards: upstream reaches them when *neither* switch
    of a pair is given, mixing both styles per decision point, which is not ported.
    """

    def __init__(self, op_style: str = "cluster", jmp_style: str = "main"):
        if op_style not in OP_STYLES:
            raise ValueError("unknown op_style {!r} (use {})".format(
                op_style, " or ".join(repr(s) for s in OP_STYLES)))
        if jmp_style not in JMP_STYLES:
            raise ValueError("unknown jmp_style {!r} (use {})".format(
                jmp_style, " or ".join(repr(s) for s in JMP_STYLES)))
        self.op_style = op_style
        self.jmp_style = jmp_style
        # Option.h defaults, then clear the field main.cc's getopt case clears.
        self.op_block = True
        self.op_inline = True
        self.jmp_main = True
        self.jmp_directly = True
        if op_style == "cluster":
            self.op_inline = False   # -c
        else:
            self.op_block = False    # -i
        if jmp_style == "main":
            self.jmp_directly = False  # -m
        else:
            self.jmp_main = False      # -d

    def back_to_main(self):
        if self.jmp_main:
            if self.jmp_directly:
                raise RuntimeError("rand() path is only reached with neither -m "
                                   "nor -d; the mt19937 style mixing is not "
                                   "ported")
            return True
        return False

    def use_op_block(self):
        if self.op_block:
            if self.op_inline:
                raise RuntimeError("rand() path is only reached with neither -c "
                                   "nor -i; the mt19937 style mixing is not "
                                   "ported")
            return True
        return False


# ---------------------------------------------------------------------------
# Program.cc
# ---------------------------------------------------------------------------

class Program:
    def __init__(self, option: Optional[Option] = None):
        self.option = option if option is not None else Option()
        self.seq_ids: Dict[str, int] = {}
        self.flags: Dict[str, int] = {}
        self.routines: Dict[str, Routine] = {}
        self.current_routine: Optional[Routine] = None
        self.ind_opr_branches: List[Instruction] = []
        self.is_using_djmp = False
        self.global_routine: Optional[Routine] = None
        # Tracks the most recently consumed token's line, for error messages.
        self.current_line: Optional[int] = None

        self.add_flag(FLAG_JMP, FLAG_OFF)
        self.add_flag(FLAG_REV_OPR_ROT, FLAG_ON)
        self.add_flag(FLAG_CASE0, FLAG_ON)
        self.add_flag(FLAG_CASE1, FLAG_ON)
        self.add_flag(FLAG_CASE2, FLAG_ON)
        r = self.add_routine(GLOBAL_ROUTINE, False)
        self.global_routine = r
        self.VAR_CON0 = r.add_var("CON0", CON0_VAL)
        self.VAR_CON1 = r.add_var("CON1", CON1_VAL)
        self.VAR_CON2 = r.add_var("CON2", CON2_VAL)
        r.add_var("BASE", 0)
        r.add_block()
        r.pop_block()

    def add_flag(self, flag_name, val):
        self.flags[flag_name] = val

    def add_routine(self, name, prototype_only):
        defined = name in self.routines
        if defined and self.routines[name].is_implemented:
            raise Mg2McError("Routine '" + name + "' is already defined.",
                             self.current_line)
        if not defined:
            self.routines[name] = Routine(self, name)
        self.routines[name].is_implemented = not prototype_only
        self.current_routine = self.routines[name]
        return self.current_routine

    def create_branch_flag(self):
        flag = self.get_next("FLAG")
        self.add_flag(flag, FLAG_OFF)
        return flag

    def get_next(self, seq_key):
        n = self.seq_ids.get(seq_key, 0)
        self.seq_ids[seq_key] = n + 1
        return seq_key + str(n)

    def check_flag(self, flag_name):
        if flag_name not in self.flags:
            raise Mg2McError("Undefined flag : " + flag_name, self.current_line)

    def generate(self) -> str:
        g = Generator()
        g.program_start_to("MAIN")
        for name in sorted(self.flags.keys()):
            g.flag(name, self.flags[name])
        use_ind_opr = len(self.ind_opr_branches) > 0
        if use_ind_opr:
            g.raw(RAW_IND_OPR_FLAGS)
            g.raw(RAW_IND_OPR_UNIT)
        if self.is_using_djmp:
            g.raw(RAW_DJMP_UNIT)
        for name in sorted(self.routines.keys()):
            self.routines[name].generate(g)
            g.ln()
        return g.output_code()


# ---------------------------------------------------------------------------
# scanner.ll -- longest-match tokenizer (flex semantics: longest wins, ties go
# to the earliest listed rule)
# ---------------------------------------------------------------------------

import re as _re

_KEYWORDS = [
    "DEF", "VAR", "FLAG", "OPR", "ROT", "SET", "RESET", "END", "IF", "ELSE",
    "REPEAT", "BREAK", "SWITCH", "CASE0", "CASE1", "CASE2", "OUTPUT", "INPUT",
    "TRUE", "FALSE", "INF", "GOTO", "IND_OPR", "CALL", "RETURN", "PROTO", "FLIP",
]
_SPECIAL_VARS = ["CON0", "CON1", "CON2", "BASE", "RETURN_ADDR"]


class _Token:
    __slots__ = ("type", "value", "line")

    def __init__(self, type, value, line):
        self.type = type
        self.value = value
        self.line = line


def _build_rules():
    rules = []
    for kw in _KEYWORDS:
        rules.append((_re.compile(_re.escape(kw)), kw))
    rules.append((_re.compile(r"="), "EQ"))
    rules.append((_re.compile(r":"), "COLON"))
    rules.append((_re.compile(r"@"), "AT"))
    # D_NUMBER: [0-9] | [1-9][0-9]*  -- ordered longest-first for Python's re
    rules.append((_re.compile(r"[1-9][0-9]*|[0-9]"), "D_NUMBER"))
    rules.append((_re.compile(r"[0-9]+t"), "T_NUMBER"))
    for sv in _SPECIAL_VARS:
        rules.append((_re.compile(_re.escape(sv)), sv))
    rules.append((_re.compile(r"[a-zA-Z][0-9a-zA-Z_]*"), "IDENT"))
    rules.append((_re.compile(r"#[^\n]+"), "SKIP"))
    rules.append((_re.compile(r"[ \t\n]+"), "SKIP"))
    rules.append((_re.compile(r"."), "UNKNOWN"))
    return rules


_RULES = _build_rules()


def _tokenize(src: str) -> List[_Token]:
    tokens: List[_Token] = []
    i = 0
    n = len(src)
    line = 1
    while i < n:
        best_len = 0
        best_kind = None
        best_text = None
        for regex, kind in _RULES:
            m = regex.match(src, i)
            if m:
                length = m.end() - i
                if length > best_len:  # strict: first rule reaching max length wins
                    best_len = length
                    best_kind = kind
                    best_text = m.group()
        if best_len == 0:
            # Unreachable (the '.' / whitespace rules cover every character), but
            # stay safe: skip one char.
            if src[i] == "\n":
                line += 1
            i += 1
            continue
        start_line = line
        line += best_text.count("\n")
        i += best_len
        if best_kind == "SKIP" or best_kind == "UNKNOWN":
            # Non-fatal: unknown characters (e.g. a bare '#') are skipped, exactly
            # like scanner.ll's '.' rule.
            continue
        tokens.append(_Token(best_kind, best_text, start_line))
    tokens.append(_Token("EOF", "", line))
    return tokens


# ---------------------------------------------------------------------------
# parser.yy -- recursive-descent driver reproducing bison's reduction order
# ---------------------------------------------------------------------------

_STATEMENT_STARTERS = frozenset({
    "OPR", "ROT", "IND_OPR", "OUTPUT", "INPUT", "SET", "RESET", "FLIP",
    "IF", "REPEAT", "BREAK", "SWITCH", "CALL", "RETURN",
})
_NUMBER_TOKENS = frozenset({"D_NUMBER", "T_NUMBER"})


class _Parser:
    def __init__(self, tokens, program):
        self.tokens = tokens
        self.pos = 0
        self.p = program

    # -- token helpers -----------------------------------------------------
    def peek(self):
        return self.tokens[self.pos]

    def peek_type(self):
        return self.tokens[self.pos].type

    def advance(self):
        t = self.tokens[self.pos]
        self.pos += 1
        self.p.current_line = t.line
        return t

    def expect(self, type_):
        t = self.peek()
        if t.type != type_:
            raise Mg2McError(
                "syntax error: expected %s but found '%s'" % (type_, t.value),
                t.line)
        return self.advance()

    def error(self, msg):
        t = self.peek()
        raise Mg2McError("syntax error: " + msg + " (near '%s')" % t.value, t.line)

    # -- grammar -----------------------------------------------------------
    def parse(self) -> str:
        self.global_var_flag_decl_list()
        self.prototypes()
        self.routines()
        if self.peek_type() != "EOF":
            self.error("unexpected input")
        return self.p.generate()

    def global_var_flag_decl_list(self):
        while self.peek_type() in ("VAR", "FLAG"):
            if self.peek_type() == "VAR":
                self.var_decl()
            else:
                self.advance()  # FLAG
                name = self.escaped_ident()
                self.expect("EQ")
                val = self.bool_const()
                self.p.add_flag(name, val)

    def prototypes(self):
        while self.peek_type() == "PROTO":
            self.advance()
            name = self.expect("IDENT").value
            self.p.add_routine(name, True)

    def routines(self):
        while self.peek_type() == "DEF":
            self.routine()

    def routine(self):
        self.expect("DEF")
        name = self.expect("IDENT").value
        self.p.add_routine(name, False)
        self.var_decl_list()
        self.block()
        self.expect("END")
        self.p.current_routine.end()

    def var_decl_list(self):
        while self.peek_type() == "VAR":
            self.var_decl()

    def var_decl(self):
        self.expect("VAR")
        name = self.escaped_ident()
        self.expect("EQ")
        num = self.number()
        self.p.current_routine.add_var(name, num)

    def block(self):
        self.p.current_routine.add_block()
        self.statements()
        return self.p.current_routine.pop_block()

    def statements(self):
        while self.peek_type() in _STATEMENT_STARTERS:
            self.statement()

    def statement(self):
        t = self.peek_type()
        if t == "OPR":
            self.advance()
            var = self.variable()
            self.p.current_routine.current_block().opr(var)
        elif t == "ROT":
            self.advance()
            var = self.variable()
            self.p.current_routine.current_block().rot(var)
        elif t == "IND_OPR":
            self.advance()
            var = self.variable()
            self.p.current_routine.current_block().ind_opr(var)
        elif t == "OUTPUT":
            self.advance()
            self.p.current_routine.current_block().output()
        elif t == "INPUT":
            self.advance()
            self.p.current_routine.current_block().input()
        elif t == "SET":
            self.advance()
            f = self.flag()
            self.p.current_routine.current_block().set(f)
        elif t == "RESET":
            self.advance()
            f = self.flag()
            self.p.current_routine.current_block().reset(f)
        elif t == "FLIP":
            self.advance()
            f = self.flag()
            self.p.current_routine.current_block().flip(f)
        elif t == "IF":
            self.if_statement()
        elif t == "REPEAT":
            self.repeat_statement()
        elif t == "BREAK":
            self.break_statement()
        elif t == "SWITCH":
            self.switch_statement()
        elif t == "CALL":
            self.advance()
            name = self.expect("IDENT").value
            self.p.current_routine.current_block().call(name)
        elif t == "RETURN":
            self.advance()
            self.p.current_routine.current_block().func_return()
        else:
            self.error("unexpected statement")

    def if_statement(self):
        self.expect("IF")
        f = self.flag()
        b1 = self.block()
        self.expect("ELSE")
        b2 = self.block()
        self.expect("END")
        self.p.current_routine.current_block().if_statement(f, b1, b2)

    def repeat_statement(self):
        self.expect("REPEAT")
        self.p.current_routine.num_of_repeat_nested += 1
        n = self.repeat_number()
        b = self.block()
        self.expect("END")
        self.p.current_routine.current_block().repeat(n, b)
        self.p.current_routine.num_of_repeat_nested -= 1

    def repeat_number(self):
        if self.peek_type() == "INF":
            self.advance()
            return INF_EXPR
        return self.number()

    def break_statement(self):
        self.expect("BREAK")
        if self.peek_type() in _NUMBER_TOKENS:
            n = self.number()
            self.p.current_routine.current_block().repeat_break(n)
        else:
            self.p.current_routine.current_block().repeat_break(1)

    def switch_statement(self):
        self.expect("SWITCH")
        var = self.variable()
        c0 = self.case_block("CASE0")
        c1 = self.case_block("CASE1")
        c2 = self.case_block("CASE2")
        self.expect("END")
        self.p.current_routine.current_block().switch_statement(var, c0, c1, c2)

    def case_block(self, casetok):
        if self.peek_type() == casetok:
            self.advance()
            return self.block()
        self.p.current_routine.add_block()
        return self.p.current_routine.pop_block()

    def variable(self):
        vs = self.variable_str()
        if self.peek_type() == "AT":
            self.advance()
            rname = self.expect("IDENT").value
            if rname not in self.p.routines:
                raise Mg2McError("Undefined routine : '" + rname + "'",
                                 self.p.current_line)
            routine = self.p.routines[rname]
            if vs in routine.variables:
                return routine.variables[vs]
            v = routine.add_var(vs, 0)
            v.is_defined = False
            return v
        routine = self.p.current_routine
        if vs not in routine.variables:
            if vs not in self.p.global_routine.variables:
                raise Mg2McError("Undefined variable : '" + vs + "'",
                                 self.p.current_line)
            routine = self.p.global_routine
        return routine.variables[vs]

    def variable_str(self):
        t = self.peek()
        if t.type == "IDENT":
            self.advance()
            return "U_" + t.value
        if t.type in ("CON0", "CON1", "CON2", "BASE", "RETURN_ADDR"):
            self.advance()
            return t.value
        self.error("expected variable")

    def flag(self):
        name = self.escaped_ident()
        self.p.check_flag(name)
        return name

    def escaped_ident(self):
        t = self.expect("IDENT")
        return "U_" + t.value

    def bool_const(self):
        t = self.peek()
        if t.type == "TRUE":
            self.advance()
            return FLAG_ON
        if t.type == "FALSE":
            self.advance()
            return FLAG_OFF
        self.error("expected TRUE or FALSE")

    def number(self):
        t = self.peek()
        if t.type == "D_NUMBER":
            self.advance()
            return radix_to_int(t.value, 10)
        if t.type == "T_NUMBER":
            self.advance()
            return radix_to_int(t.value[:-1], 3)
        self.error("expected number")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def translate_mg_to_mc(mg_source: str, *, op_style: str = "cluster",
                       jmp_style: str = "main") -> str:
    """Translate ``.mg`` source text to ``.mc`` (LAL) text.

    ``op_style`` picks how OUTPUT/INPUT/SET/RESET are emitted: ``"cluster"``
    (default, upstream ``-c``) shares one cluster module per operation, while
    ``"inline"`` (upstream ``-i``) expands each occurrence in place.  ``jmp_style``
    picks how continuous ROT/OPR calls chain: ``"main"`` (default, upstream ``-m``)
    returns to the main control flow between modules, ``"direct"`` (upstream ``-d``)
    jumps straight to the next one.  All four combinations are deterministic.

    With the defaults the output is byte-identical to
    ``ref/nagoya-ternary/parser -m -c -s 1 <file>``.  Raises :class:`Mg2McError` on
    any syntax or semantic error and :class:`ValueError` on an unknown style.
    """
    program = Program(Option(op_style=op_style, jmp_style=jmp_style))
    tokens = _tokenize(mg_source)
    return _Parser(tokens, program).parse()


__all__ = ["translate_mg_to_mc", "Mg2McError", "Option"]
