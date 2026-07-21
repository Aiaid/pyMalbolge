"""Tests for malbolge.compiler.c2mg (the Nagoya high-level C -> .mg port).

Two layers:

* Pure-Python unit tests (lexer, parser accept/reject, codegen structure,
  known reference bugs).  These need no external tool and never skip.
* Conformance tests against the captured corpus in
  ``test/fixtures/c2mg_corpus`` -- every ``.c`` must compile byte-identically
  to its ``.mg.ref``.  Skips gracefully only if the corpus directory is absent.
"""

import json
import os
import unittest

from malbolge.compiler.c2mg import (
    compile_c_to_mg,
    C2MgError,
    tokenize,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS_DIR = os.path.join(REPO_ROOT, "test", "fixtures", "c2mg_corpus")
MANIFEST = os.path.join(CORPUS_DIR, "manifest.json")


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------
class TestLexer(unittest.TestCase):
    def kinds(self, src):
        toks, _ = tokenize(src)
        return [t.kind for t in toks]

    def test_keywords_vs_ident(self):
        # exact keyword vs identifier that merely starts with one
        self.assertEqual(self.kinds("int"), ["INT", "EOF"])
        self.assertEqual(self.kinds("integer"), ["IDENT", "EOF"])
        toks, _ = tokenize("integer")
        self.assertEqual(toks[0].value, "integer")

    def test_number_multi_digit(self):
        toks, _ = tokenize("123")
        self.assertEqual((toks[0].kind, toks[0].value), ("NUMBER", 123))

    def test_leading_zero_splits(self):
        # 007 lexes as three NUMBER tokens 0,0,7 (flex quirk) -> not one number
        toks, _ = tokenize("007")
        nums = [(t.kind, t.value) for t in toks if t.kind == "NUMBER"]
        self.assertEqual(nums, [("NUMBER", 0), ("NUMBER", 0), ("NUMBER", 7)])

    def test_char_literal(self):
        toks, _ = tokenize("'A'")
        self.assertEqual((toks[0].kind, toks[0].value), ("NUMBER", 65))

    def test_backslash_char_literal_mistokenizes(self):
        # '\n' as 4 raw chars does NOT match the 3-char pattern; the backslash
        # hits the catch-all warning and the rest lexes as ident/quotes.
        toks, warns = tokenize(r"'\n'")
        self.assertTrue(any("cannot handle" in w for w in warns))

    def test_line_comment(self):
        self.assertEqual(self.kinds("int // bool\n bool"), ["INT", "BOOL", "EOF"])

    def test_block_comment_same_line(self):
        self.assertEqual(self.kinds("int /* x */ bool"), ["INT", "BOOL", "EOF"])

    def test_block_comment_does_not_span_newline(self):
        # unclosed on the line -> '/' and '*' fall through to catch-all warnings
        toks, warns = tokenize("int /* x\n bool")
        self.assertTrue(any("cannot handle" in w for w in warns))

    def test_unknown_char_warns_nonfatal(self):
        toks, warns = tokenize("int @ bool")
        self.assertIn("cannot handle such characters: @", warns)
        # scanning continues past the bad char
        self.assertEqual([t.kind for t in toks], ["INT", "BOOL", "EOF"])

    def test_two_char_operators(self):
        self.assertEqual(
            self.kinds("++ -- && || == != <= >= += -="),
            ["INC", "DEC", "AND", "OR", "EQ", "NEQ", "LTE", "GTE",
             "PLUS_ASSIGN", "MINUS_ASSIGN", "EOF"],
        )


# ---------------------------------------------------------------------------
# Codegen structure (tiny inputs, structural assertions)
# ---------------------------------------------------------------------------
class TestCodegenStructure(unittest.TestCase):
    def test_hello_minimal(self):
        out = compile_c_to_mg("int MAIN(){ putchar(65); }")
        self.assertIn("DEF MAIN", out)
        self.assertIn("END", out)
        self.assertIn("OUTPUT", out)

    def test_main_uppercased(self):
        out = compile_c_to_mg("int main(){ putchar(65); }")
        self.assertIn("DEF MAIN", out)
        self.assertIn("PROTO MAIN", out)

    def test_identifier_mangling_lowercase(self):
        out = compile_c_to_mg("int foo; int main(){ foo = 1; }")
        # lowercase "u_" prefix (NOT "U_" -- that is the other Nagoya tool)
        self.assertIn("u_foo", out)
        self.assertNotIn("U_foo", out)

    def test_con_not_declared_as_var(self):
        out = compile_c_to_mg("int a=64; int main(){ a++; putchar(a); }")
        # CON0/1/2 are referenced but never declared with VAR
        self.assertNotIn("VAR CON0", out)
        self.assertNotIn("VAR CON1", out)
        self.assertNotIn("VAR CON2", out)
        self.assertIn("ROT CON2", out)

    def test_global_var_lines_sorted(self):
        out = compile_c_to_mg("int a=64; int main(){ a++; putchar(a); }")
        var_names = [ln[4:].split("=")[0] for ln in out.splitlines()
                     if ln.startswith("VAR ") and not ln.startswith("VAR RETURN")]
        # the leading (global) VAR block is emitted in ascending name order
        self.assertEqual(var_names, sorted(var_names))

    def test_assembly_section_order(self):
        out = compile_c_to_mg("int a=64; int main(){ a++; putchar(a); }")
        i_var = out.index("VAR ")
        i_flag = out.index("FLAG ")
        i_proto = out.index("PROTO ")
        i_def = out.index("DEF ")
        self.assertTrue(i_var < i_flag < i_proto < i_def)

    def test_negative_init(self):
        out = compile_c_to_mg("int g = -5; int main(){ putchar(g); }")
        # -5 stored as 3^20 - 5 = 3486784396
        self.assertIn("VAR u_g=3486784396", out)

    def test_char_literal_init(self):
        out = compile_c_to_mg("int i='A'; int main(){ putchar(i); }")
        self.assertIn("VAR u_i=65", out)

    def test_local_gets_entry_init_copy(self):
        # every non-static local gets an explicit copy-from-CONST at entry
        # (VAR_UNINITIALIZED is dead code); bare `int x` => copy from CONST_0.
        out = compile_c_to_mg("int foo(){ int x; return x; } int main(){}")
        self.assertIn("CONST_0", out)

    def test_recursion_protection_always_applied(self):
        # every function is treated recursive => CALL sites are stack-wrapped
        src = ("int f(int n){ int r; r = n; return r; }"
               "int main(){ putchar(f(3)); }")
        out = compile_c_to_mg(src)
        self.assertIn("CALL F", out)
        # RETURN_ADDR push/pop appears around calls
        self.assertIn("RETURN_ADDR@F", out)


# ---------------------------------------------------------------------------
# Operator precedence (STANDARD -- confirmed against parser.output + binary)
# ---------------------------------------------------------------------------
class TestPrecedence(unittest.TestCase):
    def test_and_binds_looser_than_lt(self):
        # a < b && c < d  parses as (a<b) && (c<d).  Under the "no precedence"
        # theory it would be a < (b && (c<d)) and checkBool(b) would raise.
        src = ("int main(){ int a,b,c,d; a=1;b=2;c=3;d=4;"
               " if(a < b && c < d){ putchar(a); } }")
        out = compile_c_to_mg(src)  # must NOT raise
        self.assertIn("DEF MAIN", out)

    def test_eq_binds_looser_than_lt(self):
        # (a<b) == (c<d) feeds bool operands into eq()'s checkInt -> "Only int"
        src = ("int main(){ int a,b,c,d; a=1;b=2;c=3;d=4;"
               " if(a < b == c < d){ putchar(a); } }")
        with self.assertRaises(C2MgError) as cm:
            compile_c_to_mg(src)
        self.assertIn("Only int", cm.exception.message)

    def test_add_binds_tighter_than_lt(self):
        # a + b < c parses as (a+b) < c -> valid, all int
        src = ("int main(){ int a,b,c; a=1;b=2;c=3;"
               " if(a + b < c){ putchar(a); } }")
        out = compile_c_to_mg(src)
        self.assertIn("DEF MAIN", out)

    def test_assignment_is_lowest(self):
        # c = a + b groups as c = (a+b); does not raise
        src = "int main(){ int a,b,c; a=1;b=2; c = a + b; putchar(c); }"
        out = compile_c_to_mg(src)
        self.assertIn("DEF MAIN", out)


# ---------------------------------------------------------------------------
# Error handling (pure-Python; both the reference and this port reject these)
# ---------------------------------------------------------------------------
class TestErrors(unittest.TestCase):
    def assertRejects(self, src, needle=None):
        with self.assertRaises(C2MgError) as cm:
            compile_c_to_mg(src)
        if needle is not None:
            self.assertIn(needle, cm.exception.message)
        return cm.exception

    def test_undefined_variable(self):
        self.assertRejects("int main(){ putchar(zzz); }", "is not defined")

    def test_duplicate_global(self):
        self.assertRejects("int a; int a; int main(){}", "already defined")

    def test_type_mismatch(self):
        self.assertRejects("int main(){ int a; bool b; a = a < a; }",
                           "Type mismatch")

    def test_cannot_call_main(self):
        self.assertRejects("int main(){ main(); }", "Can not call 'main'")

    def test_undefined_function(self):
        self.assertRejects("int main(){ putchar(nope(1)); }",
                           "Undefined function")

    def test_argument_size_mismatch(self):
        self.assertRejects(
            "int f(int x){ return x; } int main(){ putchar(f(1,2)); }",
            "Argument size missmatch")

    def test_function_redefinition(self):
        self.assertRejects(
            "int f(){return 0;} int f(){return 0;} int main(){}",
            "already defined")

    def test_static_array_rejected(self):
        self.assertRejects("static int a[3]; int main(){}",
                           "Static array is not supported")

    def test_error_carries_line_number(self):
        exc = self.assertRejects("int main(){\n\n putchar(undef_here); }")
        self.assertIsNotNone(exc.lineno)


# ---------------------------------------------------------------------------
# Known reference bugs that MUST be reproduced (fidelity checks)
# ---------------------------------------------------------------------------
class TestKnownBugs(unittest.TestCase):
    def test_bool_local_type_mismatch(self):
        # A bool local's mandatory entry-init pulls the INT-typed CONST_0
        # (const cache is keyed by value, pre-seeded INT) -> Type mismatch.
        with self.assertRaises(C2MgError) as cm:
            compile_c_to_mg("int main(){ int a; bool b; a = 1; }")
        self.assertIn("Type mismatch", cm.exception.message)

    def test_true_literal_is_int_typed(self):
        # `true` returns the pre-existing INT-typed CONST_3486784399, so storing
        # it into a bool variable raises Type mismatch.
        with self.assertRaises(C2MgError):
            compile_c_to_mg("int main(){ bool b; b = true; }")

    def test_fib_double_recursion_bug_reproduced(self):
        # The upstream inline double-recursion codegen bug: this compiles
        # (no error) and matches the captured broken reference output.  We only
        # assert it compiles here; byte-fidelity is covered by the corpus test
        # against upstream/official_fib.mg.ref.
        src = ("int fib(int n){ int r;"
               " if(n < 2){ r = n; } else { r = fib(n-1) + fib(n-2); }"
               " return r; }"
               "int main(){ putchar(fib(4)); }")
        out = compile_c_to_mg(src)
        self.assertIn("DEF FIB", out)


# ---------------------------------------------------------------------------
# Conformance against the captured corpus
# ---------------------------------------------------------------------------
def _load_manifest():
    if not os.path.isfile(MANIFEST):
        return None
    with open(MANIFEST) as fh:
        return json.load(fh)


@unittest.skipUnless(os.path.isdir(CORPUS_DIR) and os.path.isfile(MANIFEST),
                     "c2mg conformance corpus not present")
class TestCorpusConformance(unittest.TestCase):
    """Each corpus .c must compile byte-identically to its .mg.ref."""

    @classmethod
    def setUpClass(cls):
        cls.manifest = _load_manifest()

    def _check(self, entry):
        cpath = os.path.join(REPO_ROOT, entry["path"])
        ref = os.path.splitext(cpath)[0] + ".mg.ref"
        with open(cpath) as fh:
            src = fh.read()
        with open(ref) as fh:
            want = fh.read()
        got = compile_c_to_mg(src)
        if got != want:
            # produce a compact first-difference message
            gl, wl = got.splitlines(), want.splitlines()
            msg = "length %d vs %d" % (len(gl), len(wl))
            for i in range(min(len(gl), len(wl))):
                if gl[i] != wl[i]:
                    msg = "line %d: got %r want %r" % (i + 1, gl[i], wl[i])
                    break
            self.fail("%s mismatch: %s" % (entry["path"], msg))

    def test_all_corpus_entries(self):
        manifest = self.manifest
        self.assertTrue(manifest, "manifest is empty")
        count = 0
        for entry in manifest:
            with self.subTest(path=entry["path"]):
                self._check(entry)
                count += 1
        self.assertEqual(count, len(manifest))


def _build_corpus_methods():
    """Give each corpus file its own test method for granular reporting."""
    manifest = _load_manifest()
    if not manifest:
        return
    for entry in manifest:
        name = os.path.splitext(os.path.basename(entry["path"]))[0]

        def method(self, entry=entry):
            self._check(entry)

        setattr(TestCorpusConformance, "test_corpus_" + name, method)


_build_corpus_methods()


if __name__ == "__main__":
    unittest.main()
