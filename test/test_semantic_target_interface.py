"""Independent contracts for the semantic IR / structured target-AST boundary.

These tests do not build Malbolge images. Ordinary-domain behavior is checked
by explicitly expanding TargetWhile for a Python oracle; backend entry, error
reachability and recursive-frame policies are checked through real MG codegen.
"""
import ast
from collections import Counter
from copy import deepcopy
from itertools import product
import sys

import pytest

if sys.version_info < (3, 10):
    pytest.skip("semantic target interface requires Python 3.10+", allow_module_level=True)
pytest.importorskip("xdsl")

from xdsl.dialects.builtin import ModuleOp

from malbolge.compiler import py2mg
from malbolge.compiler.ir.frontend import compile_python_to_semantic_ir
from malbolge.compiler.ir.interpreter import run_semantic
from malbolge.compiler.ir.lowering import (
    SemanticLoweringError, lower_semantic_to_mg, lower_semantic_to_target_ast,
)
from malbolge.compiler.ir.semantic import (
    BinaryOp, ConstOp, FuncOp, LoadOp, ProgramOp, PutCharOp, ReturnOp, verify_semantic,
)
from malbolge.compiler.mg2mc import translate_mg_to_mc
from malbolge.compiler.target_ast import TargetAST, TargetWhile, to_legacy_ast


OPTIONS = tuple(product((False, True), repeat=2))
OPTION_IDS = [f"skip-init={skip},structured-while={structured}" for skip, structured in OPTIONS]


def target(source):
    semantic = compile_python_to_semantic_ir(source)
    return semantic, lower_semantic_to_target_ast(semantic)


def generated_snapshot(tree):
    return (ast.dump(tree, include_attributes=True),
            tuple(sorted((name, tuple(sorted(locals_))) for name, locals_ in tree.generated_locals.items())))


def run_expanded(tree, data=b""):
    """Explicitly interpret the extension via its legacy expansion, never compile
    a raw TargetWhile whose extra field CPython would silently ignore.
    """
    expanded = to_legacy_ast(tree)
    assert isinstance(expanded, ast.Module)
    assert not any(isinstance(node, TargetWhile) for node in ast.walk(expanded))
    output = bytearray()
    position = 0

    def getchar():
        nonlocal position
        if position == len(data):
            return 59049
        char = data[position]
        position += 1
        return char

    def putchar(value):
        output.append(value % 256)

    def input_(prompt=""):
        nonlocal position
        output.extend(prompt.encode("latin-1"))
        end = data.find(b"\n", position)
        if end < 0:
            end = len(data)
        line = data[position:end].decode("latin-1")
        position = min(end + 1, len(data))
        return line

    def print_(*values, sep=" ", end="\n"):
        output.extend((sep.join(map(str, values)) + end).encode("latin-1"))

    status = "completed"
    try:
        exec(compile(ast.fix_missing_locations(expanded), "<expanded-target-oracle>", "exec"),
             {"getchar": getchar, "putchar": putchar, "input": input_, "print": print_})
    except (ValueError, ZeroDivisionError):
        output.extend(b"error\n")
        status = "runtime_error"
    return bytes(output), position, status


CASES = [
    ("global-snapshot", """x=65
def change():
    global x
    x=66
    return 1
print(x,change(),x)
""", b"", b"65 1 66\n"),
    ("keyword-capture", """counter=0
def mark(value):
    global counter
    counter+=1
    putchar(64+counter)
    return value
def pair(a,b):
    return a+b
putchar(pair(b=mark(1),a=mark(64)))
""", b"", b"ABA"),
    ("sibling-recursion", """def fib(n):
    if n<2:
        return n
    return fib(n-1)+fib(n-2)
print(fib(5),fib(4))
""", b"", b"5 3\n"),
    ("condition-input-continue", """count=0
while getchar():
    count+=1
    if count==1:
        continue
    putchar(64+count)
putchar(64+count)
""", b"AB\0Z", b"BB"),
    ("nested-break-continue", """for i in range(3):
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
""", b"", b"BCDBCF"),
    ("condition-error-call", """def condition():
    return 65//getchar()
def work():
    while condition():
        putchar(65)
work()
putchar(90)
""", b"\0", b"error\n"),
    ("condition-reader-error", """def work():
    while int(input("?")):
        putchar(65)
work()
putchar(90)
""", b"\n", b"?error\n"),
    ("condition-reader-repeat", """while int(input("?")):
    putchar(65)
    continue
putchar(90)
""", b"1\n0\n", b"?A?Z"),
    ("void-and-word-returns", """def emit(value):
    if value:
        putchar(value)
        return None
    return
def scalar():
    while True:
        return 66
emit(65)
emit(0)
putchar(scalar())
""", b"", b"AB"),
    ("user-prefix-lookalikes", """def mbirf0(mbira0):
    mbirt0=mbira0+1
    return mbirt0
putchar(mbirf0(64))
""", b"", b"A"),
]


