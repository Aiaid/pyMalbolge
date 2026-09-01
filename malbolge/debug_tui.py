"""
Malbolge Debugger TUI - compatibility shim.

The implementation now lives in the :mod:`malbolge.tui` package; this module
stays as the public import path used by ``malbolge/__main__.py``,
``malbolge/debug_cli.py``, the ``malbolge-tui`` script, the README and
CLAUDE.md.

Usage:
    python -m malbolge.debug_tui <file.mal> [-i input]
"""

from .tui import HAS_TEXTUAL, run_tui, main

__all__ = ['HAS_TEXTUAL', 'run_tui', 'main']

if HAS_TEXTUAL:
    # Mirrors the single-file version: ``DebuggerApp`` only exists when
    # textual could be imported.
    from .tui import DebuggerApp

    __all__.append('DebuggerApp')


if __name__ == '__main__':
    main()
