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
    """
    breakpoints = [
        {
            "addr": bp.address,
            "mnemonic": _mnemonic_at(dbg, bp.address),
            "hit_count": bp.hit_count,
            "enabled": bp.enabled,
            "temporary": bp.temporary,
            "has_condition": bp.condition is not None,
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
