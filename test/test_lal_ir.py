"""LAL structure and semantic compatibility, independent of optimizations."""

from pathlib import Path
import sys

import pytest

if sys.version_info < (3, 10):
    pytest.skip("optional LAL IR requires Python 3.10+", allow_module_level=True)
pytest.importorskip("xdsl")

from xdsl.dialects.builtin import ModuleOp, StringAttr
from malbolge.compiler.ir.lal import (
    DataOp, EntryOp, FlagOp, InstructionOp, LabelOp,
    LalIRError, RoutineOp, TargetAttr, UnitCellOp, UnitLabelOp, UnitOp,
    emit_mc, parse_lal, parse_mc, print_lal, unit_cell_addresses, verify_lal,
)
from malbolge.compiler.mc2mb import Mc2MbError, assemble_mc_to_mb, parse_mc_to_data
from malbolge.compiler.mg2mc import translate_mg_to_mc
from malbolge.malbolge20 import run


ROOT = Path(__file__).resolve().parents[1]
MC_CORPUS = sorted((ROOT / "test/fixtures/nagoya").glob("*.mc"))
MC_CORPUS += sorted((ROOT / "ref/nagoya-lowass/sample").glob("*.mc"))
MG_CORPUS = sorted((ROOT / "test/fixtures/nagoya").glob("*.mg"))
MG_CORPUS += sorted((ROOT / "test/fixtures/nagoya/mg2mc").glob("*.mg"))
MG_CORPUS += sorted((ROOT / "runtime/mg/official").glob("*.mg"))
MG_CORPUS += sorted((ROOT / "runtime/mg/tests").glob("t_*.mg"))
STYLES = [(op, jump) for op in ("cluster", "inline") for jump in ("main", "direct")]


def program(body="END", declarations="", routine="MAIN"):
    return (f"PROGRAM_START_TO ENTRY@{routine}\n{declarations}"
            f"ROUTINE {routine}{{\nENTRY:\n{body}\n}}\n")


def assert_roundtrip(source):
    module = parse_mc(source)
    printed = print_lal(module)
    restored = parse_lal(printed)
    assert print_lal(restored) == printed
    canonical = emit_mc(restored)
    assert emit_mc(parse_mc(canonical)) == canonical
    assert parse_mc_to_data(canonical) == parse_mc_to_data(source)
    return module


