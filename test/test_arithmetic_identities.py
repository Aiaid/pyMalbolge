"""Division/remainder identities retain evaluation and error-return semantics.

Fast checks execute the emitted C and validate both downstream IR paths.
Set MALBOLGE_SLOW_TESTS=1 for actual compiled Malbolge20 execution.
"""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

from malbolge.compiler import (
    CompileError, Py2MgError, compile_c_to_mg, compile_python_to_c,
    compile_python_to_mb, compile_python_to_mg, translate_mg_to_mc,
)


INPUT_AND_AUGMENTED = """\
x = getchar()
y = x // 1
putchar(y)
x //= 1
putchar(x)
x %= 1
putchar(48 + x)
putchar(48 + (getchar() % 1))
putchar(getchar() // 1)
"""

CALL_ORDER = """\
g = 65
def touch():
    global g
    g = g + 1
    putchar(84)
    return g
putchar((touch() % 1) + g)
putchar((touch() // 1) + 0)
putchar((g // 1) + (touch() % 1))
"""

WORD_BOUNDARIES = """\
x = 3486784400
if x // 1 == 3486784400:
    putchar(65)
x //= 1
if x == 3486784400:
    putchar(66)
putchar(48 + (x % 1))
x %= 1
putchar(48 + x)
x = (3486784400 + 1) // 1
putchar(48 + x)
x = (0 - 1) % 1
putchar(48 + x)
"""

READ_RETURN = """\
def read():
    return int(input()) // 1
def wrapper():
    return (read() % 1) + 65
putchar(wrapper())
putchar(90)
"""

DIVIDE_RETURN = """\
def fail():
    divisor = 0
    return 7 // divisor
def wrapper():
    return (fail() % 1) + 65
putchar(wrapper())
putchar(90)
"""

CASES = (
    (INPUT_AND_AUGMENTED, b"ABC", b"AA00C"),
    (CALL_ORDER, b"", b"TBTCTC"),
    (WORD_BOUNDARIES, b"", b"AB0000"),
    (READ_RETURN, b"7\n", b"AZ"),
    (READ_RETURN, b"bad\n", b"error\n"),
    (DIVIDE_RETURN, b"", b"error\n"),
)


def frontend(source, backend):
    if backend == "c":
        return compile_c_to_mg(compile_python_to_c(source))
    return compile_python_to_mg(source)


@pytest.mark.parametrize("backend", ("c", "direct"))
@pytest.mark.parametrize("source", (INPUT_AND_AUGMENTED, CALL_ORDER,
                                    WORD_BOUNDARIES))
def test_identities_omit_helpers_and_downstream_accepts(source, backend):
    mg = frontend(source, backend)
    assert "ZZDIV" not in mg
    assert "ZZMOD" not in mg
    assert translate_mg_to_mc(mg)


@pytest.mark.parametrize("backend", ("c", "direct"))
@pytest.mark.parametrize("expression", ("x // 1", "x % 1", "x // (2 - 1)",
                                        "x % (3486784401 + 1)"))
def test_identity_with_folded_literal_divisor(expression, backend):
    mg = frontend("x=getchar()\nputchar(" + expression + ")\n", backend)
    assert "ZZDIV" not in mg
    assert "ZZMOD" not in mg
    assert mg.count("INPUT") == 1


@pytest.mark.parametrize("backend", ("c", "direct"))
@pytest.mark.parametrize("operator", ("//=", "%="))
def test_augmented_identity_releases_snapshot_for_folded_call(operator, backend):
    # ord() is conservatively classified as a call before folding. This path
    # captures the old target in a temporary, which %= must release once.
    source = ("x=getchar()\nx " + operator + " ord('\\x01')\n"
              "putchar(x)\nputchar(getchar())\n")
    mg = frontend(source, backend)
    assert "ZZDIV" not in mg
    assert "ZZMOD" not in mg
    assert mg.count("INPUT") == 2
    assert translate_mg_to_mc(mg)


@pytest.mark.parametrize("backend", ("c", "direct"))
@pytest.mark.parametrize("source", (READ_RETURN, DIVIDE_RETURN))
def test_nested_error_guards_survive_identity(source, backend):
    mg = frontend(source, backend)
    # The identity removes only its own arithmetic helper. The inner failing
    # computation and caller-to-main error propagation must remain.
    assert "ZZMOD" not in mg
    assert "zzioerror" in mg.lower()
    assert "CALL WRAPPER" in mg
    assert "RETURN" in mg
    if source == READ_RETURN:
        assert "ZZREADINT" in mg
        assert "ZZDIV" not in mg
    else:
        assert "ZZDIV" in mg
    assert translate_mg_to_mc(mg)


@pytest.mark.parametrize("compile_source,error", (
    (compile_python_to_c, CompileError),
    (compile_python_to_mg, Py2MgError),
))
@pytest.mark.parametrize("expression", ("7 // 0", "7 % 0",
                                        "7 // 3486784401", "7 % 3486784401"))
def test_constant_zero_divisor_remains_source_error(compile_source, error,
                                                   expression):
    with pytest.raises(error, match="division or modulo by zero"):
        compile_source("putchar(" + expression + ")\n")


@pytest.mark.skipif(shutil.which("cc") is None, reason="C compiler unavailable")
@pytest.mark.parametrize("source,stdin,expected", CASES)
def test_emitted_c_preserves_values_effects_and_error_returns(
        source, stdin, expected, tmp_path):
    # uint32 can represent every Malbolge20 word. These sources use runtime
    # arithmetic within the word ring; overflowing constant expressions have
    # already been folded by the frontend.
    c = compile_python_to_c(source).replace("int ", "unsigned int ")
    c = c.replace("unsigned int main(", "int main(")
    path = tmp_path / "identity.c"
    executable = tmp_path / "identity"
    path.write_text("#include <stdio.h>\n" + c)
    subprocess.run([shutil.which("cc"), str(path), "-o", str(executable)],
                   check=True, capture_output=True, timeout=30)
    run = subprocess.run([str(executable)], input=stdin, capture_output=True,
                         timeout=5)
    assert run.returncode == 0, run.stderr
    assert run.stdout == expected


def test_portable_compiled_vm_consumes_both_identity_operands():
    from malbolge.malbolge20 import run

    source = "a=getchar()\nputchar(a//1)\nputchar(48+(getchar()%1))\n"
    result = run(compile_python_to_mb(source, backend="direct"), b"AB",
                 max_steps=2_000_000, max_output=16)
    assert result.stop_reason == "terminated"
    assert result.output == b"A0"
    assert result.input_consumed == 2


@pytest.mark.skipif(os.environ.get("MALBOLGE_SLOW_TESTS") != "1",
                    reason="set MALBOLGE_SLOW_TESTS=1 for target VM regressions")
@pytest.mark.parametrize("backend", ("c", "direct"))
@pytest.mark.parametrize("source,stdin,expected", CASES)
def test_actual_mb_preserves_identity_semantics(source, stdin, expected,
                                               backend, tmp_path):
    default = (Path(__file__).resolve().parents[1] / "ref" /
               "nagoya-malbolge20-interpreter" / "malbolge20")
    executable = Path(os.environ.get("MALBOLGE_NATIVE_INTERPRETER", default))
    if not executable.is_file():
        pytest.skip("reference Malbolge20 interpreter unavailable")
    image = tmp_path / "identity.mb"
    image.write_text(compile_python_to_mb(source, backend=backend))
    run = subprocess.run([str(executable), str(image)], input=stdin,
                         capture_output=True, timeout=120)
    assert run.returncode == 0, run.stderr
    assert run.stderr == b""
    assert run.stdout == expected
