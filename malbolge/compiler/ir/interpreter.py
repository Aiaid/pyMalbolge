"""Independent, budgeted execution oracle for the structured semantic dialect.

This evaluator dispatches semantic operations directly. It neither reconstructs
Python source/AST nor invokes either legacy compiler or the Malbolge VM. Its
operation counts are oracle work budgets, never target-performance metrics.
"""
from __future__ import annotations

from dataclasses import dataclass
import operator
from xdsl.dialects.builtin import ModuleOp
from xdsl.ir import Block, SSAValue

from .semantic import (MOD, MAX_WORD, EOF_WORD, BinaryOp, BoolOp, BreakOp, CallOp,
    CompareOp, ConstOp, ContinueOp, ForOp, FuncOp, GetCharOp, IfExprOp, IfOp,
    LoadOp, PrintLiteralOp, PrintWordOp, ProgramOp, PutCharOp, ReadIntOp,
    ReturnOp, SemanticIRError, StoreOp, UnaryOp, UnboundNameOp, WhileOp, YieldOp, get_program,
    strings, verify_semantic)


@dataclass(frozen=True)
class RunResult:
    """Deterministic result, including effects preceding errors or exhaustion.

    ``operations`` counts dispatched IR operations and decimal-input characters;
    ``calls`` includes the entry invocation. ``status`` is completed,
    runtime_error, operation_budget, call_budget, call_depth_budget, or
    output_budget. Global values preserve declaration order.
    """
    output: bytes
    globals: dict[str, int]
    return_value: int | None
    operations: int
    calls: int
    input_consumed: int
    status: str
    error: str | None = None

    @property
    def halted(self) -> bool:
        return self.status in ("completed", "runtime_error")


class _Control(Exception):
    def __init__(self, kind: str, value: int | None = None):
        self.kind = kind
        self.value = value


class _RuntimeFailure(Exception):
    pass


class _Budget(Exception):
    def __init__(self, kind: str):
        self.kind = kind


_COMPARE = {"lt": operator.lt, "le": operator.le, "gt": operator.gt,
            "ge": operator.ge, "eq": operator.eq, "ne": operator.ne}


