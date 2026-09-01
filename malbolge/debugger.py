"""
Malbolge Debugger - Core debugging functionality for the Malbolge interpreter.

This module provides:
- MalbolgeDebugger: Main debugger class with step/run/breakpoint support
- MalbolgeState: Immutable snapshot of execution state
- Breakpoint/Watchpoint: Debugging primitives

Supports multiple Malbolge variants:
- Original Malbolge (10 trits)
- Malbolge20 (20 trits)
"""

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import (
    Callable,
    Dict,
    Iterator,
    List,
    Mapping,
    Optional,
    Tuple,
    Union,
)
import copy

from .core import (
    MalbolgeConfig,
    MalbolgeVariant,
    TABLE_CRAZY,
    ENCRYPT,
    OPS_VALID,
    rotate as core_rotate,
    crazy as core_crazy,
    create_memory,
    parse_source,
    SparseMemory,
    DenseMemory,
)

# Legacy constants for backward compatibility
POW9, POW10 = 3**9, 3**10  # 19683, 59049

# Opcode name mapping
OPCODE_NAMES = {
    4: "jmp",    # jmp [d]
    5: "out",    # out a
    23: "in",    # in a
    39: "rotr",  # rotr[d]; mov a, [d]
    40: "mov",   # mov d, [d]
    62: "crz",   # crz [d], a; mov a, [d]
    68: "nop",   # nop
    81: "end"    # end
}

# Detailed opcode help for teaching mode
OPCODE_HELP = {
    4: {
        'name': 'jmp',
        'syntax': 'jmp [d]',
        'description': 'Jump to the address stored in memory at address D.',
        'pseudocode': 'c = mem[d]',
        'affects': ['C (code pointer)'],
        'note': 'Sets C to mem[D], causing execution to jump to that address.'
    },
    5: {
        'name': 'out',
        'syntax': 'out a',
        'description': 'Output the character with ASCII value A mod 256.',
        'pseudocode': 'print(chr(a % 256))',
        'affects': ['Output stream'],
        'note': 'Only the lowest 8 bits of A are used for output.'
    },
    23: {
        'name': 'in',
        'syntax': 'in a',
        'description': 'Read one character from input into A.',
        'pseudocode': 'a = ord(read_char())',
        'affects': ['A (accumulator)'],
        'note': 'Program terminates if input is exhausted.'
    },
    39: {
        'name': 'rotr',
        'syntax': 'rotr [d]; mov a, [d]',
        'description': 'Rotate mem[D] right by one ternary digit, store in both mem[D] and A.',
        'pseudocode': 'mem[d] = rotate(mem[d])\na = mem[d]',
        'affects': ['A (accumulator)', 'mem[D]'],
        'note': 'Rotation: LSB wraps to MSB. Formula: 3^9 * (n%3) + n//3'
    },
    40: {
        'name': 'mov',
        'syntax': 'mov d, [d]',
        'description': 'Load the value at address D into D itself.',
        'pseudocode': 'd = mem[d]',
        'affects': ['D (data pointer)'],
        'note': 'D becomes the value stored at its current address.'
    },
    62: {
        'name': 'crz',
        'syntax': 'crz [d], a; mov a, [d]',
        'description': 'Perform crazy operation on A and mem[D], store in both.',
        'pseudocode': 'mem[d] = crazy(a, mem[d])\na = mem[d]',
        'affects': ['A (accumulator)', 'mem[D]'],
        'note': 'Crazy: ternary digit-by-digit lookup table operation.'
    },
    68: {
        'name': 'nop',
        'syntax': 'nop',
        'description': 'No operation. Does nothing except advance pointers.',
        'pseudocode': '# do nothing',
        'affects': [],
        'note': 'C and D still increment after nop.'
    },
    81: {
        'name': 'end',
        'syntax': 'end',
        'description': 'Terminate program execution.',
        'pseudocode': 'exit()',
        'affects': ['Program state'],
        'note': 'Program stops immediately.'
    }
}


class StopReason(Enum):
    """Reason why execution stopped."""
    RUNNING = "running"
    BREAKPOINT = "breakpoint"
    STEP = "step"
    WATCHPOINT = "watchpoint"
    TERMINATED = "terminated"
    ERROR = "error"
    INPUT_EXHAUSTED = "input_exhausted"


