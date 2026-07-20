"""
Tests running the compiled .mg -> .mc -> .mb fixtures
(test/fixtures/nagoya/mg_*.mb).

These fixtures are original programs written against the Nagoya
pseudo-instruction language (.mg) and compiled through the Nagoya
toolchain (ref/nagoya-ternary + ref/nagoya-lowass, both MIT-licensed) to
Malbolge20 -- see test/fixtures/nagoya/README.md for provenance,
compile commands, and expected I/O for each fixture.

These tests only exercise the already-compiled .mb files via
`python3 -m malbolge --variant=malbolge20`; they do not depend on the
ref/ toolchain being built (that is only needed to regenerate the
fixtures, via scripts/mg2mb.sh).
"""

import os
import subprocess
import sys
import unittest

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures', 'nagoya')

SUBPROCESS_TIMEOUT = 60


def fixture_path(name):
    return os.path.join(FIXTURES_DIR, name)


def run_mb(mb_filename, stdin_bytes=b''):
    """Run a .mb fixture via `python3 -m malbolge --variant=malbolge20 <file>`
    and return (returncode, stdout_bytes)."""
    result = subprocess.run(
        [sys.executable, '-m', 'malbolge', '--variant=malbolge20',
         fixture_path(mb_filename)],
        input=stdin_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=SUBPROCESS_TIMEOUT,
    )
    return result.returncode, result.stdout


class TestMgMinimal(unittest.TestCase):
    """mg_a_minimal.mb is `DEF MAIN OUTPUT END`: a single unconditional
    OUTPUT with no preceding ROT, smoke-testing that the pipeline
    produces a runnable program at all."""

    def test_runs_and_outputs_one_byte(self):
        returncode, stdout = run_mb('mg_a_minimal.mb')
        self.assertEqual(returncode, 0)
        self.assertEqual(stdout, b'\xde')


class TestMgHi(unittest.TestCase):
    """mg_b_hi.mb loads 3*ascii literals via ROT and OUTPUTs them,
    printing 'Hi'."""

    def test_prints_hi(self):
        returncode, stdout = run_mb('mg_b_hi.mb')
        self.assertEqual(returncode, 0)
        self.assertEqual(stdout, b'Hi')


class TestMgEcho(unittest.TestCase):
    """mg_c_echo.mb is `DEF MAIN INPUT OUTPUT END`: reads one byte from
    stdin and echoes it back."""

    def test_echoes_input_byte(self):
        for byte in (b'Q', b'\x00', b'\xff', b'A'):
            with self.subTest(byte=byte):
                returncode, stdout = run_mb('mg_c_echo.mb', byte)
                self.assertEqual(returncode, 0)
                self.assertEqual(stdout, byte)


class TestMgRepeat(unittest.TestCase):
    """mg_d_repeat.mb exercises REPEAT/BREAK/REPEAT INF: ROT loads 'A'
    into the A register once, then a bounded REPEAT 3 and a REPEAT INF
    (broken after one iteration) each OUTPUT it, for 'AAAA' total."""

    def test_prints_four_a(self):
        returncode, stdout = run_mb('mg_d_repeat.mb')
        self.assertEqual(returncode, 0)
        self.assertEqual(stdout, b'AAAA')


class TestMgCall(unittest.TestCase):
    """mg_e_call.mb exercises CALL/RETURN: MAIN calls SUB, which OUTPUTs
    'X' and returns."""

    def test_prints_x(self):
        returncode, stdout = run_mb('mg_e_call.mb')
        self.assertEqual(returncode, 0)
        self.assertEqual(stdout, b'X')


if __name__ == "__main__":
    unittest.main()
