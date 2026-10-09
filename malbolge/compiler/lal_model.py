"""Dependency-free, ordered records for Nagoya Low-Level Assembly.

This is the shared handoff between the MG lowering and memory-image assembler.
It preserves semantic operands and declaration order, not comments or whitespace.
In particular, UNIT offsets are a stream: repeated/decreasing offsets matter.
The optional xDSL representation adapts these records without owning the base
compiler's runtime dependencies.
"""

from dataclasses import dataclass
import re
from typing import Optional, Tuple, Union


@dataclass(frozen=True)
class Target:
    label: str
    routine: str = ""
    subtract: int = 0


@dataclass(frozen=True)
class FlagDecl:
    name: str
    initial: int
    period: int


@dataclass(frozen=True)
class JFlagDecl:
    name: str


@dataclass(frozen=True)
class UnitLabel:
    name: str


@dataclass(frozen=True)
class UnitCell:
    offset: int
    value: Union[int, str]


@dataclass(frozen=True)
class UnitDecl:
    body: Tuple[Union[UnitLabel, UnitCell], ...]


@dataclass(frozen=True)
class Label:
    name: str


@dataclass(frozen=True)
class DataWord:
    value: int
    radix: int = 10


@dataclass(frozen=True)
class LalInstruction:
    """CALL invokes a unit; its optional continuation ends a reserved gap.

    JMP occupies two cells; all other instructions occupy one. ADDRESS is an
    explicit address word. REV/IF/NEXT target unit symbols, BRANCH/JMP/ADDRESS
    target routine labels. DUP encodes zero.
    """

    opcode: str
    target: Optional[Target] = None
    continuation: Optional[Target] = None


@dataclass(frozen=True)
class Align:
    remainder: int = 0


@dataclass(frozen=True)
class RoutineDecl:
    name: str
    body: Tuple[Union[Label, DataWord, LalInstruction, Align], ...]


@dataclass(frozen=True)
class LalProgram:
    entry: Target
    declarations: Tuple[Union[FlagDecl, JFlagDecl, UnitDecl, RoutineDecl], ...]


class LalModelError(ValueError):
    """Invalid structured LAL records or symbolic operands."""


_NAME = re.compile(r"[A-Za-z]\w*\Z")
_MAX_WORD = 3 ** 20 - 1
_UNIT_OPS = frozenset(("DUP", "OPR", "ROT", "JMP", "MOV_D", "HALT",
                       "OUTPUT", "INPUT", "NOOP"))
_STANDARD_UNITS = {"END": 1, "OUTPUT": 25, "SKIP": 40, "INPUT": 47,
                   "ROT": 59, "JMP": 64, "OPR": 86}
_FLAG_ADDRESSES = {2: (64, 60), 4: (92, 9, 29), 5: (32, 74, 83),
                   6: (3, 31, 17), 9: (84, 68, 72, 58, 61)}
_OPCODES = frozenset(("DUP", "JMP", "BRANCH", "IF", "REV", "NEXT",
                      "CALL", "ADDRESS"))
_RESERVED_ROUTINE_NAMES = frozenset(("DUP", "JMP", "IF", "REV", "NEXT",
                                     "BRANCH", "ALIGN"))


def _name(value):
    if not isinstance(value, str) or _NAME.fullmatch(value) is None:
        raise LalModelError("invalid symbol name %r" % (value,))


def _target(value, unit=False):
    if not isinstance(value, Target):
        raise LalModelError("expected a Target record")
    _name(value.label)
    if value.routine:
        _name(value.routine)
    if type(value.subtract) is not int or value.subtract < 0:
        raise LalModelError("target subtraction must be nonnegative")
    if unit and (value.routine or value.subtract):
        raise LalModelError("unit targets must be unqualified without subtraction")


