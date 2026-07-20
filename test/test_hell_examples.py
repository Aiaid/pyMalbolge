"""
Tests running the assembled HeLL example programs (test/fixtures/hell/).

These fixtures come from the LMAO project (Low-level Malbolge Assembler,
Ooh!, GPL-3.0, https://github.com/esoteric-programmer/LMAO) -- see
test/fixtures/hell/README.md for provenance details.  The expected
input/output pairs below are hardcoded from LMAO's own testcases.bash so
these tests do not depend on anything outside test/fixtures/.

Two execution strategies are used:

- eval() (in-process, fast) for programs whose behavior does not depend on
  exact EOF sentinel semantics or exact byte-for-byte binary I/O.
- subprocess, invoking `python3 -m malbolge <file.mal>` (out-of-process),
  for programs that rely on the CLI's EOF-sentinel behavior (A = 59048 on
  EOF) and/or need exact binary stdin/stdout round-tripping.
"""

import os
import subprocess
import sys
import unittest

from malbolge import eval

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures', 'hell')

SUBPROCESS_TIMEOUT = 60


def fixture_path(name):
    return os.path.join(FIXTURES_DIR, name)


def load_fixture(name):
    with open(fixture_path(name)) as f:
        return f.read()


def run_via_cli(mal_filename, stdin_bytes=b''):
    """Run a .mal fixture via `python3 -m malbolge <file>` and return
    (returncode, stdout_bytes)."""
    result = subprocess.run(
        [sys.executable, '-m', 'malbolge', fixture_path(mal_filename)],
        input=stdin_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=SUBPROCESS_TIMEOUT,
    )
    return result.returncode, result.stdout


class TestHelloWorld(unittest.TestCase):
    """example_hello_world.mal / example_simple_hello_world.mal both print
    'Hello, World!\\n'."""

    def test_hello_world(self):
        code = load_fixture('example_hello_world.mal')
        self.assertEqual(eval(code), "Hello, World!\n")

    def test_simple_hello_world(self):
        code = load_fixture('example_simple_hello_world.mal')
        self.assertEqual(eval(code), "Hello, World!\n")


class TestDigitalRoot(unittest.TestCase):
    """example_digital_root.mal reads a decimal number (newline-terminated,
    as fed by `echo` in LMAO's testcases.bash) and prints its digital root.
    Non-digit characters are ignored."""

    CASES = [
        ("", "0"),
        ("0", "0"),
        ("xxx0aaa", "0"),
        ("1", "1"),
        ("11", "2"),
        ("99999999999", "9"),
        ("1337", "5"),
    ]

    def setUp(self):
        self.code = load_fixture('example_digital_root.mal')

    def test_digital_root_cases(self):
        for input_str, expected in self.CASES:
            with self.subTest(input=input_str):
                # LMAO's testcases.bash feeds input via `echo`, which
                # appends a trailing newline.
                result = eval(self.code, input_str + "\n")
                self.assertEqual(result, expected + "\n")


class TestAdder(unittest.TestCase):
    """example_adder.mal reads two numbers separated by a space
    (newline-terminated) and prints their sum."""

    CASES = [
        ("0 0", "0"),
        ("1 0", "1"),
        ("0 1", "1"),
        ("1 1", "2"),
        ("999 2", "1001"),
        ("222111 555", "666"),
    ]

    def setUp(self):
        self.code = load_fixture('example_adder.mal')

    def test_adder_cases(self):
        for input_str, expected in self.CASES:
            with self.subTest(input=input_str):
                result = eval(self.code, input_str + "\n")
                self.assertEqual(result, expected + "\n")


class TestCatHaltOnEof(unittest.TestCase):
    """example_cat_halt_on_eof.mal echoes stdin back to stdout exactly and
    exits cleanly once it sees EOF (it relies on the CLI's EOF sentinel
    value, A = 59048, to detect end of input), so it is run out-of-process
    via `python3 -m malbolge`."""

    def test_echoes_all_256_byte_values(self):
        data = bytes(range(256))
        returncode, stdout = run_via_cli('example_cat_halt_on_eof.mal', data)
        self.assertEqual(returncode, 0)
        self.assertEqual(stdout, data)

    def test_echoes_random_binary_input(self):
        data = os.urandom(2048)
        returncode, stdout = run_via_cli('example_cat_halt_on_eof.mal', data)
        self.assertEqual(returncode, 0)
        self.assertEqual(stdout, data)

    def test_echoes_empty_input(self):
        returncode, stdout = run_via_cli('example_cat_halt_on_eof.mal', b'')
        self.assertEqual(returncode, 0)
        self.assertEqual(stdout, b'')


class TestSimpleCat(unittest.TestCase):
    """example_simple_cat.mal is an infinite echo loop with no EOF
    handling: it never halts on its own. Using eval(..., eof='stop') lets
    us observe the echoed output without running the infinite loop, since
    'stop' returns as soon as input is exhausted instead of feeding the
    program an EOF sentinel it would loop forever trying to consume."""

    def test_echoes_input(self):
        code = load_fixture('example_simple_cat.mal')
        input_str = ''.join(chr(b) for b in range(256))
        result = eval(code, input_str, eof='stop')
        self.assertEqual(result, input_str)


if __name__ == "__main__":
    unittest.main()
