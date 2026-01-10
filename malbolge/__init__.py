"""
pyMalbolge - A Python interpreter for the Malbolge esoteric programming language.

Basic usage:
    from malbolge import eval
    result = eval(code)

Debugging:
    from malbolge import MalbolgeDebugger
    dbg = MalbolgeDebugger(code)
    dbg.add_breakpoint(10)
    dbg.run()
"""

from .malbolge import eval, interpret, initialize, crazy, rotate

from .debugger import (
    MalbolgeDebugger,
    MalbolgeState,
    Breakpoint,
    Watchpoint,
    StopReason,
    debug,
)

__version__ = "0.1.0"

__all__ = [
    # Original interpreter
    'eval',
    'interpret',
    'initialize',
    'crazy',
    'rotate',
    # Debugger
    'MalbolgeDebugger',
    'MalbolgeState',
    'Breakpoint',
    'Watchpoint',
    'StopReason',
    'debug',
]
