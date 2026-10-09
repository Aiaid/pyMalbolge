"""Conservative bounded dataflow passes over explicit semantic slots.

All functions begin with unknown slot values. Stores establish facts, calls
invalidate global facts, branches retain only agreeing facts, and loops kill
all potentially written slots before analyzing either condition or body.
Expression SSA values remain immutable captures across calls. No target code
is generated, no source variable is implicitly initialized, and stores and
slot declarations are deliberately retained.
"""
from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import ClassVar

from . import require_ir_support

require_ir_support()

from xdsl.context import Context
from xdsl.dialects.builtin import ModuleOp
from xdsl.ir import Block, Operation, SSAValue
from xdsl.passes import ModulePass
from xdsl.rewriter import Rewriter

from .semantic import (
    MOD, BinaryOp, BoolOp, BreakOp, CallOp, CompareOp, ConstOp, ContinueOp,
    ForOp, FuncOp, IfExprOp, IfOp, LoadOp, ReturnOp, StoreOp, UnaryOp,
    WhileOp, YieldOp, get_program, strings,
)

_Slot = tuple[str, str]
_Facts = dict[_Slot, int]
_COMPARE = {"lt": operator.lt, "le": operator.le, "gt": operator.gt,
            "ge": operator.ge, "eq": operator.eq, "ne": operator.ne}


class _WorkLimit(Exception):
    pass


class _Budget:
    def __init__(self, limit: int):
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
            raise ValueError("dataflow pass max_operations must be a nonnegative integer")
        self.remaining = limit

    def spend(self, amount: int = 1):
        if self.remaining < amount:
            raise _WorkLimit()
        self.remaining -= amount


def _binary(kind: str, left: int | None, right: int | None) -> int | None:
    if left is None or right is None:
        return None
    if kind == "add":
        return (left + right) % MOD
    if kind == "sub":
        return (left - right) % MOD
    if kind == "mul":
        return (left * right) % MOD
    if right == 0:
        return None
    return left // right if kind == "floordiv" else left % right


def _join(states: list[_Facts], budget: _Budget) -> _Facts:
    if not states:
        return {}
    first, *others = states
    budget.spend(len(first) * max(1, len(others)))
    return {slot: value for slot, value in first.items()
            if all(state.get(slot) == value for state in others)}


def _agreed(values: list[int | None]) -> int | None:
    if not values or values[0] is None:
        return None
    first = values[0]
    return first if all(value == first for value in values[1:]) else None


def _kill_globals(facts: _Facts, budget: _Budget) -> _Facts:
    budget.spend(len(facts))
    return {slot: value for slot, value in facts.items() if slot[0] != "global"}


