"""Side-effect, flow-analysis and iterator regressions for the C frontend.

Set MALBOLGE_QOS_NATIVE=1 to run target-VM differential cases. Set
MALBOLGE_NATIVE_INTERPRETER to select a separately built reference executable.
"""

import io
import os
from pathlib import Path
import re
import subprocess
import tempfile

import pytest

from malbolge.compiler import (
    CompileError, compile_c_to_mg, compile_python_to_c, compile_python_to_mb,
)


SEMANTICS = """\
g = 7
def change():
    global g
    g = 12
    return 3
def pair(a, b):
    return a + b
def touch():
    putchar(84)
    return 1
putchar(48 + (g + change()))
g = 7
putchar(48 + pair(g, change()))
g = 7
g += change()
putchar(48 + g)
if 0 and touch():
    pass
putchar(65)
if 1 or touch():
    pass
putchar(66)
if 2 < 1 < touch():
    pass
putchar(67)
x = 9
x = x > 5
putchar(48 + x)
limit = 3
for i in range(limit):
    putchar(65 + i)
    limit = 0
"""

RANGES = """\
i = 5
for i in range(0, i):
    putchar(65 + i)
putchar(124)
for j in range(3):
    putchar(65 + j)
    j = 10
putchar(124)
"""

VALUES = """\
def touch():
    putchar(84)
    return 9
putchar(48 + (5 or touch()))
putchar(48 + (0 and touch()))
putchar(48 + (2 and 7))
putchar(48 + (0 or 8))
for i in range(3, -1, -1):
    putchar(48 + i)
putchar(124)
for j in range(3):
    pass
putchar(48 + j)
"""

STAGE2 = """\
def read():
    return int(input())
def quotient(n):
    return 12 // n
def pair(a, b):
    return a + b
x, y = 1, 2
x, y = y, x
print(f'{x}:{y}|', pair(b=x, a=y), quotient(read()), sep=':', end='!')
"""


@pytest.mark.parametrize("source", [SEMANTICS, RANGES, VALUES, STAGE2])
def test_qos_sources_accepted_by_c_pipeline(source):
    assert compile_c_to_mg(compile_python_to_c(source))


def test_snapshot_precedes_mutating_call():
    c = compile_python_to_c(SEMANTICS)
    main = c[c.index("int main(){"):]
    capture = re.search(r"(zzt\d+) = g;", main)
    assert capture is not None
    assert capture.start() < main.index("= change();")
    assert "{} +".format(capture.group(1)) in main


def test_comparison_middle_operand_captured_before_later_call():
    c = compile_python_to_c(
        "g = 2\ndef change():\n    global g\n    g = 0\n"
        "    return 3\nif 1 < g < change():\n    putchar(65)\n")
    main = c[c.index("int main(){"):]
    capture = re.search(r"(zzt\d+) = g;", main)
    assert capture is not None
    assert capture.start() < main.index("= change();")
    assert re.search(r"if\({} < zzt\d+\)".format(capture.group(1)), main)


def test_while_break_does_not_recheck_condition():
    c = compile_python_to_c(
        "def touch():\n    putchar(84)\n    return 1\n"
        "while touch():\n    break\n")
    main = c[c.index("int main(){"):]
    body = main[main.index("while("):]
    assert re.search(r"if\(zzt\d+ == 0\)\{\s+zzt\d+ = touch\(\);", body)


@pytest.mark.parametrize("source", [
    "x = x + 1\n",
    "if 0:\n    x = 65\nputchar(x)\n",
    "n = 0\nif n:\n    x = 65\nputchar(x)\n",
    "for i in range(0):\n    x = 65\nputchar(x)\n",
    "while 0:\n    x = 65\nputchar(x)\n",
    "for i in range(0):\n    pass\nputchar(i)\n",
    "x = 65\ndef f():\n    putchar(x)\n    x = 66\nf()\n",
])
def test_possible_unbound_reads_rejected(source):
    with pytest.raises(CompileError, match="before.*assigned"):
        compile_python_to_c(source)


@pytest.mark.parametrize("source", [
    "if 1:\n    x = 65\nputchar(x)\n",
    "n = 1\nif n:\n    x = 65\nelse:\n    x = 66\nputchar(x)\n",
    "for i in range(3):\n    pass\nputchar(i)\n",
    "i = 65\nfor i in range(0):\n    pass\nputchar(i)\n",
    "for i in range(3):\n    x = 65\n    break\nputchar(x)\n",
    "while 1:\n    x = 65\n    break\nputchar(x)\n",
    "def f(n):\n    if n:\n        return 1\n    else:\n        x = 65\n    return x\nf(0)\n",
])
def test_proven_bindings_are_accepted(source):
    compile_python_to_c(source)


def test_late_global_rejected_at_original_source_line():
    source = "x = 65\ndef f():\n    putchar(x)\n    global x\nf()\n"
    with pytest.raises(CompileError) as error:
        compile_python_to_c(source)
    assert error.value.lineno == 4
    assert "prior to global" in str(error.value)


def test_comparison_assignment_uses_new_flag():
    c = compile_python_to_c("x = 9\nx = x > 5\n")
    assert "if(x > 5){" in c
    assert c.index("if(x > 5){") < c.index("x = zzt")
    assert "x = 0;" not in c


