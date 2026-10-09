"""Explicit, independently checked expression-emission policy for arithmetic.

The pass adds metadata only: the semantic operations, operands, source
locations, and evaluation order remain unchanged. Target lowering may inline
a marked add/sub expression only after recomputing the eligibility proof from
the current SSA graph using ``verified_inline_arithmetic_hints``. Neither stale
metadata nor a forged attribute is an instruction to bypass that proof.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import islice
from typing import ClassVar, Iterator

from . import require_ir_support

require_ir_support()

from xdsl.context import Context
from xdsl.dialects.builtin import ModuleOp, UnitAttr
from xdsl.ir import Operation
from xdsl.passes import ModulePass

from .semantic import BinaryOp, ProgramOp


INLINE_ARITHMETIC_ATTR = "pysem.inline_arithmetic"
DEFAULT_MAX_OPERATIONS = 100_000
MAX_INLINE_ARITHMETIC_DEPTH = 16


def _budgeted_operations(module: ModuleOp | ProgramOp, limit: int) -> Iterator[Operation]:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        raise ValueError("inline arithmetic max_operations must be a nonnegative integer")
    return islice(module.walk(), limit)


def _eligible(operation: Operation) -> bool:
    if not isinstance(operation, BinaryOp) or operation.kind.data not in ("add", "sub"):
        return False
    if operation.parent is None:
        return False
    # Two operand occurrences in one consumer are two uses, not one. Inspect
    # only two list entries so a heavily reused value cannot defeat the budget.
    uses = iter(operation.result.uses)
    use = next(uses, None)
    if use is None or next(uses, None) is not None:
        return False
    consumer = use.operation
    return (isinstance(consumer, BinaryOp)
            and consumer.kind.data in ("add", "sub")
            and consumer.parent is operation.parent
            and consumer is operation.next_op)


def inline_arithmetic_candidates(
    module: ModuleOp | ProgramOp,
    *,
    max_operations: int = DEFAULT_MAX_OPERATIONS,
) -> frozenset[BinaryOp]:
    """Recompute structural candidates without trusting any existing marker.

    The caller must verify semantic IR first, establishing lexical dominance:
    every operand is an immutable SSA value already defined before its use.
    Only a single use by the immediately following add/sub in the same block
    permits moving a pure expression into its consumer. No intervening input,
    call, computation, terminator, or region boundary is skipped.

    A chain has at most 16 marked expression levels; materializing the next
    operation resets that depth. The final consumer may add one AST level.
    This bounds copying, serialization, and parsing of generated expressions,
    even for thousands of adjacent SSA operations or forged markers.

    Exhausting the work cap returns only the proved prefix; omitted operations
    remain materialized by target lowering.
    """
    candidates: set[BinaryOp] = set()
    depths: dict[Operation, int] = {}
    for operation in _budgeted_operations(module, max_operations):
        if not _eligible(operation):
            continue
        assert isinstance(operation, BinaryOp)
        depth = 1 + max(depths.get(value.owner, 0) for value in operation.operands)
        if depth <= MAX_INLINE_ARITHMETIC_DEPTH:
            candidates.add(operation)
            depths[operation] = depth
        # Missing depth means this operation stays materialized. Later chains
        # read a captured value rather than inheriting its expression depth.
    return frozenset(candidates)


def verified_inline_arithmetic_hints(
    module: ModuleOp | ProgramOp,
    *,
    max_operations: int = DEFAULT_MAX_OPERATIONS,
) -> frozenset[BinaryOp]:
    """Return only correctly typed markers whose current graph still proves safety."""
    return frozenset(operation for operation in inline_arithmetic_candidates(
        module, max_operations=max_operations)
        if isinstance(operation.attributes.get(INLINE_ARITHMETIC_ATTR), UnitAttr))


@dataclass(frozen=True)
class InlinePureArithmeticPass(ModulePass):
    """Mark adjacent, once-used add/sub operations for nested target emission.

    Repeated application is idempotent. Stale or incorrectly typed markers on
    visited operations are repaired or removed. An unvisited suffix is left
    intact under the work cap; consumers must independently recheck all hints.
    """

    name: ClassVar[str] = "inline-pure-arithmetic"
    max_operations: int = DEFAULT_MAX_OPERATIONS

    def apply(self, ctx: Context, op: ModuleOp) -> None:
        candidates = inline_arithmetic_candidates(op, max_operations=self.max_operations)
        for operation in _budgeted_operations(op, self.max_operations):
            if operation in candidates:
                operation.attributes[INLINE_ARITHMETIC_ATTR] = UnitAttr()
            else:
                operation.attributes.pop(INLINE_ARITHMETIC_ATTR, None)


__all__ = ["INLINE_ARITHMETIC_ATTR", "MAX_INLINE_ARITHMETIC_DEPTH", "InlinePureArithmeticPass",
           "inline_arithmetic_candidates", "verified_inline_arithmetic_hints"]
