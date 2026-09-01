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


# Unicode "Control Pictures" (U+2400..U+241F) name C0 control characters
# visibly: U+2400 SYMBOL FOR NULL, U+2407 SYMBOL FOR BELL, and so on. DEL is
# the odd one out at U+2421 (U+2420 is the symbol for space, which is not a
# control character and so is never reached here).
_CONTROL_PICTURES_BASE = 0x2400
_SYMBOL_FOR_DELETE = "␡"


def _classify_a(value: int):
    """Classify the A register's low byte and give it a displayable symbol.

    Returns ``(kind, symbol)``.

    A is a full ternary word, not a byte -- ``a`` routinely runs into the tens
    of thousands -- so the classification is of ``a % 256``, which is the byte
    ``out a`` would actually emit (``malbolge.py``: ``chr(int(a % 256))``).
    The printable bound is 32..126 inclusive, matching what the TUI's register
    panel and ``debug_cli`` already show for A; note this is *not* the 33..126
    bound ``a_char`` uses, which is the memory-cell convention (a space is not
    a legal instruction character but is a perfectly ordinary output byte).

    ``kind`` is "printable", "control" (a C0 control or DEL) or "other"
    (0x80..0xFF, which is not a character at all until an encoding is chosen,
    so no symbol is invented for it).
    """
    byte = value % 256
    if 32 <= byte <= 126:
        return "printable", chr(byte)
    if byte < 32:
        return "control", chr(_CONTROL_PICTURES_BASE + byte)
    if byte == 127:
        return "control", _SYMBOL_FOR_DELETE
    return "other", None


#: How much of the program's output a snapshot carries, in characters.
#:
#: The output panel wants the actual text, but a snapshot is rebuilt on every
#: step and crosses postMessage, so it cannot carry all of it: 99bottles.mal
#: emits 11,459 characters and quine.mal emits its own 59,851-byte source. The
#: *tail* is what a running program's output panel is scrolled to anyway.
#:
#: Truncating here rather than in each renderer is deliberate — otherwise the
#: TUI and the web build pick different limits and disagree about what "the
#: output" is.
OUTPUT_TAIL_CHARS = 4096


def build(dbg: MalbolgeDebugger, *,
          output_tail_chars: int = OUTPUT_TAIL_CHARS) -> Dict[str, Any]:
    """Build a :class:`RegisterView` dict from the debugger's current state.

    ``next_a`` / ``next_c`` / ``next_d`` come from
    ``preview_next_instruction()['register_changes']``, which omits a register
    entirely when the next step would not touch it (e.g. ``a`` on ``mov``) --
    those come back as ``None``.
    """
    state = dbg.get_state()
    a_kind, a_symbol = _classify_a(state.a)
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
        # a_char keeps its original meaning exactly -- the TUI and existing
        # tests depend on it. a_char_kind / a_char_symbol are the strictly
        # additional information: which *sort* of byte A holds, and a glyph
        # that is displayable even when the byte is not (a control character
        # gets its Control Pictures symbol, so A=7 reads "␇" rather than ".").
        "a_char": _char_or_dot(state.a),
        "a_char_kind": a_kind,
        "a_char_symbol": a_symbol,
        "c": state.c,
        "d": state.d,
        "next_a": _next("a"),
        "next_c": _next("c"),
        "next_d": _next("d"),
        "step": state.step_count,
        "history_size": dbg.history_size,
        "output_len": len(state.output),
        # The text itself, tail-truncated: output_len stays the true total, so
        # a renderer can always say "showing the last N of M".
        "output_tail": state.output[-output_tail_chars:] if output_tail_chars else "",
        "output_truncated": len(state.output) > output_tail_chars,
        "input_consumed": state.input_consumed,
        # No public accessor exposes total input length today (only
        # set_input() and the private self._input). Falling back to the
        # private attribute -- flagged for a follow-up public property
        # (e.g. `input_total`) on MalbolgeDebugger.
        "input_total": len(getattr(dbg, "_input", "")),
        "terminated": dbg.is_terminated,
        "stop_reason": state.stop_reason.value,
    }
