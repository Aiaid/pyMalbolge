"""Source semantic IR conformance, independent of target code generation."""

import ast
import json
from pathlib import Path

import pytest

pytest.importorskip("xdsl")

from malbolge.compiler.ir.frontend import (  # noqa: E402
    SemanticFrontendError, compile_python_to_semantic_ir,
)
from malbolge.compiler.ir.semantic import (  # noqa: E402
    BinaryOp, BoolOp, CompareOp, ConstOp, ForOp, FuncOp, LoadOp,
    ReadIntOp, StoreOp, get_program, parse_semantic, print_semantic,
)
from test.test_py2mg_qos import ADVANCED_CASES, CASES  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "test" / "fixtures" / "qos" / "direct"
MANIFEST = json.loads((ROOT / "benchmarks" / "manifest.json").read_text())


def run(source, stdin=b""):
    from malbolge.compiler.ir.interpreter import run_semantic

    return run_semantic(compile_python_to_semantic_ir(source), stdin)


def output(result):
    return result.output


def test_frontend_does_not_invoke_target_codegen(monkeypatch):
    from malbolge.compiler import c2mg, mc2mb, mg2mc, py2c, py2mg

    def forbidden(*args, **kwargs):
        pytest.fail("semantic frontend invoked an old compiler or code generator")

    for module, name in [(py2mg, "compile_python_to_mg"), (py2c, "compile_python_to_c"),
                         (c2mg, "translate_c_to_mg"), (mg2mc, "translate_mg_to_mc"),
                         (mc2mb, "assemble_mc_to_mb")]:
        if hasattr(module, name):
            monkeypatch.setattr(module, name, forbidden)
    for name in ("__init__", "compile", "lower", "_generate_program", "_compile_user_function"):
        monkeypatch.setattr(py2mg._DirectCompiler, name, forbidden)
    module = compile_python_to_semantic_ir(
        "def scale(n):\n    return n * 17\nx = int(input())\nprint(scale(x))\n")
    assert any(isinstance(op, BinaryOp) and op.kind.data == "mul" for op in module.walk())
    assert any(isinstance(op, ReadIntOp) for op in module.walk())


def test_frontend_preserves_arithmetic_and_locations_without_source_payload():
    module = compile_python_to_semantic_ir("n = 4\nprint(n * 17, 6 * 7, n // 1, n % 1)\n")
    binaries = [op for op in module.walk() if isinstance(op, BinaryOp)]
    assert [op.kind.data for op in binaries] == ["mul", "mul", "floordiv", "mod"]
    assert all(op.location.line.data == 2 for op in binaries)
    assert all(op.rhs.owner.value.data in (17, 7, 1) for op in binaries)
    text = print_semantic(module)
    assert "pysem.binary" in text
    assert "lal." not in text and "py_ast" not in text and "python_source" not in text
    assert print_semantic(parse_semantic(text)) == text


_AUDIT_RUNS = [(name, stdin, expected) for name, (expected, stdin) in CASES.items()]
_AUDIT_RUNS += [(name, stdin, expected) for name, runs in ADVANCED_CASES.items()
                for stdin, expected in runs]


@pytest.mark.parametrize("name,stdin,expected", _AUDIT_RUNS,
                         ids=[f"{name}-{index}" for index, (name, _, _) in enumerate(_AUDIT_RUNS)])
def test_existing_qos_oracles(name, stdin, expected):
    source = (FIXTURES / (name + ".py")).read_text()
    assert output(run(source, stdin)) == expected.encode("latin1")


_BENCHMARKS = [(program, workload) for program in MANIFEST["programs"]
               for workload in program["workloads"]]


@pytest.mark.parametrize("program,workload", _BENCHMARKS,
                         ids=[f"{program['id']}-{workload['id']}" for program, workload in _BENCHMARKS])
def test_fixed_benchmark_oracles(program, workload):
    source = (ROOT / "benchmarks" / program["path"]).read_text()
    assert output(run(source, workload["stdin"].encode())) == workload["stdout"].encode()


