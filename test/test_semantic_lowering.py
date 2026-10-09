"""Authoritative semantic-IR lowering and ordered evaluation contracts."""

import ast
import sys

import pytest

if sys.version_info < (3, 10):
    pytest.skip("optional semantic IR requires Python 3.10+", allow_module_level=True)
pytest.importorskip("xdsl")

from xdsl.dialects.builtin import IntAttr, ModuleOp, StringAttr

from malbolge.compiler.ir.frontend import compile_python_to_semantic_ir
from malbolge.compiler.ir.interpreter import run_semantic
from malbolge.compiler.ir.lowering import (
    SemanticLoweringError, lower_semantic_to_mg, lower_semantic_to_python,
    lower_semantic_to_python_ast,
)
from malbolge.compiler.ir.semantic import (
    BinaryOp, ConstOp, FuncOp, GetCharOp, ProgramOp, PutCharOp, ReturnOp,
    SemanticIRError, UnboundNameOp, parse_semantic,
    print_semantic, verify_semantic,
)
from malbolge.compiler.mc2mb import assemble_mc_to_mb
from malbolge.compiler.mg2mc import translate_mg_to_mc
from malbolge.malbolge20 import run


def python_output(source_or_ast, data=b"", *, errors=()):
    """Execute ordinary Python with the subset's byte I/O hooks."""
    output = bytearray()
    cursor = 0

    def getchar():
        nonlocal cursor
        if cursor == len(data):
            return 59049
        value = data[cursor]
        cursor += 1
        return value

    def putchar(value):
        output.append(value % 256)

    def input_(prompt=""):
        nonlocal cursor
        output.extend(prompt.encode("latin-1"))
        end = data.find(b"\n", cursor)
        if end < 0:
            end = len(data)
        line = data[cursor:end].decode("latin-1")
        cursor = min(end + 1, len(data))
        return line

    def print_(*values, sep=" ", end="\n"):
        output.extend((sep.join(str(value) for value in values) + end).encode("latin-1"))

    environment = {"putchar": putchar, "getchar": getchar, "input": input_, "print": print_}
    code = compile(source_or_ast, "<semantic-lowering-test>", "exec")
    if errors:
        with pytest.raises(errors):
            exec(code, environment)
    else:
        exec(code, environment)
    return bytes(output), cursor


CASES = [
    ("arithmetic", "x=20\ny=3\nputchar(x+y+42)\nputchar(x//y+59)\nputchar(x%y+63)\n", b""),
    ("keyword_order", """counter=0
def mark(v):
    global counter
    counter+=1
    putchar(counter+64)
    return v
def pair(a,b):
    return a+b
putchar(pair(b=mark(1),a=mark(64)))
""", b""),
    ("global_snapshot", """x=65
def change():
    global x
    x=66
    return 0
putchar(x+change())
putchar(x)
""", b""),
    ("short_circuit", "putchar(0 or getchar())\nputchar(65 or getchar())\nputchar(0 and getchar())\n", b"QZ"),
    ("lazy_comparison", """def mark(x):
    putchar(x+65)
    return x
putchar(65+(mark(2)<mark(1)<mark(3)))
putchar(65+(mark(0)<mark(1)<mark(2)<mark(3)))
""", b""),
    ("conditional_expression", "putchar(getchar() if getchar() else 65)\n", b"\x00Z"),
    ("while_condition", """count=0
while getchar():
    count+=1
    if count==1:
        continue
    putchar(64+count)
putchar(64+count)
""", b"AB\x00Z"),
    ("descending_range", """for i in range(2,-1,-1):
    putchar(65+i)
    i=99
putchar(i)
""", b""),
    ("captured_range", """stop=3
for stop in range(0,stop):
    putchar(65+stop)
    stop=99
putchar(stop)
""", b""),
    ("nested_control", """for i in range(3):
    j=0
    while j<3:
        j+=1
        if j==1:
            continue
        if i==1:
            break
        putchar(64+j)
    if i==1:
        continue
    putchar(68+i)
""", b""),
    ("void_calls", """def emitbyte(x):
    if x:
        putchar(x)
        return None
    return
emitbyte(65)
emitbyte(0)
putchar(66)
""", b""),
    ("recursion", """def fib(n):
    if n<2:
        return n
    return fib(n-1)+fib(n-2)
putchar(65+fib(5))
""", b""),
    ("print_capture", """x=1
def change():
    global x
    x=2
    return x
print(x,change(),sep=":",end="!")
""", b""),
    ("decimal_input", 'x=int(input("n="))\nprint("v",x,sep=":",end="!")\n', b"7\n"),
    ("tuple_fstring", 'x,y=3,4\nx,y=y,x\nprint(f"{x}:{y}",end="!")\n', b""),
    ("local_global", """x=65
def f(x):
    x+=1
    return x
putchar(f(x))
putchar(x)
""", b""),
    ("name_hygiene", """mbirf0=65
def mbirt0(mbirg0):
    return mbirg0
putchar(mbirt0(mbirf0))
""", b""),
]


