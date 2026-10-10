"""Base-toolchain contracts for structured target AST to the MG backend."""

import ast
from copy import deepcopy
import itertools
from pathlib import Path

import pytest

from malbolge.compiler import py2mg
from malbolge.compiler.py2mg import Py2MgError, compile_python_to_mg, compile_target_ast_to_mg
from malbolge.compiler.target_ast import (
    TargetAST, TargetASTError, TargetWhile, to_legacy_ast, validate_target_ast,
)


ROOT = Path(__file__).resolve().parents[1]
OPTIONS = list(itertools.product((False, True), repeat=2))


def target(source, generated_locals=None):
    parsed = ast.parse(source)
    return ast.fix_missing_locations(TargetAST(parsed.body, generated_locals=generated_locals))


def structured_loop(source, prelude, *, test="condition", generated_locals=None):
    tree = target(source, generated_locals)
    class Replace(ast.NodeTransformer):
        def visit_While(self, node):
            return ast.copy_location(TargetWhile(ast.parse(test, mode="eval").body,
                node.body, condition_prelude=ast.parse(prelude).body, orelse=node.orelse), node)
    return ast.fix_missing_locations(Replace().visit(tree))


def execute(tree, data=b""):
    incoming = iter(data)
    output = bytearray()
    reads = []
    def getchar():
        value = next(incoming, 59049)
        reads.append(value)
        return value
    namespace = {"putchar": lambda value: output.append(value % 256), "getchar": getchar}
    exec(compile(to_legacy_ast(tree), "<target-oracle>", "exec"), namespace)
    return bytes(output), reads, namespace


def test_target_fields_remain_visible_to_existing_ast_visitors():
    tree = structured_loop("def f():\n    while 1:\n        pass\nf()\n",
                           "condition=getchar()", generated_locals={"f": {"condition"}})
    loop = tree.body[0].body[0]
    assert isinstance(loop, ast.While)
    assert isinstance(loop, TargetWhile)
    assert "condition_prelude" in loop._fields
    assert any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
               and node.func.id == "getchar" for node in ast.walk(loop))
    clone = deepcopy(tree)
    assert clone.generated_locals == tree.generated_locals
    assert isinstance(clone.body[0].body[0], TargetWhile)


@pytest.mark.parametrize("skip,structured", OPTIONS)
def test_target_compilation_is_independent_of_source_roundtrips(monkeypatch, skip, structured):
    tree = structured_loop(
        "def f():\n    x=0\n    while 1:\n        putchar(65+x)\n        x+=1\nf()\n",
        "condition=x<3", generated_locals={"f": {"condition"}})
    before = ast.dump(tree, include_attributes=True)
    def forbidden(*args, **kwargs):
        pytest.fail("structured target compilation round-tripped through source text")
    monkeypatch.setattr(ast, "parse", forbidden)
    if hasattr(ast, "unparse"):
        monkeypatch.setattr(ast, "unparse", forbidden)
    mg = compile_target_ast_to_mg(tree, skip_generated_initialization=skip,
                                  structured_while=structured)
    assert "DEF F" in mg
    assert ast.dump(tree, include_attributes=True) == before
    assert tree.generated_locals == {"f": {"condition"}}


@pytest.mark.parametrize("skip,structured", OPTIONS)
@pytest.mark.parametrize("source,expected", [
    ("def f():\n    while 1:\n        putchar(condition)\nf()\n", b"AB"),
    ("def f():\n    while 1:\n        if condition == 65:\n            continue\n"
     "        putchar(condition)\nf()\n", b"B"),
    ("def f():\n    while 1:\n        putchar(condition)\n        break\nf()\n", b"A"),
    ("def f():\n    while 1:\n        if condition == 65:\n            return\n"
     "        putchar(condition)\nf()\n", b""),
])
def test_prelude_evaluation_control_and_four_backend_combinations(skip, structured, source, expected):
    tree = structured_loop(source, "condition=getchar()", generated_locals={"f": {"condition"}})
    actual, reads, _ = execute(tree, b"AB\0")
    assert actual == expected
    assert reads == ([65] if expected in (b"A", b"") else [65, 66, 0])
    mg = compile_target_ast_to_mg(tree, skip_generated_initialization=skip,
                                  structured_while=structured)
    assert "INPUT" in mg


