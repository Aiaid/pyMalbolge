"""
End-to-end tests for the Python -> Malbolge20 compiler front-end.

Two tiers, each skipped unless the (gitignored, MIT-licensed) Nagoya
reference toolchain under ref/ is built:

* ParserAcceptance -- transpile Python and confirm the generated C is
  accepted by the reference high-level parser (ref/nagoya-highlevel/parser).
  Fast; needs only that one tool.

* EndToEnd -- transpile Python all the way to a Malbolge20 program with the
  pure-Python pipeline (malbolge.compiler.compile_python_to_mb; no external
  tools needed) and run it, asserting the observed output. Slow (each case
  builds and runs a multi-megabyte program). Runs on the C reference
  interpreter when built (much faster), else falls back to pyMalbolge.

See test/fixtures/nagoya/README.md for reference-toolchain provenance.
"""

import os
import subprocess
import sys
import tempfile
import unittest

from malbolge.compiler import compile_python_to_c, compile_python_to_mb

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HL_PARSER = os.path.join(REPO_ROOT, "ref", "nagoya-highlevel", "parser")
TERNARY = os.path.join(REPO_ROOT, "ref", "nagoya-ternary", "parser")
INIT = os.path.join(REPO_ROOT, "ref", "nagoya-lowass", "init", "init")
PARSE_MC2 = os.path.join(REPO_ROOT, "ref", "nagoya-lowass", "parse_mc2.pl")
MG2MB = os.path.join(REPO_ROOT, "scripts", "mg2mb.sh")
# The C reference interpreter is 15-100x faster than pyMalbolge, so end-to-end
# assertions run against it when available; a couple of cases are additionally
# cross-checked on pyMalbolge itself.
C_INTERP = os.path.join(
    REPO_ROOT, "ref", "nagoya-malbolge20-interpreter", "malbolge20")

HAVE_HL = os.access(HL_PARSER, os.X_OK)
HAVE_PIPELINE = (
    HAVE_HL
    and os.access(TERNARY, os.X_OK)
    and os.access(INIT, os.X_OK)
    and os.path.isfile(PARSE_MC2)
    and os.access(MG2MB, os.R_OK)
)
HAVE_C_INTERP = os.access(C_INTERP, os.X_OK)

# Each end-to-end case builds and runs a multi-megabyte Malbolge20 program;
# programs that call user functions are the slowest.
SUBPROCESS_TIMEOUT = 300


def py_to_c(source):
    return compile_python_to_c(source)


def c_to_mg(c_source, mg_path):
    """Run the reference high-level parser; return its stderr (empty == ok).

    The parser always exits 0 and reports problems only on stderr, so callers
    must treat non-empty stderr as failure."""
    with tempfile.NamedTemporaryFile("w", suffix=".c", delete=False) as cf:
        cf.write(c_source)
        c_path = cf.name
    try:
        with open(mg_path, "w") as mg_out:
            proc = subprocess.run(
                [HL_PARSER, c_path], stdout=mg_out, stderr=subprocess.PIPE,
                text=True)
        return proc.stderr
    finally:
        os.unlink(c_path)


@unittest.skipUnless(
    HAVE_HL, "reference high-level parser not built (ref/nagoya-highlevel)")