def validate_lal(program: LalProgram) -> None:
    """Check record structure, symbol scopes, words and continuation gaps.

    It also rejects legacy instruction-prefix spelling ambiguities, so the
    canonical text exporter cannot silently change an operand's role.
    """
    if not isinstance(program, LalProgram):
        raise LalModelError("expected a LalProgram record")
    _target(program.entry)
    if not program.entry.routine or program.entry.subtract:
        raise LalModelError("entry must name label@routine without subtraction")
    if not isinstance(program.declarations, tuple):
        raise LalModelError("declarations must be an immutable tuple")
    units, routines, labels, addresses = {}, {}, {}, {}
    counts = dict.fromkeys(_FLAG_ADDRESSES, 0)
    routine_seen = False

    def declare(name, address):
        _name(name)
        if name in units:
            raise LalModelError("duplicate unit symbol %r" % name)
        units[name] = address

    for decl in program.declarations:
        if isinstance(decl, RoutineDecl):
            routine_seen = True
            _name(decl.name)
            if decl.name in routines:
                raise LalModelError("duplicate routine %r" % decl.name)
            if not isinstance(decl.body, tuple):
                raise LalModelError("routine body must be an immutable tuple")
            routines[decl.name] = decl
            local, locations, address = {}, {}, 0
            for index, record in enumerate(decl.body):
                if isinstance(record, Label):
                    _name(record.name)
                    if record.name in local:
                        raise LalModelError("duplicate label %r in %r" %
                                            (record.name, decl.name))
                    local[record.name] = address
                    continue
                if isinstance(record, Align):
                    if type(record.remainder) is not int or record.remainder not in (0, 1, 2):
                        raise LalModelError("ALIGN remainder must be 0, 1, or 2")
                    address += (record.remainder - address) % 3
                elif isinstance(record, DataWord):
                    if (type(record.value) is not int or
                            not 0 <= record.value <= _MAX_WORD or
                            type(record.radix) is not int or record.radix not in (3, 10)):
                        raise LalModelError("invalid 20-trit data word or radix")
                elif isinstance(record, LalInstruction):
                    if not isinstance(record.opcode, str) or record.opcode not in _OPCODES:
                        raise LalModelError("unsupported opcode %r" % record.opcode)
                    if record.target is not None:
                        _target(record.target)
                    if record.continuation is not None:
                        _target(record.continuation)
                    if record.opcode == "JMP":
                        units.setdefault("JMP", _STANDARD_UNITS["JMP"])
                    if record.opcode == "CALL" and record.target is not None:
                        name = record.target.label
                        if name in _STANDARD_UNITS:
                            units.setdefault(name, _STANDARD_UNITS[name])
                else:
                    raise LalModelError("invalid routine record %r" % (record,))
                locations[index] = address
                address += 2 if (isinstance(record, LalInstruction) and
                                 record.opcode == "JMP") else 1
            labels[decl.name], addresses[decl.name] = local, locations
        elif isinstance(decl, (FlagDecl, JFlagDecl, UnitDecl)):
            if routine_seen:
                raise LalModelError("unit declarations must precede routines")
            if isinstance(decl, (FlagDecl, JFlagDecl)):
                if decl.name in _STANDARD_UNITS or decl.name == "DUP":
                    raise LalModelError("flag names cannot shadow standard units")
                period = decl.period if isinstance(decl, FlagDecl) else 2
                if (type(period) is not int or period not in _FLAG_ADDRESSES or
                        (isinstance(decl, FlagDecl) and
                         (type(decl.initial) is not int or
                          not 0 <= decl.initial < period))):
                    raise LalModelError("invalid flag period or initial state")
                choices = _FLAG_ADDRESSES[period] if isinstance(decl, FlagDecl) else (24, 28)
                declare(decl.name, choices[counts[period] % len(choices)])
                counts[period] = (counts[period] + 1) % len(choices)
            else:
                if not isinstance(decl.body, tuple):
                    raise LalModelError("unit body must be an immutable tuple")
                pending, page, previous, found = [], 0, -1, False
                for record in decl.body:
                    if isinstance(record, UnitLabel):
                        pending.append(record.name)
                    elif isinstance(record, UnitCell):
                        if type(record.offset) is not int or record.offset < 0:
                            raise LalModelError("UNIT offset must be nonnegative")
                        if isinstance(record.value, str):
                            if record.value not in _UNIT_OPS:
                                raise LalModelError("invalid UNIT instruction")
                        elif (type(record.value) is not int or
                              not 0 <= record.value <= _MAX_WORD):
                            raise LalModelError("UNIT word must fit in 20 trits")
                        # Preserve the reference's offset reset after a page
                        # transition; three equal offsets can share an address.
                        if previous >= record.offset:
                            page += 1
                            previous = -1
                        else:
                            previous = record.offset
                        address = page * 94 + record.offset
                        for name in pending:
                            declare(name, address)
                        pending.clear()
                        found = True
                    else:
                        raise LalModelError("invalid UNIT record")
                if pending or not found:
                    raise LalModelError("UNIT labels require a following cell")
        else:
            raise LalModelError("invalid declaration %r" % (decl,))

    def resolve(target, scope):
        _target(target)
        routine = target.routine or scope
        if routine not in labels or target.label not in labels[routine]:
            raise LalModelError("undefined routine target %r" % (target,))
        return labels[routine][target.label] - target.subtract

    resolve(program.entry, "")
    for name, decl in routines.items():
        for index, record in enumerate(decl.body):
            if not isinstance(record, LalInstruction):
                continue
            opcode, target, continuation = record.opcode, record.target, record.continuation
            if opcode == "DUP":
                if target is not None:
                    raise LalModelError("DUP takes no target")
            elif opcode == "JMP":
                if target is not None:
                    resolve(target, name)
            elif opcode in ("BRANCH", "ADDRESS"):
                if target is None:
                    raise LalModelError("%s requires a target" % opcode)
                if opcode == "ADDRESS":
                    if not target.routine and (target.label in units or
                            target.label in _STANDARD_UNITS or
                            target.label in _RESERVED_ROUTINE_NAMES):
                        raise LalModelError("ambiguous ADDRESS target %r" % target.label)
                    if any(target.label.startswith(prefix) for prefix in _STANDARD_UNITS):
                        raise LalModelError("legacy instruction-prefix ambiguity for ADDRESS %r"
                                            % target.label)
                resolve(target, name)
            else:
                _target(target, unit=True)
                if target.label not in units:
                    raise LalModelError("undefined unit %r" % target.label)
                if opcode == "CALL" and target.label in ("DUP", "JMP", "BRANCH"):
                    raise LalModelError("unit requires its dedicated opcode")
                if (opcode == "CALL" and target.label not in _STANDARD_UNITS and
                        any(target.label.startswith(prefix) for prefix in _STANDARD_UNITS)):
                    raise LalModelError("legacy instruction-prefix ambiguity for CALL %r"
                                        % target.label)
                if (opcode == "CALL" and continuation is not None and
                        target.label in _RESERVED_ROUTINE_NAMES):
                    raise LalModelError("ambiguous CALL continuation for %r" % target.label)
            if continuation is not None:
                if opcode != "CALL":
                    raise LalModelError("only CALL can have a continuation")
                _target(continuation, unit=True)
                gap = resolve(continuation, name) - addresses[name][index] - 1
                if gap < 0 or (gap and gap >= units[target.label]):
                    raise LalModelError("invalid unit continuation gap")