def test_no_source_loop_control_does_not_allocate_flags_for_native_prelude():
    tree = structured_loop("def f():\n    while 1:\n        putchar(condition)\nf()\n",
                           "condition=getchar()", generated_locals={"f": {"condition"}})
    legacy = compile_target_ast_to_mg(tree, structured_while=False)
    native = compile_target_ast_to_mg(tree, structured_while=True)
    assert "VAR BRK0" in legacy and "VAR SKP0" in legacy
    assert "VAR BRK0" not in native and "VAR SKP0" not in native


def test_source_break_continue_still_allocate_flags_in_native_loop():
    tree = structured_loop(
        "def f():\n    while 1:\n        if condition == 65:\n            continue\n"
        "        putchar(condition)\n        if condition == 66:\n            break\nf()\n",
        "condition=getchar()", generated_locals={"f": {"condition"}})
    mg = compile_target_ast_to_mg(tree)
    assert "VAR BRK0" in mg and "VAR SKP0" in mg
    assert execute(tree, b"ABC\0")[:2] == (b"B", [65, 66])


def test_false_test_still_runs_prelude_once_but_skips_body():
    tree = structured_loop("def f():\n    while 1:\n        putchar(88)\nf()\n",
                           "condition=getchar()\nputchar(condition)", test="0",
                           generated_locals={"f": {"condition"}})
    assert execute(tree, b"AB")[:2] == (b"A", [65])
    native = compile_target_ast_to_mg(tree)
    assert native.count("INPUT") == 1
    assert "VAR BRK0" not in native


@pytest.mark.parametrize("skip,structured", OPTIONS)
def test_generated_local_definite_assignment_is_required_for_every_option(skip, structured):
    tree = target("slot=65\ndef f():\n    putchar(slot)\n    slot=66\nf()\n", {"f": {"slot"}})
    with pytest.raises(Py2MgError, match="before assignment") as caught:
        compile_target_ast_to_mg(tree, skip_generated_initialization=skip, structured_while=structured)
    assert caught.value.lineno == 3


@pytest.mark.parametrize("skip,structured", OPTIONS)
def test_prelude_assignments_are_checked_before_test_and_body(skip, structured):
    valid = structured_loop("def f():\n    while 1:\n        putchar(condition)\nf()\n",
                            "condition=getchar()", generated_locals={"f": {"condition"}})
    assert compile_target_ast_to_mg(valid, skip_generated_initialization=skip, structured_while=structured)
    invalid = structured_loop("def f():\n    while 1:\n        putchar(condition)\nf()\n",
                              "if getchar():\n    condition=1",
                              generated_locals={"f": {"condition"}})
    with pytest.raises(Py2MgError, match="before assignment"):
        compile_target_ast_to_mg(invalid, skip_generated_initialization=skip, structured_while=structured)


@pytest.mark.parametrize("metadata,phrase", [
    ({"missing": {"tmp"}}, "undefined function"),
    ({"f": {"missing"}}, "not assigned"),
    ({"f": {"value"}}, "parameter"),
    ({"f": {"shared"}}, "global"),
    ({"f": "tmp"}, "collection"),
    ({"f": {1}}, "collection"),
    ([], "must map"),
])
def test_invalid_generated_local_metadata_is_rejected(metadata, phrase):
    tree = target("shared=0\ndef f(value):\n    global shared\n    tmp=value\n    shared=tmp\nf(1)\n", metadata)
    with pytest.raises(Py2MgError, match=phrase):
        compile_target_ast_to_mg(tree)


@pytest.mark.parametrize("prelude", ["break", "continue", "return", "global x",
                                      "while 0:\n    pass", "def local():\n    pass"])
def test_control_transfer_or_scope_changes_cannot_hide_in_prelude(prelude):
    tree = structured_loop("def f():\n    while 1:\n        pass\nf()\n", prelude, test="0")
    with pytest.raises(Py2MgError, match="condition prelude statement"):
        compile_target_ast_to_mg(tree)


