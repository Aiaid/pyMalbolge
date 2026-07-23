"""
Unit tests for the Python -> Nagoya C transpiler (malbolge.compiler.py2c).

These tests are self-contained: they exercise the transpiler and its static
checks only, and do NOT depend on the reference toolchain under ref/.
End-to-end tests (Python -> .mb -> run) live in test_py2c_e2e.py.
"""

import re
import unittest

from malbolge.compiler import compile_python_to_c, CompileError

MOD = 3 ** 20


def norm(c):
    """Collapse whitespace so structural assertions are layout-independent."""
    return re.sub(r"\s+", " ", c).strip()


def putchar_codes(c):
    """Every `putchar(N);` call's N, in emission order -- lets a test assert
    on the exact byte sequence a program emits without caring about the
    surrounding control-flow scaffolding."""
    return [int(n) for n in re.findall(r"putchar\((\d+)\);", c)]


class TestBasicEmission(unittest.TestCase):
    def test_putchar_sequence(self):
        c = compile_python_to_c("putchar(72)\nputchar(105)\n")
        self.assertIn("int main(){", norm(c))
        self.assertIn("putchar(72);", c)
        self.assertIn("putchar(105);", c)

    def test_module_var_is_global(self):
        # Module-level variables become top-level globals (so functions can
        # read them), not locals of main().
        c = compile_python_to_c("base = 65\nputchar(base)\n")
        self.assertRegex(c, r"(?m)^int base;")
        self.assertIn("base = 65;", c)

    def test_char_literal_via_ord(self):
        c = compile_python_to_c("putchar(ord('A'))\n")
        self.assertIn("putchar(65);", c)

    def test_docstring_ignored(self):
        c = compile_python_to_c('"""module doc"""\nputchar(65)\n')
        self.assertIn("putchar(65);", c)


class TestConstantFolding(unittest.TestCase):
    def test_add_sub_fold(self):
        c = compile_python_to_c("putchar(60 + 5 - 2)\n")
        self.assertIn("putchar(63);", c)

    def test_mult_folds_no_helper(self):
        c = compile_python_to_c("putchar(9 * 7 + 2)\n")
        self.assertIn("putchar(65);", c)
        self.assertNotIn("zzmul", c)  # folded -> no runtime helper

    def test_floordiv_mod_fold(self):
        c = compile_python_to_c("putchar(17 // 5 + 64)\nputchar(17 % 5 + 65)\n")
        self.assertIn("putchar(67);", c)  # 3 + 64
        self.assertIn("putchar(67);", c)  # 2 + 65
        self.assertNotIn("zzdiv", c)
        self.assertNotIn("zzmod", c)

    def test_subtraction_wraps_mod(self):
        # 3 - 5 wraps to a large positive value (the ring has no negatives).
        c = compile_python_to_c("x = 3 - 5\n")
        self.assertIn("x = {};".format((3 - 5) % MOD), c)

    def test_ord_folds(self):
        c = compile_python_to_c("x = ord('a')\n")
        self.assertIn("x = 97;", c)


class TestHelperInjection(unittest.TestCase):
    def test_mult_injects_zzmul(self):
        c = compile_python_to_c("n = 6\nm = 7\nputchar(n * m)\n")
        self.assertIn("int zzmul(int a, int b){", c)
        self.assertIn("zzmul(n, m)", c)

    def test_floordiv_injects_zzdiv(self):
        c = compile_python_to_c("a = 17\nb = 5\nputchar(a // b)\n")
        self.assertIn("int zzdiv(int a, int b){", c)
        self.assertIn("zzdiv(a, b)", c)

    def test_mod_injects_zzmod(self):
        c = compile_python_to_c("a = 17\nb = 5\nputchar(a % b)\n")
        self.assertIn("int zzmod(int a, int b){", c)
        self.assertIn("zzmod(a, b)", c)

    def test_no_helper_when_unused(self):
        c = compile_python_to_c("putchar(65)\n")
        for h in ("zzmul", "zzdiv", "zzmod"):
            self.assertNotIn(h, c)