@pytest.mark.parametrize("name,source,data,expected", CASES, ids=[item[0] for item in CASES])
def test_explicit_target_expansion_matches_independent_semantic_oracle(name, source, data, expected):
    module, tree = target(source)
    before = generated_snapshot(tree)
    reference = run_semantic(module, data)
    actual, consumed, status = run_expanded(tree, data)
    assert actual == reference.output == expected
    assert consumed == reference.input_consumed
    assert status == reference.status
    assert generated_snapshot(tree) == before


@pytest.mark.parametrize("skip_initialization,structured_while", OPTIONS, ids=OPTION_IDS)
@pytest.mark.parametrize("name,source,data,expected", CASES, ids=[item[0] for item in CASES])
def test_all_interface_ablation_combinations_compile_real_mg_without_mutating_ast(
        name, source, data, expected, skip_initialization, structured_while):
    _, tree = target(source)
    before = generated_snapshot(tree)
    text = py2mg.compile_target_ast_to_mg(
        tree, skip_generated_initialization=skip_initialization,
        structured_while=structured_while)
    assert "DEF MAIN" in text and "OUTPUT" in text
    assert generated_snapshot(tree) == before


def test_native_while_has_condition_prelude_and_only_source_loop_controls():
    _, tree = target("""x=0
while x<3:
    x+=1
    if x==1:
        continue
    if x==2:
        break
""")
    loop, = [node for node in ast.walk(tree) if isinstance(node, TargetWhile)]
    assert "condition_prelude" in loop._fields
    assert loop.condition_prelude
    assert any(isinstance(node, ast.Assign) for node in loop.condition_prelude)
    assert sum(isinstance(node, ast.Break) for node in ast.walk(tree)) == 1
    assert sum(isinstance(node, ast.Continue) for node in ast.walk(tree)) == 1
    assert not any(isinstance(node, (ast.Break, ast.Continue))
                   for statement in loop.condition_prelude for node in ast.walk(statement))


def test_generated_inventory_is_per_function_and_contains_only_real_locals():
    _, tree = target("""x=7
def f(value):
    local=value+x
    while local<10:
        local+=1
    return local
putchar(f(58))
""")
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert tree.generated_locals
    assert set(tree.generated_locals) <= functions.keys()
    for name, selected in tree.generated_locals.items():
        function = functions[name]
        parameters = {argument.arg for argument in function.args.args}
        globals_ = {name for node in ast.walk(function) if isinstance(node, ast.Global) for name in node.names}
        assignments = {node.id for node in ast.walk(function)
                       if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)}
        assert isinstance(selected, (set, frozenset))
        assert selected <= assignments - parameters - globals_


@pytest.mark.parametrize("skip_initialization,structured_while", OPTIONS, ids=OPTION_IDS)
def test_target_and_lowering_never_roundtrip_source_text(monkeypatch, skip_initialization, structured_while):
    module, tree = target("def f(value):\n    return value+1\nputchar(f(64))\n")

    def forbidden(*args, **kwargs):
        pytest.fail("structured target entry attempted source serialization or parsing")

    monkeypatch.setattr(ast, "unparse", forbidden)
    monkeypatch.setattr(ast, "parse", forbidden)
    monkeypatch.setattr(py2mg, "compile_python_to_mg", forbidden)
    expected = py2mg.compile_target_ast_to_mg(
        tree, skip_generated_initialization=skip_initialization, structured_while=structured_while)
    actual = lower_semantic_to_mg(
        module, skip_generated_initialization=skip_initialization, structured_while=structured_while)
    assert actual == expected


