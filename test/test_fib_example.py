"""Runtime-input regression cases for the ordinary-Python Fibonacci example."""

import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from malbolge.compiler import (
    compile_c_to_mg, compile_python_to_c, compile_python_to_mg,
    translate_mg_to_mc,
)
from test.test_py2mg_e2e import (
    C_INTERP, HAVE_C_INTERP, HAVE_PIPELINE, _build_via_ref,
)


SOURCE = (Path(__file__).resolve().parents[1] / "examples" / "fib.py").read_text()
VALID_CASES = (
    (b"0\n", "0\n"), (b"1\n", "1\n"), (b"2\n", "1\n"),
    (b"6\n", "8\n"), (b"7\n", "13\n"), (b"10\n", "55\n"),
    (b"12\n", "144\n"), (b"0007\n", "13\n"), (b"7", "13\n"),
    (b"7\r\n", "13\n"), (b" +7 \t\n", "13\n"), (b"48\n", "error\n"),
)
INVALID_CASES = tuple((value, "error\n") for value in (
    b"", b"\n", b"-1\n", b"1x\n", b"999999999999999999999\n",
))


class FibExample(unittest.TestCase):
    def test_runs_as_ordinary_python(self):
        for stdin, expected in VALID_CASES:
            with self.subTest(stdin=stdin):
                out = io.StringIO()
                with patch("sys.stdin", io.StringIO(stdin.decode("ascii"))), \
                        contextlib.redirect_stdout(out):
                    exec(compile(SOURCE, "examples/fib.py", "exec"), {})
                self.assertEqual(out.getvalue(), expected)

    def test_both_frontends_accept_example(self):
        for backend in ("c", "direct"):
            with self.subTest(backend=backend):
                mg = (compile_python_to_mg(SOURCE) if backend == "direct"
                      else compile_c_to_mg(compile_python_to_c(SOURCE)))
                self.assertTrue(translate_mg_to_mc(mg))


@unittest.skipUnless(
    os.environ.get("MALBOLGE_SLOW_TESTS") == "1" and HAVE_PIPELINE and HAVE_C_INTERP,
    "multi-MB builds: set MALBOLGE_SLOW_TESTS=1 and build the reference tools",
)
class FibExampleCompiled(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workdir = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.workdir.cleanup)
        cls.images = {}
        for backend in ("c", "direct"):
            mg = (compile_python_to_mg(SOURCE) if backend == "direct"
                  else compile_c_to_mg(compile_python_to_c(SOURCE)))
            image = os.path.join(cls.workdir.name, backend + ".mb")
            _build_via_ref(mg, image)
            cls.images[backend] = image

    def test_runtime_inputs_on_same_images(self):
        for backend, image in self.images.items():
            for stdin, expected in VALID_CASES + INVALID_CASES:
                with self.subTest(backend=backend, stdin=stdin):
                    proc = subprocess.run(
                        [C_INTERP, image], input=stdin, capture_output=True,
                        timeout=600,
                    )
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    self.assertEqual(proc.stdout, expected.encode("ascii"))


if __name__ == "__main__":
    unittest.main()
