"""
Tests for malbolge.compiler.mg2mc -- the pure-Python port of the Nagoya
``.mg`` -> ``.mc`` translator (ref/nagoya-ternary/parser).

Two layers:

* Unit tests (never skipped): exercise ``translate_mg_to_mc`` / ``Mg2McError``
  directly against known-good output and known-bad input.  These do not need the
  ref/ toolchain built.

* Conformance tests (skipped when ``ref/nagoya-ternary/parser`` is absent):
  byte-for-byte diff of ``translate_mg_to_mc`` against
  ``ref/nagoya-ternary/parser -m -c -s 1`` for a corpus of real ``.mg`` programs,
  plus "both reject" checks for error inputs.

Corpus:
  * test/fixtures/nagoya/mg_*.mg              (5 pipeline fixtures)
  * runtime/mg/official/*.mg                  (13 official templates)
  * runtime/mg/tests/t_*.mg                   (7 primitive test drivers)
  * test/fixtures/nagoya/mg2mc/*.mg           (authored SWITCH/IF/FLAG/IND_OPR/
                                               nested/cross-routine + two README
                                               examples)
  * test/fixtures/nagoya/mg2mc/errors/*.mg    (authored rejection cases)
"""

import glob
import os
import subprocess
import unittest

from malbolge.compiler.mg2mc import translate_mg_to_mc, Mg2McError

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARSER_PATH = os.path.join(REPO_ROOT, 'ref', 'nagoya-ternary', 'parser')
FIXTURES = os.path.join(REPO_ROOT, 'test', 'fixtures', 'nagoya')
MG2MC_DIR = os.path.join(FIXTURES, 'mg2mc')
MG2MC_ERR_DIR = os.path.join(MG2MC_DIR, 'errors')

SUBPROCESS_TIMEOUT = 120


def have_ref_parser():
    return os.path.exists(PARSER_PATH) and os.access(PARSER_PATH, os.X_OK)


