"""Tests for malbolge.compiler.py2mg (the direct Python -> .mg backend).

Two layers, neither needing any external tool:

* Pure-Python unit tests -- AST -> .mg structure, the frame policy (real
  recursion analysis, per-function temporaries, per-function push/pop), and
  rejection of unsupported input.
* Downstream acceptance -- every generated .mg must be accepted, unchanged, by
  the existing pure-Python ``mg2mc`` translator (the v0 contract: no new
  pseudo-instructions).

End-to-end output equality against the C backend is covered separately by
``test/test_py2mg_e2e.py`` (slow; builds real .mb programs).
"""

import unittest

from malbolge.compiler.py2mg import (
    compile_python_to_mg,
    Py2MgError,
    _DirectCompiler,
)
from malbolge.compiler.mg2mc import translate_mg_to_mc


def compile_and_flags(source):
    """Compile and also expose the internal recursion flags for assertions."""
    c = _DirectCompiler(source)
    mg = c.compile()
    flags = {name: c.functions[name].is_recursive for name in c.functions}
    return mg, flags


# ---------------------------------------------------------------------------
# Basic generation
# ---------------------------------------------------------------------------
class TestGeneration(unittest.TestCase):
    def test_minimal_putchar(self):
        mg = compile_python_to_mg("putchar(72)\n")
        self.assertIn("DEF MAIN", mg)
        self.assertIn("PROTO MAIN", mg)
        self.assertIn("OUTPUT", mg)
        self.assertIn("VAR CONST_72=72", mg)
        # main is not a routine that returns a value: no RETURN_VALUE cell.
        self.assertNotIn("VAR RETURN_VALUE=0", mg)

    def test_getchar(self):
        mg = compile_python_to_mg("c = getchar()\nputchar(c)\n")
        self.assertIn("INPUT", mg)
        self.assertIn("OUTPUT", mg)

    def test_stack_top_global_present(self):
        mg = compile_python_to_mg("putchar(65)\n")
        self.assertIn("VAR STACK_TOP=", mg)

    def test_all_protos_before_defs(self):
        mg = compile_python_to_mg(
            "def f(n):\n    return n\nputchar(f(65))\n")
        first_def = mg.index("DEF ")
        self.assertTrue(all(
            mg.index(line) < first_def
            for line in mg.splitlines() if line.startswith("PROTO ")))

    def test_function_and_call(self):
        mg = compile_python_to_mg(
            "def add1(n):\n    return n + 1\nputchar(add1(64))\n")
        self.assertIn("DEF ADD1", mg)
        self.assertIn("CALL ADD1", mg)
        self.assertIn("PROTO ADD1", mg)


# ---------------------------------------------------------------------------
# Frame policy: real recursion analysis
# ---------------------------------------------------------------------------
class TestRecursionAnalysis(unittest.TestCase):
    def flags(self, source):
        return compile_and_flags(source)[1]

    def test_leaf_function_not_recursive(self):
        f = self.flags("def g(n):\n    return n + 1\nputchar(g(64))\n")
        self.assertFalse(f["G"])
        self.assertFalse(f["MAIN"])

    def test_self_recursion_detected(self):
        f = self.flags(
            "def s(n):\n    if n == 0:\n        return 0\n"
            "    return n + s(n - 1)\nputchar(s(5) + 50)\n")
        self.assertTrue(f["S"])
        self.assertFalse(f["MAIN"])

    def test_mutual_recursion_detected(self):
        f = self.flags(
            "def iseven(n):\n    if n == 0:\n        return 1\n"
            "    return isodd(n - 1)\n"
            "def isodd(n):\n    if n == 0:\n        return 0\n"
            "    return iseven(n - 1)\nputchar(iseven(4) + 64)\n")
        self.assertTrue(f["ISEVEN"])
        self.assertTrue(f["ISODD"])
        self.assertFalse(f["MAIN"])

    def test_injected_helpers_not_recursive(self):
        f = self.flags("n = 6\nm = 7\nputchar(n * m + 48 - 42)\n")
        self.assertIn("ZZMUL", f)
        self.assertFalse(f["ZZMUL"])
        self.assertFalse(f["MAIN"])

    def test_non_cyclic_chain_not_recursive(self):
        # a -> b -> c, no cycle: none is recursive.
        f = self.flags(
            "def c(n):\n    return n + 1\n"
            "def b(n):\n    return c(n)\n"
            "def a(n):\n    return b(n)\n"
            "putchar(a(64))\n")
        self.assertFalse(any(f[k] for k in ("A", "B", "C")))