@pytest.mark.parametrize("skip_initialization,structured_while", OPTIONS, ids=OPTION_IDS)
def test_interface_output_is_accepted_by_existing_mg_translator(skip_initialization, structured_while):
    _, tree = target("x=0\nwhile x<2:\n    putchar(x+65)\n    x+=1\n")
    mg = py2mg.compile_target_ast_to_mg(
        tree, skip_generated_initialization=skip_initialization, structured_while=structured_while)
    mc = translate_mg_to_mc(mg)
    assert "ENTRY" in mc


@pytest.mark.parametrize("skip_initialization,structured_while", OPTIONS, ids=OPTION_IDS)
def test_uninitialized_semantic_local_is_rejected_before_target_generation(
        monkeypatch, skip_initialization, structured_while):
    read = LoadOp("x")
    module = ModuleOp([ProgramOp([], [FuncOp("entry", [], ["x"],
        [read, PutCharOp(read), ReturnOp()], returns="void")], entry="entry")])
    verify_semantic(module)

    def forbidden(*args, **kwargs):
        pytest.fail("uninitialized local reached target generation")

    monkeypatch.setattr(py2mg._DirectCompiler, "_generate_program", forbidden)
    with pytest.raises(SemanticLoweringError, match="not defined|before assignment"):
        lower_semantic_to_mg(module, skip_generated_initialization=skip_initialization,
                             structured_while=structured_while)


@pytest.mark.parametrize("skip_initialization,structured_while", OPTIONS, ids=OPTION_IDS)
def test_constructed_zero_divisor_still_compiles_as_checked_runtime_error(skip_initialization, structured_while):
    left, right = ConstOp(65), ConstOp(0)
    division = BinaryOp("floordiv", left, right)
    module = ModuleOp([ProgramOp([], [FuncOp("entry", [], [],
        [left, right, division, PutCharOp(division), ReturnOp()], returns="void")], entry="entry")])
    assert run_semantic(module).output == b"error\n"
    tree = lower_semantic_to_target_ast(module)
    assert run_expanded(tree) == (b"error\n", 0, "runtime_error")
    mg = py2mg.compile_target_ast_to_mg(
        tree, skip_generated_initialization=skip_initialization, structured_while=structured_while)
    assert "ZZDIV" in mg


def capture_backend_events(monkeypatch):
    """Observe real codegen without replacing its evaluator or generated blocks."""
    events = {"copies": [], "pushes": [], "pops": [], "compilers": []}
    original_body = py2mg._DirectCompiler._compile_body
    original_generate = py2mg._DirectCompiler._generate_function
    original_program = py2mg._DirectCompiler._generate_program
    original_copy = py2mg._DirectCompiler.copy
    original_push = py2mg._DirectCompiler.push_stack
    original_pop = py2mg._DirectCompiler.pop_stack

    def body(self, *args, **kwargs):
        previous = getattr(self, "_interface_test_phase", None)
        self._interface_test_phase = "body"
        try:
            return original_body(self, *args, **kwargs)
        finally:
            self._interface_test_phase = previous

    def generate(self, *args, **kwargs):
        previous = getattr(self, "_interface_test_phase", None)
        self._interface_test_phase = "generation"
        try:
            return original_generate(self, *args, **kwargs)
        finally:
            self._interface_test_phase = previous

    def program(self, *args, **kwargs):
        events["compilers"].append(self)
        return original_program(self, *args, **kwargs)

    def copy(self, block, source, destination):
        owner = self._func.name if self._func is not None else None
        events["copies"].append((owner, getattr(self, "_interface_test_phase", None), source.name, destination.name))
        return original_copy(self, block, source, destination)

    def push(self, block, source):
        events["pushes"].append((self._func.name, source.name))
        return original_push(self, block, source)

    def pop(self, block, destination):
        events["pops"].append((self._func.name, destination.name))
        return original_pop(self, block, destination)

    monkeypatch.setattr(py2mg._DirectCompiler, "_compile_body", body)
    monkeypatch.setattr(py2mg._DirectCompiler, "_generate_function", generate)
    monkeypatch.setattr(py2mg._DirectCompiler, "_generate_program", program)
    monkeypatch.setattr(py2mg._DirectCompiler, "copy", copy)
    monkeypatch.setattr(py2mg._DirectCompiler, "push_stack", push)
    monkeypatch.setattr(py2mg._DirectCompiler, "pop_stack", pop)
    return events


