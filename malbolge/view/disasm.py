"""
DisasmView -- disassembly window data.

Contract: ``docs/design/tui-web-architecture.md`` §3.2. Field names are
normative; see :mod:`malbolge.view` for the two rules this package must obey.

Departure from §3.2 as written: ``effect`` is a semantic key from
:data:`EFFECT_KEYS`, not the display string ("d ← mem[d]") the spec's example
shows. See the comment on :data:`EFFECT_KEYS` for why; the spec text needs
reconciling.
"""

from typing import Any, Dict, Optional

from ..debugger import MalbolgeDebugger, OPCODE_NAMES


#: Every value ``effect`` can take. A renderer maps these to its own wording
#: (the TUI and the web build are not written in the same language, and the
#: web build's is not English), so this set -- not the wording -- is the
#: contract. ``OPCODE_HELP[opcode]['pseudocode']`` still holds the English
#: "d = mem[d]" form for a renderer that wants an operational gloss.
EFFECT_KEYS = frozenset({
    # the eight executable opcodes, keyed by their OPCODE_NAMES mnemonic
    "jmp", "out", "in", "rotr", "mov", "crz", "nop", "end",
    # a printable cell whose (raw + addr) % 94 is none of those eight: the
    # machine skips it and carries on, so a renderer says "treated as nop"
    "unknown_opcode",
    # a cell outside 33..126: execution does not skip it, it *stops* there,
    # which is a different sentence entirely
    "illegal",
})

#: `effect` was previously a display string ("d <- mem[d]"). It is now a key,
#: because that string was English -- baking one natural language into the
#: layer that both renderers share makes the other renderer either wrong or
#: forced to reverse-engineer text back into meaning.
#:
#: The three non-executing cases stay distinguishable through this field
#: alone. `legal` plus `mnemonic == "???"` can already tell them apart, but
#: only if every renderer independently knows that rule; naming them here
#: means a renderer's lookup table is total over EFFECT_KEYS and needs no
#: second field to disambiguate.


def _effect_key(opcode: Optional[int]) -> str:
    """The semantic key for one disassembly row.

    `opcode` is None exactly when the cell is not a legal instruction
    character (33..126) -- ``MalbolgeDebugger.disassemble`` sets it that way.
    """
    if opcode is None:
        return "illegal"
    return OPCODE_NAMES.get(opcode, "unknown_opcode")


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
            "effect": _effect_key(r["opcode"]),
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
