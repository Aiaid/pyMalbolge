"""Decimal runtime algorithms, including full-word bounds and bad input."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from malbolge.compiler.decimal_io import C_HELPERS, PYTHON_HELPERS
from malbolge.compiler.py2c import HELPER_DIV


class DecimalHelpers(unittest.TestCase):
    def test_unsigned_input_contract(self):
        cases = (
            (b"0\n", 0), (b"0007\n", 7), (b"42", 42),
            (b" \t+12\v\f\r\n", 12), (b"3486784400\n", 3486784400),
            (b"0000000000000000000000000000000007\n", 7),
        )
        invalid = (b"", b"\n", b" \t\n", b"-1\n", b"+\n", b"++1\n",
                   b"+ 1\n", b"1 2\n", b"1x\n", b"3486784401\n",
                   b"9999999999999999999999\n")
        for stdin, expected in cases + tuple((value, None) for value in invalid):
            with self.subTest(stdin=stdin):
                values = iter(stdin)
                ns = {"getchar": lambda: next(values, 59049)}
                exec(PYTHON_HELPERS["ZZREADINT"], ns)
                value = ns["zzreadint"]()
                self.assertEqual(ns["zzioerror"], int(expected is None))
                if expected is not None:
                    self.assertEqual(value, expected)

    def test_two_input_lines_and_error_flag_reset(self):
        values = iter(b"7\r\n +10 \n")
        ns = {"getchar": lambda: next(values, 59049)}
        exec(PYTHON_HELPERS["ZZREADINT"], ns)
        self.assertEqual(ns["zzreadint"](), 7)
        self.assertEqual(ns["zzreadint"](), 10)
        self.assertEqual(ns["zzioerror"], 0)
        ns["zzreadint"]()
        self.assertEqual(ns["zzioerror"], 1)

    def test_decimal_print_word_boundaries(self):
        out = []
        ns = {"putchar": lambda value: out.append(chr(value))}
        exec(PYTHON_HELPERS["ZZPRINTINT"], ns)
        for value in list(range(101)) + [1000, 1000000000, 2971215073, 3486784400]:
            with self.subTest(value=value):
                out.clear()
                ns["zzprintint"](value)
                self.assertEqual("".join(out), str(value))

    @unittest.skipUnless(shutil.which("cc"), "C compiler not available")
    def test_c_and_python_helpers_agree(self):
        # Use uint32 arithmetic to exercise the entire Malbolge20 word range,
        # including values above the host C signed-int maximum.
        read = C_HELPERS["zzreadint"].replace("int ", "unsigned int ")
        read = read.replace("getchar()", "decimal_getchar()")
        source = """\
#include <stdio.h>
unsigned int zzioerror;
unsigned int decimal_getchar(void){
  int c = getchar();
  return c == EOF ? 59049u : (unsigned int)c;
}
""" + HELPER_DIV.replace("int ", "unsigned int ") + read
        source += C_HELPERS["zzprintint"].replace("int ", "unsigned int ")
        source += """\
int main(void){
  unsigned int value = zzreadint();
  printf("%u,%u\\n", value, zzioerror);
  if(zzioerror == 0){ zzprintint(value); }
  putchar(10);
  return 0;
}
"""
        cases = (b"0\n", b"0007\n", b"42", b" \t+12\v\f\r\n",
                 b"3486784400\n", b"3486784401\n", b"", b"\n",
                 b"-1\n", b"+\n", b"++1\n", b"+ 1\n", b"1 2\n",
                 b"1x\n", b"9999999999999999999999\n")
        with tempfile.TemporaryDirectory() as tmp:
            c_path, exe = Path(tmp) / "decimal.c", Path(tmp) / "decimal"
            c_path.write_text(source)
            subprocess.run([shutil.which("cc"), str(c_path), "-o", str(exe)],
                           check=True, capture_output=True, timeout=30)
            for stdin in cases:
                with self.subTest(stdin=stdin):
                    values = iter(stdin)
                    ns = {"getchar": lambda: next(values, 59049)}
                    exec(PYTHON_HELPERS["ZZREADINT"], ns)
                    value = ns["zzreadint"]()
                    error = ns["zzioerror"]
                    expected = "{},{}\n{}\n".format(
                        value, error, str(value) if not error else "")
                    proc = subprocess.run([str(exe)], input=stdin,
                                          capture_output=True, timeout=5)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    self.assertEqual(proc.stdout, expected.encode("ascii"))
