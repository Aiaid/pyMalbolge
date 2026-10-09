"""Native MG lowering parity and dependency-free LAL record contracts."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from malbolge.compiler import mg2mc
from malbolge.compiler.lal_model import (
    Align, DataWord, FlagDecl, Label, LalInstruction, LalModelError, LalProgram,
    RoutineDecl, Target, UnitCell, UnitDecl, UnitLabel, emit_lal_to_mc,
    validate_lal,
)


ROOT = Path(__file__).resolve().parents[1]
CORPUS = sorted(
    list((ROOT / "test/fixtures/nagoya").glob("mg_*.mg"))
    + list((ROOT / "test/fixtures/nagoya/mg2mc").glob("*.mg"))
    + list((ROOT / "runtime/mg/official").glob("*.mg"))
    + list((ROOT / "runtime/mg/tests").glob("t_*.mg"))
)
STYLES = [(op, jmp) for op in ("cluster", "inline")
          for jmp in ("main", "direct")]


@pytest.mark.parametrize("path", CORPUS, ids=lambda path: path.stem)
@pytest.mark.parametrize("op,jmp", STYLES)
def test_corpus_structural_parity(path, op, jmp):
    # Independent existing MC-to-xDSL parser provides the symbolic oracle.
    # Base-model tests below do not need the optional IR extra.
    pytest.importorskip("xdsl")
    from malbolge.compiler.ir.lal import emit_mc, parse_mc

    source = path.read_text(encoding="utf-8")
    model = mg2mc.translate_mg_to_lal(source, op_style=op, jmp_style=jmp)
    validate_lal(model)
    original = mg2mc.translate_mg_to_mc(source, op_style=op, jmp_style=jmp)
    assert emit_mc(parse_mc(emit_lal_to_mc(model))) == emit_mc(parse_mc(original))


def test_native_sink_bypasses_legacy_text(monkeypatch):
    source = (ROOT / "test/fixtures/nagoya/mg2mc/case_indopr.mg").read_text()

    def forbidden(*args, **kwargs):
        raise AssertionError("native lowering entered a legacy text path")

    monkeypatch.setattr(mg2mc, "Generator", forbidden)
    monkeypatch.setattr(mg2mc.Program, "generate", forbidden)
    monkeypatch.setattr(mg2mc, "translate_mg_to_mc", forbidden)
    # Protocol templates must already be records, not dynamically parsed.
    monkeypatch.setattr(mg2mc, "_fixed_lal_template", forbidden)
    model = mg2mc.translate_mg_to_lal(source)
    validate_lal(model)
    assert any(isinstance(decl, UnitDecl) for decl in model.declarations)
    assert any(isinstance(decl, FlagDecl) and decl.period == 9
               for decl in model.declarations)


def test_forward_cross_routine_and_return_addresses_are_typed():
    source = (ROOT / "test/fixtures/nagoya/mg2mc/case_cross_routine.mg").read_text()
    model = mg2mc.translate_mg_to_lal(source)
    validate_lal(model)
    routines = {decl.name: decl for decl in model.declarations
                if isinstance(decl, RoutineDecl)}
    assert any(isinstance(record, LalInstruction) and record.target is not None
               and record.target.routine == "SUB"
               for record in routines["MAIN"].body)
    assert any(isinstance(record, LalInstruction) and record.opcode == "ADDRESS"
               for record in routines["MAIN"].body)
    with pytest.raises(FrozenInstanceError):
        model.entry = Target("OTHER", "MAIN")


def test_fixed_indirect_protocol_has_address_words():
    source = (ROOT / "test/fixtures/nagoya/mg2mc/case_indopr.mg").read_text()
    model = mg2mc.translate_mg_to_lal(source)
    main = next(decl for decl in model.declarations
                if isinstance(decl, RoutineDecl) and decl.name == "MAIN")
    assert LalInstruction("ADDRESS", Target("MID_L3")) in main.body
    assert LalInstruction("CALL", Target("UNIT2_3")) in main.body
    assert not any(isinstance(record, str) for record in main.body)


def test_ordered_unit_offsets_and_multiple_labels_are_preserved():
    body = (UnitLabel("A"), UnitLabel("Alias"), UnitCell(90, "DUP"),
            UnitLabel("B"), UnitCell(2, "MOV_D"), UnitCell(2, "JMP"),
            UnitCell(2, "NOOP"))
    model = LalProgram(Target("ENTRY", "MAIN"), (
        UnitDecl(body),
        RoutineDecl("MAIN", (Label("ENTRY"), LalInstruction("CALL", Target("A")),
                             LalInstruction("CALL", Target("END")))),
    ))
    validate_lal(model)
    text = emit_lal_to_mc(model)
    assert model.declarations[0].body == body
    assert text.index("90: DUP") < text.index("2: MOV_D") < text.index("2: JMP")
    assert text.count("2:") == 3


def test_subtraction_and_ternary_spelling_follow_legacy_grammar():
    model = LalProgram(Target("ENTRY", "MAIN"), (
        RoutineDecl("MAIN", (Label("ENTRY"), DataWord(7, 3),
                             LalInstruction("JMP", Target("ENTRY", subtract=1)),
                             LalInstruction("CALL", Target("END")))),
    ))
    text = emit_lal_to_mc(model)
    assert "JMP ENTRY -1" in text
    assert "00000000000000000021t" in text


@pytest.mark.parametrize("body", [
    (Label("ENTRY"), LalInstruction("IF", Target("UNKNOWN"))),
    (Label("ENTRY"), LalInstruction("BRANCH", Target("UNKNOWN"))),
    (Label("ENTRY"), LalInstruction("DUP", Target("ENTRY"))),
    (Label("ENTRY"), LalInstruction("DUP", continuation=Target("ENTRY"))),
    (Label("ENTRY"), DataWord(3 ** 20)),
    (Label("ENTRY"), DataWord(True)),
    (Label("ENTRY"), DataWord(0, True)),
    (Label("ENTRY"), Align(3)),
    (Label("ENTRY"), Align(True)),
    (Label("ENTRY"), Label("ENTRY")),
    (Label("ENTRY"), LalInstruction("CALL", "END")),
    (Label("ENTRY"), LalInstruction("JMP", Target("ENTRY", subtract=True))),
    (Label("ENTRY"), Label("OPR_LABEL"),
     LalInstruction("ADDRESS", Target("OPR_LABEL"))),
])
def test_invalid_models_are_rejected(body):
    with pytest.raises(LalModelError):
        validate_lal(LalProgram(Target("ENTRY", "MAIN"), (RoutineDecl("MAIN", body),)))


@pytest.mark.parametrize("declaration", [
    FlagDecl("F", True, 2), FlagDecl("F", 0, True),
    UnitDecl((UnitCell(True, "DUP"),)),
    UnitDecl((UnitCell(0, True),)),
    UnitDecl((UnitLabel("OPR_CUSTOM"), UnitCell(5, "DUP"))),
])
def test_malformed_and_ambiguous_unit_records_are_rejected(declaration):
    body = (Label("ENTRY"), LalInstruction("CALL", Target("END")))
    if isinstance(declaration, UnitDecl) and isinstance(declaration.body[0], UnitLabel):
        body += (LalInstruction("CALL", Target("OPR_CUSTOM")),)
    with pytest.raises(LalModelError):
        validate_lal(LalProgram(Target("ENTRY", "MAIN"),
                                (declaration, RoutineDecl("MAIN", body))))


@pytest.mark.parametrize("path", sorted((ROOT / "test/fixtures/nagoya/mg2mc/errors").glob("*.mg")),
                         ids=lambda path: path.stem)
def test_native_mg_errors_keep_legacy_message_and_location(path):
    source = path.read_text(encoding="utf-8")
    with pytest.raises(mg2mc.Mg2McError) as legacy:
        mg2mc.translate_mg_to_mc(source)
    with pytest.raises(mg2mc.Mg2McError) as native:
        mg2mc.translate_mg_to_lal(source)
    assert str(native.value) == str(legacy.value)
    assert native.value.line == legacy.value.line


def test_native_unknown_style_keeps_legacy_error():
    with pytest.raises(ValueError):
        mg2mc.translate_mg_to_lal("DEF MAIN\nEND\n", op_style="unknown")
