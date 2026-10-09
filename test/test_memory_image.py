"""Memory-image handoff preserves layout, bootstrap and streaming semantics."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from malbolge.compiler import mc2mb
from malbolge.compiler.lal_model import (
    Align, DataWord, FlagDecl, JFlagDecl, Label, LalInstruction,
    LalModelError, LalProgram, RoutineDecl, Target, UnitCell, UnitDecl,
    UnitLabel, emit_lal_to_mc,
)
from malbolge.compiler.memory_image import (
    MAX_WORD, MemoryImage, MemoryImageError, MemorySegment,
    image_to_data, parse_data_to_image,
)
from malbolge.compiler.mg2mc import translate_mg_to_lal, translate_mg_to_mc


FIXTURES = Path(__file__).parent / "fixtures" / "nagoya"
MC_PATHS = sorted(FIXTURES.glob("*.mc"))
MG_PATHS = sorted(FIXTURES.glob("*.mg"))


def program(body, declarations=()):
    return LalProgram(Target("ENTRY", "MAIN"), declarations + (
        RoutineDecl("MAIN", (Label("ENTRY"),) + body),))


def call(name, continuation=None):
    return LalInstruction("CALL", Target(name),
                          Target(continuation) if continuation is not None else None)


@pytest.mark.parametrize("path", MC_PATHS, ids=lambda path: path.stem)
def test_fixture_data_and_bootstrap_parity(path):
    source = path.read_text()
    data = mc2mb.parse_mc_to_data(source)
    image = mc2mb.parse_mc_to_image(source)
    assert image_to_data(image) == data
    assert parse_data_to_image(data) == image
    assert mc2mb.image_to_mb(image) == mc2mb.data_to_mb(data)


@pytest.mark.parametrize("path", MG_PATHS, ids=lambda path: path.stem)
@pytest.mark.parametrize("op_style", ("cluster", "inline"))
@pytest.mark.parametrize("jmp_style", ("main", "direct"))
def test_all_mg_styles_keep_native_layout(path, op_style, jmp_style):
    source = path.read_text()
    options = dict(op_style=op_style, jmp_style=jmp_style)
    model = translate_mg_to_lal(source, **options)
    expected = mc2mb.parse_mc_to_data(translate_mg_to_mc(source, **options))
    assert image_to_data(mc2mb.layout_lal_to_image(model)) == expected


def test_native_custom_units_labels_gap_base_and_address_biases():
    model = program((
        call("DJMP", "AFTER"), DataWord(23), Label("AFTER"),
        LalInstruction("NEXT", Target("F")),
        LalInstruction("IF", Target("J")),
        LalInstruction("REV", Target("DJMP")),
        LalInstruction("JMP", Target("VALUE", subtract=1)),
        LalInstruction("ADDRESS", Target("VALUE", subtract=1)),
        LalInstruction("BRANCH", Target("TAIL", "OTHER")),
        call("END"), Label("BASE"), DataWord(0),
        Label("VALUE"), DataWord(3486784400, radix=3),
    ), (
        FlagDecl("F", 1, 2), JFlagDecl("J"),
        UnitDecl((UnitCell(59, "DUP"), UnitLabel("DJMP"),
                  UnitCell(60, "MOV_D"), UnitCell(61, "JMP"))),
    ))
    model = LalProgram(model.entry, model.declarations + (
        RoutineDecl("OTHER", (Label("TAIL"), call("END"))),))
    image = mc2mb.layout_lal_to_image(model)
    assert image_to_data(image) == mc2mb.parse_mc_to_data(emit_lal_to_mc(model))
    main = next(segment for segment in image.segments if segment.kind == "routine")
    assert main.words[6] == main.words[7]  # JMP operand and ADDRESS use the same -1 bias.
    assert main.words[-2] & 1  # BASE is odd after max routine/indirect extent + 3.


def test_unit_offsets_remain_ordered_including_overwrites():
    model = program((call("CUSTOM"), call("END")), (
        UnitDecl((UnitLabel("CUSTOM"), UnitCell(3, "MOV_D"),
                  UnitCell(3, 71), UnitCell(3, 72),
                  UnitCell(2, "NOOP"), UnitCell(5, "JMP"))),))
    image = mc2mb.layout_lal_to_image(model)
    assert image_to_data(image) == mc2mb.parse_mc_to_data(emit_lal_to_mc(model))
    indirect = next(segment for segment in image.segments if segment.kind == "indirect")
    assert indirect.words[97] == 72
    assert indirect.words[96] == -1


@pytest.mark.parametrize("period", (2, 4, 5, 6, 9))
def test_flags_keep_cycle_and_initial_state(period):
    declarations = tuple(FlagDecl("F%d" % index, index % period, period)
                         for index in range(12))
    model = program((LalInstruction("NEXT", Target("F11")), call("END")), declarations)
    assert image_to_data(mc2mb.layout_lal_to_image(model)) == \
        mc2mb.parse_mc_to_data(emit_lal_to_mc(model))


def test_native_path_does_not_visit_text_boundaries(monkeypatch):
    model = translate_mg_to_lal((FIXTURES / "mg_a_minimal.mg").read_text())
    expected = mc2mb.assemble_mc_to_mb(emit_lal_to_mc(model))

    def forbidden(*args, **kwargs):
        pytest.fail("native image path visited a text boundary")

    monkeypatch.setattr(mc2mb, "parse_mc_to_data", forbidden)
    monkeypatch.setattr(mc2mb, "parse_mc_to_image", forbidden)
    monkeypatch.setattr(mc2mb._Assembler, "memory_init_code1", forbidden)
    assert mc2mb.assemble_lal_to_mb(model) == expected
    for size in (1, 7, 376, 4096, 65536):
        chunks = list(mc2mb.iter_lal_to_mb(model, size))
        assert b"".join(chunks) == expected.encode("ascii")
        assert all(isinstance(chunk, bytes) and 0 < len(chunk) <= size for chunk in chunks)


@pytest.mark.parametrize("size", (0, -1, True, 1.5, None))
def test_bad_chunk_size_fails_before_layout_or_bootstrap(size, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid chunk size reached compilation")

    monkeypatch.setattr(mc2mb, "layout_lal_to_image", forbidden)
    monkeypatch.setattr(mc2mb._Assembler, "setup_data_module", forbidden)
    with pytest.raises(ValueError, match="positive integer"):
        list(mc2mb.iter_lal_to_mb(None, size))
    with pytest.raises(ValueError, match="positive integer"):
        list(mc2mb.iter_image_to_mb(None, size))


@pytest.mark.parametrize("record, message", (
    (Align(1), "ALIGN"),
    (LalInstruction("ADDRESS", Target("ENTRY", "MAIN")), "cross-routine ADDRESS"),
    (LalInstruction("BRANCH", Target("ENTRY", subtract=1)), "BRANCH subtraction"),
    (LalInstruction("JMP", Target("ENTRY", "MAIN", 1)), "cross-routine JMP subtraction"),
))
def test_structurally_valid_unsupported_records_fail_explicitly(record, message):
    with pytest.raises(mc2mb.Mc2MbError, match=message):
        mc2mb.layout_lal_to_image(program((record, call("END"))))


def test_invalid_model_is_not_silently_dropped():
    with pytest.raises(LalModelError, match="invalid flag"):
        mc2mb.layout_lal_to_image(program((call("END"),), (FlagDecl("F", 2, 2),)))


def test_native_path_preserves_bootstrap_overlap_error():
    model = program((call("END"),))
    with pytest.raises(mc2mb.Mc2MbError, match="Direct unit has been destroyed"):
        mc2mb.assemble_mc_to_mb(emit_lal_to_mc(model))
    with pytest.raises(mc2mb.Mc2MbError, match="Direct unit has been destroyed"):
        mc2mb.assemble_lal_to_mb(model)


def test_image_records_are_immutable_and_validate_words():
    image = MemoryImage(0, (MemorySegment("routine", 0, MAX_WORD, (-1,)),))
    with pytest.raises(FrozenInstanceError):
        image.entry = 2
    with pytest.raises(FrozenInstanceError):
        image.segments[0].offset = 2
    for words in ((MAX_WORD + 1,), (-2,), (True,), [0]):
        with pytest.raises(MemoryImageError):
            MemorySegment("routine", 0, 0, words)
    with pytest.raises(MemoryImageError, match="extends past"):
        MemorySegment("routine", 0, MAX_WORD, (1, 2))
    with pytest.raises(MemoryImageError, match="kind"):
        MemorySegment("unknown", 0, 0, ())
    with pytest.raises(MemoryImageError):
        MemoryImage(-1, ())
    assert parse_data_to_image(image_to_data(image)) == image


@pytest.mark.parametrize("source", (
    "", "END\n", "ENTRY_ADDRESS:0\n", "ENTRY_ADDRESS:0\nEND\nextra\n",
    "ENTRY_ADDRESS:0\nUNKNOWN:0\noffset:0\nlen:0\nEND\n",
    "ENTRY_ADDRESS:0\nROUTINE_CODE:0\noffset:0\nlen:2\n1\nEND\n",
))
def test_data_codec_rejects_truncated_and_unknown_records(source):
    with pytest.raises(MemoryImageError):
        parse_data_to_image(source)


def test_layout_diagnostic_anchor_still_exports_the_same_addresses():
    from test.diagnostics.layout_tool import layout_map
    source = emit_lal_to_mc(program((call("END"),)))
    image = mc2mb.parse_mc_to_image(source)
    layout = layout_map(source)
    assert layout["rt"]["MAIN"][0] == image.entry
