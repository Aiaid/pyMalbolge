"""
Conformance tests for malbolge.compiler.mc2mb -- the pure-Python port of the
Nagoya "lowass" assembler (LAL / .mc -> Malbolge20 / .mb).

Corpus: the five checked-in ``test/fixtures/nagoya/mg_*.mc`` programs plus the
three ``ref/nagoya-lowass/sample/*.mc`` samples.

Three layers of verification:

* **Stage 1 byte-exactness** -- ``parse_mc_to_data`` output is diffed
  byte-for-byte against ``PERL_HASH_SEED=0 perl parse_mc2.pl`` (skipped when
  ``perl`` or the reference script is unavailable).

* **End-to-end behaviour** -- the assembled ``.mb`` is run on pyMalbolge's own
  Malbolge20 interpreter and its I/O checked against the known-good output
  (input path covered by ``mg_c_echo``).  This needs only the package itself.

* **Toolchain conformance** -- when the reference C++ ``init`` binary and the
  Nagoya C interpreter are present, the port's ``.mb`` is compared structurally
  (every non-padding cell identical to ``init``'s output) and behaviourally
  (both .mb variants, on both interpreters, produce identical I/O).  These are
  skipped automatically when ``ref/`` binaries are missing.
"""

import os
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from malbolge.compiler.mc2mb import (            # noqa: E402
    parse_mc_to_data, assemble_mc_to_mb, _Assembler,
)

SUBPROCESS_TIMEOUT = 300  # big programs can take minutes on the interpreter

PARSE_MC2_PL = os.path.join(REPO_ROOT, 'ref', 'nagoya-lowass', 'parse_mc2.pl')
INIT_BIN = os.path.join(REPO_ROOT, 'ref', 'nagoya-lowass', 'init', 'init')
C_INTERP = os.path.join(REPO_ROOT, 'ref', 'nagoya-malbolge20-interpreter',
                        'malbolge20')

FIX = os.path.join(REPO_ROOT, 'test', 'fixtures', 'nagoya')
SAMPLE = os.path.join(REPO_ROOT, 'ref', 'nagoya-lowass', 'sample')

# (name, mc_path, expected_stdout | None, stdin)
# expected None + name == 'mg_c_echo' means "output equals stdin".
CORPORA = [
    ('mg_a_minimal', os.path.join(FIX, 'mg_a_minimal.mc'), b'\xde', b''),
    ('mg_b_hi', os.path.join(FIX, 'mg_b_hi.mc'), b'Hi', b''),
    ('mg_c_echo', os.path.join(FIX, 'mg_c_echo.mc'), None, b'Q'),
    ('mg_d_repeat', os.path.join(FIX, 'mg_d_repeat.mc'), b'AAAA', b''),
    ('mg_e_call', os.path.join(FIX, 'mg_e_call.mc'), b'X', b''),
    ('hello', os.path.join(SAMPLE, 'hello.mc'), b'Hello', b''),
    ('hello-transFrom-mg', os.path.join(SAMPLE, 'hello-transFrom-mg.mc'),
     b'Hello', b''),
    ('hello-transFrom-c-mg', os.path.join(SAMPLE, 'hello-transFrom-c-mg.mc'),
     b'Hello', b''),
]


def _have(path):
    return os.path.exists(path)


def _which_perl():
    from shutil import which
    return which('perl')


# --- module-level cache: assemble each present corpus exactly once ----------
# Assembly of the largest program takes tens of seconds, so we do it just once
# and reuse the result (and its real/non-padding cell map) across tests.
_CACHE = {}
_TMPDIR = None


def setUpModule():
    global _TMPDIR
    _TMPDIR = tempfile.mkdtemp(prefix='mc2mb_test_')
    for name, mc, _exp, _stdin in CORPORA:
        if not _have(mc):
            continue
        with open(mc) as f:
            src = f.read()
        asm = _Assembler()
        asm.setup_data_module()
        data = parse_mc_to_data(src)
        asm.memory_init_code1(data)
        real = dict(asm.code)          # non-padding cells (before finish fill)
        mb = asm.finish()
        mb_bytes = mb.encode('latin-1')
        mb_path = os.path.join(_TMPDIR, name + '.py.mb')
        with open(mb_path, 'wb') as f:
            f.write(mb_bytes)
        _CACHE[name] = {
            'src': src, 'data': data, 'mb': mb_bytes,
            'real': real, 'mb_path': mb_path,
        }


def tearDownModule():
    if _TMPDIR and os.path.isdir(_TMPDIR):
        import shutil
        shutil.rmtree(_TMPDIR, ignore_errors=True)


def _run_pymalbolge(mb_path, stdin=b''):
    r = subprocess.run(
        [sys.executable, '-m', 'malbolge', '--variant=malbolge20', mb_path],
        input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=SUBPROCESS_TIMEOUT, cwd=REPO_ROOT)
    return r.returncode, r.stdout


def _run_c_interp(mb_path, stdin=b''):
    r = subprocess.run(
        [C_INTERP, mb_path], input=stdin, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=SUBPROCESS_TIMEOUT)
    return r.returncode, r.stdout


def _run_init(data_path, out_path):
    with open(out_path, 'wb') as f:
        subprocess.run([INIT_BIN, data_path], stdout=f, stderr=subprocess.DEVNULL,
                       timeout=SUBPROCESS_TIMEOUT, check=True)


