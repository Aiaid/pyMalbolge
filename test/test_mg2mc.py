"""
Tests for malbolge.compiler.mg2mc -- the pure-Python port of the Nagoya
``.mg`` -> ``.mc`` translator (ref/nagoya-ternary/parser).

Two layers:

* Unit tests (never skipped): exercise ``translate_mg_to_mc`` / ``Mg2McError``
  directly against known-good output and known-bad input.  These do not need the
  ref/ toolchain built.

* Code-generation style tests (never skipped): the ``op_style``/``jmp_style``
  keyword arguments, including a byte-level regression that the defaults are
  exactly the old fixed ``-m -c`` behaviour.

* Conformance tests (skipped when ``ref/nagoya-ternary/parser`` is absent):
  byte-for-byte diff of ``translate_mg_to_mc`` against
  ``ref/nagoya-ternary/parser -m -c -s 1`` for a corpus of real ``.mg`` programs,
  plus "both reject" checks for error inputs.

* Style behaviour equivalence (gated behind ``MALBOLGE_SLOW_TESTS=1``): assembles
  the fixtures under all four styles and runs the resulting Malbolge20 programs.

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

from malbolge import malbolge20
from malbolge.compiler.mc2mb import assemble_mc_to_mb
from malbolge.compiler.mg2mc import Option, translate_mg_to_mc, Mg2McError

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARSER_PATH = os.path.join(REPO_ROOT, 'ref', 'nagoya-ternary', 'parser')
FIXTURES = os.path.join(REPO_ROOT, 'test', 'fixtures', 'nagoya')
MG2MC_DIR = os.path.join(FIXTURES, 'mg2mc')
MG2MC_ERR_DIR = os.path.join(MG2MC_DIR, 'errors')

SUBPROCESS_TIMEOUT = 120

SLOW = os.environ.get('MALBOLGE_SLOW_TESTS') == '1'

STYLES = [(op, jmp) for op in ('cluster', 'inline')
          for jmp in ('main', 'direct')]


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
# Code-generation styles (no ref/ dependency)
# ---------------------------------------------------------------------------

def _fixture_mgs():
    """The five pipeline fixtures, as (basename, source) pairs."""
    return [(os.path.basename(p), read_text(p))
            for p in sorted(glob.glob(os.path.join(FIXTURES, 'mg_*.mg')))]


class TestStyleDefaults(unittest.TestCase):
    """The defaults must stay the old pinned ``-m -c`` behaviour, byte for byte.

    TestConformance already pins the default output against the ref parser, but
    only when ref/ is built; these run everywhere.
    """

    def test_default_equals_explicit_cluster_main(self):
        for name, mg in _fixture_mgs():
            with self.subTest(fixture=name):
                self.assertEqual(
                    translate_mg_to_mc(mg),
                    translate_mg_to_mc(mg, op_style="cluster",
                                       jmp_style="main"))

    def test_default_still_matches_golden_mc(self):
        # The committed .mc goldens were produced by `parser -m -c -s 1`.
        for name, mg in _fixture_mgs():
            golden = os.path.join(FIXTURES, name[:-3] + '.mc')
            with self.subTest(fixture=name):
                self.assertEqual(translate_mg_to_mc(mg), read_text(golden))


class TestStyleSelection(unittest.TestCase):
    """All four deterministic styles translate the fixture corpus."""

    # `FLAG 1/2` lines per fixture, measured. Only op_style moves these: the
    # inline expansion of OUTPUT/INPUT/SET/RESET drops the per-operation
    # cluster branch flag, so inline <= cluster everywhere.
    FLAG_1_2 = {
        'cluster': {'mg_a_minimal.mg': 2, 'mg_b_hi.mg': 5, 'mg_c_echo.mg': 3,
                    'mg_d_repeat.mg': 8, 'mg_e_call.mg': 14},
        'inline':  {'mg_a_minimal.mg': 1, 'mg_b_hi.mg': 3, 'mg_c_echo.mg': 1,
                    'mg_d_repeat.mg': 4, 'mg_e_call.mg': 13},
    }

    def test_every_style_translates_the_fixtures(self):
        for name, mg in _fixture_mgs():
            for op_style, jmp_style in STYLES:
                with self.subTest(fixture=name, op=op_style, jmp=jmp_style):
                    mc = translate_mg_to_mc(mg, op_style=op_style,
                                            jmp_style=jmp_style)
                    self.assertTrue(mc.startswith("PROGRAM_START_TO ENTRY@MAIN\n"))
                    self.assertTrue(mc.endswith("}\n\n"))

    def test_flag_counts_track_op_style(self):
        for name, mg in _fixture_mgs():
            for op_style, jmp_style in STYLES:
                with self.subTest(fixture=name, op=op_style, jmp=jmp_style):
                    mc = translate_mg_to_mc(mg, op_style=op_style,
                                            jmp_style=jmp_style)
                    count = sum(1 for line in mc.splitlines()
                                if line.startswith('FLAG 1/2'))
                    self.assertEqual(count, self.FLAG_1_2[op_style][name])

    def test_inline_never_needs_more_flags_than_cluster(self):
        for name in self.FLAG_1_2['cluster']:
            self.assertLessEqual(self.FLAG_1_2['inline'][name],
                                 self.FLAG_1_2['cluster'][name])

    def test_styles_actually_change_the_output(self):
        mg = read_text(os.path.join(FIXTURES, 'mg_e_call.mg'))
        outputs = {(op, jmp): translate_mg_to_mc(mg, op_style=op,
                                                 jmp_style=jmp)
                   for op, jmp in STYLES}
        self.assertEqual(len(set(outputs.values())), len(STYLES))


class TestStyleErrors(unittest.TestCase):
    def test_unknown_op_style(self):
        with self.assertRaises(ValueError) as cm:
            translate_mg_to_mc("DEF MAIN\n  OUTPUT\nEND\n", op_style="block")
        self.assertIn("'cluster'", str(cm.exception))
        self.assertIn("'inline'", str(cm.exception))

    def test_unknown_jmp_style(self):
        with self.assertRaises(ValueError) as cm:
            translate_mg_to_mc("DEF MAIN\n  OUTPUT\nEND\n", jmp_style="rand")
        self.assertIn("'main'", str(cm.exception))
        self.assertIn("'direct'", str(cm.exception))

    def test_rand_paths_are_still_unported(self):
        """Upstream's default (neither -c/-i, neither -m/-d) mixes both styles
        per decision point via mt19937. No style selectable through the public
        API reaches those branches, so poke the fields directly."""
        opt = Option()
        opt.op_inline = True   # back to Option.h's default: -c not given
        with self.assertRaises(RuntimeError):
            opt.use_op_block()
        opt = Option()
        opt.jmp_directly = True  # -m not given
        with self.assertRaises(RuntimeError):
            opt.back_to_main()


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


# ---------------------------------------------------------------------------
# Style behaviour equivalence (slow: assembles and runs .mb programs)
# ---------------------------------------------------------------------------

@unittest.skipUnless(SLOW, 'set MALBOLGE_SLOW_TESTS=1 (assembles 20 .mb '
                           'programs of up to 800 KB and runs them)')
class TestStyleBehaviourEquivalence(unittest.TestCase):
    """The four styles are alternative encodings of the same program, so the
    assembled Malbolge20 programs must behave identically.

    mg_a_minimal is deliberately excluded: it is a bare ``OUTPUT`` with no
    preceding ROT, so it prints whatever the bootstrap left in the A register --
    an undefined value, and one that genuinely differs between the styles
    ('\\xde' under cluster, '\\x9e' under inline). Adding a single ``ROT`` to
    define A makes all four agree; there is nothing to compare without one.
    """

    CASES = {
        'mg_b_hi.mg': ('', 'Hi'),
        'mg_c_echo.mg': ('Q', 'Q'),
        'mg_d_repeat.mg': ('', 'AAAA'),
        'mg_e_call.mg': ('', 'X'),
    }

    def test_all_styles_produce_the_same_output(self):
        for name, (stdin, expected) in sorted(self.CASES.items()):
            mg = read_text(os.path.join(FIXTURES, name))
            for op_style, jmp_style in STYLES:
                with self.subTest(fixture=name, op=op_style, jmp=jmp_style):
                    mc = translate_mg_to_mc(mg, op_style=op_style,
                                            jmp_style=jmp_style)
                    mb = assemble_mc_to_mb(mc)
                    self.assertEqual(malbolge20.eval(mb, stdin), expected)


if __name__ == '__main__':
    unittest.main()
