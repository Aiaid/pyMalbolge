"""
MemoryView -- memory window / heat-map panel data.

Contract: ``docs/design/tui-web-architecture.md`` §3.3. Field names are
normative; see :mod:`malbolge.view` for the two rules this package must obey.
"""

from typing import Any, Dict, FrozenSet, List

from ..debugger import MalbolgeDebugger


def _char_or_dot(value: int) -> str:
    """Printable-ASCII-or-'.' rendering, matching debugger.py's own convention
    (see ``MalbolgeDebugger.get_memory_context`` / ``disassemble``)."""
    return chr(value) if 33 <= value <= 126 else "."


def _just_written(dbg: MalbolgeDebugger) -> FrozenSet[int]:
    """Addresses written by the step that produced the current state.

    ``step()`` appends a history entry at the start of the step and then fills
    in that entry's ``mem_changes`` with the writes the step actually made, so
    the last entry describes the most recent *completed* step. A step that only
    hit the termination check returns before appending anything and writes
    nothing, so the last entry keeps describing the last step that did run --
    which is the right answer, not a stale one.

    NOTE: no public accessor exposes this today; ``_history`` is private.
    Flagged for a follow-up public property on MalbolgeDebugger (something like
    ``last_step_writes``) -- ``registers.py`` has the same kind of note about
    ``_input``. The ``getattr`` fallback keeps this view working against a
    debugger that no longer carries the attribute rather than crashing a UI.
    """
    history = getattr(dbg, "_history", None)
    if not history:
        return frozenset()
    return frozenset(history[-1].mem_changes)


def build(dbg: MalbolgeDebugger, *, offset: int = 0,
          count: int = 24) -> Dict[str, Any]:
    """Build a :class:`MemoryView` dict for a ``count``-cell window near D.

    ``offset`` is the manual scroll offset *relative to D*, per §3.3. The
    window is CENTRED on ``d + offset`` -- the same rule the single-file TUI
    used (``start_addr = center - half_cells``) -- and then clamped into the
    address space. Centring belongs here rather than in each renderer: a
    window anchored at D would show only never-executed addresses ahead of the
    data pointer, hiding exactly the recently-written cells the heat map
    exists to show. Cells past the end of memory are simply not emitted, so
    ``count`` in the returned dict is the number of cells actually present
    (``len(cells)``) -- a renderer can rely on that invariant instead of
    re-deriving the truncation.

    ``heat_max`` is the maximum heat *within this window*, not globally: the
    heat map normalises against what is on screen, otherwise one very hot cell
    flattens every other cell to black.
    """
    state = dbg.get_state()
    d, c = state.d, state.c
    memory_size = dbg.config.memory_size

    count = max(0, count)
    center = d + offset
    start = max(0, min(center - count // 2, memory_size - count))
    end = min(start + count, memory_size)

    # Deliberately read_memory_value() per address rather than the bulk
    # read_memory(): the latter does `self._mem[start:end]` and SparseMemory
    # (i.e. every malbolge20 debugger) has no slice support, so it raises
    # TypeError. Reported upstream; a window is ~24 cells, so the per-cell
    # cost is irrelevant and this works on both memory backends.
    values: List[int] = [dbg.read_memory_value(a) for a in range(start, end)]
    heats: List[int] = dbg.get_write_heat(start, len(values))
    written = _just_written(dbg)

    cells = [
        {
            "addr": start + i,
            "value": value,
            "char": _char_or_dot(value),
            "heat": heats[i],
            "is_d": start + i == d,
            "is_c": start + i == c,
            "just_written": start + i in written,
        }
        for i, value in enumerate(values)
    ]

    return {
        "d": d,
        "c": c,
        "start": start,
        "count": len(cells),
        "offset": offset,
        "heat_max": max(heats) if heats else 0,
        "cells": cells,
    }
