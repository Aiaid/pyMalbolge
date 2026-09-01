"""
RegisterView -- register/status panel data.

Contract: ``docs/design/tui-web-architecture.md`` §3.1. Field names are
normative; see :mod:`malbolge.view` for the two rules this package must obey.
"""

from typing import Any, Dict

from ..debugger import MalbolgeDebugger


def _char_or_dot(value: int) -> str:
    """Printable-ASCII-or-'.' rendering, matching debugger.py's own convention
    (see ``MalbolgeDebugger.get_memory_context`` / ``disassemble``)."""
    return chr(value) if 33 <= value <= 126 else "."


def build(dbg: MalbolgeDebugger) -> Dict[str, Any]:
    """Build a :class:`RegisterView` dict from the debugger's current state.

    ``next_a`` / ``next_c`` / ``next_d`` come from
    ``preview_next_instruction()['register_changes']``, which omits a register
    entirely when the next step would not touch it (e.g. ``a`` on ``mov``) --
    those come back as ``None``.
    """
    state = dbg.get_state()
    preview = dbg.preview_next_instruction()
    reg_changes = preview.get("register_changes") or {}

    def _next(reg: str):
        pair = reg_changes.get(reg)
        return pair[1] if pair is not None else None

    # NOTE: get_state().stop_reason is only ever RUNNING or TERMINATED --
    # the richer StopReason values (STEP/BREAKPOINT/WATCHPOINT/...) are
    # transient values returned by step()/run() and are not stored on the
    # debugger. This view reports the current, not the most-recent-transition,
    # reason.
    return {
        "a": state.a,
        "a_char": _char_or_dot(state.a),
        "c": state.c,
        "d": state.d,
        "next_a": _next("a"),
        "next_c": _next("c"),
        "next_d": _next("d"),
        "step": state.step_count,
        "history_size": dbg.history_size,
        "output_len": len(state.output),
        "input_consumed": state.input_consumed,
        # No public accessor exposes total input length today (only
        # set_input() and the private self._input). Falling back to the
        # private attribute -- flagged for a follow-up public property
        # (e.g. `input_total`) on MalbolgeDebugger.
        "input_total": len(getattr(dbg, "_input", "")),
        "terminated": dbg.is_terminated,
        "stop_reason": state.stop_reason.value,
    }
