"""
Staged pytest corpus from the py2c.py diagnostic audit (docs/python-subset-spec.md
appendix, /Users/anend/.claude/jobs/1d5df563/tmp/subset-spec/{probe.py,defects.md}).

Two kinds of cases:

  * TestAcceptedRejections -- A-class results from the audit (compile_python_to_c
    already raises CompileError with the right line/message). These are safe
    regression locks: if any of them starts failing, an A-class diagnostic has
    regressed.

  * TestKnownDefects -- originally staged as B/C-class results (see
    defects.md) with xfail markers pointing at the root cause and suggested
    fix. All six defects (C1-C5, B3, plus B1/B2/B4-B6 which share a root
    cause) have since been fixed in py2c.py; every xfail here has been
    flipped to a real assertion documenting the FIXED behaviour (an
    unexpected pass on a strict xfail already makes pytest fail by default,
    which is what forced this file to be updated in lockstep with the fix
    rather than going green silently). If py2c.py regresses on any of
    these, this class will fail.

Run standalone (no pytest dependency required for a quick smoke check):
    python3 test_diagnostics_staged.py
Run under pytest (recommended, gives you the xfail bookkeeping):
    python3 -m pytest test_diagnostics_staged.py -v
"""
import sys

REPO = "/Users/anend/Desktop/project/pyMalbolge"
sys.path.insert(0, REPO)

import pytest  # noqa: E402

from malbolge.compiler.py2c import compile_python_to_c, CompileError  # noqa: E402

MOD = 3 ** 20


