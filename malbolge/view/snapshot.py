"""
The snapshot -- all six ViewModels built from one moment in time.

Contract: ``docs/design/tui-web-architecture.md`` §3.7. See
:mod:`malbolge.view` for the two rules this package must obey.

This module exists for one reason: **the six ViewModels must be built from a
single debugger state**. Timeline scrubbing triggers a rebuild on every drag
event, and a model where each panel asks the debugger for itself produces torn
frames -- disassembly at step 900 while memory is still at step 380. Building
them together, from one debugger that nobody steps in between, is what makes
that impossible.

The builders are pure reads: none of them steps, seeks or otherwise mutates
the debugger, so the six parts of a snapshot always describe the same step.
"""

from typing import Any, Dict

from ..debugger import MalbolgeDebugger
from . import breakpoints, disasm, memory, registers, teaching, timeline


def build_snapshot(dbg: MalbolgeDebugger, *, mem_offset: int = 0,
                   mem_count: int = 24,
                   disasm_count: int = 11) -> Dict[str, Any]:
    """Build all six ViewModels from the debugger's current state.

    Returns ``{"registers": …, "disasm": …, "memory": …, "teaching": …,
    "timeline": …, "breakpoints": …}``.

    Args:
        dbg: the debugger to snapshot. It is only read, never stepped.
        mem_offset: MemoryView scroll offset relative to D (§3.3).
        mem_count: number of memory cells in the window.
        disasm_count: number of disassembly rows around C.
    """
    return {
        "registers": registers.build(dbg),
        "disasm": disasm.build(dbg, count=disasm_count),
        "memory": memory.build(dbg, offset=mem_offset, count=mem_count),
        "teaching": teaching.build(dbg),
        "timeline": timeline.build(dbg),
        "breakpoints": breakpoints.build(dbg),
    }
