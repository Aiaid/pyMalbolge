"""Instruction encoding preserves address, opcode and mapping contracts."""
import unittest

from malbolge.compiler.mc2mb import _Assembler, _LEGAL, _xlat1, Mc2MbError


class InstructionEncoding(unittest.TestCase):
    def test_every_opcode_round_trips_at_each_address_residue(self):
        asm = _Assembler()
        positions = list(range(-188, 188)) + [
            -(3**20), 3**20 - 1, -(10**30), 10**30,
        ]
        for opcode in _LEGAL:
            for position in positions:
                with self.subTest(opcode=opcode, position=position):
                    encoded = asm.setchr(opcode, position)
                    self.assertGreaterEqual(encoded, 33)
                    self.assertLessEqual(encoded, 126)
                    self.assertEqual(_xlat1(encoded, position), ord(opcode))
                    self.assertEqual(asm.code[position], encoded)
        self.assertEqual(len(asm.code), len(positions))
        self.assertEqual(asm.code_size, max(positions) + 1)

    def test_cursor_writes_and_replaceable_mapping_keep_their_contract(self):
        asm = _Assembler()
        asm.code = {}
        asm.C = -1
        asm.D = 94
        c_value = asm.setchr_C('o')
        d_value = asm.setchr_D('j')
        self.assertEqual((asm.C, asm.D, asm.code_size), (0, 95, 95))
        self.assertEqual(asm.code, {-1: c_value, 94: d_value})
        self.assertEqual(_xlat1(c_value, -1), ord('o'))
        self.assertEqual(_xlat1(d_value, 94), ord('j'))

    def test_invalid_arguments_keep_errors_without_writing(self):
        asm = _Assembler()
        with self.assertRaisesRegex(Mc2MbError, "'x' is not an instruction"):
            asm.setchr('x', 0)
        for opcode in ('', 'ji'):
            with self.subTest(opcode=opcode):
                with self.assertRaises(TypeError):
                    asm.setchr(opcode, 0)
        with self.assertRaisesRegex(TypeError, 'source cell addresses must be integers'):
            asm.setchr('o', 1.5)
        self.assertEqual(len(asm.code), 0)
        self.assertEqual(asm.code_size, 0)