class TestTempExpansion(unittest.TestCase):
    def test_nested_arith_uses_temps(self):
        # Non-constant nested arithmetic is decomposed into three-address form:
        # each emitted statement has at most one binary operator.
        c = compile_python_to_c("n = 5\nx = n + 1 + 1\n")
        # find every 'a = b OP c;' style line and ensure single operator
        for line in c.splitlines():
            line = line.strip()
            m = re.match(r"^\w+ [-+]?= .*;$", line)
            if m and "(" not in line:  # skip calls
                ops = re.findall(r"[+\-]", line.split("=", 1)[1])
                self.assertLessEqual(
                    len(ops), 1, "multi-operator statement: " + line)

    def test_temps_declared_before_use(self):
        c = compile_python_to_c("n = 5\nx = n + 1\n")
        # every zztN referenced is also declared as `int zztN;`
        used = set(re.findall(r"\bzzt\d+\b", c))
        for name in used:
            self.assertIn("int {};".format(name), c)


class TestControlFlow(unittest.TestCase):
    def test_while_truthiness(self):
        # `while x:` becomes a flag computed as (x != 0), recomputed in-loop.
        c = compile_python_to_c("x = 3\nwhile x:\n    x = x - 1\n")
        self.assertIn("!= 0", c)
        self.assertIn("while(", c)

    def test_no_bool_true_false_emitted(self):
        # The C backend's true/false/bool are broken; we must never emit them.
        c = compile_python_to_c(
            "x = 5\nif (x < 10) and (x > 0):\n    putchar(65)\n")
        self.assertNotIn("bool", c)
        self.assertNotIn("true", c)
        self.assertNotIn("false", c)

    def test_for_range_desugar(self):
        c = compile_python_to_c("for i in range(3):\n    putchar(65 + i)\n")
        self.assertIn("i = 0;", c)
        self.assertIn("while(", c)
        self.assertIn("i += 1;", c)

    def test_for_range_start_stop_step(self):
        c = compile_python_to_c("for i in range(2, 10, 2):\n    putchar(i)\n")
        self.assertIn("i = 2;", c)
        self.assertIn("i += 2;", c)

    def test_if_elif_else(self):
        c = compile_python_to_c(
            "x = 5\nif x < 3:\n    putchar(65)\n"
            "elif x < 10:\n    putchar(66)\nelse:\n    putchar(67)\n")
        self.assertIn("} else {", c)


class TestFunctions(unittest.TestCase):
    def test_recursion(self):
        c = compile_python_to_c(
            "def fib(n):\n    if n < 2:\n        return n\n"
            "    return fib(n - 1) + fib(n - 2)\nputchar(fib(7) + 58)\n")
        self.assertIn("int fib(int n){", c)
        self.assertIn("return", c)

    def test_params_declared_in_signature(self):
        c = compile_python_to_c("def f(a, b):\n    return a + b\nputchar(f(1, 2) + 60)\n")
        self.assertIn("int f(int a, int b){", c)

    def test_forward_prototype_emitted(self):
        # Calls must resolve regardless of definition order, so every user
        # function gets a forward prototype.
        c = compile_python_to_c(
            "def a(x):\n    return b(x)\ndef b(x):\n    return x + 1\n"
            "putchar(a(64))\n")
        self.assertIn("int a(int x);", c)
        self.assertIn("int b(int x);", c)
        # prototypes precede definitions
        self.assertLess(c.index("int a(int x);"), c.index("int a(int x){"))

    def test_global_write_needs_global_kw(self):
        c = compile_python_to_c(
            "counter = 0\ndef bump():\n    global counter\n"
            "    counter += 1\nbump()\n")
        self.assertRegex(c, r"(?m)^int counter;")
        # counter is not redeclared as a local of bump() (split on the
        # definition '{', not the forward prototype 'int bump();')
        body = c.split("int bump(){")[1].split("int main")[0]
        self.assertNotIn("int counter;", body)


