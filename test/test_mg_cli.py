"""Handwritten MG CLI integration and output-safety regressions."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from malbolge.compiler import Mc2MbError, translate_mg_to_mc, translate_mg_to_lal
from malbolge.compiler import mg_cli
from malbolge.compiler.lal_model import emit_lal_to_mc


FIXTURE = Path("test/fixtures/nagoya/mg_a_minimal.mg")


def run_cli(*args):
    return subprocess.run([sys.executable, "-m", "malbolge", "compile-mg",
                           *map(str, args)], capture_output=True, timeout=120)


@pytest.mark.parametrize("pipeline", ["text", "structured"])
@pytest.mark.parametrize("op", ["cluster", "inline"])
@pytest.mark.parametrize("jmp", ["main", "direct"])
def test_mc_matches_existing_api(pipeline, op, jmp):
    result = run_cli(FIXTURE, "--target-pipeline", pipeline,
                     "--op-style", op, "--jmp-style", jmp, "--stats")
    assert result.returncode == 0, result.stderr
    expected = (emit_lal_to_mc(translate_mg_to_lal(
        FIXTURE.read_text(), op_style=op, jmp_style=jmp)) if pipeline == "structured"
        else translate_mg_to_mc(FIXTURE.read_text(), op_style=op, jmp_style=jmp))
    assert result.stdout.decode().replace("\r\n", "\n") == expected
    assert json.loads(result.stderr)["source_language"] == "mg"


def test_mb_file_stdout_and_pipelines_match_golden(tmp_path):
    import hashlib
    output = tmp_path / "program.mb"
    mc = tmp_path / "program.mc"
    result = run_cli(FIXTURE, "-o", output, "--emit-mc", mc, "--stats")
    assert result.returncode == 0, result.stderr
    assert result.stdout == b""
    image = output.read_bytes()
    assert hashlib.sha256(image).hexdigest() == "9cd064c41ec8b699a3287f980197a78da7268464e1fec85ab4a0dceffa7aa4a0"
    assert mc.read_text() == emit_lal_to_mc(translate_mg_to_lal(FIXTURE.read_text()))
    assert json.loads(result.stderr.splitlines()[-1])["stages"][-1]["bytes"] == len(image)
    result = run_cli(FIXTURE, "-o", "-", "--target-pipeline", "text")
    assert result.returncode == 0, result.stderr
    assert result.stdout == image
    assert result.stderr == b""
    from malbolge.malbolge20 import run
    executed = run(image, max_steps=1000000, max_output=2, engine="python")
    assert executed.stop_reason == "terminated"
    assert executed.output == b"\xde"


def test_preflight_preserves_source_and_outputs(tmp_path):
    source = tmp_path / "source.mg"
    source.write_text("DEF MAIN\n OUTPUT\nEND\n")
    original = source.read_bytes()
    output = tmp_path / "old.mb"
    output.write_bytes(b"keep")
    cases = [(["-o", source], "overwrite the MG source"),
             (["-o", output, "--emit-mc", output], "distinct"),
             (["-o", "-", "--emit-mc", "-"], "distinct"),
             (["-o", tmp_path], "is a directory"),
             (["-o", tmp_path / "missing" / "out.mb"], "directory does not exist")]
    for args, message in cases:
        result = run_cli(source, *args)
        assert result.returncode == 1
        assert message in result.stderr.decode()
        assert b"Traceback" not in result.stderr
        assert source.read_bytes() == original
        assert output.read_bytes() == b"keep"


@pytest.mark.parametrize("kind", ["hardlink", "symlink"])
def test_source_link_alias_rejected(tmp_path, kind):
    source = tmp_path / "source.mg"
    source.write_bytes(FIXTURE.read_bytes())
    alias = tmp_path / "alias.mg"
    try:
        if kind == "hardlink":
            os.link(source, alias)
        else:
            alias.symlink_to(source)
    except OSError as error:
        pytest.skip("filesystem does not permit {}: {}".format(kind, error))
    result = run_cli(source, "-o", alias)
    assert result.returncode == 1
    assert b"overwrite the MG source" in result.stderr
    assert source.read_bytes() == FIXTURE.read_bytes()


@pytest.mark.parametrize("payload", [b"not valid MG", b"\xff"])
def test_bad_source_preserves_output(tmp_path, payload):
    source = tmp_path / "bad.mg"
    source.write_bytes(payload)
    output = tmp_path / "old.mb"
    output.write_bytes(b"keep")
    result = run_cli(source, "-o", output)
    assert result.returncode == 1
    assert b"error:" in result.stderr and b"Traceback" not in result.stderr
    assert output.read_bytes() == b"keep"


def test_missing_source_and_unknown_options(tmp_path):
    result = run_cli(tmp_path / "missing.mg")
    assert result.returncode == 1 and b"file I/O failed:" in result.stderr
    for option in ("--backend=direct", "-O3", "--no-cache", "--op-style=bad"):
        result = run_cli(FIXTURE, option)
        assert result.returncode == 2


@pytest.mark.parametrize("error,code,message", [
    (Mc2MbError("late failure"), 1, "compiler stage failed: late failure"),
    (OSError("disk failure"), 1, "file I/O failed: disk failure"),
    (KeyboardInterrupt(), 130, "interrupted")])
def test_late_failure_preserves_artifact_and_cleans_temp(tmp_path, error, code, message):
    target = tmp_path / "old.mb"
    target.write_bytes(b"keep")
    def chunks(*args):
        yield b"partial"
        raise error
    stderr = io.StringIO()
    with patch.object(mg_cli, "iter_lal_to_mb", chunks), contextlib.redirect_stderr(stderr):
        with pytest.raises(SystemExit) as caught:
            mg_cli.main([str(FIXTURE), "-o", str(target)])
    assert caught.value.code == code
    assert message in stderr.getvalue()
    assert target.read_bytes() == b"keep"
    assert list(tmp_path.iterdir()) == [target]


def test_mc_only_does_not_assemble_or_load_optional_ir():
    code = """
import sys
from unittest.mock import patch
from malbolge.compiler.mg_cli import main
with patch('malbolge.compiler.mg_cli.iter_lal_to_mb', side_effect=AssertionError):
    main(['test/fixtures/nagoya/mg_a_minimal.mg'])
assert not any(name == 'xdsl' or name.startswith('xdsl.') for name in sys.modules)
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
