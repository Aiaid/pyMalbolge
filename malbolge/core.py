"""
Core components for Malbolge variants.

This module provides shared infrastructure for:
- Original Malbolge (10 trits)
- Malbolge20 (20 trits)
- Malbolge Unshackled (unbounded, future)
"""

from array import array
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Callable, List


class MalbolgeVariant(Enum):
    """Supported Malbolge variants."""
    ORIGINAL = "malbolge"      # 10 trits, 3^10 memory
    MALBOLGE20 = "malbolge20"  # 20 trits, 3^20 memory
    UNSHACKLED = "unshackled"  # Unbounded (future)


# The crazy operation lookup table (shared across all variants)
TABLE_CRAZY = (
    (1, 0, 0),
    (1, 0, 2),
    (2, 2, 1)
)

# Encryption table for self-modifying code (shared)
ENCRYPT = list(map(ord,
    '5z]&gqtyfr$(we4{WP)H-Zn,[%\\3dL+Q;>U!pJS72FhOA1CB'
    '6v^=I_0/8|jsb9m<.TVac`uY*MK\'X~xDl}REokN:#?G"i@'))

# Valid opcodes (shared)
OPS_VALID = (4, 5, 23, 39, 40, 62, 68, 81)


@dataclass
class MalbolgeConfig:
    """Configuration for a Malbolge variant."""
    variant: MalbolgeVariant
    trit_width: int           # Number of ternary digits (10 or 20)
    memory_size: int          # Total memory cells (3^trit_width)
    rotate_multiplier: int    # 3^(trit_width-1) for rotate operation
    use_sparse_memory: bool = False  # Use sparse memory for large variants

    @classmethod
    def original(cls) -> 'MalbolgeConfig':
        """Create config for original Malbolge."""
        return cls(
            variant=MalbolgeVariant.ORIGINAL,
            trit_width=10,
            memory_size=3**10,  # 59,049
            rotate_multiplier=3**9,  # 19,683
            use_sparse_memory=False
        )

    @classmethod
    def malbolge20(cls) -> 'MalbolgeConfig':
        """Create config for Malbolge20."""
        return cls(
            variant=MalbolgeVariant.MALBOLGE20,
            trit_width=20,
            memory_size=3**20,  # 3,486,784,401
            rotate_multiplier=3**19,
            use_sparse_memory=True  # Must use sparse memory
        )


def rotate(n: int, config: MalbolgeConfig) -> int:
    """
    Rotate ternary number right by one digit.

    The LSB wraps to become the MSB.
    Formula: rotate_multiplier * (n % 3) + n // 3
    """
    return config.rotate_multiplier * (n % 3) + n // 3