@pytest.mark.parametrize("name,source,data", CASES, ids=[case[0] for case in CASES])
def test_ordinary_python_oracle_ast_and_target_adapter_agree(name, source, data):
    module = compile_python_to_semantic_ir(source)
    expected, consumed = python_output(source, data)
    generated = lower_semantic_to_python_ast(module)
    observed, lowered_consumed = python_output(generated, data)
    reference = run_semantic(module, data)
    assert observed == reference.output == expected
    assert lowered_consumed == reference.input_consumed == consumed
    assert lower_semantic_to_mg(module).startswith("VAR ")
    # Regeneration is deterministic and does not write cached ASTs into IR.
    assert ast.dump(generated) == ast.dump(lower_semantic_to_python_ast(parse_semantic(print_semantic(module))))


@pytest.mark.parametrize("source", [
    "putchar(65+(0 and never_read))\n",
    "putchar(64+(1 or never_read))\n",
    "while 0:\n    never_read\nputchar(65)\n",
    "if 0:\n    never_read\nputchar(65)\n",
    "putchar(never_read if 0 else 65)\n",
    "putchar(65+(0 and mbirf0))\n",
    "putchar(65+((0 and unseen) and never_read))\n",
    "putchar(64+((1 or unseen) or never_read))\n",
    "putchar(65+((not 1) and never_read))\n",
    "if 0 and unseen:\n    never_read\nputchar(65)\n",
    "while 0 and unseen:\n    never_read\nputchar(65)\n",
])
def test_dead_name_traps_remain_lazy_but_explicit(source):
    module = compile_python_to_semantic_ir(source)
    assert any(isinstance(op, UnboundNameOp) for op in module.walk())
    assert python_output(lower_semantic_to_python_ast(module))[0] == b"A"
    assert run_semantic(module).output == b"A"
    lower_semantic_to_mg(module)


def test_mutating_dead_guard_makes_original_name_trap_fail_target_validation():
    module = compile_python_to_semantic_ir("putchar(65+(0 and never_read))\n")
    guard = next(op for op in module.walk() if isinstance(op, ConstOp) and op.value.data == 0)
    guard.properties["value"] = IntAttr(1)
    with pytest.raises(SemanticLoweringError, match="never_read.*not defined"):
        lower_semantic_to_mg(module)


def test_boolean_results_are_words_when_printed():
    module = compile_python_to_semantic_ir("print(1<2,not 1,1==2,not 0)\n")
    assert python_output(lower_semantic_to_python_ast(module))[0] == b"1 0 0 1\n"
    assert run_semantic(module).output == b"1 0 0 1\n"
    lower_semantic_to_mg(module)


@pytest.mark.parametrize("source,data,exception,prefix", [
    ("def f():\n    x=getchar()\n    return 65//x\nf()\nputchar(90)\n", b"\0", ZeroDivisionError, b""),
    ('def f():\n    return int(input("?"))\nf()\nputchar(90)\n', b"bad\n", ValueError, b"?"),
    ("x=getchar()\nprint('before',65//x)\nputchar(90)\n", b"\0", ZeroDivisionError, b""),
])
def test_checked_errors_precede_later_effects(source, data, exception, prefix):
    module = compile_python_to_semantic_ir(source)
    assert python_output(lower_semantic_to_python_ast(module), data, errors=(exception,))[0] == prefix
    reference = run_semantic(module, data)
    assert reference.output == prefix + b"error\n"
    assert b"Z" not in reference.output
    lower_semantic_to_mg(module)