# ===========================================================================
# A-class regression locks -- one assertion per accepted-rejection case from
# the audit corpus (probe.py). Kept independent of probe.py's own CASES list
# so this file has no import-time dependency on the scratch harness.
# ===========================================================================
class TestAcceptedRejections:
    def assert_rejected(self, src, exp_line, msg_has):
        with pytest.raises(CompileError) as excinfo:
            compile_python_to_c(src)
        err = excinfo.value
        assert err.lineno == exp_line, (
            "expected CompileError at line {}, got line {} for source:\n{}"
            .format(exp_line, err.lineno, src))
        if msg_has is not None:
            assert msg_has in str(err), (
                "expected message to contain {!r}, got: {}"
                .format(msg_has, err))

    # -- unsupported AST nodes --------------------------------------------
    def test_class_toplevel(self):
        self.assert_rejected("class C:\n    pass\n", 1, "class definitions")

    def test_class_nested(self):
        self.assert_rejected(
            "def f():\n    class C:\n        pass\n    return 1\n"
            "putchar(f())\n", 2, "unsupported statement")

    def test_import(self):
        self.assert_rejected("import os\nputchar(65)\n", 1, "'import'")

    def test_importfrom(self):
        self.assert_rejected(
            "from os import path\nputchar(65)\n", 1, "'import'")

    def test_lambda(self):
        self.assert_rejected(
            "f = lambda x: x + 1\n", 1, "unsupported expression")

    def test_nested_function(self):
        self.assert_rejected(
            "def outer():\n    def inner():\n        return 1\n"
            "    return inner()\nputchar(outer())\n", 2, "nested function")

    def test_closure_free_var(self):
        self.assert_rejected(
            "def make():\n    y = 1\n    def add(x):\n        return x + y\n"
            "    return add(1)\nputchar(make())\n", 3, "nested function")

    def test_generator_func(self):
        self.assert_rejected(
            "def gen():\n    yield 1\nputchar(65)\n", 2,
            "unsupported expression")

    def test_generator_expr(self):
        self.assert_rejected(
            "a = (i for i in range(3))\n", 1, "unsupported expression")

    def test_try_except(self):
        self.assert_rejected(
            "try:\n    x = 1\nexcept Exception:\n    x = 2\nputchar(x)\n",
            1, "unsupported statement")

    def test_with(self):
        self.assert_rejected(
            "with open('f') as fh:\n    x = 1\nputchar(x)\n", 1,
            "unsupported statement")

    def test_assert(self):
        self.assert_rejected(
            "x = 1\nassert x == 1\nputchar(65)\n", 2, "unsupported statement")

    def test_del(self):
        self.assert_rejected(
            "x = 1\ndel x\nputchar(65)\n", 2, "unsupported statement")

    def test_starargs_def(self):
        self.assert_rejected(
            "def f(*args):\n    return 1\nputchar(f(1, 2))\n", 1,
            "only simple positional parameters")

    def test_kwargs_def(self):
        self.assert_rejected(
            "def f(**kw):\n    return 1\nputchar(f())\n", 1,
            "only simple positional parameters")

    def test_default_arg(self):
        self.assert_rejected(
            "def f(x=1):\n    return x\nputchar(f())\n", 1,
            "only simple positional parameters")

    def test_kwonly_arg(self):
        self.assert_rejected(
            "def f(*, x):\n    return x\nputchar(f(x=1))\n", 1,
            "only simple positional parameters")

    def test_posonly_arg(self):
        self.assert_rejected(
            "def f(x, /):\n    return x\nputchar(f(65))\n", 1,
            "only simple positional parameters")

    def test_kwargs_call(self):
        self.assert_rejected(
            "def f(a):\n    return a\nputchar(f(a=65))\n", 3,
            "keyword arguments")

    def test_float_literal(self):
        self.assert_rejected("x = 3.14\nputchar(65)\n", 1, "floating-point")

    def test_str_literal(self):
        self.assert_rejected("s = 'hi'\nputchar(65)\n", 1, "string literals")

    def test_bytes_literal(self):
        self.assert_rejected(
            "b = b'hi'\nputchar(65)\n", 1, "unsupported constant")

    def test_list_literal(self):
        self.assert_rejected(
            "a = [1, 2, 3]\nputchar(65)\n", 1, "unsupported expression")

    def test_dict_literal(self):
        self.assert_rejected(
            "a = {1: 2}\nputchar(65)\n", 1, "unsupported expression")

    def test_set_literal(self):
        self.assert_rejected(
            "a = {1, 2}\nputchar(65)\n", 1, "unsupported expression")

    def test_tuple_literal(self):
        self.assert_rejected(
            "a = (1, 2)\nputchar(65)\n", 1, "unsupported expression")

    def test_tuple_unpack_assign(self):
        self.assert_rejected(
            "a, b = 1, 2\nputchar(a)\n", 1, "unsupported assignment target")

    def test_starred_assign_target(self):
        self.assert_rejected(
            "a, *b = 1, 2, 3\nputchar(a)\n", 1,
            "unsupported assignment target")

    def test_fstring(self):
        self.assert_rejected(
            "x = 65\nputchar(f'{x}')\n", 2, "unsupported expression")

    def test_negative_literal(self):
        self.assert_rejected("x = -5\nputchar(65)\n", 1, "no negatives")

    def test_unary_negative_var(self):
        self.assert_rejected(
            "x = 5\ny = -x\nputchar(65)\n", 2, "unary minus")

    def test_power_op(self):
        self.assert_rejected(
            "x = 2 ** 10\nputchar(65)\n", 1, "unsupported binary operator")

    def test_bitand(self):
        self.assert_rejected(
            "x = 5 & 3\nputchar(65)\n", 1, "unsupported binary operator")

    def test_lshift(self):
        self.assert_rejected(
            "x = 5 << 1\nputchar(65)\n", 1, "unsupported binary operator")

    def test_invert(self):
        self.assert_rejected("x = 5\ny = ~x\nputchar(65)\n", 2, "bitwise")

    def test_is(self):
        self.assert_rejected(
            "x = 1\nif x is 1:\n    putchar(65)\n", 2,
            "comparison operator")

    def test_in(self):
        self.assert_rejected(
            "x = 1\nif x in (1, 2):\n    putchar(65)\n", 2,
            "comparison operator")

    def test_walrus(self):
        self.assert_rejected(
            "if (n := 5) > 0:\n    putchar(n)\n", 1, "unsupported expression")

    def test_subscript_read(self):
        self.assert_rejected(
            "a = 5\nx = a[0]\nputchar(65)\n", 2, "unsupported expression")

    def test_subscript_assign(self):
        self.assert_rejected(
            "a = 5\na[0] = 1\nputchar(65)\n", 2,
            "unsupported assignment target")

    def test_attribute_assign(self):
        self.assert_rejected(
            "a = 5\na.x = 1\nputchar(65)\n", 2,
            "unsupported assignment target")

    def test_async_def(self):
        self.assert_rejected(
            "async def f():\n    return 1\nputchar(65)\n", 1,
            "unsupported statement")

    @pytest.mark.skipif(
        sys.version_info < (3, 10),
        reason="'match' statement syntax requires Python 3.10+; on older "
        "interpreters ast.parse() itself raises SyntaxError before py2c "
        "ever sees a Match node, which is a different (still-correct, but "
        "differently-worded) rejection path than the one this test checks.")
    def test_match_stmt(self):
        self.assert_rejected(
            "x = 1\nmatch x:\n    case 1:\n        putchar(65)\n"
            "    case _:\n        putchar(66)\n", 2, "unsupported statement")

    def test_raise(self):
        self.assert_rejected(
            "raise ValueError('x')\nputchar(65)\n", 1, "unsupported statement")

    # -- semantic-class errors ----------------------------------------------
    def test_call_undefined_function(self):
        self.assert_rejected("putchar(bar(1))\n", 1, "undefined function")

    def test_wrong_argcount_too_few(self):
        self.assert_rejected(
            "def f(a, b):\n    return a + b\nputchar(f(1))\n", 3,
            "argument(s)")

    def test_wrong_argcount_too_many(self):
        self.assert_rejected(
            "def f(a, b):\n    return a + b\nputchar(f(1, 2, 3))\n", 3,
            "argument(s)")

    def test_duplicate_function(self):
        self.assert_rejected(
            "def f():\n    return 1\ndef f():\n    return 2\nputchar(f())\n",
            3, "already defined")

    def test_function_case_collision(self):
        self.assert_rejected(
            "def foo():\n    return 1\ndef FOO():\n    return 2\n"
            "putchar(foo() + FOO())\n", 3, "collides with")

    def test_zz_prefix_var_lower(self):
        self.assert_rejected("zzx = 5\nputchar(zzx)\n", 1, "reserved")

    def test_zz_prefix_var_upper(self):
        self.assert_rejected("ZZfoo = 5\nputchar(ZZfoo)\n", 1, "reserved")

    def test_var_named_main(self):
        self.assert_rejected("main = 5\nputchar(main)\n", 1, "C keyword")

    def test_var_named_putchar(self):
        self.assert_rejected(
            "putchar = 5\nputchar(putchar)\n", 1, "C keyword")

    def test_func_named_main(self):
        self.assert_rejected(
            "def main():\n    return 1\nputchar(65)\n", 1, "C keyword")

    def test_func_named_main_case_variant(self):
        self.assert_rejected(
            "def Main():\n    return 1\nputchar(65)\n", 1, "reserved")

    def test_func_named_putchar(self):
        self.assert_rejected(
            "def putchar(x):\n    return x\nputchar(65)\n", 1, "C keyword")

    def test_range_zero_args(self):
        self.assert_rejected(
            "for i in range():\n    putchar(65)\n", 1, "1 to 3 arguments")

    def test_range_four_args(self):
        self.assert_rejected(
            "for i in range(1, 2, 3, 4):\n    putchar(65)\n", 1,
            "1 to 3 arguments")

    def test_range_var_step(self):
        self.assert_rejected(
            "n = 2\nfor i in range(0, 10, n):\n    putchar(65)\n", 2,
            "positive integer literal")

    def test_getchar_with_args(self):
        self.assert_rejected(
            "putchar(getchar(1))\n", 1, "no arguments")

    def test_putchar_zero_args(self):
        self.assert_rejected("putchar()\n", 1, "exactly one argument")

    def test_putchar_as_value(self):
        self.assert_rejected(
            "x = putchar(65)\nputchar(66)\n", 1,
            "cannot be used as a value")

    def test_ord_non_literal_arg(self):
        self.assert_rejected(
            "x = 65\nputchar(ord(x))\n", 2, "compile time")

    def test_ord_multichar(self):
        self.assert_rejected(
            "putchar(ord('AB'))\n", 1, "single character")

    def test_chr_call(self):
        self.assert_rejected("putchar(chr(65))\n", 1, "chr()")

    def test_true_division(self):
        self.assert_rejected(
            "x = 10\nputchar(x / 2)\n", 2, "true division")

    def test_division_by_zero_const(self):
        self.assert_rejected(
            "putchar(5 // 0)\n", 1, "division or modulo by zero")

    # -- identifier edge cases ------------------------------------------
    def test_nonascii_identifier(self):
        self.assert_rejected(
            "変数 = 5\nputchar(変数)\n", 1,
            "not a valid C identifier")

    def test_leading_underscore(self):
        self.assert_rejected(
            "_x = 5\nputchar(_x)\n", 1, "not a valid C identifier")

    def test_c_keyword_int(self):
        self.assert_rejected("int = 5\nputchar(int)\n", 1, "C keyword")