def run_ref_parser(mg_path):
    """Run ``parser -m -c -s 1 <mg_path>``; return (returncode, stdout_bytes,
    stderr_bytes)."""
    result = subprocess.run(
        [PARSER_PATH, '-m', '-c', '-s', '1', mg_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=SUBPROCESS_TIMEOUT,
    )
    return result.returncode, result.stdout, result.stderr


def ref_rejected(returncode, stderr_bytes):
    """True when the ref parser signalled an error for this input.

    Upstream exits 0 for syntax/semantic errors and only writes to stderr; a
    PROTO-without-DEF instead crashes (negative returncode).  Either counts as a
    rejection.
    """
    if returncode != 0:
        return True
    for marker in (b'syntax error', b'Undefined', b'already defined',
                   b"REPEAT' to break", b'not defined'):
        if marker in stderr_bytes:
            return True
    return False


def read_text(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


# ---------------------------------------------------------------------------
# Unit tests (no ref/ dependency)
# ---------------------------------------------------------------------------

class TestTranslateBasics(unittest.TestCase):
    def test_minimal_output_matches_golden(self):
        """DEF MAIN / OUTPUT / END must reproduce the committed golden .mc
        (test/fixtures/nagoya/mg_a_minimal.mc), byte for byte."""
        mg = read_text(os.path.join(FIXTURES, 'mg_a_minimal.mg'))
        expected = read_text(os.path.join(FIXTURES, 'mg_a_minimal.mc'))
        self.assertEqual(translate_mg_to_mc(mg), expected)

    def test_output_ends_with_blank_line(self):
        mc = translate_mg_to_mc("DEF MAIN\n  OUTPUT\nEND\n")
        self.assertTrue(mc.endswith("}\n\n"))

    def test_header_and_builtins(self):
        mc = translate_mg_to_mc("DEF MAIN\n  OUTPUT\nEND\n")
        self.assertTrue(mc.startswith("PROGRAM_START_TO ENTRY@MAIN\n"))
        # Builtin GLOBAL variables appear in sorted order.
        self.assertIn("BASE:0\nCON0:0\nCON1:1743392200\nCON2:3486784400\n", mc)

    def test_flags_sorted(self):
        mc = translate_mg_to_mc("DEF MAIN\n  OUTPUT\nEND\n")
        idx0 = mc.index("FLAG0")
        idx_case0 = mc.index("FLAG_CASE0")
        idx_jmp = mc.index("FLAG_JMP")
        # lexicographic: 'FLAG0' < 'FLAG_CASE0' < 'FLAG_JMP'
        self.assertLess(idx0, idx_case0)
        self.assertLess(idx_case0, idx_jmp)

    def test_ternary_literal(self):
        # 10t (ternary) == 3 decimal; goes into the GLOBAL var table verbatim.
        mc = translate_mg_to_mc("VAR X = 10t\nDEF MAIN\n  ROT X\nEND\n")
        self.assertIn("U_X:3", mc)

    def test_user_identifiers_are_prefixed(self):
        mc = translate_mg_to_mc("VAR foo = 7\nDEF MAIN\n  ROT foo\nEND\n")
        self.assertIn("U_foo:7", mc)

    def test_bare_hash_is_non_fatal(self):
        # A line consisting of a single '#' is an "unknown character" that the
        # lexer skips (matching scanner.ll's '.' rule), not an error.
        mc = translate_mg_to_mc("#\nDEF MAIN\n  OUTPUT\nEND\n")
        self.assertIn("ROUTINE MAIN{", mc)


class TestTranslateErrors(unittest.TestCase):
    def _err(self, src):
        with self.assertRaises(Mg2McError) as cm:
            translate_mg_to_mc(src)
        return cm.exception

    def test_undefined_variable(self):
        e = self._err("DEF MAIN\n  ROT Y\nEND\n")
        self.assertIn("Undefined variable", str(e))
        self.assertEqual(e.line, 2)

    def test_undefined_flag(self):
        e = self._err("DEF MAIN\n  SET F\nEND\n")
        self.assertIn("Undefined flag", str(e))

    def test_undefined_routine(self):
        e = self._err("DEF MAIN\n  CALL NOPE\nEND\n")
        self.assertIn("Undefined routine", str(e))

    def test_duplicate_variable(self):
        e = self._err("DEF MAIN\n  VAR X = 1\n  VAR X = 2\n  OUTPUT\nEND\n")
        self.assertIn("already defined", str(e))

    def test_duplicate_routine(self):
        e = self._err("DEF MAIN\n  OUTPUT\nEND\nDEF MAIN\n  OUTPUT\nEND\n")
        self.assertIn("already defined", str(e))

    def test_break_too_deep(self):
        e = self._err("DEF MAIN\n  REPEAT 5\n    BREAK 2\n  END\nEND\n")
        self.assertIn("REPEAT", str(e))

    def test_leading_zero_is_syntax_error(self):
        # 007 lexes as 0 / 0 / 7 -> not a single number -> syntax error.
        self._err("VAR X = 007\nDEF MAIN\n  OUTPUT\nEND\n")

    def test_flag_inside_def(self):
        self._err("DEF MAIN\n  FLAG F = TRUE\n  OUTPUT\nEND\n")

    def test_var_after_statement(self):
        self._err("DEF MAIN\n  OUTPUT\n  VAR X = 5\nEND\n")

    def test_proto_without_def(self):
        e = self._err("PROTO FOO\nDEF MAIN\n  CALL FOO\nEND\n")
        self.assertIn("never defined", str(e))

    def test_error_line_number_present(self):
        e = self._err("DEF MAIN\n\n\n  ROT Y\nEND\n")
        self.assertEqual(e.line, 4)


# ---------------------------------------------------------------------------
# Conformance tests (need ref/nagoya-ternary/parser)
# ---------------------------------------------------------------------------

def _conformance_corpus():
    files = []
    files += sorted(glob.glob(os.path.join(FIXTURES, 'mg_*.mg')))
    files += sorted(glob.glob(os.path.join(REPO_ROOT, 'runtime', 'mg',
                                           'official', '*.mg')))
    files += sorted(glob.glob(os.path.join(REPO_ROOT, 'runtime', 'mg',
                                           'tests', 't_*.mg')))
    files += sorted(glob.glob(os.path.join(MG2MC_DIR, '*.mg')))
    return files


@unittest.skipUnless(have_ref_parser(),
                     "ref/nagoya-ternary/parser not built")
class TestConformance(unittest.TestCase):
    """Byte-for-byte agreement with parser -m -c -s 1."""

    def test_corpus_byte_exact(self):
        corpus = _conformance_corpus()
        self.assertGreater(len(corpus), 20,
                           "expected the full corpus to be present")
        mismatches = []
        for mg_path in corpus:
            rc, ref_stdout, ref_stderr = run_ref_parser(mg_path)
            ref = ref_stdout.decode('utf-8', 'surrogateescape')
            mine = translate_mg_to_mc(read_text(mg_path))
            if mine != ref:
                mismatches.append(os.path.relpath(mg_path, REPO_ROOT))
        self.assertEqual(mismatches, [], "byte mismatch in: %r" % mismatches)


@unittest.skipUnless(have_ref_parser(),
                     "ref/nagoya-ternary/parser not built")
class TestErrorConformance(unittest.TestCase):
    """Every authored error input is rejected by the ref parser AND raises
    Mg2McError in the port."""

    def test_errors_both_reject(self):
        err_files = sorted(glob.glob(os.path.join(MG2MC_ERR_DIR, '*.mg')))
        self.assertGreater(len(err_files), 5)
        for mg_path in err_files:
            rc, ref_stdout, ref_stderr = run_ref_parser(mg_path)
            with self.subTest(fixture=os.path.basename(mg_path)):
                self.assertTrue(
                    ref_rejected(rc, ref_stderr),
                    "ref parser did not reject %s" % mg_path)
                with self.assertRaises(Mg2McError):
                    translate_mg_to_mc(read_text(mg_path))


if __name__ == '__main__':
    unittest.main()