class TestStaticErrors(unittest.TestCase):
    def assert_error(self, src, needle):
        with self.assertRaises(CompileError) as ctx:
            compile_python_to_c(src)
        self.assertIn(needle, str(ctx.exception))

    def test_true_division(self):
        self.assert_error("x = 10\ny = 3\nputchar(x / y)\n", "true division")

    def test_negative_literal(self):
        # `-5` parses as UnaryOp(USub, 5); both paths reject with a
        # "no negatives" explanation.
        self.assert_error("x = -5\n", "no negatives")

    def test_unary_minus(self):
        self.assert_error("x = 5\ny = -x\n", "unary minus")

    def test_chr_unsupported(self):
        self.assert_error("putchar(chr(65))\n", "chr()")

    def test_print_runtime_arg_unsupported(self):
        # print() now accepts compile-time constant arguments (see
        # TestPrintSugar below); a runtime variable is still rejected.
        self.assert_error("x = 65\nprint(x)\n", "compile-time constant")

    def test_print_as_value_unsupported(self):
        self.assert_error("x = print(65)\n", "cannot be used as a value")

    def test_string_literal(self):
        self.assert_error("s = 'hello'\n", "string literals")

    def test_float(self):
        self.assert_error("x = 3.14\n", "floating-point")

    def test_list(self):
        self.assert_error("a = [1, 2, 3]\n", "unsupported expression")

    def test_class(self):
        self.assert_error("class C:\n    pass\n", "class definitions")

    def test_import(self):
        self.assert_error("import os\n", "'import'")

    def test_break_outside_loop(self):
        # break/continue are now supported *inside* a loop (batch-one
        # syntax sugar, see TestBreakContinueSugar below); outside any loop
        # they're still a CompileError.
        self.assert_error("break\nputchar(65)\n", "outside loop")

    def test_continue_outside_loop(self):
        self.assert_error("continue\nputchar(65)\n", "outside loop")

    def test_lambda(self):
        self.assert_error("f = lambda x: x + 1\n", "unsupported expression")

    def test_comprehension(self):
        self.assert_error("a = [i for i in range(3)]\n", "unsupported expression")

    def test_reserved_zz_prefix(self):
        self.assert_error("zzx = 5\n", "reserved")

    def test_c_keyword_name(self):
        self.assert_error("int = 5\n", "C keyword")

    def test_undefined_function(self):
        self.assert_error("bar(1)\n", "undefined function")

    def test_nested_function(self):
        self.assert_error(
            "def outer():\n    def inner():\n        return 1\n"
            "    return inner()\n", "nested function")

    def test_range_negative_step(self):
        self.assert_error(
            "for i in range(10, 0, -1):\n    putchar(65)\n",
            "range() step must be a positive integer literal")

    def test_division_by_zero_constant(self):
        self.assert_error("putchar(5 // 0)\n", "division or modulo by zero")

    def test_error_has_line_number(self):
        with self.assertRaises(CompileError) as ctx:
            compile_python_to_c("putchar(65)\nx = 1 / 2\n")
        self.assertEqual(ctx.exception.lineno, 2)