class _Machine:
    def __init__(self, program: ProgramOp, data: bytes, max_operations: int,
                 max_calls: int, max_call_depth: int, max_output: int):
        self.program = program
        self.functions = {f.sym_name.data: f for f in program.body.block.ops}
        self.globals = dict.fromkeys(strings(program.globals), 0)
        self.data = data
        self.position = 0
        self.output = bytearray()
        self.operations = 0
        self.calls = 0
        self.depth = 0
        self.max_operations = max_operations
        self.max_calls = max_calls
        self.max_call_depth = max_call_depth
        self.max_output = max_output

    def tick(self):
        if self.operations >= self.max_operations:
            raise _Budget("operation_budget")
        self.operations += 1

    def emit(self, data: bytes):
        remaining = self.max_output - len(self.output)
        self.output.extend(data[:remaining])
        if len(data) > remaining:
            raise _Budget("output_budget")

    def getchar(self) -> int:
        if self.position >= len(self.data):
            return EOF_WORD
        result = self.data[self.position]
        self.position += 1
        return result

    def read_int(self) -> int:
        value = 0
        digits = False
        phase = 0  # initial whitespace, digits/sign, trailing whitespace
        while True:
            self.tick()
            char = self.getchar()
            if char in (10, EOF_WORD):
                if not digits:
                    raise _RuntimeFailure("invalid decimal input")
                return value
            if 48 <= char <= 57:
                if phase == 2:
                    raise _RuntimeFailure("invalid decimal input")
                value = value * 10 + char - 48
                if value > MAX_WORD:
                    raise _RuntimeFailure("decimal input overflow")
                digits = True
                phase = 1
            elif char in (32, 9, 11, 12, 13):
                if phase == 1:
                    phase = 2
            elif char == 43 and phase == 0:
                phase = 1
            else:
                raise _RuntimeFailure("invalid decimal input")

    def call(self, name: str, arguments: list[int]) -> int | None:
        if self.calls >= self.max_calls:
            raise _Budget("call_budget")
        if self.depth >= self.max_call_depth:
            raise _Budget("call_depth_budget")
        self.calls += 1
        self.depth += 1
        function = self.functions[name]
        env = dict(zip(function.body.block.args, arguments))
        local: dict[str, int] = {}
        try:
            self.block(function.body.block, env, local)
        except _Control as control:
            if control.kind != "return":
                raise SemanticIRError("loop control escaped function") from control
            return control.value
        finally:
            self.depth -= 1
        return None

    def block(self, block: Block, inherited: dict[SSAValue, int], local: dict[str, int]) -> int | None:
        env = dict(inherited)
        for op in block.ops:
            self.tick()
            value: int | None = None
            if isinstance(op, ConstOp):
                value = op.value.data
            elif isinstance(op, UnboundNameOp):
                raise SemanticIRError(f"executed unresolved source name {op.symbol.data!r}")
            elif isinstance(op, LoadOp):
                storage = self.globals if op.scope.data == "global" else local
                if op.slot.data not in storage:
                    raise SemanticIRError(f"read of uninitialized local slot {op.slot.data!r}")
                value = storage[op.slot.data]
            elif isinstance(op, StoreOp):
                storage = self.globals if op.scope.data == "global" else local
                storage[op.slot.data] = env[op.value]
            elif isinstance(op, BinaryOp):
                left, right = env[op.lhs], env[op.rhs]
                kind = op.kind.data
                if kind in ("floordiv", "mod") and right == 0:
                    raise _RuntimeFailure("division by zero" if kind == "floordiv" else "remainder by zero")
                if kind == "add":
                    value = (left + right) % MOD
                elif kind == "sub":
                    value = (left - right) % MOD
                elif kind == "mul":
                    value = (left * right) % MOD
                elif kind == "floordiv":
                    value = left // right
                else:
                    value = left % right
            elif isinstance(op, UnaryOp):
                value = int(not env[op.value]) if op.kind.data == "not" else env[op.value]
            elif isinstance(op, YieldOp):
                return env[op.value]
            elif isinstance(op, BoolOp):
                for nested in op.values:
                    value = self.block(nested.block, env, local)
                    if (op.kind.data == "and" and value == 0) or (op.kind.data == "or" and value != 0):
                        break
            elif isinstance(op, CompareOp):
                left = self.block(op.values[0].block, env, local)
                value = 1
                for kind, nested in zip(strings(op.kinds), op.values[1:]):
                    right = self.block(nested.block, env, local)
                    if not _COMPARE[kind](left, right):
                        value = 0
                        break
                    left = right
            elif isinstance(op, IfExprOp):
                selected = op.then_region if env[op.condition] else op.else_region
                value = self.block(selected.block, env, local)
            elif isinstance(op, IfOp):
                selected = op.then_region if env[op.condition] else op.else_region
                self.block(selected.block, env, local)
            elif isinstance(op, WhileOp):
                while self.block(op.condition.block, env, local):
                    try:
                        self.block(op.body.block, env, local)
                    except _Control as control:
                        if control.kind == "break":
                            break
                        if control.kind != "continue":
                            raise
            elif isinstance(op, ForOp):
                current = env[op.start]
                stop = -1 if op.stop_sentinel.data else env[op.stop]
                step = op.step.data
                storage = self.globals if op.scope.data == "global" else local
                while (current < stop if step > 0 else current > stop):
                    # Charge iteration even when its body is empty.
                    self.tick()
                    storage[op.target.data] = current
                    try:
                        self.block(op.body.block, env, local)
                    except _Control as control:
                        if control.kind == "break":
                            break
                        if control.kind != "continue":
                            raise
                    current += step
                    if not 0 <= current < MOD:
                        break
            elif isinstance(op, BreakOp):
                raise _Control("break")
            elif isinstance(op, ContinueOp):
                raise _Control("continue")
            elif isinstance(op, ReturnOp):
                raise _Control("return", env[op.value] if op.value is not None else None)
            elif isinstance(op, CallOp):
                value = self.call(op.callee.data, [env[arg] for arg in op.arguments])
                if op.result is not None and value is None:
                    raise SemanticIRError("word-returning call produced None")
            elif isinstance(op, GetCharOp):
                value = self.getchar()
            elif isinstance(op, PutCharOp):
                self.emit(bytes([env[op.value] % 256]))
            elif isinstance(op, PrintLiteralOp):
                self.emit(op.text.data.encode("latin-1"))
            elif isinstance(op, PrintWordOp):
                self.emit(str(env[op.value]).encode("ascii"))
            elif isinstance(op, ReadIntOp):
                self.emit(op.prompt.data.encode("latin-1"))
                value = self.read_int()
            else:
                raise SemanticIRError(f"unsupported semantic operation {op.name}")
            if op.results:
                if value is None:
                    raise SemanticIRError(f"{op.name} did not produce its declared result")
                env[op.results[0]] = value
        return None


def run_semantic(module: ModuleOp | ProgramOp, input_data: bytes | str = b"", *,
                 max_operations: int = 1_000_000, max_calls: int = 100_000,
                 max_call_depth: int = 128, max_output: int = 1_000_000) -> RunResult:
    """Verify and execute IR; retain partial effects at errors and budgets.

    ``str`` input is encoded as UTF-8, matching the bounded target VM's byte I/O.
    Program globals start at zero; local slots require executed stores. Runtime
    input/arithmetic failures emit ``error\\n`` exactly once and halt entry.
    """
    limits = (max_operations, max_calls, max_call_depth, max_output)
    if any(not isinstance(limit, int) or isinstance(limit, bool) or limit < 0 for limit in limits):
        raise ValueError("semantic execution budgets must be nonnegative integers")
    verify_semantic(module)
    program = get_program(module)
    if isinstance(input_data, str):
        data = input_data.encode("utf8")
    elif isinstance(input_data, (bytes, bytearray, memoryview)):
        data = bytes(input_data)
    else:
        raise TypeError("input_data must be text or bytes-like")
    machine = _Machine(program, data, max_operations, max_calls, max_call_depth, max_output)
    status, error, result = "completed", None, None
    try:
        result = machine.call(program.entry.data, [])
    except _RuntimeFailure as exc:
        status, error = "runtime_error", str(exc)
        try:
            machine.emit(b"error\n")
        except _Budget as budget:
            status = budget.kind
    except _Budget as exc:
        status = exc.kind
    except RecursionError:
        # An explicit large depth request must never escape as a host traceback.
        status = "call_depth_budget"
        error = "host recursion limit reached before requested call depth"
    return RunResult(bytes(machine.output), dict(machine.globals), result,
                     machine.operations, machine.calls, machine.position, status, error)


__all__ = ["RunResult", "run_semantic"]