class _Propagation:
    def __init__(self, budget: _Budget):
        self.budget = budget
        self.constants: dict[SSAValue, int] = {}

    def constant(self, value: SSAValue) -> int | None:
        return self.constants.get(value)

    def copy_facts(self, facts: _Facts) -> _Facts:
        self.budget.spend(len(facts))
        return dict(facts)

    def record(self, op: Operation, value: int | None):
        if op.results and value is not None:
            self.constants[op.results[0]] = value

    def expression(self, block: Block, facts: _Facts) -> tuple[_Facts, int | None]:
        facts = self.block(block, facts)
        terminator = block.last_op
        assert isinstance(terminator, YieldOp)
        return facts, self.constant(terminator.value)

    def loop_writes(self, op: Operation) -> tuple[set[_Slot], bool]:
        """Scan fully before rewriting a repeated region; exhaustion aborts it."""
        written: set[_Slot] = set()
        calls = False
        pending = [op]
        while pending:
            current = pending.pop()
            self.budget.spend()
            if isinstance(current, StoreOp):
                written.add((current.scope.data, current.slot.data))
            elif isinstance(current, ForOp):
                written.add((current.scope.data, current.target.data))
            elif isinstance(current, CallOp):
                calls = True
            children = [child for region in current.regions for block in region.blocks for child in block.ops]
            pending.extend(reversed(children))
        return written, calls

    def boolean(self, op: BoolOp, facts: _Facts) -> tuple[_Facts, int | None]:
        exits: list[_Facts] = []
        results: list[int | None] = []
        current = self.copy_facts(facts)
        for index, region in enumerate(op.values):
            current, value = self.expression(region.block, current)
            if index == len(op.values) - 1:
                exits.append(current)
                results.append(value)
                break
            if value is None:
                # This prefix may short-circuit. Only the continuing path
                # reaches the next region; join it with exits at the end.
                exits.append(self.copy_facts(current))
                results.append(None)
            elif (op.kind.data == "and" and not value) or (op.kind.data == "or" and value):
                exits.append(current)
                results.append(value)
                break
        return _join(exits, self.budget), _agreed(results)

    def comparison(self, op: CompareOp, facts: _Facts) -> tuple[_Facts, int | None]:
        current, previous = self.expression(op.values[0].block, facts)
        exits: list[_Facts] = []
        results: list[int | None] = []
        for index, (kind, region) in enumerate(zip(strings(op.kinds), op.values[1:])):
            current, value = self.expression(region.block, current)
            passed = None if previous is None or value is None else _COMPARE[kind](previous, value)
            if passed is False:
                exits.append(current)
                results.append(0)
                break
            if passed is None:
                exits.append(self.copy_facts(current))
                results.append(0)
            if index == len(op.kinds) - 1:
                exits.append(current)
                results.append(1)
            previous = value
        return _join(exits, self.budget), _agreed(results)

    def block(self, block: Block, facts: _Facts) -> _Facts:
        facts = self.copy_facts(facts)
        for op in tuple(block.ops):
            self.budget.spend()
            value = None
            if isinstance(op, ConstOp):
                value = op.value.data
            elif isinstance(op, LoadOp):
                value = facts.get((op.scope.data, op.slot.data))
                if value is not None:
                    replacement = ConstOp(value)
                    replacement.location = op.location
                    Rewriter.replace_op(op, replacement)
                    op = replacement
            elif isinstance(op, StoreOp):
                slot = (op.scope.data, op.slot.data)
                stored = self.constant(op.value)
                if stored is None:
                    facts.pop(slot, None)
                else:
                    facts[slot] = stored
            elif isinstance(op, BinaryOp):
                value = _binary(op.kind.data, self.constant(op.lhs), self.constant(op.rhs))
            elif isinstance(op, UnaryOp):
                operand = self.constant(op.value)
                if operand is not None:
                    value = int(not operand) if op.kind.data == "not" else operand
            elif isinstance(op, CallOp):
                facts = _kill_globals(facts, self.budget)
            elif isinstance(op, BoolOp):
                facts, value = self.boolean(op, facts)
            elif isinstance(op, CompareOp):
                facts, value = self.comparison(op, facts)
            elif isinstance(op, (IfExprOp, IfOp)):
                known = self.constant(op.condition)
                branches = ([op.then_region] if known else [op.else_region]) if known is not None else [op.then_region, op.else_region]
                states, values = [], []
                for region in branches:
                    if isinstance(op, IfExprOp):
                        state, selected = self.expression(region.block, facts)
                        values.append(selected)
                    else:
                        state = self.block(region.block, facts)
                    states.append(state)
                facts = _join(states, self.budget)
                value = _agreed(values)
            elif isinstance(op, (WhileOp, ForOp)):
                written, calls = self.loop_writes(op)
                self.budget.spend(len(facts))
                surviving = {slot: value for slot, value in facts.items() if slot not in written}
                if calls:
                    surviving = _kill_globals(surviving, self.budget)
                repeated = surviving
                if isinstance(op, WhileOp):
                    repeated, _ = self.expression(op.condition.block, repeated)
                self.block(op.body.block, repeated)
                # A loop may execute zero times or exit through any break.
                # Keep only facts that no repeated region can invalidate.
                facts = surviving
            elif isinstance(op, (ReturnOp, BreakOp, ContinueOp)):
                break
            self.record(op, value)
        return facts

    def run(self, module: ModuleOp):
        for function in get_program(module).body.block.ops:
            assert isinstance(function, FuncOp)
            self.constants = {}
            self.block(function.body.block, {})