# ===========================================================================
# Former B/C-class defects, cross-referenced to defects.md -- now FIXED in
# py2c.py. Each test now asserts the corrected behaviour (a CompileError at
# the accurate original-source line, with a message naming the user's own
# identifier, not an internal-renamed one or a downstream stage's error).
# ===========================================================================
class TestKnownDefects:
    # -- former C-class: were silently accepted, semantically wrong vs
    # CPython; now rejected with an accurate CompileError -----------------

    def test_stray_return_toplevel_should_be_rejected(self):
        """defects.md C1, FIXED: py2c.py _stmt_Return now checks
        `self.in_main` (previously it checked the always-false
        `self.locals is None`, dead code that let a stray top-level
        `return` compile straight into the synthesized main() and
        silently truncate the program)."""
        with pytest.raises(CompileError) as excinfo:
            compile_python_to_c("return 5\nputchar(65)\n")
        err = excinfo.value
        assert err.lineno == 1
        assert "outside function" in str(err)

    def test_bare_annassign_then_read_should_be_rejected(self):
        """defects.md C2, FIXED: a bare annotation (`x: int`, no value) no
        longer binds the name (py2c.py _stmt_AnnAssign), so a subsequent
        read falls through to the normal use-before-assignment check."""
        with pytest.raises(CompileError) as excinfo:
            compile_python_to_c("x: int\nputchar(x)\n")
        err = excinfo.value
        assert err.lineno == 2
        assert "used before it is assigned" in str(err)

    def test_unbound_augassign_should_be_rejected(self):
        """defects.md C3, FIXED: py2c.py _stmt_AugAssign now checks the
        target is already bound before treating `x += 1` as a read-modify-
        write."""
        with pytest.raises(CompileError) as excinfo:
            compile_python_to_c("x += 1\nputchar(x)\n")
        err = excinfo.value
        assert err.lineno == 1
        assert "used before it is assigned" in str(err)

    def test_decorator_should_be_rejected(self):
        """defects.md C4, FIXED: _register_function now rejects any
        non-empty decorator_list instead of silently ignoring it."""
        with pytest.raises(CompileError) as excinfo:
            compile_python_to_c(
                "@property\ndef foo(x):\n    return x\nputchar(foo(65))\n")
        err = excinfo.value
        assert err.lineno == 1
        assert "decorators are unsupported" in str(err)

    def test_global_shadows_param_should_be_rejected(self):
        """defects.md C5, FIXED: _stmt_Global now rejects `global x` when x
        names a parameter of the enclosing function."""
        with pytest.raises(CompileError) as excinfo:
            compile_python_to_c(
                "x = 1\ndef foo(x):\n    global x\n    return x\n"
                "putchar(foo(65))\n")
        err = excinfo.value
        assert err.lineno == 3
        assert "is parameter and global" in str(err)

    # -- former B-class: were rejected by the wrong stage / with a bad
    # message; now rejected by py2c itself with an accurate message -------

    def test_undefined_var_read_toplevel_should_be_rejected(self):
        """defects.md B1, FIXED: py2c itself now rejects an undefined
        module-level variable read -- compile_python_to_c raises directly,
        using the user's own identifier spelling and the original Python
        source line, instead of silently succeeding and deferring to a
        confusing downstream C2MgError (internally-renamed identifier,
        generated-.c line number)."""
        with pytest.raises(CompileError) as excinfo:
            compile_python_to_c("putchar(never_assigned)\n")
        err = excinfo.value
        assert err.lineno == 1
        assert "never_assigned" in str(err)
        assert "u_never_assigned" not in str(err)

    def test_undefined_var_read_func_should_be_rejected(self):
        """Same fix as above, function scope."""
        with pytest.raises(CompileError) as excinfo:
            compile_python_to_c(
                "def foo():\n    return undefined_var\nputchar(foo())\n")
        err = excinfo.value
        assert err.lineno == 2
        assert "undefined_var" in str(err)
        assert "u_undefined_var" not in str(err)

    def test_user_func_named_range_should_be_rejected_at_definition(self):
        """defects.md B3, FIXED: 'range' (and print/ord/chr, see below) is
        now reserved at function-registration time (_register_function ->
        check_func_name -> BUILTIN_CALL_NAMES), matching how
        main/putchar/getchar were already reserved -- so `def range(x):
        ...` is rejected right at the definition, with a name-collision
        message, instead of being accepted and then failing at every call
        site with the misleading "only valid in a 'for' loop header"
        message that blamed the wrong thing."""
        src = "def range(x):\n    return x + 1\nputchar(range(65))\n"
        with pytest.raises(CompileError) as excinfo:
            compile_python_to_c(src)
        err = excinfo.value
        assert err.lineno == 1
        assert "for" not in str(err)
        assert "reserved" in str(err)

    def test_user_func_named_print_should_be_rejected_at_definition(self):
        """defects.md B4, FIXED: same fix as B3, for 'print'."""
        src = "def print(x):\n    return x\nputchar(print(65))\n"
        with pytest.raises(CompileError) as excinfo:
            compile_python_to_c(src)
        assert excinfo.value.lineno == 1
        assert "reserved" in str(excinfo.value)

    def test_user_func_named_ord_should_be_rejected_at_definition(self):
        """defects.md B5, FIXED: same fix as B3, for 'ord'."""
        src = "def ord(x):\n    return x\nputchar(ord(65))\n"
        with pytest.raises(CompileError) as excinfo:
            compile_python_to_c(src)
        assert excinfo.value.lineno == 1
        assert "reserved" in str(excinfo.value)

    def test_user_func_named_chr_should_be_rejected_at_definition(self):
        """defects.md B6, FIXED: same fix as B3, for 'chr'."""
        src = "def chr(x):\n    return x\nputchar(chr(65))\n"
        with pytest.raises(CompileError) as excinfo:
            compile_python_to_c(src)
        assert excinfo.value.lineno == 1
        assert "reserved" in str(excinfo.value)