class TestStage1ByteExact(unittest.TestCase):
    """parse_mc_to_data must reproduce PERL_HASH_SEED=0 parse_mc2.pl output
    byte-for-byte."""

    def _perl_data(self, mc_path):
        env = dict(os.environ, PERL_HASH_SEED='0')
        with tempfile.TemporaryDirectory() as td:
            prefix = os.path.join(td, 'out')
            subprocess.run(['perl', PARSE_MC2_PL, mc_path, prefix],
                           env=env, cwd=td, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=SUBPROCESS_TIMEOUT)
            with open(prefix + '.data', 'rb') as f:
                return f.read()

    def test_byte_exact(self):
        if _which_perl() is None or not _have(PARSE_MC2_PL):
            self.skipTest('perl or parse_mc2.pl unavailable')
        for name, mc, _exp, _stdin in CORPORA:
            if not _have(mc):
                continue
            with self.subTest(corpus=name):
                ref = self._perl_data(mc)
                with open(mc) as f:
                    got = parse_mc_to_data(f.read()).encode('latin-1')
                self.assertEqual(got, ref,
                                 '%s: .data differs from parse_mc2.pl' % name)


class TestEndToEndBehaviour(unittest.TestCase):
    """The assembled .mb, run on pyMalbolge, must produce the expected I/O.

    Needs only the package under test (no ref/ toolchain)."""

    def test_expected_output(self):
        for name, mc, exp, stdin in CORPORA:
            if name not in _CACHE:
                self.skipTest('%s .mc not present' % name)
            with self.subTest(corpus=name):
                rc, out = _run_pymalbolge(_CACHE[name]['mb_path'], stdin)
                self.assertEqual(rc, 0, '%s: nonzero exit' % name)
                want = stdin if exp is None else exp
                self.assertEqual(out, want, '%s: output mismatch' % name)

    def test_echo_input_path(self):
        """mg_c_echo exercises the INPUT opcode: output must equal input."""
        if 'mg_c_echo' not in _CACHE:
            self.skipTest('mg_c_echo not present')
        mb_path = _CACHE['mg_c_echo']['mb_path']
        for byte in (b'Q', b'\x00', b'\xff', b'A'):
            with self.subTest(byte=byte):
                rc, out = _run_pymalbolge(mb_path, byte)
                self.assertEqual(rc, 0)
                self.assertEqual(out, byte)

    def test_api_smoke(self):
        """assemble_mc_to_mb is the public one-shot entry point."""
        if 'hello' not in _CACHE:
            self.skipTest('hello sample not present')
        mb = assemble_mc_to_mb(_CACHE['hello']['src'])
        self.assertEqual(mb.encode('latin-1'), _CACHE['hello']['mb'])


class TestToolchainConformance(unittest.TestCase):
    """Structural + behavioural conformance against the reference C++ init and
    the Nagoya C interpreter.  Skipped when ref/ binaries are absent."""

    def test_structural_nonpadding_cells(self):
        if not _have(INIT_BIN):
            self.skipTest('ref init binary unavailable')
        for name, mc, _exp, _stdin in CORPORA:
            if name not in _CACHE:
                continue
            with self.subTest(corpus=name):
                data_path = os.path.join(_TMPDIR, name + '.data')
                with open(data_path, 'wb') as f:
                    f.write(_CACHE[name]['data'].encode('latin-1'))
                init_mb_path = os.path.join(_TMPDIR, name + '.init.mb')
                _run_init(data_path, init_mb_path)
                with open(init_mb_path, 'rb') as f:
                    init_mb = f.read()
                real = _CACHE[name]['real']
                self.assertEqual(len(_CACHE[name]['mb']), len(init_mb),
                                 '%s: code_size differs from init' % name)
                mism = [p for p in real
                        if p < len(init_mb) and real[p] != init_mb[p]]
                self.assertEqual(mism, [],
                                 '%s: %d non-padding cells differ from init'
                                 % (name, len(mism)))

    def test_behavioural_four_way(self):
        if not (_have(INIT_BIN) and _have(C_INTERP)):
            self.skipTest('ref init or C interpreter unavailable')
        for name, mc, exp, stdin in CORPORA:
            if name not in _CACHE:
                continue
            with self.subTest(corpus=name):
                py_mb = _CACHE[name]['mb_path']
                data_path = os.path.join(_TMPDIR, name + '.data')
                with open(data_path, 'wb') as f:
                    f.write(_CACHE[name]['data'].encode('latin-1'))
                init_mb_path = os.path.join(_TMPDIR, name + '.init.mb')
                _run_init(data_path, init_mb_path)

                _, o_py_py = _run_pymalbolge(py_mb, stdin)
                _, o_py_c = _run_c_interp(py_mb, stdin)
                _, o_in_py = _run_pymalbolge(init_mb_path, stdin)
                _, o_in_c = _run_c_interp(init_mb_path, stdin)
                self.assertEqual(o_py_py, o_py_c, '%s py.mb: interp disagree' % name)
                self.assertEqual(o_py_py, o_in_py, '%s: py vs init on pyMalbolge' % name)
                self.assertEqual(o_py_py, o_in_c, '%s: py vs init on C' % name)
                want = stdin if exp is None else exp
                self.assertEqual(o_py_py, want, '%s: output mismatch' % name)


if __name__ == '__main__':
    unittest.main()