def _spell_target(target):
    return (target.label + ("@" + target.routine if target.routine else "") +
            (" -" + str(target.subtract) if target.subtract else ""))


def _word(word):
    if word.radix == 10:
        return str(word.value)
    value, digits = word.value, []
    while value:
        value, digit = divmod(value, 3)
        digits.append(str(digit))
    return "".join(reversed(digits)).zfill(20) + "t"


def emit_lal_to_mc(program: LalProgram) -> str:
    """Emit canonical diagnostic MC text (legacy whitespace is not retained)."""
    validate_lal(program)
    lines = ["PROGRAM_START_TO " + _spell_target(program.entry)]
    for decl in program.declarations:
        if isinstance(decl, FlagDecl):
            lines.append("FLAG %d/%d, %s" % (decl.initial, decl.period, decl.name))
        elif isinstance(decl, JFlagDecl):
            lines.append("JFLAG " + decl.name)
        elif isinstance(decl, UnitDecl):
            lines.append("UNIT{")
            for record in decl.body:
                lines.append(record.name + ":" if isinstance(record, UnitLabel)
                             else "%d: %s" % (record.offset, record.value))
            lines.append("}")
        elif isinstance(decl, RoutineDecl):
            lines.append("ROUTINE " + decl.name + "{")
            for record in decl.body:
                if isinstance(record, Label):
                    lines.append(record.name + ":")
                elif isinstance(record, DataWord):
                    lines.append("  " + _word(record))
                elif isinstance(record, Align):
                    lines.append("  ALIGN " + str(record.remainder))
                else:
                    if record.opcode == "CALL":
                        text = _spell_target(record.target)
                    elif record.opcode == "ADDRESS":
                        text = _spell_target(record.target)
                    else:
                        text = record.opcode
                        if record.target is not None:
                            text += " " + _spell_target(record.target)
                    if record.continuation is not None:
                        text += " " + _spell_target(record.continuation)
                    lines.append("  " + text)
            lines.append("}")
    return "\n".join(lines) + "\n"


verify_lal_program = validate_lal


__all__ = ["Target", "FlagDecl", "JFlagDecl", "UnitLabel", "UnitCell",
           "UnitDecl", "Label", "DataWord", "LalInstruction", "Align",
           "RoutineDecl", "LalProgram", "LalModelError", "validate_lal",
           "verify_lal_program", "emit_lal_to_mc"]