def test_plain_ast_or_text_does_not_acquire_generated_privileges():
    for invalid in (ast.parse("x=1"), "x=1", None):
        with pytest.raises(Py2MgError, match="requires a TargetAST"):
            compile_target_ast_to_mg(invalid)


def test_metadata_is_explicit_and_entry_zero_skip_does_not_touch_parameters(monkeypatch):
    source = "def f(value):\n    ordinary=1\n    mbirt0=value+ordinary\n    return mbirt0\nputchar(f(65))\n"
    tree = target(source, {"f": {"mbirt0"}})
    copies = []
    original = py2mg._DirectCompiler.copy
    def copy(self, block, first, second):
        if self._func is not None and self._func.name == "F":
            copies.append((first.name, second.name))
        return original(self, block, first, second)
    monkeypatch.setattr(py2mg._DirectCompiler, "copy", copy)
    compile_target_ast_to_mg(tree, skip_generated_initialization=False)
    initialized = list(copies)
    copies.clear()
    compile_target_ast_to_mg(tree, skip_generated_initialization=True)
    skipped = list(copies)
    omitted = [pair for pair in initialized if pair not in skipped]
    assert omitted == [("CONST_0", "u_mbirt0")]
    assert ("CONST_0", "u_ordinary") in skipped
    assert ("CONST_0", "u_value") in skipped
    assert any(first.startswith("ARG") and second == "u_value" for first, second in skipped)
    # A generated-looking name has no privilege when the explicit inventory is empty.
    copies.clear()
    compile_target_ast_to_mg(target(source), skip_generated_initialization=True)
    assert ("CONST_0", "u_mbirt0") in copies


def test_generated_locals_keep_recursive_frame_push_and_pop(monkeypatch):
    tree = target("def f(n):\n    if n == 0:\n        return 0\n    saved=f(n-1)\n    return saved+1\n"
                  "putchar(f(2))\n", {"f": {"saved"}})
    events = []
    for method in ("push_stack", "pop_stack"):
        original = getattr(py2mg._DirectCompiler, method)
        def trace(self, block, variable, operation=method, original=original):
            if self._func is not None and self._func.name == "F":
                events.append((operation, variable.name, variable.is_temporary))
            return original(self, block, variable)
        monkeypatch.setattr(py2mg._DirectCompiler, method, trace)
    mg = compile_target_ast_to_mg(tree, skip_generated_initialization=True)
    assert "VAR u_saved" in mg
    assert ("push_stack", "u_saved", False) in events
    assert ("pop_stack", "u_saved", False) in events


def test_error_reachability_visits_condition_prelude_calls():
    tree = structured_loop(
        "def read():\n    return int(input())\ndef f():\n    while 1:\n        putchar(condition)\nf()\n",
        "condition=read()", generated_locals={"f": {"condition"}})
    native = compile_target_ast_to_mg(tree)
    assert "PROTO ZZREADINT" in native
    assert "VAR u_zzioerror" in native
    from malbolge.compiler.python_normalize import io_reachable_functions
    assert io_reachable_functions(tree) >= {"read", "f"}


def test_standard_loop_empty_prelude_has_identical_mg():
    source = "def f():\n    x=0\n    while x<3:\n        x+=1\n    return x\nputchar(f())\n"
    tree = target(source)
    loop = tree.body[0].body[1]
    tree.body[0].body[1] = ast.copy_location(TargetWhile(loop.test, loop.body), loop)
    assert compile_target_ast_to_mg(tree, arithmetic_optimizations=True,
                                    skip_generated_initialization=False) == compile_python_to_mg(source)


@pytest.mark.parametrize("path", sorted((ROOT / "benchmarks/programs").glob("*.py")), ids=lambda path: path.stem)
def test_plain_target_ast_with_zero_exemptions_matches_legacy_source_mg(path):
    source = path.read_text()
    assert compile_target_ast_to_mg(target(source), arithmetic_optimizations=True,
                                    skip_generated_initialization=False) == compile_python_to_mg(source)


@pytest.mark.parametrize("option", ["skip_generated_initialization", "structured_while", "arithmetic_optimizations"])
def test_representation_switches_require_actual_bools(option):
    with pytest.raises(ValueError, match="must be a bool"):
        compile_target_ast_to_mg(target("putchar(65)"), **{option: 1})