# ===========================================================================
# Batch-one syntax sugar (docs/python-subset-spec.md v2 plan items now
# implemented): four probe IDs from the original audit corpus that were
# A-class "correctly rejected" results are now A-class "correctly accepted"
# results instead, because the underlying constructs moved from the "must
# reject" column of the accept table into the "accept" column. Flipped here
# the same way TestKnownDefects flips B/C-class fixes: keep the original
# probe ID in a docstring for audit traceability, assert the NEW behaviour.
# ===========================================================================
class TestBatchOneSugar:
    def test_ternary_ifexp_now_accepted(self):
        """probe ID ast_ternary_ifexp, FLIPPED: `a if c else b` is now
        materialised into a temp through real if/else (see py2c.py
        _ifexp), so only the selected branch's side effects run."""
        c = compile_python_to_c(
            "x = 5\ny = 1 if x > 0 else 0\nputchar(y + 64)\n")
        assert "if(" in c and "} else {" in c

    def test_break_in_loop_now_accepted(self):
        """probe ID sem_break_in_loop, FLIPPED: break is now supported
        inside while/for loops via a flag-downgrade rewrite (the target C
        subset still has no real break/continue/goto)."""
        c = compile_python_to_c(
            "x = 1\nwhile x:\n    putchar(65)\n    break\n")
        assert "putchar(65);" in c

    def test_continue_in_loop_now_accepted(self):
        """probe ID sem_continue_in_loop, FLIPPED: continue is now
        supported the same way as break."""
        c = compile_python_to_c(
            "for i in range(3):\n    continue\n    putchar(65)\n")
        assert "i += 1;" in c

    def test_print_call_now_accepted(self):
        """probe ID sem_print_call, FLIPPED: print() with compile-time
        constant arguments now compiles to a fixed putchar() sequence
        (65 -> the decimal text "65" followed by the default "\\n" end)."""
        c = compile_python_to_c("print(65)\n")
        assert "putchar(54);" in c  # '6'
        assert "putchar(53);" in c  # '5'
        assert "putchar(10);" in c  # '\n'

    # -- new diagnostic surface introduced by this batch: break/continue
    # outside a loop (previously unreachable -- break/continue were
    # *always* rejected, in or out of a loop) --------------------------
    def test_break_outside_loop_rejected(self):
        with pytest.raises(CompileError) as excinfo:
            compile_python_to_c("break\nputchar(65)\n")
        assert excinfo.value.lineno == 1
        assert "outside loop" in str(excinfo.value)

    def test_continue_outside_loop_rejected(self):
        with pytest.raises(CompileError) as excinfo:
            compile_python_to_c("continue\nputchar(65)\n")
        assert excinfo.value.lineno == 1
        assert "outside loop" in str(excinfo.value)


if __name__ == "__main__":
    # Minimal standalone smoke test (no pytest dependency) -- exercises the
    # regression locks only; the xfail bookkeeping needs real pytest.
    import traceback
    failures = 0
    inst = TestAcceptedRejections()
    for name in dir(inst):
        if name.startswith("test_"):
            try:
                getattr(inst, name)()
            except Exception:
                failures += 1
                print("FAIL:", name)
                traceback.print_exc()
    print("{} failures (TestAcceptedRejections only; run under pytest for "
          "the full xfail-tracked defect corpus)".format(failures))
    sys.exit(1 if failures else 0)
