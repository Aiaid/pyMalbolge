"""
DisasmView -- disassembly window data.

Contract: ``docs/design/tui-web-architecture.md`` §3.2. Field names are
normative; see :mod:`malbolge.view` for the two rules this package must obey.
"""

from typing import Any, Dict, Optional

from ..debugger import MalbolgeDebugger, OPCODE_HELP


# Two opcodes' pseudocode isn't of the "x = y" assignment shape that the
# mechanical "=" -> "<-" rewrite below produces a sensible effect string for
# (out prints, in blocks on input, nop/end don't touch registers/memory at
# all) -- those four get a hand-written effect string instead.
_EFFECT_OVERRIDES = {
    5: "output ← a",     # out a
    23: "a ← input",     # in a
    68: "(no effect)",        # nop
    81: "(halt)",             # end
}


def _effect_for_opcode(opcode: Optional[int]) -> str:
    """Derive the one-line "effect" string for a legal opcode.

    NOTE ON SPEC WORDING: §3.2 says effect is "derived from
    OPCODE_HELP[opcode]['syntax']", but its own examples ("d <- mem[d]",
    "c <- mem[d]") are actually OPCODE_HELP[opcode]['pseudocode'] with '='
    rewritten to an arrow -- 'mov'/'jmp' pseudocode is exactly 'd = mem[d]'
    / 'c = mem[d]', while their 'syntax' strings are 'mov d, [d]' / 'jmp [d]'
    and don't match. This implementation follows the examples (pseudocode),
    not the prose (syntax); flagged for the spec to be reconciled.
    """
    if opcode is None:
        return ""
    if opcode in _EFFECT_OVERRIDES:
        return _EFFECT_OVERRIDES[opcode]
    help_ = OPCODE_HELP.get(opcode)
    if help_ is None:
        return "???"
    lines = help_["pseudocode"].split("\n")
    return "; ".join(line.replace(" = ", " ← ", 1) for line in lines)


def build(dbg: MalbolgeDebugger, *, count: int = 11) -> Dict[str, Any]:
    """Build a :class:`DisasmView` dict centred on the current C register.

    ``count`` mirrors ``MalbolgeDebugger.disassemble()``'s own parameter
    (and ``build_snapshot``'s planned ``disasm_count``).
    """
    center = dbg.get_state().c
    raw_rows = dbg.disassemble(count=count)

    rows = []
    for r in raw_rows:
        legal = r["opcode"] is not None
        rows.append({
            "addr": r["address"],
            "raw": r["raw"],
            "char": r["char"],
            "legal": legal,
            "opcode": r["opcode"],
            "mnemonic": r["mnemonic"],
            "effect": _effect_for_opcode(r["opcode"]) if legal else "",
            "is_current": r["is_current"],
            "has_breakpoint": r["has_breakpoint"],
        })

    if rows:
        window = [rows[0]["addr"], rows[-1]["addr"]]
    else:
        window = [center, center]

    return {
        "center": center,
        "window": window,
        "rows": rows,
    }
