"""
Malbolge20 interpreter - 20-trit variant of Malbolge.

Malbolge20 extends the original Malbolge by using 20 trits instead of 10,
allowing for a vastly expanded address space of ~3.48 billion values (3^20).

Key differences from original Malbolge:
- Word size: 20 trits (vs 10)
- Memory size: 3^20 = 3,486,784,401 cells (vs 3^10 = 59,049)
- rotate() uses 20-bit rotation
- crazy() processes 20 ternary digits

The self-modifying code mechanism and instruction set remain the same.
"""

import sys
from typing import Union

from .core import (
    MalbolgeConfig,
    MalbolgeVariant,
    TABLE_CRAZY,
    ENCRYPT,
    OPS_VALID,
    rotate,
    crazy,
    create_memory,
    parse_source,
    SparseMemory,
)


# Malbolge20 configuration
CONFIG = MalbolgeConfig.malbolge20()
POW19 = CONFIG.rotate_multiplier  # 3^19 = 1,162,261,467
POW20 = CONFIG.memory_size        # 3^20 = 3,486,784,401

# Value of A after reading EOF. The Nagoya reference interpreter sets
# A = 59049 (= 3^10), NOT the all-2s value 3^20-1
# (ref/nagoya-malbolge20-interpreter/malbolge20.c: `if (x == EOF) a = 59049`).
EOF_A = 59049


def rotate20(n: int) -> int:
    """Rotate 20-trit ternary number right."""
    return rotate(n, CONFIG)


def crazy20(a: int, b: int) -> int:
    """Malbolge20's crazy operation (20 trits)."""
    return crazy(a, b, 20)


def initialize(source: str, mem: Union[SparseMemory, list]) -> None:
    """
    Load source code into memory.

    Args:
        source: Malbolge20 source code
        mem: Memory object (SparseMemory or list)
    """
    cells = parse_source(source, CONFIG)

    if hasattr(mem, 'initialize_source'):
        mem.initialize_source(cells)
    else:
        # List-based memory (for compatibility)
        for i, val in enumerate(cells):
            mem[i] = val
        i = len(cells)
        while i < len(mem):
            mem[i] = crazy20(mem[i-1], mem[i-2])
            i += 1


def interpret(mem: Union[SparseMemory, list]) -> None:
    """
    Execute Malbolge20 program.

    Args:
        mem: Initialized memory
    """
    write = sys.stdout.buffer.write
    flush = sys.stdout.buffer.flush
    read = sys.stdin.buffer.read

    a, c, d = 0, 0, 0
    mem_size = POW20

    while True:
        if mem[c] < 33 or mem[c] > 126:
            return

        v = (mem[c] + c) % 94

        if v == 4:      # jmp [d]
            c = mem[d]
        elif v == 5:    # out a
            write(bytes([int(a % 256)]))
            flush()
        elif v == 23:   # in a
            ch = read(1)
            a = ch[0] if ch else EOF_A
        elif v == 39:   # rotr[d]; mov a, [d]
            a = mem[d] = rotate20(mem[d])
        elif v == 40:   # mov d, [d]
            d = mem[d]
        elif v == 62:   # crz [d], a; mov a, [d]
            a = mem[d] = crazy20(a, mem[d])
        elif v == 81:   # end
            return
        # v == 68: nop

        if 33 <= mem[c] <= 126:
            mem[c] = ENCRYPT[mem[c] - 33]

        c = 0 if c == mem_size - 1 else c + 1
        d = 0 if d == mem_size - 1 else d + 1


def eval(code: str, input_data: str = "", eof: str = 'stop') -> str:
    """
    Evaluate Malbolge20 code and return output as string.

    Args:
        code: Malbolge20 source code
        input_data: Input string for the program
        eof: 'stop' returns collected output when input runs out;
             'sentinel' sets A to EOF_A (59049, per the Nagoya reference
             interpreter) and lets the program decide

    Returns:
        Program output as string
    """
    if eof not in ('stop', 'sentinel'):
        raise ValueError(f"eof must be 'stop' or 'sentinel', got {eof!r}")
    mem = create_memory(CONFIG)
    cells = parse_source(code, CONFIG)
    mem.initialize_source(cells)

    output = ""
    input_pos = 0
    a, c, d = 0, 0, 0
    mem_size = POW20

    while True:
        if mem[c] < 33 or mem[c] > 126:
            return output

        v = (mem[c] + c) % 94

        if v == 4:      # jmp [d]
            c = mem[d]
        elif v == 5:    # out a
            output += chr(int(a % 256))
        elif v == 23:   # in a
            if input_pos >= len(input_data):
                if eof == 'stop':
                    return output
                a = EOF_A
            else:
                a = ord(input_data[input_pos])
                input_pos += 1
        elif v == 39:   # rotr[d]; mov a, [d]
            a = mem[d] = rotate20(mem[d])
        elif v == 40:   # mov d, [d]
            d = mem[d]
        elif v == 62:   # crz [d], a; mov a, [d]
            a = mem[d] = crazy20(a, mem[d])
        elif v == 81:   # end
            return output
        # v == 68: nop

        if 33 <= mem[c] <= 126:
            mem[c] = ENCRYPT[mem[c] - 33]

        c = 0 if c == mem_size - 1 else c + 1
        d = 0 if d == mem_size - 1 else d + 1


def main():
    """Command-line entry point for Malbolge20 interpreter."""
    if len(sys.argv) < 2:
        print('Usage: python -m malbolge.malbolge20 <file.mal>')
        sys.exit(1)

    filename = sys.argv[1]

    try:
        with open(filename, 'r') as f:
            source = f.read()
    except IOError:
        print(f'Unable to open file: {filename}')
        sys.exit(1)

    mem = create_memory(CONFIG)
    try:
        cells = parse_source(source, CONFIG)
        mem.initialize_source(cells)
    except ValueError as e:
        print(f'Error: {e}')
        sys.exit(1)

    try:
        interpret(mem)
    except KeyboardInterrupt:
        print('\nUser interrupt')
        sys.exit(0)


if __name__ == '__main__':
    main()
