"""
ViewModel layer: what the debugger's state MEANS, as plain data.

This package sits between :mod:`malbolge.debugger` and any renderer. It is
what the Textual TUI and the (planned) Pyodide web build share; what they do
NOT share is presentation. Contracts are specified in
``docs/design/tui-web-architecture.md`` §3 — those field names are normative.

Two rules, both enforced at runtime rather than by review:

1. **Nothing here may import textual.** The web build runs this layer inside
   Pyodide, where Textual is neither present nor meaningful.

2. **Every return value must survive ``json.dumps()``.** The web build runs
   Pyodide inside a Web Worker, and Worker traffic goes through structured
   clone. A stray ``Enum``, callable or Rich object breaks the web build at
   runtime instead of at review time. Concretely: ``StopReason`` is emitted as
   ``.value`` (a ``str``), and ``Breakpoint.condition`` — a ``Callable`` —
   is emitted as ``has_condition: bool``, never as the predicate.

Each panel module exposes ``build(dbg, ...) -> dict``; they are re-exported
here under distinct names. Renderers should normally call
:func:`build_snapshot` instead, which constructs all six from a single moment
-- building them independently is what produces a torn frame during timeline
scrubbing (disassembly at step 900, memory still at step 380).
"""

from .breakpoints import build as build_breakpoints
from .disasm import build as build_disasm
from .memory import build as build_memory
from .registers import build as build_registers
from .snapshot import build_snapshot
from .teaching import build as build_teaching
from .timeline import build as build_timeline

__all__ = [
    'build_snapshot',
    'build_registers',
    'build_disasm',
    'build_memory',
    'build_teaching',
    'build_timeline',
    'build_breakpoints',
]