def crazy(a: int, b: int, trit_width: int) -> int:
    """
    Malbolge's 'crazy' operation.

    Performs digit-by-digit ternary lookup using TABLE_CRAZY.

    Args:
        a: First operand
        b: Second operand
        trit_width: Number of ternary digits to process (10 or 20)
    """
    result = 0
    d = 1
    for _ in range(trit_width):
        result += TABLE_CRAZY[(b // d) % 3][(a // d) % 3] * d
        d *= 3
    return result


def _block_seed_jump_map(block_size: int) -> Dict[tuple, tuple]:
    """
    Per-trit map from a block's first two trits to the next block's first two.

    The crazy-fill rule mem[i] = crazy(mem[i-1], mem[i-2]) acts on each trit
    independently, so given the trit pair at a block start, the trit pair at
    the next block start (after block_size fill steps plus the two seed
    combination steps) is a pure function of it.  This lets seeds for
    arbitrarily far blocks be chained without filling the gap — the same trick
    as the num0/num1 tables in the Nagoya reference interpreter
    (ref/nagoya-malbolge20-interpreter/malbolge20.c, make_init_mem).
    """
    cached = _block_seed_jump_map._cache.get(block_size)
    if cached is not None:
        return cached
    result = {}
    for t0 in range(3):
        for t1 in range(3):
            prev2, prev1 = t0, t1
            for _ in range(block_size - 2):
                prev2, prev1 = prev1, TABLE_CRAZY[prev2][prev1]
            # prev2/prev1 are now the block's last-but-one/last trits
            u0 = TABLE_CRAZY[prev2][prev1]   # crazy(last, last_but_one)
            u1 = TABLE_CRAZY[prev1][u0]      # crazy(u0, last)
            result[(t0, t1)] = (u0, u1)
    _block_seed_jump_map._cache[block_size] = result
    return result


_block_seed_jump_map._cache = {}


class _MemoryBlock:
    """A mutable page shared by snapshots until either owner writes it."""
    __slots__ = ("values", "written", "shared")

    def __init__(self, values, written=None):
        self.values = values
        self.written = written if written is not None else bytearray(len(values))
        self.shared = False

    def copy(self):
        return _MemoryBlock(self.values[:], self.written[:])


class SparseMemory:
    """Compact immutable source plus copy-on-write mutable pages.

    Source bytes cost one byte per cell, not a Python object/dict entry.
    Instruction encryption writes into byte pages; wide data writes promote
    just that page to uint32 (arbitrary Python integers retain a list fallback).
    Initialization fill is an immutable periodic sequence derived from frozen
    seeds. Reads, writes, copies, and debugger probes cannot change that fill.
    """
    _PAGE_SIZE = 4096

    def __init__(self, config: MalbolgeConfig):
        self.config = config
        self.size = config.memory_size
        self.block_size = 3 ** (config.trit_width - config.trit_width // 2)
        self.num_blocks = self.size // self.block_size
        self.initialize_source(b"")

    def initialize_source(self, source_cells) -> None:
        if len(source_cells) > self.size:
            raise ValueError("Source file is too long")
        if isinstance(source_cells, bytes):
            source = source_cells
        elif isinstance(source_cells, array) or (
                isinstance(source_cells, memoryview) and source_cells.itemsize > 1):
            source = memoryview(array("I", source_cells).tobytes()).cast("I")
        else:
            try:
                source = bytes(source_cells)
            except (ValueError, OverflowError):
                try:
                    # Read-only compact wide-word backing, detached from callers.
                    source = memoryview(array("I", source_cells).tobytes()).cast("I")
                except (ValueError, OverflowError):
                    source = tuple(source_cells)
        self._source = source
        self._source_length = len(source)
        self._fill_start = max(len(source), 2)
        self._tail_block = self._fill_start // self.block_size
        p1 = source[-1] if len(source) > 1 else 0
        p2 = source[-2] if len(source) > 1 else (source[0] if source else 0)
        self._initial_tail = (p1, p2)
        # Each trit's pair transition has at most a one-step transient and
        # period dividing six. Detect the word-pair cycle rather than assuming
        # a phase; this also handles empty and one-cell sources exactly.
        seen, values = {}, []
        while (p2, p1) not in seen:
            seen[(p2, p1)] = len(values)
            p2, p1 = p1, crazy(p1, p2, self.config.trit_width)
            values.append(p1)
        self._fill_values = tuple(values)
        self._cycle_start = seen[(p2, p1)]
        self._cycle_length = len(values) - self._cycle_start
        self._blocks = {}
        self._allocated_count = len(source)

    def _initial_value(self, addr):
        if addr < self._source_length:
            return self._source[addr]
        if addr < self._fill_start:
            return 0
        offset = addr - self._fill_start
        if offset >= len(self._fill_values):
            offset = self._cycle_start + (offset - self._cycle_start) % self._cycle_length
        return self._fill_values[offset]

    def _materialize_block(self, block):
        """Compatibility helper: immutable initialization defaults only."""
        start = block * self.block_size
        return tuple(self._initial_value(i) for i in
                     range(start, min(start + self.block_size, self.size)))

    def _seed_for_block(self, block):
        start = block * self.block_size
        return self._initial_value(start), self._initial_value(start + 1)

    def __getitem__(self, addr):
        if isinstance(addr, slice):
            return [self[i] for i in range(*addr.indices(self.size))]
        if addr < 0 or addr >= self.size:
            raise IndexError(f"Memory address {addr} out of range (0-{self.size-1})")
        page, offset = divmod(addr, self._PAGE_SIZE)
        block = self._blocks.get(page)
        if block is not None:
            return block.values[offset]
        return self._initial_value(addr)

    def __setitem__(self, addr, value):
        if addr < 0 or addr >= self.size:
            raise IndexError(f"Memory address {addr} out of range (0-{self.size-1})")
        page, offset = divmod(addr, self._PAGE_SIZE)
        block = self._blocks.get(page)
        if block is None:
            start = page * self._PAGE_SIZE
            end = min(start + self._PAGE_SIZE, self.size)
            if isinstance(self._source, bytes) and end <= self._source_length:
                values = bytearray(self._source[start:end])
            else:
                initial = [self._initial_value(i) for i in range(start, end)]
                try:
                    values = array("I", initial)
                except (ValueError, OverflowError):
                    values = initial
            block = self._blocks[page] = _MemoryBlock(values)
        elif block.shared:
            block = self._blocks[page] = block.copy()
        if isinstance(block.values, bytearray) and not 0 <= value <= 255:
            block.values = array("I", list(block.values))
        if isinstance(block.values, array) and not 0 <= value <= 0xffffffff:
            block.values = list(block.values)
        block.values[offset] = value
        if addr >= self._source_length and not block.written[offset]:
            block.written[offset] = 1
            self._allocated_count += 1

    def __len__(self):
        return self.size

    def get_allocated_count(self):
        """Source cells plus unique explicitly written non-source cells."""
        return self._allocated_count

    def copy(self):
        # No source/default-fill copy, and no copying mutable page payloads.
        new_mem = object.__new__(SparseMemory)
        new_mem.__dict__ = self.__dict__.copy()
        new_mem._blocks = self._blocks.copy()
        for block in self._blocks.values():
            block.shared = True
        return new_mem


class DenseMemory:
    """
    Dense memory implementation for small address spaces.

    Uses a simple list for O(1) access to all cells.
    """

    def __init__(self, config: MalbolgeConfig):
        """
        Initialize dense memory.

        Args:
            config: Malbolge configuration
        """
        self.config = config
        self.size = config.memory_size
        self._data: List[int] = [0] * self.size

    def initialize_source(self, source_cells: List[int]) -> None:
        """
        Initialize memory with source code, then fill rest with crazy operation.

        Args:
            source_cells: List of cell values from source code
        """
        self._data = [0] * self.size
        # Copy source
        for i, val in enumerate(source_cells):
            self._data[i] = val

        # Fill remaining with crazy operation
        i = max(len(source_cells), 2)
        while i < self.size:
            self._data[i] = crazy(self._data[i-1], self._data[i-2], self.config.trit_width)
            i += 1

    def __getitem__(self, addr: int) -> int:
        """Get memory value at address."""
        return self._data[addr]

    def __setitem__(self, addr: int, value: int) -> None:
        """Set memory value at address."""
        self._data[addr] = value

    def __len__(self) -> int:
        """Return size of memory."""
        return self.size

    def copy(self) -> 'DenseMemory':
        """Create a copy of this memory."""
        new_mem = DenseMemory(self.config)
        new_mem._data = self._data.copy()
        return new_mem


def create_memory(config: MalbolgeConfig):
    """
    Create appropriate memory type for the given configuration.

    Returns:
        SparseMemory or DenseMemory instance
    """
    if config.use_sparse_memory:
        return SparseMemory(config)
    else:
        return DenseMemory(config)


def parse_source(source, config: MalbolgeConfig):
    """Validate source without a per-cell Python list.

    Byte-valued source returns immutable bytes; legacy wide text remains a
    compact uint32 sequence. Validation is grouped by the 94-position opcode
    period, so normal large ASCII images are checked in C-level byte scans.
    """
    if isinstance(source, str):
        try:
            raw = source.encode("latin1")
        except UnicodeEncodeError:
            cells = array("I")
            for char in source:
                if char in " \n\r\t":
                    continue
                i, value = len(cells), ord(char)
                if (value + i) % 94 not in OPS_VALID:
                    raise ValueError(f"Invalid character {char!r} at position {i}")
                if i >= config.memory_size:
                    raise ValueError(f"Source file is too long (max {config.memory_size} cells)")
                cells.append(value)
            return cells
    else:
        raw = bytes(source)
    cells = raw.translate(None, b" \n\r\t")
    if len(cells) > config.memory_size:
        raise ValueError(f"Source file is too long (max {config.memory_size} cells)")
    first_bad = None
    for residue in range(min(94, len(cells))):
        allowed = bytes(value for value in range(256)
                        if (value + residue) % 94 in OPS_VALID)
        column = cells[residue::94]
        if column.translate(None, allowed):
            for offset, value in enumerate(column):
                if (value + residue) % 94 not in OPS_VALID:
                    position = residue + offset * 94
                    first_bad = position if first_bad is None else min(first_bad, position)
                    break
    if first_bad is not None:
        raise ValueError(f"Invalid character {chr(cells[first_bad])!r} at position {first_bad}")
    return cells


@dataclass(frozen=True)
class RunResult:
    """Byte-oriented bounded execution result, at an instruction boundary."""
    output: bytes
    stop_reason: str
    steps: int
    input_consumed: int
    a: int
    c: int
    d: int

    @property
    def output_count(self):
        return len(self.output)

    def to_dict(self):
        return {"stop_reason": self.stop_reason, "steps": self.steps,
                "input_consumed": self.input_consumed,
                "output_count": len(self.output), "output_hex": self.output.hex(),
                "registers": {"a": self.a, "c": self.c, "d": self.d}}


def run_memory(mem, config, input_data=b"", *, max_steps=None,
               max_output=None, eof="sentinel"):
    """Execute initialized memory with explicit byte I/O and resource bounds.

    Text input is explicitly encoded as UTF-8; input consumption counts bytes.
    Legacy eval() retains its historical Unicode-codepoint input semantics.
    A stop instruction counts as an executed step. Invalid instructions and
    budget/input stops do not execute the pending instruction. Output caps are
    checked before an output instruction would exceed the allowed byte count.
    """
    if isinstance(input_data, str):
        data = input_data.encode("utf8")
    elif isinstance(input_data, (bytes, bytearray, memoryview)):
        data = bytes(input_data)
    else:
        raise TypeError("input_data must be text or bytes-like")
    for name, value in (("max_steps", max_steps), ("max_output", max_output)):
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError(f"{name} must be a nonnegative integer or None")
    if eof not in ("sentinel", "stop"):
        raise ValueError("eof must be 'stop' or 'sentinel'")
    sentinel = 59049 if config.variant == MalbolgeVariant.MALBOLGE20 else config.memory_size - 1
    a = c = d = steps = position = 0
    output = bytearray()
    size, multiplier, width = config.memory_size, config.rotate_multiplier, config.trit_width
    while True:
        if max_steps is not None and steps >= max_steps:
            reason = "step_limit"
            break
        raw = mem[c]
        if not 33 <= raw <= 126:
            reason = "invalid_instruction"
            break
        opcode = (raw + c) % 94
        if opcode == 5 and max_output is not None and len(output) >= max_output:
            reason = "output_limit"
            break
        if opcode == 23 and position >= len(data) and eof == "stop":
            reason = "input_exhausted"
            break
        steps += 1
        if opcode == 4:
            c = mem[d]
        elif opcode == 5:
            output.append(a % 256)
        elif opcode == 23:
            if position < len(data):
                a = data[position]
                position += 1
            else:
                a = sentinel
        elif opcode == 39:
            value = mem[d]
            a = mem[d] = multiplier * (value % 3) + value // 3
        elif opcode == 40:
            d = mem[d]
        elif opcode == 62:
            a = mem[d] = crazy(a, mem[d], width)
        elif opcode == 81:
            reason = "terminated"
            break
        value = mem[c]
        if 33 <= value <= 126:
            mem[c] = ENCRYPT[value - 33]
        c = 0 if c == size - 1 else c + 1
        d = 0 if d == size - 1 else d + 1
    return RunResult(bytes(output), reason, steps, position, a, c, d)