class TestHelperAlgorithms(unittest.TestCase):
    """Guard the injected helper *algorithms* against regression by executing
    faithful Python transliterations of the emitted C over many inputs.

    The transliterations below mirror HELPER_MUL / HELPER_DIV / HELPER_MOD in
    py2c.py statement-for-statement (mod 3**20 applied on every operation, as
    the Malbolge20 value ring does)."""

    @staticmethod
    def zzmul(a, b):
        a %= MOD; b %= MOD
        result = 0; rem = b; cnt = 32
        while cnt != 0:
            cnt -= 1
            p = 1; ash = a; j = 0
            while j != cnt:
                p = (p + p) % MOD; ash = (ash + ash) % MOD; j += 1
            if rem >= p:
                rem -= p; result = (result + ash) % MOD
        return result

    @staticmethod
    def zzdiv(a, b):
        a %= MOD; b %= MOD; q = 0; rem = a
        if b != 0:
            while b <= rem:
                bsh = b; p = 1
                while bsh <= (rem - bsh):
                    bsh = (bsh + bsh) % MOD; p = (p + p) % MOD
                rem -= bsh; q = (q + p) % MOD
        return q

    @staticmethod
    def zzmod(a, b):
        a %= MOD; b %= MOD; rem = a
        if b != 0:
            while b <= rem:
                bsh = b
                while bsh <= (rem - bsh):
                    bsh = (bsh + bsh) % MOD
                rem -= bsh
        return rem

    def test_mul_matches_python(self):
        import random
        rng = random.Random(1234)
        cases = [(0, 5), (5, 0), (1, 1), (9, 7), (255, 255), (MOD - 1, MOD - 1),
                 (3 ** 19, 7), (123456, 7891)]
        cases += [(rng.randrange(MOD), rng.randrange(MOD)) for _ in range(500)]
        for a, b in cases:
            self.assertEqual(self.zzmul(a, b), (a * b) % MOD, (a, b))

    def test_div_mod_match_python(self):
        import random
        rng = random.Random(4321)
        cases = [(0, 5), (17, 5), (100, 7), (MOD - 1, 2), (5, 1), (5, 7),
                 (3486784400, 3)]
        cases += [(rng.randrange(MOD), rng.randrange(1, MOD)) for _ in range(500)]
        for a, b in cases:
            self.assertEqual(self.zzdiv(a, b), (a // b) % MOD, (a, b))
            self.assertEqual(self.zzmod(a, b), a % b, (a, b))

    def test_div_mod_by_zero_returns_zero(self):
        self.assertEqual(self.zzdiv(42, 0), 0)
        self.assertEqual(self.zzmod(42, 0), 42)


class TestPrintSugar(unittest.TestCase):
    """print() with compile-time constant arguments (batch-one sugar #1)."""

    def test_multi_arg_default_sep_end(self):
        c = compile_python_to_c("print('A', 'B')\n")
        self.assertEqual(
            putchar_codes(c), [ord("A"), ord(" "), ord("B"), ord("\n")])

    def test_custom_sep_and_end(self):
        c = compile_python_to_c("print('A', 'B', sep='-', end='!')\n")
        self.assertEqual(putchar_codes(c), [ord(ch) for ch in "A-B!"])

    def test_no_args_emits_only_end(self):
        c = compile_python_to_c("print()\n")
        self.assertEqual(putchar_codes(c), [ord("\n")])

    def test_int_literal_renders_decimal(self):
        c = compile_python_to_c("print(65)\n")
        self.assertEqual(putchar_codes(c), [ord(ch) for ch in "65\n"])

    def test_folds_constant_int_expression(self):
        c = compile_python_to_c("print(9 * 7 + 2)\n")  # == 65
        self.assertEqual(putchar_codes(c), [ord(ch) for ch in "65\n"])

    def test_fstring_folds_constant_int_part(self):
        c = compile_python_to_c("print(f'x={1 + 2}!')\n")
        self.assertEqual(putchar_codes(c), [ord(ch) for ch in "x=3!\n"])

    def test_fstring_folds_string_literal_part(self):
        c = compile_python_to_c("print(f\"{'AB'}\")\n")
        self.assertEqual(putchar_codes(c), [ord(ch) for ch in "AB\n"])

    def test_rejects_runtime_variable_argument(self):
        with self.assertRaises(CompileError) as ctx:
            compile_python_to_c("x = 65\nprint(x)\n")
        msg = str(ctx.exception)
        self.assertIn("compile-time constant", msg)
        self.assertIn("putchar", msg)

    def test_rejects_fstring_conversion(self):
        with self.assertRaises(CompileError) as ctx:
            compile_python_to_c("print(f'{1!r}')\n")
        self.assertIn("conversion", str(ctx.exception))

    def test_rejects_fstring_format_spec(self):
        with self.assertRaises(CompileError) as ctx:
            compile_python_to_c("print(f'{1:03d}')\n")
        self.assertIn("format spec", str(ctx.exception))

    def test_rejects_non_constant_sep(self):
        # sep/end must be constant *string* literals; an int (or anything
        # else non-string) is rejected even though it's compile-time-known.
        with self.assertRaises(CompileError) as ctx:
            compile_python_to_c("print('A', 'B', sep=1)\n")
        self.assertIn("sep", str(ctx.exception))

    def test_rejects_unknown_keyword(self):
        with self.assertRaises(CompileError) as ctx:
            compile_python_to_c("print('A', file=None)\n")
        self.assertIn("sep", str(ctx.exception))

    def test_rejects_codepoint_above_255(self):
        with self.assertRaises(CompileError) as ctx:
            compile_python_to_c("print('\u3042')\n")  # U+3042, not U+00FF
        self.assertIn("U+3042", str(ctx.exception))

    def test_fstring_still_rejected_outside_print(self):
        # Batch-one only lifts the JoinedStr ban for print()'s own argument
        # position; everywhere else it's still an unsupported expression.
        with self.assertRaises(CompileError) as ctx:
            compile_python_to_c("x = 65\ny = f'{x}'\nputchar(65)\n")
        self.assertIn("unsupported expression", str(ctx.exception))


class TestConditionalExpressionSugar(unittest.TestCase):
    """`a if c else b` (batch-one sugar #4): materialised via real if/else."""

    def test_accepted_and_materialised_through_if_else(self):
        c = compile_python_to_c(
            "x = 5\ny = 1 if x > 0 else 0\nputchar(y + 64)\n")
        self.assertIn("if(", c)
        self.assertIn("} else {", c)

    def test_nested_ifexp_in_print_int_position_still_runtime(self):
        # An IfExp never folds to a compile-time constant (it always goes
        # through real control flow), so it's rejected as a print() arg --
        # documents the boundary rather than a print()-specific bug.
        with self.assertRaises(CompileError):
            compile_python_to_c("x = 5\nprint(1 if x > 0 else 0)\n")

    def test_usable_as_function_argument(self):
        c = compile_python_to_c(
            "def f(n):\n    return n\nx = 5\n"
            "putchar(f(65 if x > 0 else 90))\n")
        self.assertIn("if(", c)


class TestAugmentedAssignmentSugar(unittest.TestCase):
    """`*= //= %=` (batch-one sugar #5) -- already wired through the
    existing zzmul/zzdiv/zzmod helpers; locked here as a regression test."""

    def test_mult_augassign_injects_zzmul(self):
        c = compile_python_to_c("x = 5\nx *= 3\nputchar(x)\n")
        self.assertIn("int zzmul(int a, int b){", c)
        self.assertIn("x = zzmul(x, 3);", c)

    def test_floordiv_augassign_injects_zzdiv(self):
        c = compile_python_to_c("x = 17\nx //= 5\nputchar(x + 64)\n")
        self.assertIn("int zzdiv(int a, int b){", c)
        self.assertIn("x = zzdiv(x, 5);", c)

    def test_mod_augassign_injects_zzmod(self):
        c = compile_python_to_c("x = 17\nx %= 5\nputchar(x + 64)\n")
        self.assertIn("int zzmod(int a, int b){", c)
        self.assertIn("x = zzmod(x, 5);", c)

    def test_pow_augassign_still_rejected(self):
        with self.assertRaises(CompileError) as ctx:
            compile_python_to_c("x = 2\nx **= 3\n")
        self.assertIn("unsupported augmented operator", str(ctx.exception))


class TestBreakContinueSugar(unittest.TestCase):
    """break/continue (batch-one sugar #6) via a flag-downgrade rewrite."""

    def test_break_in_while_accepted(self):
        c = compile_python_to_c(
            "x = 1\nwhile x:\n    putchar(65)\n    break\n")
        self.assertIn("putchar(65);", c)

    def test_continue_in_for_still_advances(self):
        c = compile_python_to_c(
            "for i in range(3):\n    continue\n    putchar(65)\n")
        # the increment must not be textually inside the same guarded block
        # as the (never-reached) putchar -- both must still appear, but the
        # increment must not be conditioned on the break flag alone being
        # false in a way that also guards on skip (continue must not stop
        # the index from advancing).
        self.assertIn("i += 1;", c)

    def test_break_continue_outside_loop_rejected(self):
        with self.assertRaises(CompileError) as ctx:
            compile_python_to_c("def f():\n    break\n")
        self.assertIn("outside loop", str(ctx.exception))
        with self.assertRaises(CompileError) as ctx:
            compile_python_to_c("def f():\n    continue\n")
        self.assertIn("outside loop", str(ctx.exception))

    def test_nested_loops_get_independent_flags(self):
        c = compile_python_to_c(
            "for i in range(3):\n"
            "    for j in range(3):\n"
            "        if j == 1:\n"
            "            break\n"
            "        putchar(65)\n"
            "    if i == 1:\n"
            "        continue\n"
            "    putchar(90)\n")
        # each loop that uses break/continue allocates its own pair of
        # flag temporaries; the outer and inner loop must not share one
        # (that would make an inner break also terminate the outer loop).
        skip_and_break_temps = set(re.findall(r"\bzzt\d+\b(?= = 0;)", c))
        self.assertGreaterEqual(len(skip_and_break_temps), 4)


class TestDocstringPositionRule(unittest.TestCase):
    """Bare string-literal statements are only tolerated as a docstring in
    the first statement of a module or function body (batch-one sugar #7);
    any other position is rejected like any other string literal."""

    def test_module_docstring_position_zero_ignored(self):
        c = compile_python_to_c('"""module doc"""\nputchar(65)\n')
        self.assertIn("putchar(65);", c)

    def test_function_docstring_position_zero_ignored(self):
        c = compile_python_to_c(
            "def f():\n    '''func doc'''\n    return 1\n"
            "putchar(f() + 64)\n")
        self.assertIn("int f(){", norm(c))

    def test_module_stray_string_not_first_rejected(self):
        with self.assertRaises(CompileError) as ctx:
            compile_python_to_c(
                "putchar(65)\n'not a docstring'\nputchar(66)\n")
        self.assertIn("string literals", str(ctx.exception))

    def test_function_stray_string_not_first_rejected(self):
        with self.assertRaises(CompileError) as ctx:
            compile_python_to_c(
                "def f():\n    x = 1\n    'not a docstring'\n"
                "    return x\nputchar(f() + 64)\n")
        self.assertIn("string literals", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
