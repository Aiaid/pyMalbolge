"""Shared source-analysis ownership and base-toolchain regression contracts."""

import ast
import inspect
from pathlib import Path
import subprocess
import sys

import pytest

from malbolge.compiler import Py2MgError
from malbolge.compiler.py2mg import _DirectCompiler, compile_python_to_mg
from malbolge.compiler.source_analysis import MOD, SourceAnalysis
from malbolge.compiler.target_ast import TargetWhile


METHODS = (
    '_check_name', '_collect_assigned', '_global_decls_in',
    '_check_definite_assignment', '_da_stmts', '_da_stmt', '_da_terminates',
    '_da_reads', '_da_name', '_static_bool', '_range_args', '_signed_literal',
    '_literal_range_nonempty', '_fold', '_fold_ord',
)


class Analysis(SourceAnalysis):
    def __init__(self, source=''):
        self.source = source
        self._fdefs = {}

    def err(self, message, node):
        return Py2MgError(message, node, self.source)


def test_direct_inherits_shared_checks_without_copies():
    for name in METHODS:
        assert name not in _DirectCompiler.__dict__
        assert getattr(_DirectCompiler, name) is getattr(SourceAnalysis, name)
    assert '__init__' not in SourceAnalysis.__dict__


def test_shared_module_loads_without_compiler_or_optional_dependencies():
    # Bypass compiler.__init__'s public exports to inspect this module's own
    # dependency graph, rather than changing the package's established API.
    code = '''
import importlib, pathlib, sys, types
import malbolge
package = types.ModuleType('malbolge.compiler')
package.__path__ = [str(pathlib.Path(malbolge.__file__).parent / 'compiler')]
sys.modules[package.__name__] = package
importlib.import_module('malbolge.compiler.source_analysis')
assert not any(n.startswith('xdsl') for n in sys.modules)
assert not any('malbolge.compiler.' + n in sys.modules
               for n in ('py2mg', 'c2mg', 'py2c', 'ir'))
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_public_error_identity_and_rendering():
    from malbolge.compiler.py2mg import Py2MgError as direct_error
    from malbolge.compiler.source_analysis import Py2MgError as shared_error

    assert Py2MgError is direct_error is shared_error
    assert Py2MgError.__module__ == 'malbolge.compiler.py2mg'
    source = 'if getchar():\n    x = 1\nprint(x)\n'
    with pytest.raises(Py2MgError) as caught:
        compile_python_to_mg(source)
    error = caught.value
    assert (error.message, error.lineno, error.col, error.snippet) == (
        "name 'x' may be used before assignment", 3, 6, 'print(x)')
    assert str(error) == (
        "compile error (line 3): name 'x' may be used before assignment\n    print(x)")


@pytest.mark.parametrize('op,a,b,expected', [
    (ast.Add(), MOD - 1, 2, 1), (ast.Sub(), 0, 1, MOD - 1),
    (ast.Mult(), MOD - 1, 2, MOD - 2), (ast.FloorDiv(), 7, 2, 3),
    (ast.Mod(), 7, 2, 1),
])
def test_ring_folding(op, a, b, expected):
    assert Analysis()._fold(op, a, b, ast.Constant(value=0)) == expected


def test_lazy_reads_and_descending_range_binding():
    source = ('print(0 and missing)\nprint(7 or missing)\n'
              'print(1 if 1 else missing)\n'
              'for i in range(2, -1, -1):\n    x = i\nprint(x)\n')
    tree = ast.parse(source)
    analysis = Analysis(source)
    analysis._check_definite_assignment(tree.body, set(), {'i', 'x'})
    assert analysis._static_bool(ast.Constant(value=MOD)) is False
    assert analysis._fold_ord(ast.parse("ord('A')", mode='eval').body) == 65


@pytest.mark.parametrize('condition,body,expected', [
    (False, 'unused = missing', {'ready'}),
    (True, 'value = ready\nbreak', {'ready', 'value'}),
])
def test_target_while_prelude_and_break_bindings(condition, body, expected):
    loop = TargetWhile(ast.Constant(value=condition), ast.parse(body).body,
                       condition_prelude=ast.parse('ready = 1').body)
    analysis = Analysis()
    analysis._da_exit_stack = []
    assert analysis._da_stmt(loop, set(), set(), {'ready', 'value'}) == expected
    assert analysis._da_exit_stack == []


def test_semantic_checks_have_shared_ownership():
    pytest.importorskip('xdsl')
    from malbolge.compiler.ir.frontend import _Analysis, SemanticFrontendError

    assert issubclass(SemanticFrontendError, Py2MgError)
    for name in METHODS:
        assert name not in _Analysis.__dict__
        assert getattr(_Analysis, name) is getattr(SourceAnalysis, name)
    frontend = Path(inspect.getfile(_Analysis)).read_text()
    assert 'from ..py2mg import' not in frontend
    assert '_DirectCompiler' not in frontend
