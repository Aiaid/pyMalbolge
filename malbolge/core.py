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


class SparseMemory:
    """
    Sparse memory implementation for large address spaces.

    Only stores cells that have been accessed or modified.
    Generates default values on-demand using the crazy operation.
    """

    def __init__(self, config: MalbolgeConfig):
        """
        Initialize sparse memory.

        Args:
            config: Malbolge configuration
        """
        self.config = config
        self.size = config.memory_size
        self._data: Dict[int, int] = {}
        self._initialized_up_to: int = 0  # Track sequential initialization
        self._source_length: int = 0

    def initialize_source(self, source_cells: List[int]) -> None:
        """
        Initialize memory with source code values.

        Args:
            source_cells: List of cell values from source code
        """
        for i, val in enumerate(source_cells):
            self._data[i] = val
        self._source_length = len(source_cells)
        self._initialized_up_to = len(source_cells)

    def _generate_value(self, addr: int) -> int:
        """Generate value for uninitialized address using crazy operation."""
        # Need values at addr-1 and addr-2
        if addr < 2:
            return 0

        # Ensure previous values exist
        val_minus_1 = self[addr - 1]
        val_minus_2 = self[addr - 2]

        return crazy(val_minus_1, val_minus_2, self.config.trit_width)

    def __getitem__(self, addr: int) -> int:
        """Get memory value at address."""
        if addr < 0 or addr >= self.size:
            raise IndexError(f"Memory address {addr} out of range (0-{self.size-1})")

        if addr in self._data:
            return self._data[addr]

        # Generate and cache value
        if addr >= self._source_length:
            value = self._generate_value(addr)
            self._data[addr] = value
            return value

        return 0

    def __setitem__(self, addr: int, value: int) -> None:
        """Set memory value at address."""
        if addr < 0 or addr >= self.size:
            raise IndexError(f"Memory address {addr} out of range (0-{self.size-1})")
        self._data[addr] = value

    def __len__(self) -> int:
        """Return logical size of memory."""
        return self.size

    def get_allocated_count(self) -> int:
        """Return number of actually allocated cells."""
        return len(self._data)

    def copy(self) -> 'SparseMemory':
        """Create a copy of this memory."""
        new_mem = SparseMemory(self.config)
        new_mem._data = self._data.copy()
        new_mem._initialized_up_to = self._initialized_up_to
        new_mem._source_length = self._source_length
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