@pytest.mark.parametrize("structured_while", [False, True])
def test_skipping_generated_zero_copies_keeps_parameters_body_stores_and_recursive_frames(
        monkeypatch, structured_while):
    _, tree = target("""def recursive(n):
    value=0
    if n<1:
        return value
    return recursive(n-1)+recursive(n-1)+n
putchar(65+recursive(2))
""")
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    recursive = next(node for node in functions.values() if any(
        isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == node.name
        for call in ast.walk(node)))
    selected = {(name.upper(), "u_" + local) for name, locals_ in tree.generated_locals.items() for local in locals_}
    source_locals = {
        (function.name.upper(), "u_" + node.id)
        for function in functions.values() for node in ast.walk(function)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    }
    baseline = None
    for skip in (False, True):
        with monkeypatch.context() as context:
            events = capture_backend_events(context)
            py2mg.compile_target_ast_to_mg(
                tree, skip_generated_initialization=skip, structured_while=structured_while)
        compiler, = events["compilers"]
        assert compiler.functions[recursive.name.upper()].is_recursive
        protected = {(recursive.name.upper(), "u_" + local)
                     for local in tree.generated_locals[recursive.name]}
        assert protected <= set(events["pushes"])
        assert protected <= set(events["pops"])
        for parameter in recursive.args.args:
            assert any(owner == recursive.name.upper() and source.startswith("ARG") and destination == "u_" + parameter.arg
                       for owner, phase, source, destination in events["copies"])
        entry_zeroes = [(owner, destination) for owner, phase, source, destination in events["copies"]
                        if phase is None and source == "CONST_0" and (owner, destination) in selected]
        body_zeroes = Counter((owner, destination) for owner, phase, source, destination in events["copies"]
                              if phase == "body" and source == "CONST_0" and (owner, destination) in source_locals)
        if skip:
            assert not entry_zeroes
            assert body_zeroes == baseline
        else:
            assert entry_zeroes
            assert body_zeroes
            baseline = body_zeroes


def test_prefix_lookalikes_without_inventory_keep_initialization(monkeypatch):
    body = ast.parse("def mbirf0(value):\n    mbirt0=value+1\n    return mbirt0\nputchar(mbirf0(64))\n").body
    tree = TargetAST(body, generated_locals={})
    ast.fix_missing_locations(tree)
    events = capture_backend_events(monkeypatch)
    py2mg.compile_target_ast_to_mg(tree, skip_generated_initialization=True)
    assert any(owner == "MBIRF0" and phase is None and source == "CONST_0" and destination == "u_mbirt0"
               for owner, phase, source, destination in events["copies"])


@pytest.mark.parametrize("wrong", ["missing-function", "global", "parameter", "unknown-local"])
def test_forged_generated_inventory_is_rejected(wrong):
    _, original = target("x=65\ndef f(value):\n    local=value+1\n    return local\nputchar(f(x))\n")
    functions = [node for node in original.body if isinstance(node, ast.FunctionDef)]
    with_parameter = next(node for node in functions if node.args.args)
    inventory = dict(original.generated_locals)
    if wrong == "missing-function":
        inventory["nonexistent"] = frozenset({"x"})
    elif wrong == "parameter":
        inventory[with_parameter.name] = frozenset({with_parameter.args.args[0].arg})
    elif wrong == "unknown-local":
        inventory[with_parameter.name] = frozenset({"unassigned"})
    else:
        global_name = next(node.targets[0].id for node in original.body if isinstance(node, ast.Assign))
        inventory[with_parameter.name] = frozenset({global_name})
    forged = TargetAST(deepcopy(original.body), generated_locals=inventory)
    ast.fix_missing_locations(forged)
    with pytest.raises(py2mg.Py2MgError):
        py2mg.compile_target_ast_to_mg(forged, skip_generated_initialization=True)
