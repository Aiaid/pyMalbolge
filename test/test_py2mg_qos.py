"""Semantic regressions for the direct Python frontend.

Native checks are explicit opt-ins because they assemble actual Malbolge20
images. Fast tests still validate fixtures against CPython and downstream IR.
"""
import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from malbolge.compiler import compile_python_to_mg, translate_mg_to_mc
from malbolge.compiler.py2mg import Py2MgError

FIXTURES = Path(__file__).parent / 'fixtures' / 'qos' / 'direct'
CASES = {
    'semantics': (':::ABC1ABC', b''),
    'ranges': ('ABCDE|ABC|', b''),
    'loop_final': ('2', b''),
}
ADVANCED_CASES = {
    'conveniences': [(b'', 'T2:1|37|12\n')],
    'input_chain': [(b'7\n', 'X7Z'), (b'bad\n', 'error\n'),
                    (b'3486784400\n', 'X/Z'), (b'3486784401\n', 'error\n')],
    'arithmetic_chain': [(b'D2', '3Z'), (b'M2', '1Z'),
                         (b'D0', 'error\n'), (b'M0', 'error\n')],
    'boolean_values': [(b'', '5077TAB')],
    'range_edges': [(b'', 'A|3210|:|9')],
    'small_multiply': [(b'', '012378@T0TEEB')],
}


class DirectSemanticContracts(unittest.TestCase):
    def test_audit_fixtures_match_python_and_compile(self):
        for name, (expected, _) in CASES.items():
            with self.subTest(name=name):
                source = (FIXTURES / (name + '.py')).read_text()
                output = io.StringIO()
                exec(source, {'putchar': lambda value: output.write(chr(value))})
                self.assertEqual(output.getvalue(), expected)
                self.assertTrue(translate_mg_to_mc(compile_python_to_mg(source)))

    def test_short_circuit_constants_preserve_operand_values(self):
        for expression, expected in [('5 or 7', 5), ('0 and 7', 0),
                                     ('0 or 7', 7), ('5 and 7', 7)]:
            with self.subTest(expression=expression):
                mg = compile_python_to_mg('x = ' + expression + '\nputchar(x)\n')
                self.assertIn('VAR CONST_{}={}'.format(expected, expected), mg)

    def test_advanced_fixtures_match_python_and_compile(self):
        for name, runs in ADVANCED_CASES.items():
            with self.subTest(name=name):
                source = (FIXTURES / (name + '.py')).read_text()
                stdin, expected = runs[0]
                data = iter(stdin)
                output = io.StringIO()
                namespace = {
                    'putchar': lambda value: output.write(chr(value % 256)),
                    'getchar': lambda: next(data, 59049),
                    'input': lambda: stdin.decode().rstrip('\r\n'),
                }
                with contextlib.redirect_stdout(output):
                    exec(source, namespace)
                # CPython integers do not wrap. The fixture's final multiply
                # deliberately checks the documented target word-ring wrap.
                python_expected = ('012378@T0TEEA' if name == 'small_multiply'
                                   else expected)
                self.assertEqual(output.getvalue(), python_expected)
                self.assertTrue(translate_mg_to_mc(compile_python_to_mg(source)))

    def test_proven_bindings_are_accepted(self):
        sources = [
            'if 1:\n    x=65\nputchar(x)\n',
            'for i in range(1):\n    x=65\nputchar(x)\n',
            'for i in range(1):\n    x=65\n    break\nputchar(x)\n',
            'while 1:\n    x=65\n    break\nputchar(x)\n',
            'x=0 and never_read\nputchar(x)\n',
            'while 0:\n    putchar(never_read)\nputchar(65)\n',
        ]
        for source in sources:
            with self.subTest(source=source):
                self.assertTrue(compile_python_to_mg(source))

    def test_unbound_exit_paths_and_python_syntax_are_rejected(self):
        sources = [
            'if 0:\n    x=65\nputchar(x)\n',
            'for i in range(0):\n    x=65\nputchar(x)\n',
            'for i in range(3486784401):\n    x=65\nputchar(x)\n',
            'for i in range(1):\n    break\n    x=65\nputchar(x)\n',
            'flag=getchar()\nfor i in range(1):\n    if flag:\n        break\n    x=65\nputchar(x)\n',
            'x=65\ndef f():\n    putchar(x)\n    global x\nf()\n',
            'def f():\n    for i in range(3486784401):\n        return 65\nputchar(f())\n',
        ]
        for source in sources:
            with self.subTest(source=source):
                self.assertRaises(Py2MgError, compile_python_to_mg, source)

    def test_unsupported_tuple_points_at_assignment(self):
        with self.assertRaises(Py2MgError) as caught:
            compile_python_to_mg('a, b = value\nputchar(a)\n')
        self.assertEqual(caught.exception.lineno, 1)
        self.assertIn('tuple assignment', str(caught.exception))

    def test_small_constant_multiply_avoids_generic_helper(self):
        for factor in (0, 1, 2, 3, 7, 8, 16):
            for expression in ('x * {}'.format(factor), '{} * x'.format(factor)):
                with self.subTest(expression=expression):
                    mg = compile_python_to_mg('x=7\ny=' + expression + '\nputchar(y)\n')
                    self.assertNotIn('DEF ZZMUL', mg)

    def test_p2_forms_are_accepted(self):
        sources = [
            'a,b=1,2\na,b=b,a\nprint(a,b)\n',
            'def pair(a,b):\n    return a+b\nprint(pair(b=2,a=1))\n',
            'x=5\nprint(f"n={x}")\n',
            'for i in range(3,-1,-1):\n    putchar(48+i)\n',
            'def read():\n    return int(input())\nputchar(read())\n',
            'def emit():\n    return None\nemit()\n',
        ]
        for source in sources:
            with self.subTest(source=source):
                self.assertTrue(translate_mg_to_mc(compile_python_to_mg(source)))


@unittest.skipUnless(os.environ.get('MALBOLGE_SLOW_TESTS') == '1',
                     'set MALBOLGE_SLOW_TESTS=1 for native compiled regressions')
class DirectNativeAuditRegressions(unittest.TestCase):
    def test_audit_cases(self):
        from malbolge.compiler import compile_python_to_mb
        executable = (Path(__file__).resolve().parents[1] / 'ref' /
                      'nagoya-malbolge20-interpreter' / 'malbolge20')
        if not executable.exists():
            self.skipTest('build the reference Malbolge20 interpreter')
        with tempfile.TemporaryDirectory() as directory:
            all_cases = {name: [(stdin, expected)]
                         for name, (expected, stdin) in CASES.items()}
            all_cases.update(ADVANCED_CASES)
            for name, runs in all_cases.items():
                with self.subTest(name=name):
                    image = Path(directory) / (name + '.mb')
                    image.write_text(compile_python_to_mb(
                        (FIXTURES / (name + '.py')).read_text(), backend='direct'))
                    for stdin, expected in runs:
                        run = subprocess.run([str(executable), str(image)], input=stdin,
                                             capture_output=True, timeout=120)
                        self.assertEqual(run.returncode, 0, run.stderr)
                        self.assertEqual(run.stderr, b'')
                        self.assertEqual(run.stdout, expected.encode())