@dataclass(frozen=True)
class ConstantPropagationPass(ModulePass):
    """Replace loads established on every path; budget nodes and fact entries."""
    name: ClassVar[str] = "propagate-constants"
    max_operations: int = 100_000

    def apply(self, ctx: Context, op: ModuleOp) -> None:
        analysis = _Propagation(_Budget(self.max_operations))
        try:
            analysis.run(op)
        except _WorkLimit:
            # Every completed replacement is independently valid; leave the
            # untouched suffix intact instead of guessing after exhaustion.
            pass


class _Elimination:
    def __init__(self, budget: _Budget):
        self.budget = budget
        self.constants: dict[SSAValue, int | None] = {}
        self.discardable: dict[Operation, bool] = {}

    def constant(self, value: SSAValue) -> int | None:
        # SSA arithmetic chains can be much deeper than the source's nested
        # regions; use an explicit stack rather than host recursion.
        pending = [(value, False)]
        while pending:
            current, ready = pending.pop()
            if current in self.constants:
                continue
            self.budget.spend()
            owner = current.owner
            dependencies = ([owner.value] if isinstance(owner, UnaryOp) else
                            [owner.lhs, owner.rhs] if isinstance(owner, BinaryOp) else [])
            if dependencies and not ready:
                pending.append((current, True))
                pending.extend((operand, False) for operand in reversed(dependencies))
                continue
            result = None
            if isinstance(owner, ConstOp):
                result = owner.value.data
            elif isinstance(owner, UnaryOp):
                operand = self.constants[owner.value]
                if operand is not None:
                    result = int(not operand) if owner.kind.data == "not" else operand
            elif isinstance(owner, BinaryOp):
                result = _binary(owner.kind.data, self.constants[owner.lhs], self.constants[owner.rhs])
            self.constants[current] = result
        return self.constants[value]

    def safe(self, op: Operation) -> bool:
        if op in self.discardable:
            return self.discardable[op]
        self.budget.spend()
        result = False
        if isinstance(op, (ConstOp, UnaryOp, YieldOp)):
            result = True
        elif isinstance(op, BinaryOp):
            result = op.kind.data in ("add", "sub", "mul") or self.constant(op.rhs) not in (None, 0)
        elif isinstance(op, (BoolOp, CompareOp, IfExprOp)):
            result = all(self.safe(child) for region in op.regions
                         for block in region.blocks for child in block.ops)
        # Loads can trap on uninitialized locals; calls, byte/decimal I/O,
        # unresolved-name traps and every mutable store remain observable.
        self.discardable[op] = result
        return result

    def block(self, block: Block):
        for op in reversed(tuple(block.ops)):
            self.budget.spend()
            for region in reversed(op.regions):
                for nested in reversed(tuple(region.blocks)):
                    self.block(nested)
            if op.results and all(not result.uses for result in op.results) and self.safe(op):
                Rewriter.erase_op(op)

    def run(self, module: ModuleOp):
        for function in get_program(module).body.block.ops:
            assert isinstance(function, FuncOp)
            self.block(function.body.block)


@dataclass(frozen=True)
class EliminatePureComputationPass(ModulePass):
    """Erase unused nontrapping computations with a bounded operation traversal."""
    name: ClassVar[str] = "eliminate-pure-computation"
    max_operations: int = 100_000

    def apply(self, ctx: Context, op: ModuleOp) -> None:
        analysis = _Elimination(_Budget(self.max_operations))
        try:
            analysis.run(op)
        except _WorkLimit:
            pass


__all__ = ["ConstantPropagationPass", "EliminatePureComputationPass"]