@dataclass
class MalbolgeState:
    """Immutable snapshot of Malbolge VM execution state."""
    # Registers
    a: int              # Accumulator
    c: int              # Code pointer
    d: int              # Data pointer

    # Current instruction info
    raw_instruction: int       # mem[c] raw value
    effective_opcode: int      # (mem[c] + c) % 94
    opcode_name: str           # Human-readable opcode name

    # Execution statistics
    step_count: int = 0        # Number of steps executed
    output: str = ""           # Accumulated output
    input_consumed: int = 0    # Characters consumed from input

    # Stop reason
    stop_reason: StopReason = StopReason.RUNNING

    def to_dict(self) -> dict:
        """Serialize state for logging/export."""
        return {
            "registers": {"a": self.a, "c": self.c, "d": self.d},
            "instruction": {
                "raw": self.raw_instruction,
                "opcode": self.effective_opcode,
                "name": self.opcode_name
            },
            "stats": {
                "steps": self.step_count,
                "output_len": len(self.output),
                "input_consumed": self.input_consumed
            },
            "stop_reason": self.stop_reason.value
        }


@dataclass
class Breakpoint:
    """Breakpoint definition."""
    address: int
    enabled: bool = True
    hit_count: int = 0
    condition: Optional[Callable[[MalbolgeState], bool]] = None
    temporary: bool = False  # One-shot breakpoint (for run-to-cursor)

    def should_break(self, state: MalbolgeState) -> bool:
        """Check if this breakpoint should trigger."""
        if not self.enabled:
            return False
        if self.condition and not self.condition(state):
            return False
        self.hit_count += 1
        return True


@dataclass
class Watchpoint:
    """Memory watchpoint - triggers when value at address changes."""
    address: int
    enabled: bool = True
    last_value: Optional[int] = None

    def check(self, current_value: int) -> bool:
        """Check if value changed. Returns True if watchpoint triggered."""
        if not self.enabled:
            return False
        if self.last_value is not None and self.last_value != current_value:
            triggered = True
        else:
            triggered = False
        self.last_value = current_value
        return triggered


@dataclass
class HistoryEntry:
    """Complete state for history/undo functionality."""
    a: int
    c: int
    d: int
    input_pos: int
    output: str
    step_count: int
    # Store only modified memory locations to save space
    mem_changes: Dict[int, int] = field(default_factory=dict)
    # Number of writes this step made to each address. Usually 1 per
    # mem_changes key, but 2 when C == D and both the crz/rotr writeback and
    # the ENCRYPT rewrite land on the same cell.
    write_counts: Dict[int, int] = field(default_factory=dict)