def test_keyword_values_evaluate_in_source_order_before_permutation():
    c = compile_python_to_c(
        "g = 7\ndef change():\n    global g\n    g = 12\n    return 3\n"
        "def pair(a, b):\n    return a + b\n"
        "putchar(pair(b=g, a=change()))\n")
    main = c[c.index("int main(){"):]
    captured = re.search(r"(zzt\d+) = g;", main)
    called = re.search(r"(zzt\d+) = change\(\);", main)
    assert captured is not None and called is not None
    assert captured.start() < called.start()
    assert "pair({}, {})".format(called.group(1), captured.group(1)) in main


@pytest.mark.parametrize("source", [
    "def f():\n    pass\nx = f()\n",
    "def f(n):\n    if n:\n        return 1\nx = f(0)\n",
    "def f():\n    return None\nprint(f())\n",
])
def test_possible_none_results_cannot_be_used_as_integer(source):
    with pytest.raises(CompileError, match="may return None"):
        compile_python_to_c(source)


def test_void_function_may_be_called_as_discarded_statement():
    c = compile_python_to_c("def f():\n    return None\nf()\n")
    assert "return 0;" in c


def test_only_error_reachable_calls_get_post_call_guard():
    c = compile_python_to_c(
        "def pure(n):\n    return n\n"
        "def read():\n    return int(input())\n"
        "def outer():\n    return read()\n"
        "print(pure(1), outer())\n")
    main = c[c.index("int main(){"):]
    assert re.search(r"= pure\(1\);\s+zzt\d+ = zzt\d+;", main)
    assert re.search(r"= outer\(\);\s+if\(zzioerror != 0\)", main)
    assert c.count("if(zzioerror != 0){") == 3


def test_dynamic_zero_division_propagates_through_call():
    c = compile_python_to_c(
        "def f(n):\n    return 7 // n\nprint(f(0))\n")
    assert "if(b == 0){ zzioerror = 1; return 0; }" in c
    assert c.count("if(zzioerror != 0){") == 2
    assert c.index("int zzioerror;") < c.index("int zzdiv(")


def test_descending_range_and_unsigned_edges_are_guarded():
    c = compile_python_to_c(
        "for i in range(3, -1, -1):\n    pass\n"
        "for j in range(3486784400, 3486784401, 2):\n    pass\n")
    assert re.search(r"if\(zzt\d+ >= 1\)", c)
    assert re.search(r"if\(zzt\d+ <= 3486784398\)", c)
    assert "i +=" not in c and "j +=" not in c


def test_huge_range_step_ends_before_any_wrapping_update():
    c = compile_python_to_c(
        "for i in range(1, 9, 3486784401):\n    putchar(i)\n"
        "for j in range(9, 1, -3486784401):\n    putchar(j)\n")
    assert "+ 3486784401" not in c and "- 3486784401" not in c
    assert "putchar(i);" in c and "putchar(j);" in c


def test_ascending_range_with_negative_stop_is_empty_after_argument_evaluation():
    c = compile_python_to_c(
        "def start():\n    putchar(65)\n    return 3\n"
        "i = 7\nfor i in range(start(), -1):\n    putchar(66)\n")
    assert "= start();" in c
    assert re.search(r"if\(zzt\d+ < 0\)", c)


@pytest.mark.parametrize("factor", [0, 1, 2, 3, 7, 8, 16])
def test_small_literal_multiply_avoids_generic_helper(factor):
    source = "x = 7\nx *= {}\nputchar(x)\n".format(factor)
    c = compile_python_to_c(source)
    assert "zzmul" not in c
    assert compile_c_to_mg(c)


NATIVE = os.environ.get("MALBOLGE_NATIVE_INTERPRETER", str(
    Path(__file__).resolve().parents[1]
    / "ref/nagoya-malbolge20-interpreter/malbolge20"))


@pytest.mark.skipif(os.environ.get("MALBOLGE_QOS_NATIVE") != "1",
                    reason="target-VM QoS cases are explicitly enabled")
@pytest.mark.parametrize("source,expected", [
    (SEMANTICS, ":::ABC1ABC"),
    (RANGES, "ABCDE|ABC|"),
    (VALUES, "50783210|2"),
])
def test_native_matches_cpython(source, expected):
    assert os.access(NATIVE, os.X_OK), "build or select the native interpreter"
    output = io.StringIO()
    exec(source, {"putchar": lambda n: output.write(chr(n))})
    assert output.getvalue() == expected
    with tempfile.TemporaryDirectory() as directory:
        mb = Path(directory) / "program.mb"
        mb.write_text(compile_python_to_mb(source, backend="c"))
        result = subprocess.run([NATIVE, str(mb)], capture_output=True,
                                text=True, timeout=300)
    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout == output.getvalue()


@pytest.mark.skipif(os.environ.get("MALBOLGE_QOS_NATIVE") != "1",
                    reason="target-VM QoS cases are explicitly enabled")
def test_native_stage2_and_runtime_failure_propagation():
    assert os.access(NATIVE, os.X_OK), "build or select the native interpreter"
    with tempfile.TemporaryDirectory() as directory:
        mb = Path(directory) / "stage2.mb"
        mb.write_text(compile_python_to_mb(STAGE2, backend="c"))
        for stdin, expected in [("3\n", "2:1|:3:4!"), ("0\n", "error\n"),
                                ("abc\n", "error\n"), ("", "error\n")]:
            result = subprocess.run([NATIVE, str(mb)], input=stdin,
                                    capture_output=True, text=True, timeout=300)
            assert result.returncode == 0
            assert result.stderr == ""
            assert result.stdout == expected
