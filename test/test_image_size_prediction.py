"""Exact image-size selection never needs to generate the bootstrap."""

from dataclasses import replace
from pathlib import Path

import pytest

from malbolge.compiler import mc2mb
from malbolge.compiler.memory_image import MemoryImage
from malbolge.compiler.mg2mc import translate_mg_to_lal, translate_mg_to_mc


FIXTURES = Path(__file__).parent / "fixtures" / "nagoya"


@pytest.fixture
def small_image():
    return mc2mb.parse_mc_to_image((FIXTURES / "mg_a_minimal.mc").read_text())


@pytest.mark.parametrize("name", ("mg_a_minimal", "mg_d_repeat", "mg_e_call"))
@pytest.mark.parametrize("op_style", ("cluster", "inline"))
@pytest.mark.parametrize("jmp_style", ("main", "direct"))
def test_prediction_matches_actual_bytes_across_small_layouts(name, op_style, jmp_style):
    source = (FIXTURES / (name + ".mg")).read_text()
    options = dict(op_style=op_style, jmp_style=jmp_style)
    image = mc2mb.layout_lal_to_image(translate_mg_to_lal(source, **options))
    text_image = mc2mb.parse_mc_to_image(translate_mg_to_mc(source, **options))
    predicted = mc2mb.predict_image_mb_size(image)
    assert image == text_image
    assert predicted == mc2mb.predict_image_mb_size(text_image)
    assert predicted == sum(map(len, mc2mb.iter_image_to_mb(image)))


@pytest.mark.parametrize("name", (
    "mg_a_minimal", "mg_b_hi", "mg_c_echo", "mg_d_repeat", "mg_e_call",
))
def test_prediction_matches_retained_reference_file_sizes(name):
    image = mc2mb.parse_mc_to_image((FIXTURES / (name + ".mc")).read_text())
    assert mc2mb.predict_image_mb_size(image) == (FIXTURES / (name + ".mb")).stat().st_size


def test_prediction_never_constructs_assembler_or_emits_code(small_image, monkeypatch):
    expected = sum(map(len, mc2mb.iter_image_to_mb(small_image)))

    def forbidden(*args, **kwargs):
        pytest.fail("size prediction attempted bootstrap generation or emission")

    monkeypatch.setattr(mc2mb, "_Assembler", forbidden)
    monkeypatch.setattr(mc2mb, "iter_image_to_mb", forbidden)
    monkeypatch.setattr(mc2mb, "image_to_mb", forbidden)
    assert mc2mb.predict_image_mb_size(small_image) == expected


def test_prediction_keeps_holes_out_of_source_high_water(small_image):
    segments = list(small_image.segments)
    last = max(index for index, segment in enumerate(segments) if segment.kind == "direct")
    segment = segments[last]
    segments[last] = replace(segment, words=segment.words + (-1,) * 94)
    with_holes = replace(small_image, segments=tuple(segments))
    assert mc2mb.predict_image_mb_size(with_holes) == mc2mb.predict_image_mb_size(small_image)
    assert mc2mb.predict_image_mb_size(with_holes) == sum(map(len, mc2mb.iter_image_to_mb(with_holes)))


@pytest.mark.parametrize("kind", ("missing-direct", "missing-routine", "reordered", "index",
                                 "empty-direct", "fixed-setup", "grid", "reservation",
                                 "non-source-word", "illegal-source-word"))
def test_unsupported_raw_images_fail_before_bootstrap(small_image, monkeypatch, kind):
    segments = list(small_image.segments)
    direct = segments[0]
    if kind == "missing-direct":
        segments = [segment for segment in segments if segment.kind != "direct"]
    elif kind == "missing-routine":
        segments = [segment for segment in segments if segment.kind != "routine"]
    elif kind == "reordered":
        segments = segments[1:] + segments[:1]
    elif kind == "index":
        segments[0] = replace(direct, index=7)
    elif kind == "empty-direct":
        segments[0] = replace(direct, words=(-1,) * len(direct.words))
    elif kind == "fixed-setup":
        segments = [replace(segment, offset=0) if segment.kind == "direct" else segment
                    for segment in segments]
    elif kind == "grid":
        segments[0] = replace(direct, offset=direct.offset + 1)
    elif kind == "reservation":
        segments = [replace(segment, offset=segment.offset + 94)
                    if segment.kind == "direct" else segment for segment in segments]
    else:
        word = 0 if kind == "non-source-word" else next(
            word for word in range(33, 127)
            if chr(mc2mb._xlat1(word, direct.offset)) not in mc2mb._LEGAL)
        segments[0] = replace(direct, words=(word,) + direct.words[1:])

    def forbidden(*args, **kwargs):
        pytest.fail("invalid prediction input invoked the assembler")

    monkeypatch.setattr(mc2mb, "_Assembler", forbidden)
    with pytest.raises(mc2mb.Mc2MbError, match="size prediction requires a standard layout"):
        mc2mb.predict_image_mb_size(replace(small_image, segments=tuple(segments)))


@pytest.mark.parametrize("value", (None, "raw data", (), MemoryImage(0, ())))
def test_prediction_rejects_non_layout_values(value):
    with pytest.raises(mc2mb.Mc2MbError, match="size prediction requires"):
        mc2mb.predict_image_mb_size(value)