@pytest.mark.parametrize("source,expected", [
    ("g=3\ndef bump():\n    global g\n    g=9\n    putchar(66)\n    return 4\n"
     "print(g,bump(),g)\n", b"B3 4 9\n"),
    ("g=3\ndef bump():\n    global g\n    g=9\n    return 4\n"
     "g += bump()\nprint(g)\n", b"7\n"),
    ("def mark(x):\n    putchar(x)\n    return x\n"
     "def pair(a,b):\n    print(a,b)\n"
     "pair(b=mark(66),a=mark(65))\n", b"BA65 66\n"),
    ("def mark(x):\n    putchar(x)\n    return x\n"
     "print(mark(65) < mark(66) < mark(67))\n"
     "print(mark(67) < mark(66) < mark(65))\n", b"ABC1\nCB0\n"),
    ("def mark(x):\n    putchar(x)\n    return x\n"
     "print(0 and mark(65), 7 or mark(66), mark(67) if 1 else mark(68))\n",
     b"C0 7 67\n"),
    ("i=7\nfor i in range(i,9):\n    putchar(65+i-7)\n    i=90\nprint(i)\n", b"AB90\n"),
    ("i=7\nfor i in range(0):\n    i=8\nprint(i)\n", b"7\n"),
    ("for i in range(3,-1,-1):\n    if i == 2:\n        continue\n"
     "    putchar(48+i)\n    if i == 1:\n        break\nprint(i)\n", b"311\n"),
    ("for i in range(2):\n    j=0\n    while j < 3:\n        j += 1\n"
     "        if j == 2:\n            break\n        putchar(65+i)\n", b"AB"),
    ("a,b=1,2\na,b=b,a\nprint(f'{a}:{b}', sep='!')\n", b"2:1\n"),
    ("def visit(n):\n    if n == 0:\n        return 1\n"
     "    return visit(n-1)+visit(n-1)\nprint(visit(5))\n", b"32\n"),
    ("def empty():\n    return None\nempty()\nprint(7)\n", b"7\n"),
    ("if 1:\n    x=7\nprint(x)\n", b"7\n"),
    ("while 1:\n    x=7\n    break\nprint(x)\n", b"7\n"),
    ("for i in range(1):\n    x=7\nprint(x)\n", b"7\n"),
])
def test_order_binding_control_and_return_contracts(source, expected):
    assert output(run(source)) == expected


@pytest.mark.parametrize("source,stdin,expected", [
    ("x=1\nputchar(65)\nx // 0\nputchar(66)\n", b"", b"Aerror\n"),
    ("x=1\nputchar(65)\nx % 0\nputchar(66)\n", b"", b"Aerror\n"),
    ("int(input('N:'))\nputchar(66)\n", b"bad\n", b"N:error\n"),
    ("def fail():\n    x=1\n    return x // 0\nprint('before',fail())\nputchar(66)\n", b"", b"error\n"),
    ("print(0 and (1 // 0),7 or int(input()))\n", b"bad\n", b"0 7\n"),
    ("print(int(input('N:')))\n", b" +0007 \r\n", b"N:7\n"),
    ("print(getchar(),getchar())\n", b"A", b"65 59049\n"),
    ("putchar(321)\nprint(0-1)\n", b"", b"A3486784400\n"),
])
def test_error_capable_discarded_expressions_and_io(source, stdin, expected):
    assert output(run(source, stdin)) == expected


@pytest.mark.parametrize("source,line,phrase", [
    ("x=1\ny = -x\n", 2, "unary minus"),
    ("x=1\ny = x / 2\n", 2, "true division"),
    ("x=1\ny = x ** 2\n", 2, "binary operator"),
    ("print(missing)\n", 1, "not defined"),
    ("if getchar():\n    x=1\nprint(x)\n", 3, "before assignment"),
    ("x=7\ndef f():\n    print(x)\n    x=1\nf()\n", 3, "before assignment"),
    ("x=7\ndef f():\n    x: int\n    return x\nprint(f())\n", 4, "before assignment"),
    ("def f():\n    x=1\n    global x\n", 3, "syntax error"),
    ("def f(a=1):\n    return a\n", 1, "simple positional"),
    ("def f(a):\n    return a\nprint(f(b=1))\n", 3, "unexpected keyword"),
    ("def f(a):\n    return a\nprint(f())\n", 3, "missing argument"),
    ("def f():\n    pass\nprint(f())\n", 3, "may return None"),
    ("for i in range(3,0,0):\n    pass\n", 1, "nonzero"),
    ("for i in range(3,-2,-1):\n    pass\n", 1, "stop=-1"),
    ("for i in range(-1,3):\n    pass\n", 1, "negative integers"),
    ("for i in range(3):\n    pass\nelse:\n    pass\n", 1, "for...else"),
    ("print(f'{1:02}')\n", 1, "format specifiers"),
    ("print(f'{1!r}')\n", 1, "conversion specifiers"),
    ("print('你好')\n", 1, "byte-oriented"),
    ("a,b=value\n", 1, "tuple assignment"),
    ("x = [1,2]\n", 1, "unsupported expression"),
    ("x=print(1)\n", 1, "cannot be used as a value"),
    ("x=input()\n", 1, "int(input())"),
    ("import os\n", 1, "'import'"),
    ("return 1\n", 1, "syntax error"),
])
def test_source_located_diagnostics(source, line, phrase):
    with pytest.raises(SemanticFrontendError) as caught:
        compile_python_to_semantic_ir(source)
    assert caught.value.lineno == line
    assert caught.value.snippet == source.splitlines()[line - 1]
    assert phrase in str(caught.value)


