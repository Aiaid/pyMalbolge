"""
Core components for Malbolge variants.

This module provides shared infrastructure for:
- Original Malbolge (10 trits)
- Malbolge20 (20 trits)
- Malbolge Unshackled (unbounded, future)
"""

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
        result += TABLE_CRAZY[int((b / d) % 3)][int((a / d) % 3)] * d
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


class SparseMemory:
    """
    Block-based sparse memory for large address spaces.

    Memory is divided into blocks of 3^(trit_width/2) cells (59,049 for
    Malbolge20), following the Nagoya reference interpreter.  A block's
    default (crazy-fill) contents are fully determined by its first two words
    ("seeds"); seeds of far blocks are derived with a per-trit jump map, so
    accessing any address materializes at most one block instead of filling
    everything below it.

    Explicit writes go to an overlay dict, so get_allocated_count() counts
    written cells only and defaults stay shared between copies.
    """

    def __init__(self, config: MalbolgeConfig):
        self.config = config
        self.size = config.memory_size
        self.block_size = 3 ** (config.trit_width - config.trit_width // 2)
        self.num_blocks = self.size // self.block_size
        self._data: Dict[int, int] = {}      # explicit writes (and source)
        self._source_length: int = 0
        # First address whose value comes from the crazy-fill rule; cells
        # below it that are not in _data read as 0 (cells 0 and 1 default
        # to 0 when the source is shorter than 2 cells).
        self._fill_start: int = 2
        self._tail_block: int = 0
        self._default_blocks: Dict[int, List[int]] = {}  # lazily materialized
        self._seeds: Dict[int, tuple] = {}   # block index -> (word0, word1)

    def initialize_source(self, source_cells: List[int]) -> None:
        """Initialize memory with source code values."""
        for i, val in enumerate(source_cells):
            self._data[i] = val
        self._source_length = len(source_cells)
        self._fill_start = max(len(source_cells), 2)
        self._tail_block = self._fill_start // self.block_size
        self._default_blocks = {}
        self._seeds = {}

    def _materialize_block(self, block: int) -> List[int]:
        """Compute and cache the default (crazy-fill) contents of a block."""
        blk = self._default_blocks.get(block)
        if blk is not None:
            return blk

        bs = self.block_size
        trit_width = self.config.trit_width
        blk = [0] * bs

        if block == self._tail_block:
            # Continue the fill right after the source (cells before
            # _fill_start stay 0 in blk; reads of source cells hit _data).
            start = self._fill_start
            p1 = self._data.get(start - 1, 0)
            p2 = self._data.get(start - 2, 0)
            for i in range(start - block * bs, bs):
                p2, p1 = p1, crazy(p1, p2, trit_width)
                blk[i] = p1
        else:
            s0, s1 = self._seed_for_block(block)
            blk[0], blk[1] = s0, s1
            p2, p1 = s0, s1
            for i in range(2, bs):
                p2, p1 = p1, crazy(p1, p2, trit_width)
                blk[i] = p1

        self._default_blocks[block] = blk
        return blk

    def _seed_for_block(self, block: int) -> tuple:
        """Seeds (first two default words) of a block past the tail block."""
        seeds = self._seeds
        cached = seeds.get(block)
        if cached is not None:
            return cached

        if not seeds:
            # Base case: derive from the last two cells of the tail block
            # (via __getitem__, since they may be source cells in _data).
            tail_end = (self._tail_block + 1) * self.block_size
            last, last_but_one = self[tail_end - 1], self[tail_end - 2]
            trit_width = self.config.trit_width
            s0 = crazy(last, last_but_one, trit_width)
            s1 = crazy(s0, last, trit_width)
            seeds[self._tail_block + 1] = (s0, s1)

        jump = _block_seed_jump_map(self.block_size)
        start = max(k for k in seeds if k <= block) if any(
            k <= block for k in seeds) else min(seeds)
        s0, s1 = seeds[start]
        for k in range(start, block):
            n0 = n1 = 0
            p = 1
            for _ in range(self.config.trit_width):
                u0, u1 = jump[(s0 % 3, s1 % 3)]
                n0 += u0 * p
                n1 += u1 * p
                s0 //= 3
                s1 //= 3
                p *= 3
            s0, s1 = n0, n1
            seeds[k + 1] = (s0, s1)
        return seeds[block]

    def __getitem__(self, addr: int) -> int:
        """Get memory value at address."""
        if addr < 0 or addr >= self.size:
            raise IndexError(f"Memory address {addr} out of range (0-{self.size-1})")

        value = self._data.get(addr)
        if value is not None:
            return value

        if addr < self._fill_start:
            return 0

        block, offset = divmod(addr, self.block_size)
        return self._materialize_block(block)[offset]

    def __setitem__(self, addr: int, value: int) -> None:
        """Set memory value at address."""
        if addr < 0 or addr >= self.size:
            raise IndexError(f"Memory address {addr} out of range (0-{self.size-1})")
        self._data[addr] = value

    def __len__(self) -> int:
        """Return logical size of memory."""
        return self.size

    def get_allocated_count(self) -> int:
        """Return number of explicitly written cells."""
        return len(self._data)

    def copy(self) -> 'SparseMemory':
        """Create a copy of this memory.

        Default-fill caches are derived data shared with the copy; only the
        write overlay is duplicated.
        """
        new_mem = SparseMemory(self.config)
        new_mem._data = self._data.copy()
        new_mem._source_length = self._source_length
        new_mem._fill_start = self._fill_start
        new_mem._tail_block = self._tail_block
        new_mem._default_blocks = self._default_blocks
        new_mem._seeds = self._seeds
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
        # Copy source
        for i, val in enumerate(source_cells):
            self._data[i] = val

        # Fill remaining with crazy operation
        i = len(source_cells)
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


def parse_source(source: str, config: MalbolgeConfig) -> List[int]:
    """
    Parse source code and validate characters.

    Args:
        source: Malbolge source code string
        config: Malbolge configuration

    Returns:
        List of cell values

    Raises:
        ValueError: If source contains invalid characters or is too long
    """
    cells = []

    for char in source:
        if char in (' ', '\n', '\r', '\t'):
            continue

        i = len(cells)
        if (ord(char) + i) % 94 not in OPS_VALID:
            raise ValueError(f"Invalid character '{char}' at position {i}")

        if i >= config.memory_size:
            raise ValueError(f"Source file is too long (max {config.memory_size} cells)")

        cells.append(ord(char))

    return cells