class ParserAcceptance(unittest.TestCase):
    """The generated C must be accepted by the reference parser (no stderr)."""

    def assert_accepts(self, source):
        c_source = py_to_c(source)
        with tempfile.TemporaryDirectory() as d:
            err = c_to_mg(c_source, os.path.join(d, "p.mg"))
        self.assertEqual(
            err.strip(), "",
            "parser rejected generated C:\n{}\n--- C ---\n{}".format(
                err, c_source))

    def test_putchar_sequence(self):
        self.assert_accepts("putchar(72)\nputchar(105)\n")

    def test_while_loop(self):
        self.assert_accepts("x = 5\nwhile x > 0:\n    putchar(65)\n    x -= 1\n")

    def test_while_truthiness(self):
        self.assert_accepts("x = 3\nwhile x:\n    x = x - 1\n")

    def test_if_elif_else(self):
        self.assert_accepts(
            "x = 5\nif x < 3:\n    putchar(65)\n"
            "elif x < 10:\n    putchar(66)\nelse:\n    putchar(67)\n")

    def test_and_or_not(self):
        self.assert_accepts(
            "x = 5\ny = 9\n"
            "if (x < 10) and (y > 3):\n    putchar(65)\n"
            "if (x > 100) or not (y == 0):\n    putchar(66)\n")

    def test_chained_comparison(self):
        self.assert_accepts("x = 5\nif 0 < x < 10:\n    putchar(65)\n")

    def test_for_range(self):
        self.assert_accepts("for i in range(3):\n    putchar(65 + i)\n")

    def test_for_range_step(self):
        self.assert_accepts("for i in range(0, 10, 2):\n    putchar(65 + i)\n")

    def test_recursion(self):
        self.assert_accepts(
            "def fib(n):\n    if n < 2:\n        return n\n"
            "    return fib(n - 1) + fib(n - 2)\nputchar(fib(7) + 58)\n")

    def test_runtime_multiply(self):
        self.assert_accepts("n = 6\nm = 7\nputchar(n * m + 48)\n")

    def test_runtime_floordiv_mod(self):
        self.assert_accepts(
            "a = 17\nb = 5\nputchar(a // b + 64)\nputchar(a % b + 65)\n")

    def test_forward_reference_and_mutual_recursion(self):
        self.assert_accepts(
            "def iseven(n):\n    if n == 0:\n        return 1\n"
            "    return isodd(n - 1)\n"
            "def isodd(n):\n    if n == 0:\n        return 0\n"
            "    return iseven(n - 1)\nputchar(iseven(4) + 64)\n")

    def test_global_read_and_write(self):
        self.assert_accepts(
            "counter = 0\nbase = 65\n"
            "def bump():\n    global counter\n    counter += 1\n"
            "def emit(off):\n    putchar(base + off)\n"
            "bump()\nemit(0)\n")