@pytest.mark.parametrize("path", MC_CORPUS, ids=lambda path: path.stem)
def test_existing_mc_corpus_memory_image(path):
    assert_roundtrip(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", MG_CORPUS, ids=lambda path: path.stem)
@pytest.mark.parametrize("op_style,jmp_style", STYLES)
def test_generated_mc_all_styles_memory_image(path, op_style, jmp_style):
    source = translate_mg_to_mc(path.read_text(encoding="utf-8"),
                                op_style=op_style, jmp_style=jmp_style)
    # Full text roundtrip is covered independently by the existing MC corpus;
    # this larger cross-product guards lowering/address parity economically.
    assert parse_mc_to_data(emit_mc(parse_mc(source))) == parse_mc_to_data(source)


def test_ir_contains_structured_ops_and_operands():
    source = program("IF READY\nBRANCH DONE\nROT VALUE\nVALUE:65\nDONE:END",
                     "FLAG [1/2] READY\n")
    module = assert_roundtrip(source)
    entry, flag, routine = list(module.ops)
    assert isinstance(entry, EntryOp)
    assert entry.target.routine.data == "MAIN"
    assert isinstance(flag, FlagOp)
    assert (flag.initial.data, flag.period.data) == (1, 2)
    assert isinstance(routine, RoutineOp)
    instructions = [op for op in routine.body.block.ops if isinstance(op, InstructionOp)]
    assert [op.opcode.data for op in instructions] == ["IF", "BRANCH", "CALL", "CALL"]
    assert instructions[2].target.label.data == "ROT"
    assert instructions[2].continuation.label.data == "VALUE"
    data = next(op for op in routine.body.block.ops if isinstance(op, DataOp))
    assert data.value.data == 65
    assert "PROGRAM_START_TO" not in print_lal(module)
    assert '"lal.instruction"' in print_lal(module)


@pytest.mark.parametrize("period", [2, 4, 5, 6, 9])
def test_flag_periods_and_shared_jflag_sequence(period):
    declarations = "".join(f"FLAG {i}/{period}, F{i}\n" for i in range(period))
    declarations += "JFLAG, J1\nJFLAG J2\n"
    body = "\n".join(f"NEXT F{i}\nIF F{i}\nBRANCH DONE" for i in range(period))
    body += "\nNEXT J1\nIF J2\nBRANCH DONE\nDONE:END"
    assert_roundtrip(program(body, declarations))


def test_repeated_unit_offsets_preserve_sequential_and_overwrite_semantics():
    declarations = """UNIT{
A: 5: DUP
B: 5: NOOP
C: 5: 72
4: NOOP
4: 73
6: JMP
1: NOOP
}
"""
    module = assert_roundtrip(program("IF A\nNEXT B\nREV C\nEND", declarations))
    unit = next(op for op in module.ops if isinstance(op, UnitOp))
    cells = unit_cell_addresses(unit)
    assert [op.offset.data for op, _ in cells] == [5, 5, 5, 4, 4, 6, 1]
    assert [address for _, address in cells] == [5, 99, 99, 192, 192, 194, 283]
    assert len(cells) == 7  # No dictionary silently deletes address events.


def test_unit_multiple_labels_and_standard_override():
    module = assert_roundtrip(program("END", "UNIT{\n0:DUP\nEND:ALIAS:1:HALT\n}\n"))
    unit = next(op for op in module.ops if isinstance(op, UnitOp))
    labels = [op.sym_name.data for op in unit.body.block.ops if isinstance(op, UnitLabelOp)]
    assert labels == ["END", "ALIAS"]


def test_local_subtraction_and_cross_routine_jump():
    source = program("JMP DONE -1\nDONE:0\nJMP ENTRY@OTHER\nEND")
    source += "ROUTINE (OTHER){\nENTRY:END\n}\n"
    module = assert_roundtrip(source)
    routine = next(op for op in module.ops if isinstance(op, RoutineOp))
    jumps = [op for op in routine.body.block.ops if isinstance(op, InstructionOp)
             and op.opcode.data == "JMP"]
    assert jumps[0].target.subtract.data == 1
    assert jumps[1].target.routine.data == "OTHER"


def test_bare_local_subtraction():
    assert_roundtrip(program("VALUE -1\nEND\nVALUE:0"))


@pytest.mark.parametrize("word", [0, 1, 65, 3486784400])
def test_decimal_and_ternary_data_words(word):
    value, digits = word, []
    for _ in range(20):
        value, digit = divmod(value, 3)
        digits.append(str(digit))
    ternary = "".join(reversed(digits)) + "t"
    module = assert_roundtrip(program(f"END\n{word}\n{ternary}"))
    values = [op for op in module.walk() if isinstance(op, DataOp)]
    assert [(op.value.data, op.radix.data) for op in values] == [(word, 10), (word, 3)]


@pytest.mark.parametrize("body", ["ALIGN 0\nEND", "BRANCH ENTRY -1\nEND", "ENTRY@MAIN\nEND"])
def test_structural_constructs_with_known_legacy_resolver_limit(body):
    module = parse_mc(program(body))
    verify_lal(parse_lal(print_lal(module)))
    emitted = emit_mc(module)
    assert body.splitlines()[0] in emitted
    # These constructs are represented, not silently rewritten to a different
    # memory layout or declared executable by the new IR layer.
    with pytest.raises((Mc2MbError, TypeError)):
        parse_mc_to_data(emitted)


@pytest.mark.parametrize("source,message", [
    ("", "begin"),
    ("PROGRAM_START_TO ENTRY@MAIN junk", "expected PROGRAM_START_TO"),
    (program().replace("END\n}", "END"), "unterminated"),
    (program(declarations="FLAG 2/2, F\n"), "FLAG requires"),
    (program(declarations="FLAG 0/3, F\n"), "FLAG requires"),
    (program(declarations="FLAG 0/2, F junk\n"), "malformed declaration"),
    (program(declarations="UNIT<94>{\n}\n"), "malformed declaration"),
    (program(declarations="UNIT{\n}\n"), "at least one cell"),
    (program(declarations="UNIT{\nL:\n}\n"), "no following cell"),
    (program(declarations="UNIT{\ngarbage\n}\n"), "expected UNIT offset"),
    (program(declarations="UNIT{\n0:FLY\n}\n"), "invalid UNIT instruction"),
    (program(declarations="UNIT{\n0:2 junk\n}\n"), "expected UNIT offset"),
    (program(declarations="FLAG 0/2, F\nJFLAG F\n"), "duplicate unit symbol"),
    (program(declarations="FLAG 0/2, END\n"), "shadow standard"),
    (program(declarations="UNIT{\nF:0:DUP\nF:1:JMP\n}\n"), "duplicate unit symbol"),
    (program("ENTRY:END"), "duplicate label"),
    (program() + "ROUTINE MAIN{\nENTRY:END\n}\n", "Redefinition of symbol"),
    (program() + "FLAG 0/2, F\n", "only ROUTINE"),
    (program("NO_SUCH_LABEL"), "undefined label"),
    (program("NEXT F\nEND"), "undefined unit symbol"),
    (program("REV ROT\nEND"), "undefined unit symbol"),
    (program("JMP ENTRY@OTHER"), "undefined routine"),
    (program("BRANCH MISSING"), "undefined label"),
    (program("IF ENTRY@MAIN\nEND"), "unit targets cannot"),
    (program("DUP junk"), "invalid symbolic target"),
    (program("ALIGN 3\nEND"), "invalid symbolic target"),
    (program("-1"), "invalid symbolic target"),
    (program("3486784401"), "fit in 20 trits"),
    (program("222t"), "invalid symbolic target"),
    (program("ROT ENTRY\nEND"), "continuation must follow"),
    (program("END VALUE\n0\nVALUE:0"), "gap exceeds"),
])
def test_strict_invalid_mc_diagnostics(source, message):
    with pytest.raises(LalIRError, match=message):
        parse_mc(source)


def test_modified_ir_is_verified_before_emit():
    module = parse_mc(program())
    entry = next(iter(module.ops))
    entry.properties["target"] = TargetAttr("MISSING", "MAIN")
    with pytest.raises(LalIRError, match="undefined label"):
        emit_mc(module)


@pytest.mark.parametrize("op", [DataOp(0), UnitCellOp(0, "DUP"), LabelOp("L"), EntryOp(TargetAttr("E", "M"))])
def test_wrong_scope_operations_rejected(op):
    module = ModuleOp([EntryOp(TargetAttr("ENTRY", "MAIN")), op,
                       RoutineOp("MAIN", [LabelOp("ENTRY"), InstructionOp("DUP")])])
    with pytest.raises(LalIRError, match="top-level"):
        verify_lal(module)


def test_malformed_xdsl_properties_and_unknown_dialect_rejected():
    text = print_lal(parse_mc(program()))
    with pytest.raises(LalIRError, match="structure"):
        parse_lal(text.replace('opcode = "CALL"', "opcode = #builtin.int<1>"))
    with pytest.raises(LalIRError, match="invalid textual LAL"):
        parse_lal(text.replace('"lal.instruction"', '"unknown.operation"'))


def test_programmatic_instruction_validation():
    module = parse_mc(program())
    end = next(op for op in module.walk() if isinstance(op, InstructionOp))
    end.properties["opcode"] = StringAttr("UNKNOWN")
    with pytest.raises(LalIRError, match="unsupported LAL opcode"):
        verify_lal(module)
    end.properties["opcode"] = StringAttr("CALL")
    end.properties["target"] = TargetAttr("END", subtract=-1)
    with pytest.raises(LalIRError, match="nonnegative"):
        verify_lal(module)


@pytest.mark.parametrize("label", ["END", "DUP", "JMP", "IF", "REV", "NEXT", "BRANCH", "ALIGN", "CUSTOM"])
@pytest.mark.parametrize("subtract", [0, 1])
def test_address_unit_and_instruction_aliases_cannot_silently_change_meaning(label, subtract):
    module = ModuleOp([
        EntryOp(TargetAttr("ENTRY", "MAIN")),
        UnitOp([UnitLabelOp("CUSTOM"), UnitCellOp(1, "HALT")]),
        RoutineOp("MAIN", [LabelOp("ENTRY"),
                            InstructionOp("ADDRESS", TargetAttr(label, subtract=subtract)),
                            LabelOp(label), DataOp(65),
                            InstructionOp("CALL", TargetAttr("END"))]),
    ])
    with pytest.raises(LalIRError, match="ambiguous ADDRESS"):
        emit_mc(module)
    # An explicit routine qualifier has stable IR spelling. Whether the old
    # address resolver implements this spelling remains a separate concern.
    address = next(op for op in module.walk() if isinstance(op, InstructionOp))
    address.properties["target"] = TargetAttr(label, "MAIN", subtract)
    if label in ("END", "JMP"):
        # A qualifier cannot defeat the legacy parser's prefix dispatch.
        with pytest.raises(LalIRError, match="instruction-prefix ambiguity"):
            emit_mc(module)
    else:
        assert print_lal(parse_mc(emit_mc(module))) == print_lal(module)


@pytest.mark.parametrize("label", ["IF", "REV", "NEXT", "BRANCH", "ALIGN"])
def test_unit_call_opcode_alias_with_continuation_is_rejected(label):
    module = ModuleOp([
        EntryOp(TargetAttr("ENTRY", "MAIN")),
        UnitOp([UnitLabelOp(label), UnitCellOp(1, "HALT")]),
        RoutineOp("MAIN", [LabelOp("ENTRY"),
                            InstructionOp("CALL", TargetAttr(label), TargetAttr("AFTER")),
                            LabelOp("AFTER"), DataOp(0)]),
    ])
    with pytest.raises(LalIRError, match="ambiguous CALL|dedicated opcode"):
        emit_mc(module)


def test_unit_and_routine_names_have_distinct_namespaces():
    assert_roundtrip(program("NEXT MAIN\nEND", "FLAG 0/2, MAIN\n"))


def test_unit_called_branch_requires_explicit_unit_access():
    declarations = "UNIT{\nBRANCH:1:HALT\n}\n"
    with pytest.raises(LalIRError, match="dedicated opcode"):
        parse_mc(program("BRANCH", declarations))
    assert_roundtrip(program("NEXT BRANCH\nEND", declarations))


@pytest.mark.parametrize("prefix", ["END", "OUTPUT", "SKIP", "INPUT", "ROT", "JMP", "OPR"])
def test_legacy_prefix_dispatch_is_not_misrepresented_as_an_address_word(prefix):
    label = prefix + "_BACK"
    raw = program(f"{label}\n{label}:0")
    safe = program("BACK\nBACK:0")
    # Prove the hazard against the actual backend: renaming a nominally local
    # symbol should not affect layout, but prefix dispatch inserts unit state
    # (and, for JMP, an extra routine cell).
    assert parse_mc_to_data(raw) != parse_mc_to_data(safe)
    with pytest.raises(LalIRError, match="instruction-prefix ambiguity"):
        parse_mc(raw)
    with pytest.raises(LalIRError, match="instruction-prefix ambiguity"):
        parse_mc(program(f"{label}@MAIN\n{label}:0"))
    if prefix == "JMP":
        assert parse_mc_to_data(raw) == parse_mc_to_data(program(f"JMP {label}\n{label}:0"))
    # Dispatch operands remain unambiguous and retain their declared widths.
    assert_roundtrip(program(f"BRANCH {label}\nJMP {label}\n{label}:END"))


@pytest.mark.parametrize("prefix", ["END", "OUTPUT", "SKIP", "INPUT", "ROT", "JMP", "OPR"])
def test_custom_unit_names_cannot_accidentally_dispatch_standard_units(prefix):
    label = prefix + "_CUSTOM"
    raw = program(label, f"UNIT{{\n{label}:1:HALT\n}}\n")
    safe = program("CUSTOM", "UNIT{\nCUSTOM:1:HALT\n}\n")
    assert parse_mc_to_data(raw) != parse_mc_to_data(safe)
    with pytest.raises(LalIRError, match="instruction-prefix ambiguity"):
        parse_mc(raw)
    assert_roundtrip(safe)


def test_exact_standard_unit_calls_and_jmp_keep_legacy_accounting():
    assert_roundtrip(program("OUTPUT\nSKIP\nINPUT\nROT\nOPR\nJMP DONE\nDUP\nDONE:END"))


def test_tiny_vm_input_output_parity():
    source = program("INPUT\nDUP\nREV INPUT\nOUTPUT\nDUP\nREV OUTPUT\nEND")
    restored = emit_mc(parse_lal(print_lal(parse_mc(source))))
    legacy_mb, ir_mb = assemble_mc_to_mb(source), assemble_mc_to_mb(restored)
    assert ir_mb == legacy_mb
    legacy = run(legacy_mb, b"Q", max_steps=2_000_000, max_output=8)
    converted = run(ir_mb, b"Q", max_steps=2_000_000, max_output=8)
    assert converted.stop_reason == legacy.stop_reason == "terminated"
    assert converted.output == legacy.output == b"Q"
    assert converted.steps == legacy.steps
