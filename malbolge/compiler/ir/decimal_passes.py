"""Explicit semantic lowering of unsigned decimal output to byte operations.

The generated nonrecursive formatter is ordinary typed semantic IR. It visits
the ten decimal positions of a 20-trit word, builds each power of ten using an
addition chain, and extracts digits using bounded subtraction. It needs no
multiplication, division, or remainder operation. Powers never exceed 10**9;
the addition-chain intermediates fit within the unsigned word ring.

Only PrintWordOp changes. Its existing SSA operand is passed directly to the
formatter, preserving preceding argument evaluation and checked-error order.
Constant words instead become literal output, without creating a formatter.
ReadIntOp, literal output, source slots, and their ordering are untouched.
This pass does not select itself as a default or claim target-speed benefits.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import ClassVar

from . import require_ir_support

require_ir_support()

from xdsl.context import Context
from xdsl.dialects.builtin import FileLineColLoc, IntAttr, ModuleOp, StringAttr
from xdsl.passes import ModulePass
from xdsl.rewriter import Rewriter

from .frontend import compile_python_to_semantic_ir
from .semantic import (
    CallOp, ConstOp, FuncOp, PrintLiteralOp, PrintWordOp, ProgramOp, UnboundNameOp,
    get_program, strings, verify_semantic,
)


def _private_prefix(program: ProgramOp) -> str:
    """Choose private function/slot names outside every existing namespace."""
    occupied = {name.lower() for name in strings(program.globals)}
    for func in program.body.block.ops:
        assert isinstance(func, FuncOp)
        occupied.add(func.sym_name.data.lower())
        occupied.update(name.lower() for names in (func.parameters, func.locals, func.globals)
                        for name in strings(names))
    occupied.update(op.symbol.data.lower() for op in program.walk() if isinstance(op, UnboundNameOp))
    prefix = "mbdecimal"
    while any(name.startswith(prefix) for name in occupied):
        prefix += "x"
    return prefix


def _formatter(prefix: str) -> FuncOp:
    """Build then transplant one verified typed helper, not source metadata."""
    names = {name: prefix + name for name in
             ("format", "value", "started", "exponent", "power", "index", "twice", "four", "digit")}
    source = """def {format}({value}):
    if {value} < 10:
        putchar(48 + {value})
        return
    {started} = 0
    for {exponent} in range(9, -1, -1):
        {power} = 1
        {index} = 0
        while {index} < {exponent}:
            {twice} = {power} + {power}
            {four} = {twice} + {twice}
            {power} = {four} + {four} + {twice}
            {index} = {index} + 1
        {digit} = 0
        while {value} >= {power}:
            {value} = {value} - {power}
            {digit} = {digit} + 1
        if {started} or {digit} or {exponent} == 0:
            putchar(48 + {digit})
            {started} = 1
""".format(**names)
    generated = get_program(compile_python_to_semantic_ir(source))
    helper = next(func for func in generated.body.block.ops
                  if isinstance(func, FuncOp) and func.sym_name.data == names["format"]).clone()
    assert isinstance(helper, FuncOp)
    helper.attributes["pysem.generated_by"] = StringAttr("lower-decimal-output")
    helper.attributes["pysem.decimal_prefix"] = StringAttr(prefix)
    for op in helper.walk():
        old = op.location
        line = old.line if isinstance(old, FileLineColLoc) else IntAttr(1)
        column = old.column if isinstance(old, FileLineColLoc) else IntAttr(1)
        op.location = FileLineColLoc(StringAttr("<lower-decimal-output>"), line, column)
    return helper


def _existing_formatter(program: ProgramOp) -> FuncOp | None:
    """Reuse a prior formatter only after checking its complete typed body.

    Metadata is a search hint, never evidence of formatter semantics. A changed
    or forged helper remains authoritative for its existing calls, but is not
    reused to implement newly introduced PrintWordOps.
    """
    for func in program.body.block.ops:
        if func.attributes.get("pysem.generated_by") != StringAttr("lower-decimal-output"):
            continue
        prefix = func.attributes.get("pysem.decimal_prefix")
        if not isinstance(prefix, StringAttr) or re.fullmatch(r"mbdecimalx*", prefix.data) is None:
            continue
        expected = _formatter(prefix.data)
        if func.is_structurally_equivalent(expected):
            assert isinstance(func, FuncOp)
            return func
    return None


@dataclass(frozen=True)
class LowerDecimalOutputPass(ModulePass):
    """Specialize constant decimal output and lower dynamic output to a helper.

    The pass mutates its supplied module, as required by ModulePass. The normal
    verified pipeline owns cloning. A module with no PrintWordOps is unchanged,
    making repeated applications after a complete rewrite exact no-ops.
    """

    name: ClassVar[str] = "lower-decimal-output"

    def apply(self, ctx: Context, op: ModuleOp) -> None:
        verify_semantic(op)
        program = get_program(op)
        prints = [operation for operation in program.walk() if isinstance(operation, PrintWordOp)]
        if not prints:
            return
        dynamic = [original for original in prints if not isinstance(original.value.owner, ConstOp)]
        helper = _existing_formatter(program) if dynamic else None
        if dynamic and helper is None:
            helper = _formatter(_private_prefix(program))
            program.body.block.add_op(helper)
        for original in prints:
            if isinstance(original.value.owner, ConstOp):
                replacement = PrintLiteralOp(str(original.value.owner.value.data))
            else:
                assert helper is not None
                replacement = CallOp(helper.sym_name.data, [original.value], returns=False)
            replacement.location = original.location
            Rewriter.replace_op(original, replacement)
        verify_semantic(op)


__all__ = ["LowerDecimalOutputPass"]
