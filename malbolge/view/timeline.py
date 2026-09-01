"""
TimelineView -- timeline / scrubber panel data.

Contract: ``docs/design/tui-web-architecture.md`` §3.5. Field names are
normative; see :mod:`malbolge.view` for the two rules this package must obey.
"""

from typing import Any, Dict

from ..debugger import MalbolgeDebugger


def build(dbg: MalbolgeDebugger) -> Dict[str, Any]:
    """Build a :class:`TimelineView` dict.

    ``seekable`` comes straight from ``MalbolgeDebugger.seekable_range`` and
    its lower bound is **not** 0: ``_max_history = 10000`` and ``_save_history``
    drops the oldest entry past that, so steps older than the window can no
    longer be reconstructed. §4.3's decision is window-style -- the timeline
    draws the full extent ``0..max_reached`` but only ``seekable`` is
    draggable, the rest rendered inert. This view reports the real bound rather
    than the design canvas's assumed 0.

    ``marks`` are *addresses*, not steps (§3.5's field is ``addr``): they are
    where breakpoints and watchpoints sit in memory, and it is up to the
    renderer to decide how -- or whether -- to project them onto a time axis.
    """
    low, high = dbg.seekable_range

    marks = [
        {"addr": bp.address, "kind": "breakpoint"}
        for bp in dbg.list_breakpoints()
    ] + [
        {"addr": wp.address, "kind": "watchpoint"}
        for wp in dbg.list_watchpoints()
    ]
    marks.sort(key=lambda m: (m["addr"], m["kind"]))

    return {
        "current": dbg.step_count,
        "max_reached": dbg.max_step_reached,
        "seekable": [low, high],
        "marks": marks,
    }
