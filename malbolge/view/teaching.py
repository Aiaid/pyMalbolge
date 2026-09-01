"""
TeachingView -- "what will happen next" panel data (canvas 1b + engineering
mode teaching panel).

Contract: ``docs/design/tui-web-architecture.md`` §3.4. Field names are
normative; see :mod:`malbolge.view` for the two rules this package must obey.
"""

from typing import Any, Dict, List, Optional

from ..debugger import MalbolgeDebugger


def _char_or_dot(value: int) -> str:
    return chr(value) if 33 <= value <= 126 else "."


def _build_effects(preview: Dict[str, Any], terminated: bool) -> List[Dict[str, Any]]:
    """The ordered, numbered "N things happen" list.

    Ordering (this ViewModel's choice, not either renderer's): any I/O first
    (it is what the instruction is "about"), then the accumulator change and
    the memory write it came from together (they are one operation for
    crz/rotr), then the pointer increments, then the self-modifying-code
    encrypt, then a termination note last.
    """
    if terminated:
        return []

    calc = preview.get("calculation_details")
    reg_changes = preview.get("register_changes") or {}
    mem_changes = preview.get("memory_changes") or {}

    steps = []  # (kind, text, detail)

    if isinstance(calc, dict):
        calc_type = calc.get("type")
        if calc_type == "output":
            steps.append(("io", f"output {calc['char']!r}", f"ascii={calc['ascii']}"))
        elif calc_type == "input":
            steps.append(("io", f"read {calc['char']!r} into a", f"ascii={calc['ascii']}"))
        elif calc_type == "input_exhausted":
            steps.append(("note", "input exhausted", "program will terminate"))

    if "a" in reg_changes:
        old, new = reg_changes["a"]
        steps.append(("register", f"a ← {new}", f"was {old}"))

    for addr, (old, new) in mem_changes.items():
        steps.append(("memory", f"mem[{addr}] ← {new}", f"was {old}"))

    for reg in ("d", "c"):
        if reg in reg_changes:
            old, new = reg_changes[reg]
            steps.append(("register", f"{reg} ← {new}", f"was {old}"))

    if preview.get("will_encrypt"):
        addr = preview.get("encrypt_address")
        steps.append((
            "encrypt",
            f"mem[{addr}] re-encrypted",
            f"→ {preview.get('encrypted_value')}",
        ))

    if preview.get("will_terminate"):
        steps.append(("note", "program terminates", None))

    return [
        {"order": i + 1, "kind": kind, "text": text, "detail": detail}
        for i, (kind, text, detail) in enumerate(steps)
    ]


def _build_encrypt(dbg: MalbolgeDebugger, preview: Dict[str, Any],
                    terminated: bool) -> Optional[Dict[str, Any]]:
    if terminated or not preview.get("will_encrypt"):
        return None
    addr = preview.get("encrypt_address")
    if addr is None:
        return None
    old = dbg.read_memory_value(addr)
    new = preview.get("encrypted_value")
    return {
        "addr": addr,
        "index": old - 33,
        "old": old,
        "old_char": _char_or_dot(old),
        "new": new,
        "new_char": _char_or_dot(new) if new is not None else ".",
    }


def _build_ternary(dbg: MalbolgeDebugger, preview: Dict[str, Any],
                    terminated: bool) -> Optional[Dict[str, Any]]:
    if terminated:
        return None
    calc = preview.get("calculation_details")
    if not isinstance(calc, dict):
        return None

    if "a_ternary" in calc:  # explain_crazy_operation()
        # NOTE: there is no natural "digit that moves" for crazy (each digit
        # is looked up independently, in place) the way there is for rotate,
        # so no highlight is derivable from the operation itself. Using -1
        # as an explicit "not applicable" sentinel rather than inventing an
        # animation cue; flagged as an open spec question.
        return {
            "kind": "crazy",
            "a": calc["a_ternary"],
            "b": calc["b_ternary"],
            "result": calc["result_ternary"],
            "highlight_before": -1,
            "highlight_after": -1,
        }

    if "original_ternary" in calc:  # explain_rotate_operation()
        trit_width = dbg.config.trit_width
        return {
            "kind": "rotate",
            "a": calc["original_ternary"],
            "b": None,
            "result": calc["rotated_ternary"],
            # "LSB wraps to MSB" (OPCODE_HELP[39]['note']): the digit at
            # position 0 ends up at the top position.
            "highlight_before": 0,
            "highlight_after": trit_width - 1,
        }

    return None


def build(dbg: MalbolgeDebugger) -> Dict[str, Any]:
    """Build a :class:`TeachingView` dict for the *next* instruction.

    When the program has already terminated, ``effects``/``encrypt``/
    ``ternary`` are empty/``None`` and ``opcode_calc`` falls back to zeroed
    placeholders -- there is no "next instruction" to describe.
    """
    terminated = dbg.is_terminated
    preview = dbg.preview_next_instruction()

    opcode = preview.get("opcode", -1)
    opcode_name = preview.get("opcode_name", "N/A")
    will_terminate = preview.get("will_terminate", terminated)

    help_ = dbg.get_opcode_help(opcode) if opcode is not None and opcode >= 0 else None
    syntax = help_["syntax"] if help_ else ""
    description = help_["description"] if help_ else ""

    calc = preview.get("opcode_calculation") or {}
    mem_c = calc.get("mem_c", 0)
    opcode_calc = {
        "mem_c": mem_c,
        "mem_c_char": calc.get("mem_c_char", _char_or_dot(mem_c)),
        "c": calc.get("c", dbg.get_state().c),
        "opcode": calc.get("opcode", opcode if opcode is not None and opcode >= 0 else None),
    }

    return {
        "terminated": terminated,
        "will_terminate": will_terminate,
        "opcode": opcode,
        "opcode_name": opcode_name,
        "syntax": syntax,
        "description": description,
        "opcode_calc": opcode_calc,
        "effects": _build_effects(preview, terminated),
        "encrypt": _build_encrypt(dbg, preview, terminated),
        "ternary": _build_ternary(dbg, preview, terminated),
    }
