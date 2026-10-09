"""Explicit word-ring arithmetic and structured-control rewrites.

These passes never remove an operand's producer just because its value becomes
unused. Calls, byte/input reads, slot loads and checked arithmetic therefore keep
their evaluation order and failure behavior; a separate effect-aware DCE pass
may remove proven nontrapping dead producers later.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from . import require_ir_support

require_ir_support()

from xdsl.context import Context
from xdsl.dialects.builtin import ModuleOp
from xdsl.ir import Operation, Region, SSAValue
from xdsl.passes import ModulePass
from xdsl.rewriter import InsertPoint, Rewriter

from .semantic import (
    MOD, BinaryOp, BoolOp, CompareOp, ConstOp, IfExprOp, IfOp, UnaryOp,
    WhileOp, YieldOp,
)


def _literal(value: SSAValue) -> int | None:
    owner = value.owner
    return owner.value.data if isinstance(owner, ConstOp) else None


def _located(operation: Operation, original: Operation):
    operation.location = original.location
    return operation


def _replace_constant(operation: Operation, value: int) -> None:
    Rewriter.replace_op(operation, _located(ConstOp(value % MOD), operation))


def _yielded(region: Region) -> SSAValue:
    terminator = region.block.last_op
    if not isinstance(terminator, YieldOp):
        raise ValueError("semantic expression region lacks its yield")
    return terminator.value


def _inline_expression(region: Region, before: Operation) -> SSAValue:
    """Move the reached computation intact; drop only its region terminator."""
    result = _yielded(region)
    terminator = region.block.last_op
    assert terminator is not None
    region.block.erase_op(terminator)
    Rewriter.inline_block(region.block, InsertPoint.before(before))
    return result


_COMPARE = {
    "lt": lambda left, right: left < right,
    "le": lambda left, right: left <= right,
    "gt": lambda left, right: left > right,
    "ge": lambda left, right: left >= right,
    "eq": lambda left, right: left == right,
    "ne": lambda left, right: left != right,
}


def _fold_comparison(operation: CompareOp) -> None:
    """Fold only after proving the result and which operand regions execute."""
    left = _literal(_yielded(operation.values[0]))
    if left is None:
        return
    reached = [operation.values[0]]
    result = True
    for comparison, region in zip(operation.kinds, operation.values[1:]):
        right = _literal(_yielded(region))
        if right is None:
            return
        reached.append(region)
        result = _COMPARE[comparison.data](left, right)
        if not result:
            break
        left = right
    # A region may contain reads, calls or failing arithmetic before yielding a
    # known constant. Inline it rather than treating the whole region as pure.
    for region in reached:
        _inline_expression(region, operation)
    _replace_constant(operation, int(result))


@dataclass(frozen=True)
class FoldArithmeticPass(ModulePass):
    """Fold proven constant words, preserving checked zero-divisor operations."""

    name: ClassVar[str] = "fold-arithmetic"

    def apply(self, ctx: Context, op: ModuleOp) -> None:
        for operation in list(op.walk(region_first=True)):
            if isinstance(operation, BinaryOp):
                left, right = _literal(operation.lhs), _literal(operation.rhs)
                if left is None or right is None:
                    continue
                kind = operation.kind.data
                if kind in ("floordiv", "mod") and right == 0:
                    continue
                if kind == "add":
                    value = left + right
                elif kind == "sub":
                    value = left - right
                elif kind == "mul":
                    value = left * right
                elif kind == "floordiv":
                    value = left // right
                elif kind == "mod":
                    value = left % right
                else:
                    continue
                _replace_constant(operation, value)
            elif isinstance(operation, UnaryOp):
                value = _literal(operation.value)
                if value is not None:
                    _replace_constant(operation, int(not value)
                                      if operation.kind.data == "not" else value)
            elif isinstance(operation, CompareOp):
                _fold_comparison(operation)


@dataclass(frozen=True)
class SimplifyArithmeticPass(ModulePass):
    """Apply scalar identities without erasing even unused operand effects."""

    name: ClassVar[str] = "simplify-arithmetic"

    def apply(self, ctx: Context, op: ModuleOp) -> None:
        for operation in list(op.walk(region_first=True)):
            if isinstance(operation, UnaryOp) and operation.kind.data == "pos":
                Rewriter.replace_op(operation, [], [operation.value])
                continue
            if not isinstance(operation, BinaryOp):
                continue
            left, right = _literal(operation.lhs), _literal(operation.rhs)
            kind = operation.kind.data
            replacement = None
            if kind == "add":
                if right == 0:
                    replacement = operation.lhs
                elif left == 0:
                    replacement = operation.rhs
            elif kind == "sub" and right == 0:
                replacement = operation.lhs
            elif kind == "mul":
                if left == 0 or right == 0:
                    _replace_constant(operation, 0)
                    continue
                if right == 1:
                    replacement = operation.lhs
                elif left == 1:
                    replacement = operation.rhs
            elif kind == "floordiv" and right == 1:
                replacement = operation.lhs
            elif kind == "mod" and right == 1:
                _replace_constant(operation, 0)
                continue
            if replacement is not None:
                Rewriter.replace_op(operation, [], [replacement])


def _binary_digits(value: int) -> tuple[int, ...]:
    return tuple(int(bit) for bit in bin(value)[2:])


def _signed_digits(value: int) -> tuple[int, ...]:
    """Most-significant-first nonadjacent digits in {-1, 0, 1}."""
    digits = []
    while value:
        digit = 2 - value % 4 if value % 2 else 0
        digits.append(digit)
        value = (value - digit) // 2
    return tuple(reversed(digits))


def _chain_plan(factor: int) -> tuple[tuple[int, ...], bool, int]:
    candidates = []
    for magnitude, negate in ((factor, False), (MOD - factor, True)):
        for digits in (_binary_digits(magnitude), _signed_digits(magnitude)):
            cost = len(digits) - 1 + sum(digit != 0 for digit in digits[1:]) + negate
            candidates.append((digits, negate, cost))
    # Stable minimum: prefer positive/binary spellings when costs tie.
    return min(candidates, key=lambda candidate: candidate[2])


@dataclass(frozen=True)
class LowerConstantMultiplyPass(ModulePass):
    """Replace cheap literal multiplication by bounded add/sub chains.

    The budget counts new arithmetic operations, not runtime instructions or
    predicted speed. Binary and signed-digit plans compete with their modular
    negations. Expensive literals and fully dynamic multiplication keep the
    generic target multiplication path.
    """

    name: ClassVar[str] = "lower-constant-multiply"
    max_operations: int = 12

    def apply(self, ctx: Context, op: ModuleOp) -> None:
        if (not isinstance(self.max_operations, int) or isinstance(self.max_operations, bool)
                or self.max_operations < 0):
            raise ValueError("constant multiply operation budget must be a nonnegative integer")
        for operation in list(op.walk(region_first=True)):
            if not isinstance(operation, BinaryOp) or operation.kind.data != "mul":
                continue
            left, right = _literal(operation.lhs), _literal(operation.rhs)
            if left is not None and right is not None:
                continue  # folding is a separately selected pass
            if right is not None:
                factor, base = right, operation.lhs
            elif left is not None:
                factor, base = left, operation.rhs
            else:
                continue
            if factor == 0:
                _replace_constant(operation, 0)
                continue
            if factor == 1:
                Rewriter.replace_op(operation, [], [base])
                continue
            digits, negate, cost = _chain_plan(factor)
            if cost > self.max_operations:
                continue
            additions = []
            current = base
            for digit in digits[1:]:
                double = _located(BinaryOp("add", current, current), operation)
                additions.append(double)
                current = double.result
                if digit:
                    combine = _located(BinaryOp("add" if digit == 1 else "sub",
                                                current, base), operation)
                    additions.append(combine)
                    current = combine.result
            if negate:
                zero = _located(ConstOp(0), operation)
                negative = _located(BinaryOp("sub", zero.result, current), operation)
                additions.extend((zero, negative))
                current = negative.result
            Rewriter.replace_op(operation, additions, [current])


@dataclass(frozen=True)
class SimplifyControlPass(ModulePass):
    """Select proven branches while retaining their ordered computations."""

    name: ClassVar[str] = "simplify-control"

    def apply(self, ctx: Context, op: ModuleOp) -> None:
        for operation in list(op.walk(region_first=True)):
            if isinstance(operation, (IfOp, IfExprOp)):
                known = _literal(operation.condition)
                if known is None:
                    continue
                selected = operation.then_region if known else operation.else_region
                if isinstance(operation, IfExprOp):
                    result = _inline_expression(selected, operation)
                    Rewriter.replace_op(operation, [], [result])
                else:
                    Rewriter.inline_block(selected.block, InsertPoint.before(operation))
                    Rewriter.erase_op(operation)
            elif isinstance(operation, WhileOp):
                if _literal(_yielded(operation.condition)) == 0:
                    # Even a loop that never enters evaluates its condition
                    # once, including all reads, calls and checked arithmetic.
                    _inline_expression(operation.condition, operation)
                    Rewriter.erase_op(operation)
            elif isinstance(operation, BoolOp):
                reached = []
                for index, region in enumerate(operation.values):
                    reached.append(region)
                    known = _literal(_yielded(region))
                    if known is None:
                        # A dynamic final operand is unconditionally reached
                        # after a known nondecisive prefix; it can be inlined.
                        if index != len(operation.values) - 1:
                            reached = []
                        break
                    if (known == 0 if operation.kind.data == "and" else known != 0):
                        break
                if reached:
                    result = None
                    for region in reached:
                        result = _inline_expression(region, operation)
                    assert result is not None
                    Rewriter.replace_op(operation, [], [result])


__all__ = ["FoldArithmeticPass", "SimplifyArithmeticPass",
           "LowerConstantMultiplyPass", "SimplifyControlPass"]
