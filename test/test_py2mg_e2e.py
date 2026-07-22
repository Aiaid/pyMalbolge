"""Dual-backend end-to-end equivalence tests for the direct .mg backend.

Every case is compiled to a runnable Malbolge20 program **twice** -- through
the default ``c`` backend (py2c + c2mg) and through the ``direct`` backend
(py2mg) -- and both programs are run.  The two observed outputs must be
byte-for-byte identical *and* equal to the expected bytes.  (The ``.mb`` bytes
themselves are not required to match; only the program behaviour.)

Like ``test_py2c_e2e.py`` this is gated on the reference toolchain under
``ref/`` because each program is multi-megabyte: with the C/C++ stages built,
both variants assemble in seconds and run on the fast C reference interpreter;
without them the pure-Python ``mc2mb`` (~40s/MB) makes the larger cases
impractical, so only the tiny ones run.  Stage equivalence of mg2mc/mc2mb is
separately covered byte-for-byte by the conformance suites.
"""

import os
import subprocess
import sys
import tempfile
import unittest

from malbolge.compiler import compile_python_to_mb

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TERNARY = os.path.join(REPO_ROOT, "ref", "nagoya-ternary", "parser")
INIT = os.path.join(REPO_ROOT, "ref", "nagoya-lowass", "init", "init")
PARSE_MC2 = os.path.join(REPO_ROOT, "ref", "nagoya-lowass", "parse_mc2.pl")
MG2MB = os.path.join(REPO_ROOT, "scripts", "mg2mb.sh")
C_INTERP = os.path.join(
    REPO_ROOT, "ref", "nagoya-malbolge20-interpreter", "malbolge20")

HAVE_PIPELINE = (
    os.access(TERNARY, os.X_OK)
    and os.access(INIT, os.X_OK)
    and os.path.isfile(PARSE_MC2)
    and os.access(MG2MB, os.R_OK)
)
HAVE_C_INTERP = os.access(C_INTERP, os.X_OK)

SUBPROCESS_TIMEOUT = 600

# Cases mirror test_py2c_e2e.py.  (source, stdin, expected_stdout).
SMALL_CASES = {
    "putchar_hi": ("putchar(72)\nputchar(105)\n", b"", b"Hi"),
    "echo_getchar": ("c = getchar()\nputchar(c)\n", b"Q", b"Q"),
    "multiply_folded": ("putchar(9 * 7 + 2)\n", b"", b"A"),
}

# Larger cases: multi-MB programs, only when the reference toolchain is built.
BIG_CASES = {
    "while_countdown": (
        "x = 3\nwhile x > 0:\n    putchar(64 + x)\n    x -= 1\n", b"", b"CBA"),
    "if_else": (
        "x = 5\nif x < 3:\n    putchar(65)\nelse:\n    putchar(90)\n", b"", b"Z"),
    "for_range": ("for i in range(3):\n    putchar(65 + i)\n", b"", b"ABC"),
    "recursion_single": (
        "def s(n):\n    if n == 0:\n        return 0\n"
        "    return n + s(n - 1)\nputchar(s(5) + 50)\n", b"", b"A"),
    # The classic double-recursion: two sibling recursive CALLs in one
    # expression.  The direct backend keeps the intermediate held across the
    # second call alive via cross-call temp protection -- the A2 bug is fixed
    # at the mechanism level, without a three-address rewrite.
    "recursion_fib": (
        "def fib(n):\n    if n < 2:\n        return n\n"
        "    return fib(n - 1) + fib(n - 2)\nputchar(fib(5) + 60)\n", b"", b"A"),
    "mutual_recursion": (
        "def iseven(n):\n    if n == 0:\n        return 1\n"
        "    return isodd(n - 1)\n"
        "def isodd(n):\n    if n == 0:\n        return 0\n"
        "    return iseven(n - 1)\nputchar(iseven(4) + 64)\n", b"", b"A"),
}


def _build_via_ref(mg_text, mb_path):
    with tempfile.NamedTemporaryFile("w", suffix=".mg", delete=False) as f:
        f.write(mg_text)
        mg_path = f.name
    try:
        proc = subprocess.run(
            ["bash", MG2MB, "-s", "1", mg_path, mb_path],
            stderr=subprocess.PIPE, text=True, timeout=SUBPROCESS_TIMEOUT)
        if proc.returncode != 0:
            raise AssertionError(".mg -> .mb pipeline failed:\n" + proc.stderr)
    finally:
        os.unlink(mg_path)


class DualBackendEquivalence(unittest.TestCase):
    def _build(self, source, backend, workdir):
        mb = os.path.join(workdir, backend + ".mb")
        if HAVE_PIPELINE:
            from malbolge.compiler import (
                compile_python_to_mg, compile_python_to_c, compile_c_to_mg)
            mg = (compile_python_to_mg(source) if backend == "direct"
                  else compile_c_to_mg(compile_python_to_c(source)))
            _build_via_ref(mg, mb)
        else:
            with open(mb, "w") as f:
                f.write(compile_python_to_mb(source, backend=backend))
        return mb

    def _run(self, mb, stdin):
        exe = ([C_INTERP, mb] if HAVE_C_INTERP
               else [sys.executable, "-m", "malbolge",
                     "--variant=malbolge20", mb])
        return subprocess.run(
            exe, input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=SUBPROCESS_TIMEOUT).stdout

    def assert_equivalent(self, source, stdin, expected):
        with tempfile.TemporaryDirectory() as d:
            mb_c = self._build(source, "c", d)
            mb_d = self._build(source, "direct", d)
            out_c = self._run(mb_c, stdin)
            out_d = self._run(mb_d, stdin)
        self.assertEqual(
            out_d, out_c,
            "direct and c backends disagree: direct={!r} c={!r}".format(
                out_d, out_c))
        self.assertEqual(
            out_d, expected,
            "output {!r} != expected {!r}".format(out_d, expected))

    # -- small cases: always run (tiny programs, pure-Python path is fine) --
    def test_putchar_hi(self):
        self.assert_equivalent(*SMALL_CASES["putchar_hi"])

    def test_echo_getchar(self):
        self.assert_equivalent(*SMALL_CASES["echo_getchar"])

    def test_multiply_folded(self):
        self.assert_equivalent(*SMALL_CASES["multiply_folded"])


def _make_big_test(name):
    def test(self):
        self.assert_equivalent(*BIG_CASES[name])
    return test


for _name in BIG_CASES:
    setattr(
        DualBackendEquivalence, "test_" + _name,
        unittest.skipUnless(
            HAVE_PIPELINE,
            "multi-MB program; build ref/ tools for the fast path")(
                _make_big_test(_name)))


if __name__ == "__main__":
    unittest.main()
