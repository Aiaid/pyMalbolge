"""Resource bounds, byte I/O, compact snapshots and legacy compatibility."""
from array import array
from collections import deque
import random
import unittest

from malbolge import malbolge, malbolge20
from malbolge.core import MalbolgeConfig, SparseMemory, crazy, parse_source
from malbolge.debugger import MalbolgeDebugger


def instructions(*opcodes):
    return ''.join(next(chr(c) for c in range(33, 127) if (c + i) % 94 == op)
                   for i, op in enumerate(opcodes))


class TestBoundedRuntime(unittest.TestCase):
    def test_byte_input_and_variant_eof(self):
        code = instructions(23, 5, 81)
        for interpreter, sentinel in ((malbolge, 59048), (malbolge20, 59049)):
            with self.subTest(variant=interpreter.__name__):
                result = interpreter.run(code, b'\xff', max_steps=10, max_output=1)
                self.assertEqual((result.output, result.steps, result.input_consumed,
                                  result.stop_reason), (b'\xff', 3, 1, 'terminated'))
                text = interpreter.run(code, 'é', max_steps=10)
                self.assertEqual((text.output, text.input_consumed), (b'\xc3', 1))
                eof = interpreter.run(code, b'', max_steps=10)
                self.assertEqual(eof.output, bytes([sentinel % 256]))
                stopped = interpreter.run(code, b'', eof='stop', max_steps=10)
                self.assertEqual((stopped.output, stopped.steps, stopped.stop_reason),
                                 (b'', 0, 'input_exhausted'))

    def test_limits_stop_before_pending_instruction(self):
        for interpreter in (malbolge, malbolge20):
            zero = interpreter.run(instructions(81), max_steps=0)
            self.assertEqual((zero.steps, zero.stop_reason), (0, 'step_limit'))
            one = interpreter.run(instructions(81), max_steps=1)
            self.assertEqual((one.steps, one.stop_reason), (1, 'terminated'))
            out = interpreter.run(instructions(23, 5, 5, 81), b'X', max_output=1)
            self.assertEqual((out.output, out.steps, out.c, out.stop_reason),
                             (b'X', 2, 2, 'output_limit'))
            self.assertEqual(out.to_dict()['output_count'], 1)
            self.assertEqual(out.to_dict()['output_hex'], '58')
            none = interpreter.run(instructions(23, 5, 81), b'X', max_output=0)
            self.assertEqual((none.output, none.steps, none.stop_reason),
                             (b'', 1, 'output_limit'))

    def test_invalid_instruction_and_argument_validation(self):
        for interpreter in (malbolge, malbolge20):
            result = interpreter.run("D'", max_steps=10)
            self.assertEqual(result.stop_reason, 'invalid_instruction')
            for keyword in ('max_steps', 'max_output'):
                for bad in (-1, 1.5, True):
                    with self.assertRaises(ValueError):
                        interpreter.run(instructions(81), **{keyword: bad})
            with self.assertRaises(TypeError):
                interpreter.run(instructions(81), 123)
            with self.assertRaises(ValueError):
                interpreter.run(instructions(81), eof='unknown')

    def test_legacy_eval_text_and_eof_contract(self):
        code = instructions(23, 5, 81)
        for interpreter in (malbolge, malbolge20):
            self.assertEqual(interpreter.eval(code, '\u0101'), '\x01')
            self.assertEqual(interpreter.eval(code, ''), '')
            self.assertEqual(interpreter.eval(code, '', eof='sentinel'),
                             interpreter.run(code).output.decode('latin1'))


class TestCompactMemory(unittest.TestCase):
    def test_wide_promotion_and_copy_on_write_at_page_boundaries(self):
        for config in (MalbolgeConfig.original(), MalbolgeConfig.malbolge20()):
            source = b'D' * 9000
            memory = SparseMemory(config)
            memory.initialize_source(source)
            first = memory.copy()
            self.assertIs(first._source, memory._source)
            for address in (0, 4095, 4096, 8999):
                memory[address] = 300
                self.assertEqual(first[address], 68)
            second = memory.copy()
            memory[4096] = config.memory_size - 1
            second[4095] = -7  # preserve the existing arbitrary-value API
            self.assertEqual(second[4096], 300)
            self.assertEqual(memory[4095], 300)
            self.assertEqual(first[4095], 68)
            self.assertEqual(len(memory._blocks), 3)
            self.assertEqual(memory.get_allocated_count(), len(source))
            for _ in range(100):
                memory[10000] = 1
            self.assertEqual(memory.get_allocated_count(), len(source) + 1)

    def test_wide_source_backing_detaches_from_caller(self):
        source = array('I', [300, 400])
        memory = SparseMemory(MalbolgeConfig.malbolge20())
        memory.initialize_source(source)
        source[0] = 123
        self.assertEqual(memory[:2], [300, 400])
        self.assertEqual(memory[2], crazy(400, 300, 20))

    def test_far_reads_and_copies_ignore_mutated_seed_words(self):
        rng = random.Random(712)
        for config in (MalbolgeConfig.original(), MalbolgeConfig.malbolge20()):
            reference = SparseMemory(config)
            memory = SparseMemory(config)
            reference.initialize_source([68, 39])
            memory.initialize_source([68, 39])
            copies = [memory.copy()]
            memory[1] = 123
            copies.append(memory.copy())
            for address in [config.memory_size-1, 2, 4096] + [
                    rng.randrange(2, config.memory_size) for _ in range(100)]:
                expected = reference[address]
                self.assertEqual(memory[address], expected)
                for snapshot in copies:
                    self.assertEqual(snapshot[address], expected)

    def test_compact_parser_checks_first_error_and_whitespace(self):
        config = MalbolgeConfig.malbolge20()
        code = instructions(*([68] * 5000))
        parsed = parse_source(' \r\n\t'.join(code), config)
        self.assertIsInstance(parsed, bytes)
        self.assertEqual(parsed, code.encode())
        invalid = bytearray(code.encode())
        invalid[3000] = 0
        invalid[7] = 0
        with self.assertRaisesRegex(ValueError, 'position 7'):
            parse_source(invalid, config)
        wide = chr(94 * 10 + 68)
        self.assertEqual(list(parse_source(wide, config)), [ord(wide)])


class TestDebuggerBoundedHistory(unittest.TestCase):
    def test_deque_and_output_deltas_preserve_back_seek_and_reset(self):
        code = instructions(23, 5, 5, 81)
        debugger = MalbolgeDebugger(code, b'\xff')
        debugger._max_history = 2
        self.assertIsInstance(debugger._history, deque)
        debugger.step(); debugger.step(); debugger.step()
        self.assertEqual(debugger.output, '\xff\xff')
        self.assertEqual(debugger.history_size, 2)
        self.assertEqual(debugger._history[-1].output_length, 1)
        debugger.step_back()
        self.assertEqual(debugger.output, '\xff')
        debugger.seek(3)
        self.assertEqual(debugger.output, '\xff\xff')
        debugger.reset()
        self.assertEqual((debugger.output, debugger.history_size), ('', 0))

    def test_debugger_sentinel_policy_matches_runtime(self):
        code = instructions(23, 5, 81)
        for config, interpreter in ((MalbolgeConfig.original(), malbolge),
                                    (MalbolgeConfig.malbolge20(), malbolge20)):
            debugger = MalbolgeDebugger(code, b'', config=config, eof='sentinel')
            self.assertFalse(debugger.preview_next_instruction()['will_terminate'])
            debugger.run()
            self.assertEqual(debugger.output, interpreter.run(code).output.decode('latin1'))


if __name__ == '__main__':
    unittest.main()
