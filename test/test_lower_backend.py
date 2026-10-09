"""Independent acceptance of the typed MG -> LAL -> image -> MB handoff."""
import hashlib
from pathlib import Path

import pytest

from malbolge import malbolge20
from malbolge.compiler import lal_model, mc2mb, mg2mc, memory_image

FIX = Path(__file__).parent / 'fixtures/nagoya'
STYLES = [(op, jmp) for op in ('cluster', 'inline') for jmp in ('main', 'direct')]
DEFINED = [('mg_b_hi', b'', b'Hi'), ('mg_c_echo', b'Q', b'Q'),
           ('mg_d_repeat', b'', b'AAAA'), ('mg_e_call', b'', b'X')]


def source(name):
    return (FIX / (name + '.mg')).read_text()


def fail_text(*args, **kwargs):
    raise AssertionError('native handoff crossed a textual compiler boundary')


@pytest.mark.parametrize('op,jmp', STYLES)
@pytest.mark.parametrize('name', ['mg_b_hi', 'mg_c_echo', 'mg_d_repeat', 'mg_e_call',
                                  'mg2mc/case_indopr', 'mg2mc/case_nested',
                                  'mg2mc/case_cross_routine', 'mg2mc/case_switch_full'])
def test_native_layout_matches_textual_protocol(op, jmp, name):
    mg = source(name)
    mc = mg2mc.translate_mg_to_mc(mg, op_style=op, jmp_style=jmp)
    expected_data = mc2mb.parse_mc_to_data(mc)
    image = mc2mb.layout_lal_to_image(mg2mc.translate_mg_to_lal(
        mg, op_style=op, jmp_style=jmp))
    assert isinstance(image, memory_image.MemoryImage)
    assert memory_image.image_to_data(image) == expected_data
    assert memory_image.parse_data_to_image(expected_data) == image
    assert all(isinstance(segment.words, tuple) for segment in image.segments)


@pytest.mark.parametrize('op,jmp', STYLES)
@pytest.mark.parametrize('name,inp,expected_output', DEFINED)
def test_native_bytes_and_vm_match_without_textual_boundary(monkeypatch, op, jmp,
                                                            name, inp, expected_output):
    mg = source(name)
    mc = mg2mc.translate_mg_to_mc(mg, op_style=op, jmp_style=jmp)
    expected_mb = mc2mb.assemble_mc_to_mb(mc).encode('ascii')
    expected_run = malbolge20.run(expected_mb, inp, max_steps=2000000, max_output=64)
    assert expected_run.stop_reason == 'terminated'
    assert expected_run.output == expected_output
    monkeypatch.setattr(mg2mc, 'translate_mg_to_mc', fail_text)
    monkeypatch.setattr(lal_model, 'emit_lal_to_mc', fail_text)
    monkeypatch.setattr(mc2mb, 'parse_mc_to_data', fail_text)
    monkeypatch.setattr(mc2mb, 'parse_mc_to_image', fail_text)
    monkeypatch.setattr(memory_image, 'parse_data_to_image', fail_text)
    monkeypatch.setattr(memory_image, 'image_to_data', fail_text)
    monkeypatch.setattr(mc2mb._Assembler, 'memory_init_code1', fail_text)
    # Patch imported aliases too: a future refactor must preserve this boundary.
    for module in (mg2mc, mc2mb):
        for name in ('emit_lal_to_mc', 'parse_data_to_image', 'image_to_data'):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, fail_text)
    lal = mg2mc.translate_mg_to_lal(mg, op_style=op, jmp_style=jmp)
    image = mc2mb.layout_lal_to_image(lal)
    chunks = list(mc2mb.iter_image_to_mb(image, 997))
    assert all(isinstance(chunk, bytes) and 0 < len(chunk) <= 997 for chunk in chunks)
    actual_mb = b''.join(chunks)
    assert actual_mb == expected_mb
    assert mc2mb.image_to_mb(image).encode('ascii') == actual_mb
    assert mc2mb.assemble_lal_to_mb(lal).encode('ascii') == actual_mb
    assert b''.join(mc2mb.iter_lal_to_mb(lal, 4096)) == actual_mb
    actual_run = malbolge20.run(actual_mb, inp, max_steps=2000000, max_output=64)
    assert actual_run.to_dict() == expected_run.to_dict()


@pytest.mark.parametrize('op,jmp', STYLES)
def test_indirect_operation_bootstrap_hash_matches(op, jmp):
    mg = source('mg2mc/case_indopr')
    expected = mc2mb.assemble_mc_to_mb(mg2mc.translate_mg_to_mc(
        mg, op_style=op, jmp_style=jmp)).encode('ascii')
    model = mg2mc.translate_mg_to_lal(mg, op_style=op, jmp_style=jmp)
    actual = b''.join(mc2mb.iter_lal_to_mb(model, 4093))
    assert len(actual) == len(expected)
    assert hashlib.sha256(actual).digest() == hashlib.sha256(expected).digest()


def test_invalid_native_models_fail_before_bootstrap(monkeypatch):
    monkeypatch.setattr(mc2mb._Assembler, 'setup_data_module', fail_text)
    bad = lal_model.LalProgram(lal_model.Target('MISSING', 'MAIN'), ())
    with pytest.raises(lal_model.LalModelError):
        mc2mb.layout_lal_to_image(bad)
    with pytest.raises(lal_model.LalModelError):
        mc2mb.assemble_lal_to_mb(bad)
    with pytest.raises(mc2mb.Mc2MbError):
        mc2mb.image_to_mb('not an image')


@pytest.mark.parametrize('chunk_size', [0, -1, True, 1.5])
def test_native_stream_rejects_invalid_chunk_sizes(chunk_size):
    model = mg2mc.translate_mg_to_lal(source('mg_c_echo'))
    with pytest.raises(ValueError):
        list(mc2mb.iter_lal_to_mb(model, chunk_size))