class MalbolgeDebugger:
    """
    Malbolge debugger with step execution, breakpoints, and state inspection.

    Usage:
        dbg = MalbolgeDebugger(source_code, input_data)
        dbg.add_breakpoint(10)
        state = dbg.run()  # Run until breakpoint
        print(dbg.output)

    For Malbolge20:
        config = MalbolgeConfig.malbolge20()
        dbg = MalbolgeDebugger(source_code, input_data, config=config)
    """

    def __init__(self, source: str, input_data: str = "",
                 config: Optional[MalbolgeConfig] = None):
        """
        Initialize debugger with Malbolge source code.

        Args:
            source: Malbolge source code
            input_data: Program input string
            config: Malbolge variant configuration (default: original Malbolge)

        Raises:
            ValueError: If source contains invalid characters
        """
        # Configuration
        self._config = config or MalbolgeConfig.original()

        # Memory and registers
        self._mem: Union[List[int], SparseMemory, DenseMemory] = create_memory(self._config)
        self._a: int = 0
        self._c: int = 0
        self._d: int = 0

        # Input/Output
        self._input: str = input_data
        self._input_pos: int = 0
        self._output: str = ""

        # Breakpoints and watchpoints
        self._breakpoints: Dict[int, Breakpoint] = {}
        self._watchpoints: Dict[int, Watchpoint] = {}

        # Execution state
        self._step_count: int = 0
        self._terminated: bool = False
        self._source_length: int = 0

        # History for step-back functionality
        self._history: List[HistoryEntry] = []
        self._max_history: int = 10000

        # Cumulative write count per memory cell (see write_heat)
        self._write_heat: Dict[int, int] = {}

        # Furthest step_count ever reached on this timeline (see seek)
        self._max_step_reached: int = 0

        # Callbacks
        self._on_step: Optional[Callable[[MalbolgeState], None]] = None
        self._on_output: Optional[Callable[[str], None]] = None
        self._on_breakpoint: Optional[Callable[[Breakpoint, MalbolgeState], None]] = None

        # Initialize memory
        self._initialize(source)

        # Store initial memory state for reset
        self._initial_mem = self._mem.copy()

    # ==================== Core Operations ====================

    def _rotate(self, n: int) -> int:
        """Rotate ternary number right."""
        return core_rotate(n, self._config)

    def _crazy(self, a: int, b: int) -> int:
        """Malbolge's 'crazy' operation."""
        return core_crazy(a, b, self._config.trit_width)

    def _initialize(self, source: str) -> None:
        """Load source code into memory."""
        cells = parse_source(source, self._config)
        self._source_length = len(cells)
        self._mem.initialize_source(cells)

    # ==================== Breakpoint Management ====================

    def add_breakpoint(self, address: int,
                       condition: Optional[Callable[[MalbolgeState], bool]] = None,
                       temporary: bool = False) -> Breakpoint:
        """Add a breakpoint at the specified address."""
        if not 0 <= address < self._config.memory_size:
            raise ValueError(f"Address {address} out of range (0-{self._config.memory_size-1})")
        bp = Breakpoint(address=address, condition=condition, temporary=temporary)
        self._breakpoints[address] = bp
        return bp

    def remove_breakpoint(self, address: int) -> bool:
        """Remove breakpoint at address. Returns True if existed."""
        return self._breakpoints.pop(address, None) is not None

    def toggle_breakpoint(self, address: int) -> Optional[bool]:
        """Toggle breakpoint enabled state. Returns new state or None if not found."""
        if address in self._breakpoints:
            self._breakpoints[address].enabled = not self._breakpoints[address].enabled
            return self._breakpoints[address].enabled
        return None

    def clear_breakpoints(self) -> int:
        """Remove all breakpoints. Returns count removed."""
        count = len(self._breakpoints)
        self._breakpoints.clear()
        return count

    def list_breakpoints(self) -> List[Breakpoint]:
        """List all breakpoints."""
        return list(self._breakpoints.values())

    # ==================== Watchpoint Management ====================

    def add_watchpoint(self, address: int) -> Watchpoint:
        """Add memory watchpoint at address."""
        if not 0 <= address < self._config.memory_size:
            raise ValueError(f"Address {address} out of range")
        wp = Watchpoint(address=address, last_value=self._mem[address])
        self._watchpoints[address] = wp
        return wp

    def remove_watchpoint(self, address: int) -> bool:
        """Remove watchpoint at address."""
        return self._watchpoints.pop(address, None) is not None

    def list_watchpoints(self) -> List[Watchpoint]:
        """List all watchpoints."""
        return list(self._watchpoints.values())

    # ==================== State Query ====================

    def get_state(self) -> MalbolgeState:
        """Get current execution state snapshot."""
        raw = self._mem[self._c] if 0 <= self._c < self._config.memory_size else 0
        if 33 <= raw <= 126:
            opcode = (raw + self._c) % 94
        else:
            opcode = -1

        return MalbolgeState(
            a=self._a,
            c=self._c,
            d=self._d,
            raw_instruction=raw,
            effective_opcode=opcode,
            opcode_name=OPCODE_NAMES.get(opcode, "invalid"),
            step_count=self._step_count,
            output=self._output,
            input_consumed=self._input_pos,
            stop_reason=StopReason.TERMINATED if self._terminated else StopReason.RUNNING
        )

    def read_memory(self, start: int, length: int = 1) -> List[int]:
        """Read memory region."""
        start = max(0, min(start, self._config.memory_size - 1))
        end = min(start + length, self._config.memory_size)
        return self._mem[start:end]

    def read_memory_value(self, address: int) -> int:
        """Read single memory value."""
        if 0 <= address < self._config.memory_size:
            return self._mem[address]
        return 0

    def get_memory_context(self, address: int, context: int = 5) -> Dict:
        """Get memory values around an address with context."""
        start = max(0, address - context)
        end = min(self._config.memory_size, address + context + 1)
        values = self._mem[start:end]
        return {
            "start": start,
            "end": end,
            "center": address,
            "values": values,
            "as_chars": [chr(v) if 33 <= v <= 126 else '.' for v in values]
        }

    @property
    def config(self) -> MalbolgeConfig:
        """Get the Malbolge variant configuration."""
        return self._config

    @property
    def registers(self) -> Dict[str, int]:
        """Get all register values."""
        return {"a": self._a, "c": self._c, "d": self._d}

    @property
    def output(self) -> str:
        """Get accumulated program output."""
        return self._output

    @property
    def is_terminated(self) -> bool:
        """Check if program has terminated."""
        return self._terminated

    @property
    def source_length(self) -> int:
        """Get length of source code in memory."""
        return self._source_length

    @property
    def step_count(self) -> int:
        """Get number of steps executed."""
        return self._step_count

    @property
    def can_step_back(self) -> bool:
        """Check if step back is possible."""
        return len(self._history) > 0

    @property
    def history_size(self) -> int:
        """Get number of history entries available."""
        return len(self._history)

    # ==================== Memory Write Heat ====================

    @property
    def write_heat(self) -> Mapping[int, int]:
        """
        Cumulative write count per memory address.

        Counts every assignment to mem[addr] made by execution: the crz/rotr
        writeback and the per-step ENCRYPT rewrite. Loading the source into
        memory is not a write.

        The mapping is a read-only *live* view of the debugger's counters, so
        it must not be iterated across a step(); snapshot it or use
        get_write_heat() instead. Addresses that have never been written are
        absent (rather than present with 0).
        """
        return MappingProxyType(self._write_heat)

    def get_write_heat(self, start: int, count: int) -> List[int]:
        """
        Write counts for `count` cells starting at `start`.

        Never-written (and out-of-range) addresses read as 0 rather than
        raising, so a UI window can run off either end of memory.
        """
        if count <= 0:
            return []
        heat = self._write_heat
        return [heat.get(start + i, 0) for i in range(count)]

    # ==================== Timeline ====================

    @property
    def max_step_reached(self) -> int:
        """Highest step_count ever reached since the last reset()."""
        return self._max_step_reached

    @property
    def seekable_range(self) -> Tuple[int, int]:
        """
        Inclusive (low, high) range of steps seek() can reach.

        `high` is max_step_reached. `low` is bounded by the history window:
        _save_history drops the oldest entry past _max_history, so steps older
        than that can no longer be reconstructed by stepping back.
        """
        low = self._history[0].step_count if self._history else self._step_count
        return (low, self._max_step_reached)

    # ==================== Execution Control ====================

    def _save_history(self, mem_changes: Dict[int, int]) -> None:
        """Save current state to history for step-back."""
        if len(self._history) >= self._max_history:
            self._history.pop(0)

        entry = HistoryEntry(
            a=self._a,
            c=self._c,
            d=self._d,
            input_pos=self._input_pos,
            output=self._output,
            step_count=self._step_count,
            mem_changes=mem_changes
        )
        self._history.append(entry)

    def _record_write(self, addr: int, old_value: int,
                      mem_changes: Dict[int, int],
                      write_counts: Dict[int, int]) -> None:
        """
        Book-keeping for one write to mem[addr], performed by the caller.

        `mem_changes` keeps the value from *before* the first write of this
        step (setdefault, not assignment: when C == D the crz/rotr writeback
        and the ENCRYPT rewrite both hit one cell, and step_back must restore
        the value from before both). `write_counts` and the write-heat counter
        count every write, so the two stay in step through step_back().
        """
        mem_changes.setdefault(addr, old_value)
        write_counts[addr] = write_counts.get(addr, 0) + 1
        self._write_heat[addr] = self._write_heat.get(addr, 0) + 1

    def step(self) -> MalbolgeState:
        """Execute one instruction and return new state."""
        if self._terminated:
            state = self.get_state()
            return state

        # Track memory changes for history
        mem_changes: Dict[int, int] = {}
        write_counts: Dict[int, int] = {}

        # Save state before execution
        old_d = self._d

        # Check termination condition
        if self._mem[self._c] < 33 or self._mem[self._c] > 126:
            self._terminated = True
            state = self.get_state()
            state = MalbolgeState(
                a=state.a, c=state.c, d=state.d,
                raw_instruction=state.raw_instruction,
                effective_opcode=state.effective_opcode,
                opcode_name=state.opcode_name,
                step_count=state.step_count,
                output=state.output,
                input_consumed=state.input_consumed,
                stop_reason=StopReason.TERMINATED
            )
            return state

        # Save current state to history before changes
        self._save_history({})

        # Calculate opcode
        v = (self._mem[self._c] + self._c) % 94

        # Execute instruction
        if v == 4:      # jmp [d]
            self._c = self._mem[self._d]
        elif v == 5:    # out a
            char = chr(int(self._a % 256))
            self._output += char
            if self._on_output:
                self._on_output(char)
        elif v == 23:   # in a
            if self._input_pos < len(self._input):
                self._a = ord(self._input[self._input_pos])
                self._input_pos += 1
            else:
                self._terminated = True
                state = self.get_state()
                return MalbolgeState(
                    a=state.a, c=state.c, d=state.d,
                    raw_instruction=state.raw_instruction,
                    effective_opcode=state.effective_opcode,
                    opcode_name=state.opcode_name,
                    step_count=state.step_count,
                    output=state.output,
                    input_consumed=state.input_consumed,
                    stop_reason=StopReason.INPUT_EXHAUSTED
                )
        elif v == 39:   # rotr[d]; mov a, [d]
            self._record_write(self._d, self._mem[self._d],
                               mem_changes, write_counts)
            self._a = self._mem[self._d] = self._rotate(self._mem[self._d])
        elif v == 40:   # mov d, [d]
            self._d = self._mem[self._d]
        elif v == 62:   # crz [d], a; mov a, [d]
            self._record_write(self._d, self._mem[self._d],
                               mem_changes, write_counts)
            self._a = self._mem[self._d] = self._crazy(self._a, self._mem[self._d])
        elif v == 81:   # end
            self._terminated = True
            state = self.get_state()
            return MalbolgeState(
                a=state.a, c=state.c, d=state.d,
                raw_instruction=state.raw_instruction,
                effective_opcode=state.effective_opcode,
                opcode_name=state.opcode_name,
                step_count=state.step_count,
                output=state.output,
                input_consumed=state.input_consumed,
                stop_reason=StopReason.TERMINATED
            )
        # v == 68: nop - do nothing

        # Self-modifying code: encrypt instruction at current c
        # Note: this happens AFTER jmp may have changed c, so we encrypt
        # the jump target, not the jmp instruction itself
        if 33 <= self._mem[self._c] <= 126:
            self._record_write(self._c, self._mem[self._c],
                               mem_changes, write_counts)
            self._mem[self._c] = ENCRYPT[self._mem[self._c] - 33]

        # Update history with actual memory changes
        if self._history:
            self._history[-1].mem_changes = mem_changes
            self._history[-1].write_counts = write_counts

        # Update pointers (with wraparound)
        # Note: c increments even after jmp, matching original behavior
        self._c = 0 if self._c == self._config.memory_size - 1 else self._c + 1
        self._d = 0 if self._d == self._config.memory_size - 1 else self._d + 1

        self._step_count += 1
        if self._step_count > self._max_step_reached:
            self._max_step_reached = self._step_count

        state = self.get_state()
        state = MalbolgeState(
            a=state.a, c=state.c, d=state.d,
            raw_instruction=state.raw_instruction,
            effective_opcode=state.effective_opcode,
            opcode_name=state.opcode_name,
            step_count=state.step_count,
            output=state.output,
            input_consumed=state.input_consumed,
            stop_reason=StopReason.STEP
        )

        if self._on_step:
            self._on_step(state)

        return state

    def step_back(self) -> Optional[MalbolgeState]:
        """
        Undo the last step and return to previous state.
        Returns None if no history available.
        """
        if not self._history:
            return None

        entry = self._history.pop()

        # Restore registers
        self._a = entry.a
        self._c = entry.c
        self._d = entry.d
        self._input_pos = entry.input_pos
        self._output = entry.output
        self._step_count = entry.step_count

        # Restore memory changes
        for addr, old_value in entry.mem_changes.items():
            self._mem[addr] = old_value

        # Undo the write heat this step contributed, so heat stays consistent
        # with the timeline that is still reachable instead of counting work
        # that has been undone.
        for addr, count in entry.write_counts.items():
            remaining = self._write_heat.get(addr, 0) - count
            if remaining > 0:
                self._write_heat[addr] = remaining
            else:
                self._write_heat.pop(addr, None)

        # Clear terminated flag if we stepped back
        self._terminated = False

        return self.get_state()

    def _run_iter(self, max_steps: int = -1,
                  chunk: int = 0) -> Iterator[MalbolgeState]:
        """
        Shared engine behind run() and run_chunked().

        Yields the current state every `chunk` executed steps (never, when
        chunk <= 0) and always yields the stopping state last, so a caller
        that keeps the final yielded value sees exactly what run() returns.
        """
        steps = 0
        first_step = True  # Skip breakpoint check on first iteration

        while not self._terminated:
            if max_steps > 0 and steps >= max_steps:
                break

            # Check breakpoints before executing (skip on first step to continue past current bp)
            if not first_step and self._c in self._breakpoints:
                bp = self._breakpoints[self._c]
                state = self.get_state()
                if bp.should_break(state):
                    state = MalbolgeState(
                        a=state.a, c=state.c, d=state.d,
                        raw_instruction=state.raw_instruction,
                        effective_opcode=state.effective_opcode,
                        opcode_name=state.opcode_name,
                        step_count=state.step_count,
                        output=state.output,
                        input_consumed=state.input_consumed,
                        stop_reason=StopReason.BREAKPOINT
                    )
                    if self._on_breakpoint:
                        self._on_breakpoint(bp, state)
                    if bp.temporary:
                        self.remove_breakpoint(self._c)
                    yield state
                    return

            # Check watchpoints
            for addr, wp in self._watchpoints.items():
                if wp.check(self._mem[addr]):
                    state = self.get_state()
                    yield MalbolgeState(
                        a=state.a, c=state.c, d=state.d,
                        raw_instruction=state.raw_instruction,
                        effective_opcode=state.effective_opcode,
                        opcode_name=state.opcode_name,
                        step_count=state.step_count,
                        output=state.output,
                        input_consumed=state.input_consumed,
                        stop_reason=StopReason.WATCHPOINT
                    )
                    return

            self.step()
            steps += 1
            first_step = False

            if chunk > 0 and steps % chunk == 0 and not self._terminated:
                yield self.get_state()

        yield self.get_state()

    def run(self, max_steps: int = -1) -> MalbolgeState:
        """
        Run until breakpoint, watchpoint, or termination.

        Args:
            max_steps: Maximum steps to execute (-1 for unlimited)

        Returns:
            State at stop point
        """
        # _run_iter always yields at least the stopping state; the pre-loop
        # assignment only guards against a future refactor of that guarantee.
        state = self.get_state()
        for state in self._run_iter(max_steps=max_steps, chunk=0):
            pass
        return state

    def run_chunked(self, chunk: int = 5000) -> Iterator[MalbolgeState]:
        """
        Run like run(), yielding the current state every `chunk` steps.

        The stop conditions are run()'s: breakpoint, watchpoint, termination
        or exhausted input. The last value yielded is the stopping state, and
        carries the same stop_reason run() would have returned.

        The caller may stop iterating at any point; the debugger is left on a
        clean instruction boundary and step()/run()/step_back() keep working.

        Args:
            chunk: Steps to execute between yields (must be positive)
        """
        if chunk <= 0:
            raise ValueError(f"chunk must be positive, got {chunk}")
        return self._run_iter(max_steps=-1, chunk=chunk)

    def run_to(self, address: int) -> MalbolgeState:
        """Run until reaching the specified address."""
        self.add_breakpoint(address, temporary=True)
        return self.run()

    def seek(self, step: int) -> MalbolgeState:
        """
        Move to `step` on the current timeline and return the state there.

        Walks backwards with step_back() when the target is behind the current
        position, forwards with step() when it is ahead.

        Raises:
            ValueError: if `step` lies outside seekable_range - either past
                max_step_reached, or so far back that _save_history has
                already dropped the entries needed to rebuild it.
        """
        low, high = self.seekable_range
        if step > high:
            raise ValueError(
                f"step {step} is beyond max_step_reached ({high})"
            )
        if step < low:
            raise ValueError(
                f"step {step} has dropped out of the history window "
                f"(seekable range is {low}..{high})"
            )

        while self._step_count > step:
            if self.step_back() is None:
                # Unreachable while seekable_range is honoured; a guard so a
                # bad bound degrades into an exception, not an endless loop.
                raise ValueError(
                    f"cannot reach step {step}: history exhausted at "
                    f"{self._step_count}"
                )

        while self._step_count < step:
            before = self._step_count
            self.step()
            if self._step_count == before:
                raise ValueError(
                    f"cannot reach step {step}: execution stopped at "
                    f"{self._step_count}"
                )

        return self.get_state()

    def reset(self) -> None:
        """Reset execution to initial state."""
        self._a = 0
        self._c = 0
        self._d = 0
        self._input_pos = 0
        self._output = ""
        self._step_count = 0
        self._terminated = False
        self._history.clear()
        self._write_heat.clear()
        self._max_step_reached = 0
        # Restore initial memory
        self._mem = self._initial_mem.copy()

    def set_input(self, input_data: str) -> None:
        """Set new input data (resets input position)."""
        self._input = input_data
        self._input_pos = 0

    # ==================== Callbacks ====================

    def on_step(self, callback: Callable[[MalbolgeState], None]) -> None:
        """Set callback for each step."""
        self._on_step = callback

    def on_output(self, callback: Callable[[str], None]) -> None:
        """Set callback for each output character."""
        self._on_output = callback

    def on_breakpoint(self, callback: Callable[[Breakpoint, MalbolgeState], None]) -> None:
        """Set callback for breakpoint hits."""
        self._on_breakpoint = callback

    # ==================== Disassembly ====================

    def disassemble(self, start: int = None, count: int = 10) -> List[Dict]:
        """
        Disassemble memory region.

        Args:
            start: Start address (defaults to current C)
            count: Number of instructions to disassemble

        Returns:
            List of instruction dictionaries
        """
        if start is None:
            start = max(0, self._c - count // 2)

        result = []
        for i in range(start, min(start + count, self._config.memory_size)):
            val = self._mem[i]
            if 33 <= val <= 126:
                opcode = (val + i) % 94
                result.append({
                    "address": i,
                    "raw": val,
                    "char": chr(val),
                    "opcode": opcode,
                    "mnemonic": OPCODE_NAMES.get(opcode, "???"),
                    "is_current": i == self._c,
                    "has_breakpoint": i in self._breakpoints
                })
            else:
                result.append({
                    "address": i,
                    "raw": val,
                    "char": ".",
                    "opcode": None,
                    "mnemonic": "DATA",
                    "is_current": i == self._c,
                    "has_breakpoint": i in self._breakpoints
                })
        return result

    def get_active_regions(self) -> List[Dict]:
        """Get list of active/interesting memory regions."""
        regions = [
            {
                "name": "source",
                "start": 0,
                "end": self._source_length,
                "description": "Original source code"
            },
            {
                "name": "code_ptr",
                "start": max(0, self._c - 10),
                "end": min(self._config.memory_size, self._c + 10),
                "description": "Around code pointer (C)"
            },
            {
                "name": "data_ptr",
                "start": max(0, self._d - 10),
                "end": min(self._config.memory_size, self._d + 10),
                "description": "Around data pointer (D)"
            }
        ]
        return regions

    # ==================== Teaching Mode Helpers ====================

    def to_ternary(self, n: int) -> List[int]:
        """Convert integer to ternary representation (LSB first)."""
        digits = []
        for _ in range(self._config.trit_width):
            digits.append(n % 3)
            n //= 3
        return digits

    def from_ternary(self, digits: List[int]) -> int:
        """Convert ternary (LSB first) to integer."""
        result = 0
        for i, d in enumerate(digits):
            result += d * (3 ** i)
        return result

    def get_opcode_help(self, opcode: int) -> Optional[Dict]:
        """Get detailed help information for an opcode."""
        return OPCODE_HELP.get(opcode)

    def explain_crazy_operation(self, a: int, b: int) -> Dict:
        """
        Explain the crazy operation step by step.

        Returns dict with:
        - a_ternary: List[int] - a in ternary (10 digits, LSB first)
        - b_ternary: List[int] - b in ternary
        - result_ternary: List[int] - result in ternary
        - result: int - final result
        - steps: List[Dict] - step-by-step calculation for each digit
        """
        a_tern = self.to_ternary(a)
        b_tern = self.to_ternary(b)
        result_tern = []
        steps = []

        for i in range(10):
            a_digit = a_tern[i]
            b_digit = b_tern[i]
            res_digit = TABLE_CRAZY[b_digit][a_digit]
            result_tern.append(res_digit)
            steps.append({
                'position': i,
                'a_digit': a_digit,
                'b_digit': b_digit,
                'result_digit': res_digit
            })

        result = self.from_ternary(result_tern)
        return {
            'a': a,
            'b': b,
            'a_ternary': a_tern,
            'b_ternary': b_tern,
            'result_ternary': result_tern,
            'result': result,
            'steps': steps,
            'table': TABLE_CRAZY
        }

    def explain_rotate_operation(self, n: int) -> Dict:
        """
        Explain the rotate operation step by step.

        Returns dict with:
        - original: int - original value
        - original_ternary: List[int] - original in ternary (LSB first)
        - rotated_ternary: List[int] - rotated in ternary
        - result: int - rotated value
        - lsb: int - the LSB that wrapped to MSB
        - formula: str - formula explanation
        """
        original_tern = self.to_ternary(n)
        lsb = n % 3
        rotated = POW9 * lsb + n // 3

        # Handle overflow (should not happen for valid values)
        if rotated >= self._config.memory_size:
            rotated = rotated % self._config.memory_size

        rotated_tern = self.to_ternary(rotated)

        return {
            'original': n,
            'original_ternary': original_tern,
            'rotated_ternary': rotated_tern,
            'result': rotated,
            'lsb': lsb,
            'formula': f"3^9 * ({n} % 3) + {n} // 3 = {POW9} * {lsb} + {n // 3} = {rotated}"
        }

    def preview_next_instruction(self) -> Dict:
        """
        Preview what will happen when the next instruction executes.

        Returns dict with:
        - opcode: int - calculated opcode
        - opcode_name: str - opcode name
        - opcode_calculation: Dict - how opcode was calculated
        - register_changes: Dict - predicted register changes {reg: (old, new)}
        - memory_changes: Dict - predicted memory changes {addr: (old, new)}
        - calculation_details: Optional[Dict] - detailed calculation for crz/rotr
        - will_encrypt: bool - whether instruction will be encrypted
        - encrypted_value: Optional[int] - new encrypted value
        - will_terminate: bool - whether this will terminate the program
        """
        if self._terminated:
            return {
                'opcode': -1,
                'opcode_name': 'N/A',
                'opcode_calculation': {},
                'register_changes': {},
                'memory_changes': {},
                'calculation_details': None,
                'will_encrypt': False,
                'encrypted_value': None,
                'will_terminate': True
            }

        raw = self._mem[self._c]
        if raw < 33 or raw > 126:
            return {
                'opcode': -1,
                'opcode_name': 'invalid',
                'opcode_calculation': {
                    'mem_c': raw,
                    'c': self._c,
                    'note': 'Invalid instruction (out of printable ASCII range)'
                },
                'register_changes': {},
                'memory_changes': {},
                'calculation_details': None,
                'will_encrypt': False,
                'encrypted_value': None,
                'will_terminate': True
            }

        opcode = (raw + self._c) % 94
        opcode_name = OPCODE_NAMES.get(opcode, "invalid")

        opcode_calc = {
            'mem_c': raw,
            'mem_c_char': chr(raw),
            'c': self._c,
            'sum': raw + self._c,
            'opcode': opcode,
            'formula': f"({raw} + {self._c}) % 94 = {opcode}"
        }

        # Predict changes based on opcode
        reg_changes = {}
        mem_changes = {}
        calc_details = None
        will_terminate = False

        # C and D always increment (unless terminated)
        new_c = 0 if self._c == self._config.memory_size - 1 else self._c + 1
        new_d = 0 if self._d == self._config.memory_size - 1 else self._d + 1

        if opcode == 4:  # jmp [d]
            new_c = self._mem[self._d]
            # After jmp, c still increments
            new_c = 0 if new_c == self._config.memory_size - 1 else new_c + 1
            reg_changes['c'] = (self._c, new_c - 1 if new_c > 0 else self._config.memory_size - 1)  # Show jump target
            reg_changes['d'] = (self._d, new_d)

        elif opcode == 5:  # out a
            reg_changes['c'] = (self._c, new_c)
            reg_changes['d'] = (self._d, new_d)
            # A doesn't change, but we show output effect
            calc_details = {
                'type': 'output',
                'char': chr(self._a % 256),
                'ascii': self._a % 256
            }

        elif opcode == 23:  # in a
            if self._input_pos < len(self._input):
                new_a = ord(self._input[self._input_pos])
                reg_changes['a'] = (self._a, new_a)
                calc_details = {
                    'type': 'input',
                    'char': self._input[self._input_pos],
                    'ascii': new_a
                }
            else:
                will_terminate = True
                calc_details = {
                    'type': 'input_exhausted',
                    'note': 'No more input available'
                }
            reg_changes['c'] = (self._c, new_c)
            reg_changes['d'] = (self._d, new_d)

        elif opcode == 39:  # rotr [d]; mov a, [d]
            rotated = self._rotate(self._mem[self._d])
            reg_changes['a'] = (self._a, rotated)
            reg_changes['c'] = (self._c, new_c)
            reg_changes['d'] = (self._d, new_d)
            mem_changes[self._d] = (self._mem[self._d], rotated)
            calc_details = self.explain_rotate_operation(self._mem[self._d])

        elif opcode == 40:  # mov d, [d]
            new_d_val = self._mem[self._d]
            # D changes to mem[D], then increments
            reg_changes['c'] = (self._c, new_c)
            reg_changes['d'] = (self._d, new_d_val)
            # Note: after mov, d still increments
            final_d = 0 if new_d_val == self._config.memory_size - 1 else new_d_val + 1
            reg_changes['d'] = (self._d, final_d)
            calc_details = {
                'type': 'mov',
                'mem_d': self._mem[self._d],
                'note': f'd = mem[{self._d}] = {self._mem[self._d]}'
            }

        elif opcode == 62:  # crz [d], a; mov a, [d]
            crazy_result = self._crazy(self._a, self._mem[self._d])
            reg_changes['a'] = (self._a, crazy_result)
            reg_changes['c'] = (self._c, new_c)
            reg_changes['d'] = (self._d, new_d)
            mem_changes[self._d] = (self._mem[self._d], crazy_result)
            calc_details = self.explain_crazy_operation(self._a, self._mem[self._d])

        elif opcode == 68:  # nop
            reg_changes['c'] = (self._c, new_c)
            reg_changes['d'] = (self._d, new_d)

        elif opcode == 81:  # end
            will_terminate = True

        # Calculate encryption
        will_encrypt = 33 <= self._mem[self._c] <= 126
        encrypted_value = None
        if will_encrypt:
            encrypted_value = ENCRYPT[self._mem[self._c] - 33]

        return {
            'opcode': opcode,
            'opcode_name': opcode_name,
            'opcode_calculation': opcode_calc,
            'register_changes': reg_changes,
            'memory_changes': mem_changes,
            'calculation_details': calc_details,
            'will_encrypt': will_encrypt,
            'encrypted_value': encrypted_value,
            'encrypt_address': self._c,
            'will_terminate': will_terminate
        }


def debug(code: str, input_data: str = "",
          config: Optional[MalbolgeConfig] = None) -> MalbolgeDebugger:
    """
    Convenience function to create a debugger session.

    Usage:
        dbg = debug(code)
        dbg.add_breakpoint(10)
        dbg.run()
        print(dbg.output)

    For Malbolge20:
        dbg = debug(code, config=MalbolgeConfig.malbolge20())
    """
    return MalbolgeDebugger(code, input_data, config=config)
