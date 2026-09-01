"""
BreakpointView -- breakpoint/watchpoint list data.

Contract: ``docs/design/tui-web-architecture.md`` §3.6. Field names are
normative; see :mod:`malbolge.view` for the two rules this package must obey.
"""

from typing import Any, Dict

from ..debugger import MalbolgeDebugger, OPCODE_NAMES


def _mnemonic_at(dbg: MalbolgeDebugger, addr: int) -> str:
    """Same legal/illegal + opcode-name convention as
    ``MalbolgeDebugger.disassemble()``."""
    raw = dbg.read_memory_value(addr)
    if 33 <= raw <= 126:
        opcode = (raw + addr) % 94
        return OPCODE_NAMES.get(opcode, "???")
    return "DATA"


def build(dbg: MalbolgeDebugger) -> Dict[str, Any]:
    """Build a :class:`BreakpointView` dict.

    Per §3.6, ``Watchpoint`` has no ``hit_count`` today and none is
    synthesized here.

    ``has_condition`` and ``condition_text`` answer different questions and
    both are emitted. The predicate is a ``Callable`` and can never cross Rule
    2's boundary; its source text is whatever the caller passed to
    ``add_breakpoint(condition_text=...)``, and is ``None`` when the caller
    gave none -- which is a legitimate state for a conditional breakpoint, not
    an error. Nothing here tries to recover text from the callable itself
    (``inspect.getsource`` on a lambda returns the whole enclosing line, and
    returns nothing at all for a partial or a C-level callable).
    """
    breakpoints = [
        {
            "addr": bp.address,
            "mnemonic": _mnemonic_at(dbg, bp.address),
            "hit_count": bp.hit_count,
            "enabled": bp.enabled,
            "temporary": bp.temporary,
            "has_condition": bp.condition is not None,
            "condition_text": bp.condition_text,
        }
        for bp in sorted(dbg.list_breakpoints(), key=lambda bp: bp.address)
    ]

    watchpoints = [
        {
            "addr": wp.address,
            "enabled": wp.enabled,
            "last_value": wp.last_value,
        }
        for wp in sorted(dbg.list_watchpoints(), key=lambda wp: wp.address)
    ]

    return {
        "breakpoints": breakpoints,
        "watchpoints": watchpoints,
    }
