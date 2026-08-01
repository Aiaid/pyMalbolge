"""
pyMalbolge - A Python interpreter for the Malbolge esoteric programming language.

Supports multiple variants:
- Original Malbolge (10 trits, 59,049 memory cells)
- Malbolge20 (20 trits, ~3.48 billion memory cells)

Basic usage:
    from malbolge import eval
    result = eval(code)

Malbolge20:
    from malbolge import eval20
    result = eval20(code)

Debugging:
    from malbolge import MalbolgeDebugger
    dbg = MalbolgeDebugger(code)
    dbg.add_breakpoint(10)
    dbg.run()
"""

from .malbolge import eval, interpret, initialize, crazy, rotate

from .malbolge20 import (
    eval as eval20,
    interpret as interpret20,
    initialize as initialize20,
    crazy20,
    rotate20,
)

from .core import (
    MalbolgeConfig,
    MalbolgeVariant,
    SparseMemory,
    DenseMemory,
    create_memory,
    TABLE_CRAZY,
    ENCRYPT,
    OPS_VALID,
)

from .debugger import (
    MalbolgeDebugger,
    MalbolgeState,
    Breakpoint,
    Watchpoint,
    StopReason,
    debug,
)

__version__ = "1.0.0"

__all__ = [
    # Original interpreter
    'eval',
    'interpret',
    'initialize',
    'crazy',
    'rotate',
    # Malbolge20 interpreter
    'eval20',
    'interpret20',
    'initialize20',
    'crazy20',
    'rotate20',
    # Core components
    'MalbolgeConfig',
    'MalbolgeVariant',
    'SparseMemory',
    'DenseMemory',
    'create_memory',
    'TABLE_CRAZY',
    'ENCRYPT',
    'OPS_VALID',
    # Debugger
    'MalbolgeDebugger',
    'MalbolgeState',
    'Breakpoint',
    'Watchpoint',
    'StopReason',
    'debug',
]