# ---------------------------------------------------------------------------
# Frame policy: per-function push/pop only for recursive functions
# ---------------------------------------------------------------------------
class TestFramePolicy(unittest.TestCase):
    def _def_body(self, mg, name):
        """Return the text of DEF <name> ... END (its matching END)."""
        start = mg.index("DEF " + name + "\n")
        depth = 0
        body = []
        # DEF/IF/SWITCH/REPEAT each open a block closed by a single END.
        openers = ("DEF ", "IF ", "SWITCH ", "REPEAT")
        for ln in mg[start:].splitlines():
            body.append(ln)
            s = ln.strip()
            if any(s.startswith(o) for o in openers):
                depth += 1
            elif s == "END":
                depth -= 1
                if depth == 0:
                    break
        return "\n".join(body)

    def test_non_recursive_function_has_no_stack_protection(self):
        mg = compile_python_to_mg(
            "def g(n):\n    return n + 1\nputchar(g(64))\n")
        body = self._def_body(mg, "G")
        # push/pop protection manipulates the stack via IND_OPR STACK_TOP.
        self.assertNotIn("IND_OPR STACK_TOP", body)

    def test_recursive_function_has_stack_protection(self):
        mg = compile_python_to_mg(
            "def s(n):\n    if n == 0:\n        return 0\n"
            "    return n + s(n - 1)\nputchar(s(5) + 50)\n")
        body = self._def_body(mg, "S")
        self.assertIn("IND_OPR STACK_TOP", body)

    def test_main_calling_nonrecursive_has_no_stack_ops(self):
        # main is never entry/exit protected, and calling a non-recursive helper
        # needs no RETURN_ADDR save either -- so no stack traffic at all.
        mg = compile_python_to_mg(
            "def g(n):\n    return n + 1\nputchar(g(64))\n")
        body = self._def_body(mg, "MAIN")
        self.assertNotIn("IND_OPR STACK_TOP", body)

    def test_main_calling_recursive_saves_only_return_addr(self):
        # main gets no protection of its own vars, but the recursive callee's
        # single-slot RETURN_ADDR is saved around the CALL (correct).
        mg = compile_python_to_mg(
            "def s(n):\n    if n == 0:\n        return 0\n"
            "    return n + s(n - 1)\nputchar(s(5) + 50)\n")
        body = self._def_body(mg, "MAIN")
        self.assertIn("OPR RETURN_ADDR@S", body)
        # main never pushes its own temporaries: every stack push here wraps the
        # RETURN_ADDR of the recursive call, never a MAIN-local TMP/var.
        self.assertNotIn("OPR RETURN_VALUE@MAIN", body)

    def test_temps_are_per_function_local(self):
        # Temporaries are declared inside their owning DEF, not as globals.
        mg = compile_python_to_mg(
            "def g(n):\n    return n + n + 1\nputchar(g(20))\n")
        # No global TMP declaration (those would appear before the first DEF).
        header = mg[:mg.index("DEF ")]
        self.assertNotIn("VAR TMP", header)
        # The function's own DEF does declare temporaries.
        self.assertIn("VAR TMP", self._def_body(mg, "G"))


# ---------------------------------------------------------------------------
# Downstream acceptance: mg2mc must accept every generated .mg unchanged
# ---------------------------------------------------------------------------
class TestMg2McAcceptance(unittest.TestCase):
    CASES = {
        "putchar": "putchar(72)\nputchar(105)\n",
        "getchar": "c = getchar()\nputchar(c)\n",
        "if_else": "x = 5\nif x < 3:\n    putchar(65)\nelse:\n    putchar(90)\n",
        "elif": "x = 5\nif x < 3:\n    putchar(65)\n"
                "elif x < 10:\n    putchar(66)\nelse:\n    putchar(67)\n",
        "while": "x = 3\nwhile x > 0:\n    putchar(64 + x)\n    x -= 1\n",
        "for": "for i in range(3):\n    putchar(65 + i)\n",
        "for_step": "for i in range(0, 10, 2):\n    putchar(65 + i)\n",
        "chained": "x = 5\nif 0 < x < 10:\n    putchar(65)\n",
        "and_or_not": "x=5\ny=9\nif (x<10) and (y>3):\n    putchar(65)\n"
                      "if (x>100) or not (y==0):\n    putchar(66)\n",
        "bool_value": "x = 5\ny = (x < 10)\nputchar(65 + y)\n",
        "multiply": "n = 6\nm = 7\nputchar(n * m + 48 - 42)\n",
        "divmod": "a=17\nb=5\nputchar(a//b+64)\nputchar(a%b+65)\n",
        "recursion": "def s(n):\n    if n == 0:\n        return 0\n"
                     "    return n + s(n - 1)\nputchar(s(5) + 50)\n",
        "double_recursion": "def fib(n):\n    if n < 2:\n        return n\n"
                            "    return fib(n - 1) + fib(n - 2)\n"
                            "putchar(fib(5) + 60)\n",
        "mutual_recursion": "def iseven(n):\n    if n == 0:\n        return 1\n"
                            "    return isodd(n - 1)\n"
                            "def isodd(n):\n    if n == 0:\n        return 0\n"
                            "    return iseven(n - 1)\nputchar(iseven(4) + 64)\n",
        "globals": "counter = 0\nbase = 65\n"
                   "def bump():\n    global counter\n    counter += 1\n"
                   "def emit(off):\n    putchar(base + off)\nbump()\nemit(0)\n",
    }

    def test_all_cases_accepted_by_mg2mc(self):
        for name, src in self.CASES.items():
            with self.subTest(case=name):
                mg = compile_python_to_mg(src)
                # Must not raise Mg2McError.
                mc = translate_mg_to_mc(mg)
                self.assertIn("PROGRAM_START_TO ENTRY@MAIN", mc)