def test_word_return_adapter_does_not_initialize_source_locals():
    module = compile_python_to_semantic_ir("def f():\n    while True:\n        return 65\nputchar(f())\n")
    source = lower_semantic_to_python(module)
    assert python_output(source)[0] == b"A"
    assert "return 0" in source  # Verified unreachable compatibility tail.
    lower_semantic_to_mg(module)


def test_uninitialized_local_is_not_silently_zero_initialized():
    from malbolge.compiler.ir.semantic import LoadOp

    value = LoadOp("x")
    module = ModuleOp([ProgramOp([], [FuncOp("entry", [], ["x"],
        [value, PutCharOp(value), ReturnOp()], returns="void")], entry="entry")])
    verify_semantic(module)
    with pytest.raises(NameError):
        python_output(lower_semantic_to_python_ast(module))
    with pytest.raises(SemanticLoweringError, match="not defined"):
        lower_semantic_to_mg(module)


def test_constructed_constant_zero_division_keeps_checked_runtime_semantics():
    left, right, suffix = ConstOp(65), ConstOp(0), ConstOp(90)
    quotient = BinaryOp("floordiv", left, right)
    module = ModuleOp([ProgramOp([], [FuncOp("entry", [], [],
        [left, right, suffix, quotient, PutCharOp(quotient), PutCharOp(suffix), ReturnOp()],
        returns="void")], entry="entry")])
    assert run_semantic(module).output == b"error\n"
    assert python_output(lower_semantic_to_python_ast(module), errors=(ZeroDivisionError,))[0] == b""
    lower_semantic_to_mg(module)


def test_invalid_semantic_ir_is_rejected_before_target_compilation(monkeypatch):
    from malbolge.compiler import py2mg

    monkeypatch.setattr(py2mg, "compile_python_to_mg", lambda source: pytest.fail("target backend ran"))
    with pytest.raises(SemanticIRError):
        lower_semantic_to_mg(ModuleOp([]))


def test_ir_is_authoritative_through_ast_mg_and_real_vm():
    literal = ConstOp(65)
    module = ModuleOp([ProgramOp([], [FuncOp("entry", [], [],
        [literal, PutCharOp(literal), ReturnOp()], returns="void")], entry="entry")])
    # Irrelevant metadata cannot act as an original-source fallback.
    module.attributes["original_source"] = StringAttr("putchar(90)")
    before_ast = lower_semantic_to_python(module)
    before_mg = lower_semantic_to_mg(module)
    literal.properties["value"] = IntAttr(66)
    restored = parse_semantic(print_semantic(module))
    after_ast = lower_semantic_to_python(restored)
    after_mg = lower_semantic_to_mg(restored)
    assert before_ast != after_ast
    assert before_mg != after_mg
    assert python_output(before_ast)[0] == b"A"
    assert python_output(after_ast)[0] == b"B"
    for mg, expected in [(before_mg, b"A"), (after_mg, b"B")]:
        image = assemble_mc_to_mb(translate_mg_to_mc(mg))
        result = run(image, max_steps=3_000_000, max_output=8)
        assert result.stop_reason == "terminated"
        assert result.output == expected


def test_reused_effectful_ssa_producer_executes_once_in_real_vm():
    read = GetCharOp()
    module = ModuleOp([ProgramOp([], [FuncOp("entry", [], [],
        [read, PutCharOp(read), PutCharOp(read), ReturnOp()], returns="void")], entry="entry")])
    generated = lower_semantic_to_python_ast(module)
    assert sum(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
               and node.func.id == "getchar" for node in ast.walk(generated)) == 1
    assert python_output(generated, b"AB") == (b"AA", 1)
    image = assemble_mc_to_mb(translate_mg_to_mc(lower_semantic_to_mg(module)))
    result = run(image, b"AB", max_steps=3_000_000, max_output=8)
    assert result.stop_reason == "terminated"
    assert result.output == b"AA"
    assert result.input_consumed == 1
