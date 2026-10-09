"""Structured xDSL representation of the existing Nagoya LAL assembly.

This dialect describes assembly, not SSA values or Python semantics. Regions
retain declaration order; a routine instruction can occupy one or two cells,
and UNIT offsets are an ordered stream rather than a dictionary. No operation
contains an opaque source line. Comments and spelling are intentionally not
preserved, but supported legacy assembly keeps the same memory image.

``verify_lal`` checks the IR and its symbol scopes. It does not promise that
the legacy assembler implements every structurally valid construct: ALIGN,
bare cross-routine addresses, and BRANCH with subtraction are represented here
although its current address resolver cannot assemble them.

Bare address words and custom calls sharing a standard-unit name prefix are
rejected: the legacy parser dispatches on prefixes (for example JMP_BACK),
which can allocate extra cells or implicitly create an unrelated builtin unit.
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterable

from . import require_ir_support

require_ir_support()

from xdsl.context import Context
from xdsl.dialects.builtin import Builtin, IntAttr, ModuleOp, StringAttr
from xdsl.ir import Block, Dialect, Operation, ParametrizedAttribute, Region
from xdsl.irdl import (
    IRDLOperation,
    irdl_attr_definition,
    irdl_op_definition,
    opt_prop_def,
    prop_def,
    region_def,
    traits_def,
)
from xdsl.parser import Parser
from xdsl.printer import Printer
from xdsl.traits import NoTerminator
from xdsl.utils.exceptions import ParseError, VerifyException


class LalIRError(ValueError):
    """Invalid LAL syntax, IR structure, or symbolic address."""


_NAME = r"[A-Za-z]\w*"
_MAX_WORD = 3**20 - 1
_UNIT_INSTRUCTIONS = frozenset(
    ("DUP", "OPR", "ROT", "JMP", "MOV_D", "HALT", "OUTPUT", "INPUT", "NOOP")
)
# Ordered like mc2mb's automatically materialized standard units. DUP is a
# routine data word (zero), not a standard UNIT label.
_STANDARD_UNITS = {
    "END": 1, "OUTPUT": 25, "SKIP": 40, "INPUT": 47,
    "ROT": 59, "JMP": 64, "OPR": 86,
}
_INSTRUCTIONS = frozenset(
    ("DUP", "JMP", "BRANCH", "IF", "REV", "NEXT", "CALL", "ADDRESS")
)
_RESERVED_ROUTINE_NAMES = frozenset(
    ("DUP", "JMP", "IF", "REV", "NEXT", "BRANCH", "ALIGN")
)
_FLAG_ADDRESSES = {
    2: (64, 60), 4: (92, 9, 29), 5: (32, 74, 83),
    6: (3, 31, 17), 9: (84, 68, 72, 58, 61),
}


@irdl_attr_definition
class TargetAttr(ParametrizedAttribute):
    """A label, optional owning routine, and nonnegative address subtraction.

    The empty routine string denotes the current scope. In a routine address,
    subtraction is applied before the assembler's implicit minus-one bias.
    Unit references have neither a routine qualifier nor subtraction.
    """

    name = "lal.target"
    label: StringAttr
    routine: StringAttr
    subtract: IntAttr

    def __init__(self, label: str, routine: str = "", subtract: int = 0):
        super().__init__(StringAttr(label), StringAttr(routine), IntAttr(subtract))


@irdl_op_definition
class EntryOp(IRDLOperation):
    name = "lal.entry"
    target = prop_def(TargetAttr)

    def __init__(self, target: TargetAttr):
        super().__init__(properties={"target": target})


@irdl_op_definition
class FlagOp(IRDLOperation):
    name = "lal.flag"
    # Unit symbols and routine names inhabit separate namespaces. Avoid the
    # builtin.module SymbolTable's shared "sym_name" property for unit names.
    sym_name = prop_def(StringAttr, prop_name="unit_name")
    initial = prop_def(IntAttr)
    period = prop_def(IntAttr)

    def __init__(self, name: str, initial: int, period: int):
        super().__init__(properties={
            "unit_name": StringAttr(name), "initial": IntAttr(initial),
            "period": IntAttr(period),
        })


@irdl_op_definition
class JFlagOp(IRDLOperation):
    name = "lal.jflag"
    sym_name = prop_def(StringAttr, prop_name="unit_name")

    def __init__(self, name: str):
        super().__init__(properties={"unit_name": StringAttr(name)})


@irdl_op_definition
class UnitOp(IRDLOperation):
    name = "lal.unit"
    body = region_def("single_block")
    traits = traits_def(NoTerminator())

    def __init__(self, ops: Iterable[Operation]):
        super().__init__(regions=[Region(Block(ops))])


@irdl_op_definition
class UnitLabelOp(IRDLOperation):
    """Bind a unit symbol to the next UNIT cell, without allocating a cell."""

    name = "lal.unit_label"
    sym_name = prop_def(StringAttr)

    def __init__(self, name: str):
        super().__init__(properties={"sym_name": StringAttr(name)})


@irdl_op_definition
class UnitCellOp(IRDLOperation):
    """An explicitly spelled UNIT offset and an instruction or numeric word.

    Offsets are intentionally not sorted or reduced modulo 94. Repeated and
    decreasing offsets advance the legacy assembler's sequential page state.
    """

    name = "lal.unit_cell"
    offset = prop_def(IntAttr)
    value = prop_def(StringAttr | IntAttr)

    def __init__(self, offset: int, value: str | int):
        super().__init__(properties={
            "offset": IntAttr(offset),
            "value": StringAttr(value) if isinstance(value, str) else IntAttr(value),
        })


@irdl_op_definition
class RoutineOp(IRDLOperation):
    name = "lal.routine"
    sym_name = prop_def(StringAttr)
    body = region_def("single_block")
    traits = traits_def(NoTerminator())

    def __init__(self, name: str, ops: Iterable[Operation]):
        super().__init__(properties={"sym_name": StringAttr(name)},
                         regions=[Region(Block(ops))])


@irdl_op_definition
class LabelOp(IRDLOperation):
    """A routine-local label at the current sequential address."""

    name = "lal.label"
    sym_name = prop_def(StringAttr)

    def __init__(self, name: str):
        super().__init__(properties={"sym_name": StringAttr(name)})


@irdl_op_definition
class InstructionOp(IRDLOperation):
    """A LAL instruction with independently represented symbolic operands.

    CALL denotes a standard/custom unit invocation; continuation, when present,
    is the local label that follows its reserved gap. ADDRESS denotes a word
    containing a routine address. JMP occupies two cells, including its unit
    dispatch word; all other instructions occupy one. DUP encodes zero.
    """

    name = "lal.instruction"
    opcode = prop_def(StringAttr)
    target = opt_prop_def(TargetAttr)
    continuation = opt_prop_def(TargetAttr)

    def __init__(self, opcode: str, target: TargetAttr | None = None,
                 continuation: TargetAttr | None = None):
        super().__init__(properties={
            "opcode": StringAttr(opcode), "target": target,
            "continuation": continuation,
        })


@irdl_op_definition
class DataOp(IRDLOperation):
    """One 20-trit word; radix retains decimal versus 20-trit literal form."""

    name = "lal.data"
    value = prop_def(IntAttr)
    radix = prop_def(IntAttr)

    def __init__(self, value: int, radix: int = 10):
        super().__init__(properties={"value": IntAttr(value), "radix": IntAttr(radix)})


@irdl_op_definition
class AlignOp(IRDLOperation):
    """Legacy ALIGN: pad to an address modulo three, then reserve one cell.

    The legacy parser performs this address accounting, but its final resolver
    currently rejects the ALIGN cell. Keeping it explicit prevents pretending
    that dropping the directive or replacing it with a data word is equivalent.
    """

    name = "lal.align"
    remainder = prop_def(IntAttr)

    def __init__(self, remainder: int):
        super().__init__(properties={"remainder": IntAttr(remainder)})


Lal = Dialect("lal", [EntryOp, FlagOp, JFlagOp, UnitOp, UnitLabelOp,
                      UnitCellOp, RoutineOp, LabelOp, InstructionOp, DataOp,
                      AlignOp], [TargetAttr])


def create_lal_context() -> Context:
    """Create a strict xDSL context containing builtin and LAL dialects."""
    context = Context()
    context.load_dialect(Builtin)
    context.load_dialect(Lal)
    return context


def _name(value: str, what: str) -> None:
    if re.fullmatch(_NAME, value) is None:
        raise LalIRError(f"invalid {what} name {value!r}")


def _target(target: TargetAttr, *, unit: bool = False) -> None:
    _name(target.label.data, "target label")
    if target.routine.data:
        _name(target.routine.data, "target routine")
    if target.subtract.data < 0:
        raise LalIRError("target subtraction must be nonnegative")
    if unit and (target.routine.data or target.subtract.data):
        raise LalIRError("unit targets cannot have a routine or address subtraction")


def unit_cell_addresses(unit: UnitOp) -> list[tuple[UnitCellOp, int]]:
    """Compute UNIT addresses without discarding repeated declarations.

    After a non-increasing offset the reference parser resets its previous
    offset to -1. In particular, three identical offsets can overwrite one
    address. This deliberate compatibility detail must not be sorted away.
    """
    page, previous = 0, -1
    result = []
    for op in unit.body.block.ops:
        if isinstance(op, UnitCellOp):
            offset = op.offset.data
            if previous >= offset:
                page += 1
                previous = -1
            else:
                previous = offset
            result.append((op, page * 94 + offset))
    return result


def _routine_addresses(routine: RoutineOp) -> tuple[dict[str, int], dict[Operation, int]]:
    labels, addresses = {}, {}
    address = 0
    for op in routine.body.block.ops:
        if isinstance(op, LabelOp):
            name = op.sym_name.data
            _name(name, "label")
            if name in labels:
                raise LalIRError(f"duplicate label {name!r} in routine {routine.sym_name.data!r}")
            labels[name] = address
        else:
            if isinstance(op, AlignOp):
                remainder = op.remainder.data
                if remainder not in (0, 1, 2):
                    raise LalIRError("ALIGN remainder must be 0, 1, or 2")
                address += (remainder - address) % 3
            addresses[op] = address
            address += 2 if isinstance(op, InstructionOp) and op.opcode.data == "JMP" else 1
    return labels, addresses


def verify_lal(module: ModuleOp) -> None:
    """Verify operation structure, declaration order, words, and symbol scopes.

    This is deliberately stricter than the old regex parser: duplicate unit
    symbols, ignored lines, truncated declarations, and invalid flag states
    are errors. The original order of valid declarations is never changed.
    """
    if not isinstance(module, ModuleOp):
        raise LalIRError("LAL IR must be a builtin.module")
    try:
        module.verify()
    except VerifyException as exc:
        raise LalIRError(f"invalid LAL IR structure: {exc}") from exc
    if module.body.block.args:
        raise LalIRError("LAL module cannot have block arguments")
    ops = list(module.ops)
    if not ops or not isinstance(ops[0], EntryOp):
        raise LalIRError("LAL module must begin with exactly one entry declaration")
    routines: dict[str, RoutineOp] = {}
    unit_symbols: dict[str, int] = {}
    flag_counts = dict.fromkeys(_FLAG_ADDRESSES, 0)
    routine_seen = False

    def declare_unit(name: str, address: int) -> None:
        _name(name, "unit symbol")
        if name in unit_symbols:
            raise LalIRError(f"duplicate unit symbol {name!r}")
        unit_symbols[name] = address

    for op in ops[1:]:
        if isinstance(op, RoutineOp):
            routine_seen = True
            name = op.sym_name.data
            _name(name, "routine")
            if name in routines:
                raise LalIRError(f"duplicate routine {name!r}")
            routines[name] = op
            if op.body.block.args:
                raise LalIRError("LAL routine cannot have block arguments")
            for child in op.body.block.ops:
                if not isinstance(child, (LabelOp, InstructionOp, DataOp, AlignOp)):
                    raise LalIRError(f"operation {child.name!r} is not valid inside a routine")
        elif isinstance(op, (FlagOp, JFlagOp, UnitOp)):
            if routine_seen:
                raise LalIRError("FLAG, JFLAG, and UNIT declarations must precede routines")
            if isinstance(op, (FlagOp, JFlagOp)):
                if op.sym_name.data in _STANDARD_UNITS or op.sym_name.data == "DUP":
                    raise LalIRError("FLAG/JFLAG names cannot shadow standard instructions")
                if isinstance(op, FlagOp) and (
                    op.period.data not in (2, 4, 5, 6, 9)
                    or not 0 <= op.initial.data < op.period.data
                ):
                    raise LalIRError("FLAG requires period 2, 4, 5, 6, or 9 and 0 <= initial < period")
                period = op.period.data if isinstance(op, FlagOp) else 2
                choices = _FLAG_ADDRESSES[period] if isinstance(op, FlagOp) else (24, 28)
                declare_unit(op.sym_name.data, choices[flag_counts[period]])
                flag_counts[period] = (flag_counts[period] + 1) % len(choices)
            else:
                if op.body.block.args:
                    raise LalIRError("LAL unit cannot have block arguments")
                addresses = dict(unit_cell_addresses(op))
                pending: list[str] = []
                for child in op.body.block.ops:
                    if isinstance(child, UnitLabelOp):
                        pending.append(child.sym_name.data)
                    elif isinstance(child, UnitCellOp):
                        if child.offset.data < 0:
                            raise LalIRError("UNIT offset must be nonnegative")
                        if isinstance(child.value, StringAttr):
                            if child.value.data not in _UNIT_INSTRUCTIONS:
                                raise LalIRError(f"invalid UNIT instruction {child.value.data!r}")
                        elif not 0 <= child.value.data <= _MAX_WORD:
                            raise LalIRError("UNIT word must fit in 20 trits")
                        for name in pending:
                            declare_unit(name, addresses[child])
                        pending.clear()
                    else:
                        raise LalIRError(f"operation {child.name!r} is not valid inside a UNIT")
                if pending:
                    raise LalIRError(f"UNIT label {pending[0]!r} has no following cell")
                if not addresses:
                    raise LalIRError("UNIT must contain at least one cell")
        else:
            raise LalIRError(f"invalid top-level LAL operation {op.name!r}")
    if not routines:
        raise LalIRError("LAL module must contain a routine")
    # Standard units are materialized only if an actual routine invocation uses
    # them. REV/IF/NEXT alone do not request a builtin in the legacy grammar.
    for routine in routines.values():
        for op in routine.body.block.ops:
            if isinstance(op, InstructionOp):
                if op.opcode.data == "JMP":
                    unit_symbols.setdefault("JMP", _STANDARD_UNITS["JMP"])
                elif op.opcode.data == "CALL" and op.target is not None:
                    name = op.target.label.data
                    if name in _STANDARD_UNITS:
                        unit_symbols.setdefault(name, _STANDARD_UNITS[name])
    labels: dict[str, dict[str, int]] = {}
    addresses: dict[str, dict[Operation, int]] = {}
    for name, routine in routines.items():
        labels[name], addresses[name] = _routine_addresses(routine)

    def resolve(target: TargetAttr, current: str) -> int:
        _target(target)
        routine = target.routine.data or current
        if routine not in labels:
            raise LalIRError(f"undefined routine {routine!r}")
        if target.label.data not in labels[routine]:
            raise LalIRError(f"undefined label {target.label.data!r} in routine {routine!r}")
        return labels[routine][target.label.data] - target.subtract.data

    entry = ops[0]
    assert isinstance(entry, EntryOp)
    _target(entry.target)
    if not entry.target.routine.data or entry.target.subtract.data:
        raise LalIRError("entry must name label@routine without subtraction")
    resolve(entry.target, "")
    for name, routine in routines.items():
        for op in routine.body.block.ops:
            if isinstance(op, DataOp):
                if not 0 <= op.value.data <= _MAX_WORD:
                    raise LalIRError("data word must fit in 20 trits")
                if op.radix.data not in (3, 10):
                    raise LalIRError("data radix must be 3 or 10")
            elif isinstance(op, InstructionOp):
                opcode, target, continuation = op.opcode.data, op.target, op.continuation
                if opcode not in _INSTRUCTIONS:
                    raise LalIRError(f"unsupported LAL opcode {opcode!r}")
                if opcode == "DUP":
                    if target is not None:
                        raise LalIRError("DUP takes no target")
                elif opcode == "JMP":
                    if target is not None:
                        resolve(target, name)
                elif opcode in ("ADDRESS", "BRANCH"):
                    if target is None:
                        raise LalIRError(f"{opcode} requires a target")
                    if (opcode == "ADDRESS" and not target.routine.data
                        and (target.label.data in unit_symbols
                             or target.label.data in _STANDARD_UNITS
                             or target.label.data in _RESERVED_ROUTINE_NAMES)):
                        raise LalIRError(
                            f"ambiguous ADDRESS target {target.label.data!r}; "
                            "its MC spelling dispatches an instruction or unit"
                        )
                    if opcode == "ADDRESS" and any(
                        target.label.data.startswith(prefix) for prefix in _STANDARD_UNITS
                    ):
                        raise LalIRError(
                            f"unsupported legacy instruction-prefix ambiguity for ADDRESS "
                            f"target {target.label.data!r}; use a label without a standard-unit prefix"
                        )
                    resolve(target, name)
                else:
                    if target is None:
                        raise LalIRError(f"{opcode} requires a unit target")
                    _target(target, unit=True)
                    if target.label.data not in unit_symbols:
                        raise LalIRError(f"undefined unit symbol {target.label.data!r}")
                    if opcode == "CALL" and target.label.data in ("DUP", "JMP", "BRANCH"):
                        raise LalIRError(f"{target.label.data} requires its dedicated opcode")
                    if (opcode == "CALL" and target.label.data not in _STANDARD_UNITS
                        and any(target.label.data.startswith(prefix) for prefix in _STANDARD_UNITS)):
                        raise LalIRError(
                            f"unsupported legacy instruction-prefix ambiguity for CALL "
                            f"target {target.label.data!r}; rename the custom unit"
                        )
                    if (opcode == "CALL" and continuation is not None
                        and target.label.data in _RESERVED_ROUTINE_NAMES):
                        raise LalIRError(
                            f"ambiguous CALL to {target.label.data!r} with a continuation"
                        )
                if continuation is not None:
                    if opcode != "CALL":
                        raise LalIRError("only a unit CALL can have a continuation")
                    _target(continuation, unit=True)
                    following = resolve(continuation, name)
                    gap = following - addresses[name][op] - 1
                    if gap < 0:
                        raise LalIRError("unit continuation must follow the call")
                    assert target is not None
                    unit_address = unit_symbols[target.label.data]
                    if gap and gap >= unit_address:
                        raise LalIRError("unit continuation gap exceeds its available prefix")


def _parse_target(text: str, line: int) -> TargetAttr:
    match = re.fullmatch(rf"({_NAME})(?:@({_NAME}))?(?:\s*-\s*(\d+))?", text)
    if match is None:
        raise LalIRError(f"line {line}: invalid symbolic target {text!r}")
    return TargetAttr(match[1], match[2] or "", int(match[3] or 0))


def parse_mc(source: str) -> ModuleOp:
    """Parse complete, line-oriented MC into structured, verified LAL IR."""
    ops: list[Operation] = []
    body: list[Operation] | None = None
    scope = ""
    routine_name = ""
    unit_names: set[str] = set()
    routine_seen = False
    for number, original in enumerate(source.splitlines(), 1):
        line = re.split(r"#|//", original, maxsplit=1)[0].strip()
        if not line:
            continue
        if not ops:
            match = re.fullmatch(rf"PROGRAM_START_TO\s+({_NAME})@({_NAME})", line)
            if match is None:
                raise LalIRError(f"line {number}: expected PROGRAM_START_TO label@routine")
            ops.append(EntryOp(TargetAttr(match[1], match[2])))
            continue
        if body is None:
            match = re.fullmatch(rf"ROUTINE\s*(?:\(\s*({_NAME})\s*\)|\s+({_NAME}))\s*\{{", line)
            if match:
                scope, routine_name, body = "routine", match[1] or match[2], []
                routine_seen = True
                continue
            if routine_seen:
                raise LalIRError(f"line {number}: only ROUTINE declarations may follow a routine")
            match = re.fullmatch(rf"FLAG\s+(\d+)\s*/\s*(\d+)(?:\s*,\s*|\s+)({_NAME})", line)
            if match is None:
                match = re.fullmatch(rf"FLAG\s+\[\s*(\d+)\s*/\s*(\d+)\s*\]\s+({_NAME})", line)
            if match:
                ops.append(FlagOp(match[3], int(match[1]), int(match[2])))
                unit_names.add(match[3])
                continue
            match = re.fullmatch(rf"JFLAG(?:\s*,\s*|\s+)({_NAME})", line)
            if match:
                ops.append(JFlagOp(match[1]))
                unit_names.add(match[1])
                continue
            if re.fullmatch(r"UNIT\s*\{", line):
                scope, body = "unit", []
                continue
            raise LalIRError(f"line {number}: unsupported or malformed declaration {line!r}")
        if line == "}":
            ops.append(UnitOp(body) if scope == "unit" else RoutineOp(routine_name, body))
            body = None
            continue
        # Multiple label prefixes on the same source line are legal.
        while match := re.match(rf"^({_NAME})\s*:\s*(.*)$", line):
            label, line = match[1], match[2]
            body.append(UnitLabelOp(label) if scope == "unit" else LabelOp(label))
            if scope == "unit":
                unit_names.add(label)
            if not line:
                break
        if not line:
            continue
        if scope == "unit":
            match = re.fullmatch(r"(\d+)\s*:\s*([A-Z_]+|\d+)", line)
            if match is None:
                raise LalIRError(f"line {number}: expected UNIT offset: instruction-or-word")
            value = int(match[2]) if match[2].isdigit() else match[2]
            body.append(UnitCellOp(int(match[1]), value))
            continue
        if re.fullmatch(r"[012]{20}t", line):
            body.append(DataOp(int(line[:-1], 3), 3))
        elif re.fullmatch(r"\d+", line):
            body.append(DataOp(int(line)))
        elif match := re.fullmatch(r"ALIGN\s+([012])", line):
            body.append(AlignOp(int(match[1])))
        elif line == "DUP":
            body.append(InstructionOp("DUP"))
        elif line == "JMP":
            body.append(InstructionOp("JMP"))
        elif match := re.fullmatch(r"(IF|REV|NEXT|BRANCH|JMP)\s+(.+)", line):
            body.append(InstructionOp(match[1], _parse_target(match[2], number)))
        else:
            # Unit names win over local labels, as they do in mc2mb. The whole
            # declaration section is already known before the first routine.
            match = re.fullmatch(rf"({_NAME})(?:\s+({_NAME}))?", line)
            if match and (match[1] in unit_names or match[1] in _STANDARD_UNITS):
                body.append(InstructionOp(
                    "CALL", TargetAttr(match[1]), TargetAttr(match[2]) if match[2] else None,
                ))
            else:
                body.append(InstructionOp("ADDRESS", _parse_target(line, number)))
    if body is not None:
        raise LalIRError(f"unterminated {scope} declaration")
    module = ModuleOp(ops)
    verify_lal(module)
    return module


def _emit_target(target: TargetAttr) -> str:
    result = target.label.data
    if target.routine.data:
        result += "@" + target.routine.data
    if target.subtract.data:
        # The legacy bare-address resolver requires whitespace before '-'.
        result += " -" + str(target.subtract.data)
    return result


def _ternary(value: int) -> str:
    digits = []
    for _ in range(20):
        value, digit = divmod(value, 3)
        digits.append(str(digit))
    return "".join(reversed(digits)) + "t"


def emit_mc(module: ModuleOp) -> str:
    """Emit canonical MC without reordering declarations or address events."""
    verify_lal(module)
    lines = []
    for op in module.ops:
        if isinstance(op, EntryOp):
            lines.append("PROGRAM_START_TO " + _emit_target(op.target))
        elif isinstance(op, FlagOp):
            lines.append(f"FLAG {op.initial.data}/{op.period.data}, {op.sym_name.data}")
        elif isinstance(op, JFlagOp):
            lines.append("JFLAG " + op.sym_name.data)
        elif isinstance(op, UnitOp):
            lines.append("UNIT{")
            for child in op.body.block.ops:
                if isinstance(child, UnitLabelOp):
                    lines.append(child.sym_name.data + ":")
                elif isinstance(child, UnitCellOp):
                    lines.append(f"  {child.offset.data}: {child.value.data}")
            lines.append("}")
        elif isinstance(op, RoutineOp):
            lines.append("ROUTINE " + op.sym_name.data + "{")
            for child in op.body.block.ops:
                if isinstance(child, LabelOp):
                    lines.append(child.sym_name.data + ":")
                elif isinstance(child, DataOp):
                    value = _ternary(child.value.data) if child.radix.data == 3 else str(child.value.data)
                    lines.append("  " + value)
                elif isinstance(child, AlignOp):
                    lines.append("  ALIGN " + str(child.remainder.data))
                elif isinstance(child, InstructionOp):
                    opcode, target = child.opcode.data, child.target
                    if opcode in ("CALL", "ADDRESS"):
                        assert target is not None
                        line = _emit_target(target)
                    else:
                        line = opcode + (" " + _emit_target(target) if target is not None else "")
                    if child.continuation is not None:
                        line += " " + _emit_target(child.continuation)
                    lines.append("  " + line)
            lines.append("}")
    return "\n".join(lines) + "\n"


def print_lal(module: ModuleOp) -> str:
    """Use xDSL's normal printer, preserving ordered regions and properties."""
    verify_lal(module)
    stream = io.StringIO()
    Printer(stream=stream).print_op(module)
    return stream.getvalue() + "\n"


def parse_lal(source: str) -> ModuleOp:
    """Parse textual xDSL LAL with unregistered operations disabled."""
    try:
        module = Parser(create_lal_context(), source).parse_module()
    except (ParseError, VerifyException, ValueError) as exc:
        raise LalIRError(f"invalid textual LAL IR: {exc}") from exc
    verify_lal(module)
    return module


__all__ = [
    "Lal", "LalIRError", "TargetAttr", "EntryOp", "FlagOp", "JFlagOp",
    "UnitOp", "UnitLabelOp", "UnitCellOp", "RoutineOp", "LabelOp",
    "InstructionOp", "DataOp", "AlignOp", "create_lal_context", "parse_mc",
    "emit_mc", "verify_lal", "print_lal", "parse_lal", "unit_cell_addresses",
]
