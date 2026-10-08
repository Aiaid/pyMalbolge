"""Portable differential and determinism canaries for the Python subset."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from malbolge import run20
from malbolge.compiler import compile_python_to_c, compile_c_to_mg, compile_python_to_mg
from malbolge.compiler.mc2mb import iter_mc_to_mb
from malbolge.compiler.mg2mc import translate_mg_to_mc


FIXTURE = Path(__file__).parent / 'fixtures/qos/direct/semantics.py'


class DeterminismCanary(unittest.TestCase):
    def test_mc_is_stable_across_hash_seeds(self):
        code = """\
import hashlib,json
from malbolge.compiler import compile_python_to_c,compile_c_to_mg,compile_python_to_mg,translate_mg_to_mc
source = 'x=7\\ndef add(a,b):\\n    return a+b\\nprint(f"{add(b=3,a=x)}")\\n'
print(json.dumps({backend: hashlib.sha256(translate_mg_to_mc(compile_python_to_mg(source) if backend=='direct' else compile_c_to_mg(compile_python_to_c(source))).encode()).hexdigest() for backend in ('c','direct')}))
"""
        results = []
        for seed in ('0', '1', '7', 'random'):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            result = subprocess.run([sys.executable, '-c', code], env=env,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            results.append(json.loads(result.stdout))
        for backend in ('c', 'direct'):
            self.assertEqual(len({result[backend] for result in results}), 1)


@unittest.skipUnless(os.environ.get('MALBOLGE_QOS_E2E') == '1',
                     'set MALBOLGE_QOS_E2E=1 for both-backend VM execution')
class PortableSemanticDifferential(unittest.TestCase):
    def test_cpython_both_compilers_and_project_vm_agree(self):
        source = FIXTURE.read_text()
        output = io.StringIO()
        exec(source, {'putchar': lambda value: output.write(chr(value))})
        expected = output.getvalue().encode('ascii')
        self.assertEqual(expected, b':::ABC1ABC')
        for backend in ('direct', 'c'):
            with self.subTest(backend=backend):
                mg = (compile_python_to_mg(source) if backend == 'direct'
                      else compile_c_to_mg(compile_python_to_c(source)))
                image = b''.join(iter_mc_to_mb(translate_mg_to_mc(mg)))
                result = run20(image, max_steps=500000000, max_output=64)
                self.assertEqual(result.output, expected)
                self.assertEqual(result.stop_reason, 'terminated', result.to_dict())
                self.assertEqual(result.input_consumed, 0)


if __name__ == '__main__':
    unittest.main()