def _existing_diagnostic_oracles():
    """Reuse the existing source/line oracle without running its C backend."""
    tree = ast.parse((ROOT / "test" / "test_py2c_diagnostics.py").read_text())
    cases = []
    for definition in tree.body:
        if not isinstance(definition, ast.ClassDef):
            continue
        for method in definition.body:
            if not isinstance(method, ast.FunctionDef):
                continue
            for call in ast.walk(method):
                if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "assert_rejected"):
                    continue
                try:
                    source, line, _ = [ast.literal_eval(arg) for arg in call.args]
                except (ValueError, TypeError):
                    continue
                cases.append(pytest.param(source, line, id=method.name))
    return cases


@pytest.mark.parametrize("source,line", _existing_diagnostic_oracles())
def test_existing_diagnostic_source_lines(source, line):
    with pytest.raises(SemanticFrontendError) as caught:
        compile_python_to_semantic_ir(source)
    assert caught.value.lineno == line
    assert caught.value.snippet == source.splitlines()[line - 1]


@pytest.mark.parametrize("source,expected", [
    ("x=0 and never_read\nprint(x)\n", b"0\n"),
    ("while 0:\n    putchar(never_read)\nputchar(65)\n", b"A"),
    ("putchar(65+(0 and never_called()))\n", b"A"),
    ("print(7 if 1 else never_read)\n", b"7\n"),
    ("def f():\n    global unused\n    pass\nf()\nprint(1)\n", b"1\n"),
    ("def f():\n    for i in range(0):\n        return 1\nf()\nprint(1)\n", b"1\n"),
])
def test_statically_unreachable_and_declaration_only_forms(source, expected):
    assert output(run(source)) == expected


def test_unreachable_unknown_name_remains_an_explicit_trap():
    from xdsl.dialects.builtin import IntAttr
    from malbolge.compiler.ir.interpreter import run_semantic
    from malbolge.compiler.ir.semantic import SemanticIRError, UnboundNameOp

    module = compile_python_to_semantic_ir("print(0 and never_read)\n")
    assert any(isinstance(op, UnboundNameOp) for op in module.walk())
    literal = next(op for op in module.walk() if isinstance(op, ConstOp))
    literal.properties["value"] = IntAttr(1)
    with pytest.raises(SemanticIRError, match="never_read"):
        run_semantic(module)


@pytest.mark.parametrize("source", [
    "putchar(5 // 0)\n",
    "putchar(5 % 0)\n",
    "print(5 // (7 - 7))\n",
    "print((7 * 9) % (3 ** 20))\n",  # unsupported power retains its own diagnostic
    "print((7 * 9) % 3486784401)\n",
    "x=1\nprint(x + (5 // (2 * 0)))\n",
    "print(5 // (ord('a') - 97))\n",
    "print((0 or 5) // (7 and 0))\n",
    "x=1\nprint((x * 0) // 0)\n",
    "x=1\nprint((x % 1) % 0)\n",
    "flag=getchar()\nprint(flag and 0 and (5 // 0))\n",
    "if getchar():\n    print(5 // 0)\n",
    "if 0 < 1:\n    print(5 // 0)\n",
    "print(1 if 1 else (5 // 0))\n",
    "print(2 < 1 < (5 // 0))\n",
    "for i in range(0):\n    print(5 // 0)\n",
])
def test_constant_zero_diagnostics_match_direct_frontend(source):
    from malbolge.compiler.py2mg import Py2MgError, compile_python_to_mg

    with pytest.raises(Py2MgError) as reference:
        compile_python_to_mg(source)
    with pytest.raises(SemanticFrontendError) as semantic:
        compile_python_to_semantic_ir(source)
    assert semantic.value.lineno == reference.value.lineno
    assert semantic.value.snippet == reference.value.snippet
    assert semantic.value.message == reference.value.message