# ---------------------------------------------------------------------------
# Rejection of unsupported / invalid input
# ---------------------------------------------------------------------------
class TestRejections(unittest.TestCase):
    def assert_rejects(self, source, needle=None):
        with self.assertRaises(Py2MgError) as cm:
            compile_python_to_mg(source)
        if needle is not None:
            self.assertIn(needle, str(cm.exception))

    def test_negative_literal(self):
        self.assert_rejects("putchar(-5)\n", "negative")

    def test_break(self):
        self.assert_rejects(
            "x = 0\nwhile x < 3:\n    break\n    x += 1\n", "break")

    def test_continue(self):
        self.assert_rejects(
            "x = 0\nwhile x < 3:\n    continue\n", "continue")

    def test_undefined_name(self):
        self.assert_rejects("putchar(y)\n", "not defined")

    def test_undefined_function(self):
        # CPython raises NameError for an undefined callee; the definite-
        # assignment pass reports it with the user's spelling.
        self.assert_rejects("putchar(f(1))\n", "'f' is not defined")

    def test_true_division(self):
        self.assert_rejects("a = 6\nputchar(a / 2)\n", "floor division")

    def test_string_literal(self):
        self.assert_rejects("x = \"hi\"\n", "string literal")

    def test_import(self):
        self.assert_rejects("import os\n", "import")

    def test_class(self):
        self.assert_rejects("class C:\n    pass\n", "class")

    def test_main_function_reserved(self):
        self.assert_rejects("def main():\n    return 0\n")

    def test_line_number_reported(self):
        with self.assertRaises(Py2MgError) as cm:
            compile_python_to_mg("x = 1\nputchar(-5)\n")
        self.assertEqual(cm.exception.lineno, 2)

    # -- definite-assignment (not replicating py2c defects D6-D9) -----------
    def test_top_level_return(self):
        self.assert_rejects("putchar(65)\nreturn 5\n", "outside function")

    def test_bare_annotation_read(self):
        # `x: int` does not bind x; reading it is a NameError.
        self.assert_rejects("x: int\nputchar(x + 65)\n", "not defined")

    def test_uninitialised_augassign(self):
        self.assert_rejects("x += 1\nputchar(x + 65)\n",
                            "used before assignment")

    def test_conditionally_assigned_read(self):
        self.assert_rejects(
            "x = 5\nif x < 3:\n    y = 1\nputchar(y + 65)\n",
            "used before assignment")

    def test_for_variable_after_loop(self):
        self.assert_rejects(
            "for i in range(3):\n    putchar(65)\nputchar(i + 65)\n",
            "used before assignment")

    def test_annotation_with_value_binds(self):
        # `x: int = 5` *does* bind -- must be accepted.
        mg = compile_python_to_mg("x: int = 5\nputchar(x + 60)\n")
        self.assertIn("OUTPUT", mg)

    def test_if_both_branches_assign_accepted(self):
        mg = compile_python_to_mg(
            "x = 5\nif x < 3:\n    y = 1\nelse:\n    y = 2\nputchar(y + 64)\n")
        self.assertIn("OUTPUT", mg)

    def test_decorator(self):
        self.assert_rejects(
            "@staticmethod\ndef f(n):\n    return n\nputchar(f(65))\n",
            "decorator")

    def test_global_same_as_parameter(self):
        self.assert_rejects(
            "g = 0\ndef f(g):\n    global g\n    return g\nputchar(f(65))\n",
            "parameter and global")

    def test_function_named_builtin(self):
        self.assert_rejects(
            "def range(n):\n    return n\nputchar(1)\n", "collides with a builtin")

    def test_forward_global_reference_accepted(self):
        # A function may read a module global assigned later (bound by call time).
        mg = compile_python_to_mg(
            "def f():\n    return base\nbase = 65\nputchar(f())\n")
        self.assertIn("CALL F", mg)


if __name__ == "__main__":
    unittest.main()
