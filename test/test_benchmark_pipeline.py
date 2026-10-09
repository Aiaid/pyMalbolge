"""Measurement boundaries and behavior checks for the performance runner."""

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/benchmark_pipeline.py"
SPEC = importlib.util.spec_from_file_location("benchmark_pipeline", SCRIPT)
BENCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCH)


def test_oracles_capture_byte_and_decimal_io():
    for case, expected in (("echo", b"Q"), ("decimal", b"7\n"),
                           ("fib_iter", b"13\n"), ("fib_rec", b"13\n")):
        source, text = BENCH.CASES[case]
        assert BENCH.oracle(source, text) == expected


def test_data_counts_keep_dup_and_sections_distinct():
    data = ("ENTRY_ADDRESS:200\r\nDIRECT_UNIT_CODE:0\r\noffset:100\r\n"
            "len:3\r\n33\r\n-1\r\n0\r\nROUTINE_CODE:0\r\n"
            "offset:200\r\nlen:2\r\n81\r\n-1\r\nEND\r\n")
    result = BENCH.data_structure(data)
    assert result["entry_address"] == 200
    assert result["sections"] == {"DIRECT_UNIT_CODE": 1, "ROUTINE_CODE": 1}
    assert result["words_including_dup"] == {"DIRECT_UNIT_CODE": 3, "ROUTINE_CODE": 2}
    assert result["non_dup_words"] == {"DIRECT_UNIT_CODE": 2, "ROUTINE_CODE": 1}
    assert BENCH.text_structure("# comment\nfoo:\nbar:\n  OUTPUT # hi\n") == {"LABEL": 2, "OUTPUT": 1}


def test_real_pipeline_metrics_and_runtime_agree_with_artifact(tmp_path):
    source, input_text = BENCH.CASES["echo"]
    args = SimpleNamespace(backend="direct", op_style="cluster", jmp_style="main",
                           max_steps=2000000)
    compiler = BENCH.compile_sample(args, tmp_path, source)
    image = (tmp_path / "program.mb").read_bytes()
    assert compiler["image"]["bytes"] == len(image)
    assert compiler["image"]["sha256"] == hashlib.sha256(image).hexdigest()
    assert [stage["stage"] for stage in compiler["stages"]] == [
        "py2mg", "mg2mc", "mc2mb.parse_layout", "mc2mb.setup_bootstrap",
        "mc2mb.generate_bootstrap", "mc2mb.emit"]
    structure = compiler["structure"]
    assert structure["generated_source_cells"] + structure["padding_source_cells"] == len(image)
    assert structure["data"]["entry_address"] > 0
    result = BENCH.runtime_sample(args, tmp_path, source, input_text)
    assert result["passed"]
    assert result["output_hex"] == b"Q".hex()
    (tmp_path / "compile.json").write_text(json.dumps(compiler))
    (tmp_path / "runtime.json").write_text(json.dumps(result))
    trace = BENCH.trace_sample(args, tmp_path, source, input_text)
    assert trace["passed"]
    assert trace["first_program_step"] > 0
    assert sum(sum(counts.values()) for counts in trace["counts_by_opcode"].values()) == result["result"]["steps"]
    args.max_steps = 0
    bounded = BENCH.runtime_sample(args, tmp_path, source, input_text)
    assert not bounded["passed"]
    assert bounded["result"]["stop_reason"] == "step_limit"