class EndToEnd(unittest.TestCase):
    """Transpile Python -> .mb and run it, asserting the observed output.

    Building uses the reference toolchain when built (its C/C++ stages
    assemble multi-MB programs in seconds) and otherwise falls back to the
    pure-Python pipeline, whose mc2mb stage is ~40s/MB -- so the larger
    cases are skipped without the reference tools. Stage equivalence is
    separately guaranteed byte-for-byte by the conformance suites
    (test_c2mg / test_mg2mc / test_mc2mb).

    Output is checked against the C reference interpreter when it is built
    (much faster than pyMalbolge); a couple of cases are additionally
    cross-checked on pyMalbolge itself."""

    def _build_mb(self, source, workdir, seed=1):
        mb = os.path.join(workdir, "prog.mb")
        if HAVE_PIPELINE:
            c_source = py_to_c(source)
            mg = os.path.join(workdir, "prog.mg")
            err = c_to_mg(c_source, mg)
            self.assertEqual(
                err.strip(), "",
                "high-level parser rejected generated C:\n" + err)
            proc = subprocess.run(
                ["bash", MG2MB, "-s", str(seed), mg, mb],
                stderr=subprocess.PIPE, text=True)
            self.assertEqual(
                proc.returncode, 0,
                ".mg -> .mb pipeline failed:\n" + proc.stderr)
        else:
            with open(mb, "w") as f:
                f.write(compile_python_to_mb(source))
        return mb

    def _run_c(self, mb, stdin):
        return subprocess.run(
            [C_INTERP, mb], input=stdin, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=SUBPROCESS_TIMEOUT).stdout

    def _run_py(self, mb, stdin):
        return subprocess.run(
            [sys.executable, "-m", "malbolge", "--variant=malbolge20", mb],
            input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=SUBPROCESS_TIMEOUT).stdout

    def run_python(self, source, stdin=b"", seed=1, cross_check=False):
        """Build and run `source`; return observed stdout.

        Runs on the C reference interpreter when available, else pyMalbolge.
        When `cross_check` is set and the C interpreter was used, the same
        program is also run on pyMalbolge and the outputs must agree."""
        with tempfile.TemporaryDirectory() as d:
            mb = self._build_mb(source, d, seed)
            if HAVE_C_INTERP:
                out = self._run_c(mb, stdin)
                if cross_check:
                    self.assertEqual(
                        self._run_py(mb, stdin), out,
                        "pyMalbolge and C reference interpreter disagree")
                return out
            return self._run_py(mb, stdin)

    def test_putchar_hi(self):
        # Cross-checked on pyMalbolge (the runtime this project actually ships).
        self.assertEqual(
            self.run_python("putchar(72)\nputchar(105)\n", cross_check=True),
            b"Hi")

    @unittest.skipUnless(
        HAVE_PIPELINE,
        "multi-MB program; pure-Python mc2mb is ~40s/MB -- build ref/ tools for the fast path")
    def test_while_countdown(self):
        # prints C, B, A
        out = self.run_python("x = 3\nwhile x > 0:\n    putchar(64 + x)\n    x -= 1\n")
        self.assertEqual(out, b"CBA")

    @unittest.skipUnless(
        HAVE_PIPELINE,
        "multi-MB program; pure-Python mc2mb is ~40s/MB -- build ref/ tools for the fast path")
    def test_if_else(self):
        out = self.run_python("x = 5\nif x < 3:\n    putchar(65)\nelse:\n    putchar(90)\n")
        self.assertEqual(out, b"Z")

    @unittest.skipUnless(
        HAVE_PIPELINE,
        "multi-MB program; pure-Python mc2mb is ~40s/MB -- build ref/ tools for the fast path")
    def test_for_range_desugar(self):
        out = self.run_python("for i in range(3):\n    putchar(65 + i)\n")
        self.assertEqual(out, b"ABC")

    def test_multiply_constant_folded(self):
        # 9 * 7 + 2 == 65 == 'A'; the multiplication is folded at compile time.
        self.assertEqual(self.run_python("putchar(9 * 7 + 2)\n"), b"A")

    def test_echo_getchar(self):
        # Cross-checked on pyMalbolge (exercises input handling).
        self.assertEqual(
            self.run_python("c = getchar()\nputchar(c)\n", stdin=b"Q",
                            cross_check=True),
            b"Q")

    @unittest.skipUnless(
        HAVE_PIPELINE,
        "multi-MB program; pure-Python mc2mb is ~40s/MB -- build ref/ tools for the fast path")
    def test_recursion_single_call(self):
        # Single recursive call per expression: sum 5+4+3+2+1 == 15; +50 == 'A'.
        out = self.run_python(
            "def s(n):\n    if n == 0:\n        return 0\n"
            "    return n + s(n - 1)\nputchar(s(5) + 50)\n")
        self.assertEqual(out, b"A")

    @unittest.skipUnless(
        HAVE_PIPELINE,
        "multi-MB program; pure-Python mc2mb is ~40s/MB -- build ref/ tools for the fast path")
    def test_recursion_double_call_fib(self):
        # Classic double-recursion Fibonacci: fib(5) == 5; +60 == 'A'.
        # Hand-written C with two *inline* recursive calls in one expression is
        # mis-compiled by the upstream high-level compiler (fib(4) yields 2, not
        # 3). This front-end always lowers to three-address form
        # (t0=fib(n-1); t1=fib(n-2); return t0+t1), which sidesteps the bug --
        # this test guards that the decomposed form stays correct.
        out = self.run_python(
            "def fib(n):\n    if n < 2:\n        return n\n"
            "    return fib(n - 1) + fib(n - 2)\nputchar(fib(5) + 60)\n")
        self.assertEqual(out, b"A")


if __name__ == "__main__":
    unittest.main()