@pytest.mark.parametrize("source,expected", [
    ("print(0 and (5 // 0))\n", b"0\n"),
    ("print(7 or (5 % 0))\n", b"7\n"),
    ("print((7-7) and (5 // 0))\n", b"0\n"),
    ("if 0:\n    print(5 // 0)\nprint(7)\n", b"7\n"),
    ("if not 0:\n    print(7)\nelse:\n    print(5 // 0)\n", b"7\n"),
    ("while 0:\n    print(5 // 0)\nprint(7)\n", b"7\n"),
    ("if 0 and (5 // 0):\n    print(1)\nprint(7)\n", b"7\n"),
    ("def f():\n    return 7\n    return 5 // 0\nprint(f())\n", b"7\n"),
    ("for i in range(1):\n    break\n    print(5 // 0)\nprint(7)\n", b"7\n"),
])
def test_unreachable_constant_zero_keeps_lazy_regions_and_legacy_acceptance(source, expected):
    from malbolge.compiler.py2mg import compile_python_to_mg

    assert compile_python_to_mg(source)
    module = compile_python_to_semantic_ir(source)
    assert any(isinstance(op, BinaryOp) and op.kind.data in {"floordiv", "mod"}
               for op in module.walk())
    assert output(run(source)) == expected


def test_function_global_write_does_not_admit_an_implicit_global_read():
    from malbolge.compiler.py2mg import Py2MgError, compile_python_to_mg

    source = ("def f():\n    global x\n    x=65\n"
              "def g():\n    return x\nf()\nputchar(g())\n")
    with pytest.raises(Py2MgError) as reference:
        compile_python_to_mg(source)
    with pytest.raises(SemanticFrontendError) as semantic:
        compile_python_to_semantic_ir(source)
    assert semantic.value.lineno == reference.value.lineno == 5
    assert semantic.value.snippet == reference.value.snippet == "    return x"
    assert semantic.value.message == reference.value.message == "name 'x' is not defined"


@pytest.mark.parametrize("source", [
    "def f():\n    global x\n    x=65\ndef g():\n    global x\n    return x\nf()\nputchar(g())\n",
    "x=65\ndef g():\n    return x\nputchar(g())\n",
    "x=0\ndef f():\n    global x\n    x=65\ndef g():\n    return x\nf()\nputchar(g())\n",
])
def test_explicit_declared_or_module_bound_global_read_is_accepted(source):
    from malbolge.compiler.py2mg import compile_python_to_mg

    assert compile_python_to_mg(source)
    assert output(run(source)) == b"A"


def test_functions_and_lazy_regions_are_structural():
    module = compile_python_to_semantic_ir(
        "def check(a,b):\n    return a and (a < b < 100)\n"
        "for i in range(3,-1,-1):\n    print(check(i,4))\n")
    functions = [op for op in get_program(module).body.block.ops if isinstance(op, FuncOp)]
    check = next(func for func in functions if func.sym_name.data == "check")
    stores = [op for op in check.body.block.ops if isinstance(op, StoreOp)]
    assert [store.value for store in stores[:2]] == list(check.body.block.args)
    boolean = next(op for op in check.walk() if isinstance(op, BoolOp))
    assert len(boolean.values) == 2
    comparison = next(op for op in boolean.values[1].walk() if isinstance(op, CompareOp))
    assert len(comparison.values) == 3
    loop = next(op for op in module.walk() if isinstance(op, ForOp))
    assert loop.step.data == -1 and loop.stop_sentinel.data == 1


def test_recompilation_is_deterministic_and_mutation_changes_semantics():
    source = "n=3\nprint(n*17)\n"
    first = compile_python_to_semantic_ir(source)
    assert print_semantic(first) == print_semantic(compile_python_to_semantic_ir(source))
    factor = next(op for op in first.walk() if isinstance(op, ConstOp) and op.value.data == 17)
    from xdsl.dialects.builtin import IntAttr
    from malbolge.compiler.ir.interpreter import run_semantic

    factor.properties["value"] = IntAttr(19)
    assert output(run_semantic(first)) == b"57\n"
