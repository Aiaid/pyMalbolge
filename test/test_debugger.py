"""
Tests for Malbolge debugger functionality.
"""

import unittest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from malbolge import (
    MalbolgeDebugger,
    MalbolgeState,
    Breakpoint,
    Watchpoint,
    StopReason,
    debug,
)
from malbolge.core import MalbolgeConfig


# Hello World program
HELLO_CODE = '''(=<`#9]~6ZY32Vx/4Rs+0No-&Jk)"Fh}|Bcy?`=*z]Kw%oG4UUS0/@-ejc(:'8dc'''

# Cat program (echoes input) - note the escaped backslash
CAT_CODE = '(=BA#9"=<;:3y7x54-21q/p-,+*)"!h%B0/.~P<<:(8&66#"!~}|{zyxwvugJ%'


def _long_running_source():
    """A program that runs far longer than one chunk (99 bottles of beer)."""
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'examples', '99bottles.mal')
    with open(path) as handle:
        return handle.read()


class TestMalbolgeDebugger(unittest.TestCase):
    """Test MalbolgeDebugger core functionality."""

    def test_init_hello(self):
        """Test debugger initialization with Hello World."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        self.assertEqual(dbg.source_length, len(HELLO_CODE.replace(' ', '').replace('\n', '')))
        self.assertFalse(dbg.is_terminated)
        self.assertEqual(dbg.step_count, 0)

    def test_init_invalid_source(self):
        """Test that invalid source raises ValueError."""
        with self.assertRaises(ValueError):
            MalbolgeDebugger("invalid source code!!!")

    def test_step(self):
        """Test single step execution."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        state = dbg.step()

        self.assertEqual(state.step_count, 1)
        self.assertEqual(state.stop_reason, StopReason.STEP)

    def test_step_multiple(self):
        """Test multiple steps."""
        dbg = MalbolgeDebugger(HELLO_CODE)

        for i in range(10):
            state = dbg.step()
            self.assertEqual(state.step_count, i + 1)

    def test_run_to_completion(self):
        """Test running Hello World to completion."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        state = dbg.run()

        self.assertEqual(state.stop_reason, StopReason.TERMINATED)
        self.assertEqual(dbg.output, "Hello World!")

    def test_cat_with_input(self):
        """Test cat program with input."""
        dbg = MalbolgeDebugger(CAT_CODE, "abc123")
        state = dbg.run()

        self.assertEqual(dbg.output, "abc123")

    def test_registers_initial(self):
        """Test initial register values."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        regs = dbg.registers

        self.assertEqual(regs['a'], 0)
        self.assertEqual(regs['c'], 0)
        self.assertEqual(regs['d'], 0)

    def test_get_state(self):
        """Test getting current state."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        state = dbg.get_state()

        self.assertIsInstance(state, MalbolgeState)
        self.assertEqual(state.a, 0)
        self.assertEqual(state.c, 0)
        self.assertEqual(state.d, 0)
        self.assertEqual(state.step_count, 0)


class TestBreakpoints(unittest.TestCase):
    """Test breakpoint functionality."""

    def test_add_breakpoint(self):
        """Test adding a breakpoint."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        bp = dbg.add_breakpoint(10)

        self.assertEqual(bp.address, 10)
        self.assertTrue(bp.enabled)
        self.assertEqual(len(dbg.list_breakpoints()), 1)

    def test_remove_breakpoint(self):
        """Test removing a breakpoint."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        dbg.add_breakpoint(10)
        result = dbg.remove_breakpoint(10)

        self.assertTrue(result)
        self.assertEqual(len(dbg.list_breakpoints()), 0)

    def test_remove_nonexistent_breakpoint(self):
        """Test removing a breakpoint that doesn't exist."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        result = dbg.remove_breakpoint(10)

        self.assertFalse(result)

    def test_breakpoint_hit(self):
        """Test that breakpoint stops execution."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        dbg.add_breakpoint(5)
        state = dbg.run()

        self.assertEqual(state.stop_reason, StopReason.BREAKPOINT)
        self.assertEqual(state.c, 5)

    def test_toggle_breakpoint(self):
        """Test toggling breakpoint enabled state."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        dbg.add_breakpoint(10)

        # Toggle off
        result = dbg.toggle_breakpoint(10)
        self.assertFalse(result)

        # Toggle on
        result = dbg.toggle_breakpoint(10)
        self.assertTrue(result)

    def test_clear_breakpoints(self):
        """Test clearing all breakpoints."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        dbg.add_breakpoint(5)
        dbg.add_breakpoint(10)
        dbg.add_breakpoint(15)

        count = dbg.clear_breakpoints()
        self.assertEqual(count, 3)
        self.assertEqual(len(dbg.list_breakpoints()), 0)

    def test_temporary_breakpoint(self):
        """Test temporary (one-shot) breakpoint."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        dbg.add_breakpoint(5, temporary=True)

        # First run should hit breakpoint
        state = dbg.run()
        self.assertEqual(state.stop_reason, StopReason.BREAKPOINT)

        # Breakpoint should be removed
        self.assertEqual(len(dbg.list_breakpoints()), 0)


class TestStepBack(unittest.TestCase):
    """Test step back (history) functionality."""

    def test_step_back_available(self):
        """Test that step back is available after stepping."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        dbg.step()

        self.assertTrue(dbg.can_step_back)

    def test_step_back_not_available_initially(self):
        """Test that step back is not available initially."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        self.assertFalse(dbg.can_step_back)

    def test_step_back_restores_state(self):
        """Test that step back restores previous state."""
        dbg = MalbolgeDebugger(HELLO_CODE)

        # Get initial state
        initial_state = dbg.get_state()

        # Step forward
        dbg.step()

        # Step back
        state = dbg.step_back()

        self.assertEqual(state.c, initial_state.c)
        self.assertEqual(state.d, initial_state.d)
        self.assertEqual(state.step_count, initial_state.step_count)

    def test_step_back_multiple(self):
        """Test stepping back multiple times."""
        dbg = MalbolgeDebugger(HELLO_CODE)

        # Step forward 5 times
        for _ in range(5):
            dbg.step()

        self.assertEqual(dbg.step_count, 5)

        # Step back 3 times
        for _ in range(3):
            dbg.step_back()

        self.assertEqual(dbg.step_count, 2)

    def test_step_back_returns_none_when_empty(self):
        """Test that step back returns None when history is empty."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        result = dbg.step_back()
        self.assertIsNone(result)


class TestMemoryInspection(unittest.TestCase):
    """Test memory inspection functionality."""

    def test_read_memory(self):
        """Test reading memory."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        mem = dbg.read_memory(0, 10)

        self.assertEqual(len(mem), 10)
        # First byte should be '(' which is 40
        self.assertEqual(mem[0], ord('('))

    def test_read_memory_value(self):
        """Test reading single memory value."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        val = dbg.read_memory_value(0)

        self.assertEqual(val, ord('('))

    def test_get_memory_context(self):
        """Test getting memory context around address."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        ctx = dbg.get_memory_context(5, context=2)

        self.assertEqual(ctx['center'], 5)
        self.assertEqual(len(ctx['values']), 5)  # 2 before + center + 2 after
        self.assertEqual(len(ctx['as_chars']), 5)


class TestDisassembly(unittest.TestCase):
    """Test disassembly functionality."""

    def test_disassemble(self):
        """Test disassembly output."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        disasm = dbg.disassemble(0, 5)

        self.assertEqual(len(disasm), 5)
        self.assertEqual(disasm[0]['address'], 0)
        self.assertTrue(disasm[0]['is_current'])

    def test_disassemble_contains_mnemonic(self):
        """Test that disassembly contains mnemonic."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        disasm = dbg.disassemble(0, 1)

        self.assertIn('mnemonic', disasm[0])
        self.assertIn(disasm[0]['mnemonic'],
                      ['jmp', 'out', 'in', 'rotr', 'mov', 'crz', 'nop', 'end', '???', 'DATA'])


class TestReset(unittest.TestCase):
    """Test reset functionality."""

    def test_reset(self):
        """Test resetting debugger state."""
        dbg = MalbolgeDebugger(HELLO_CODE)

        # Run for a bit
        for _ in range(100):
            dbg.step()

        # Reset
        dbg.reset()

        self.assertEqual(dbg.step_count, 0)
        self.assertEqual(dbg.registers['c'], 0)
        self.assertEqual(dbg.registers['d'], 0)
        self.assertEqual(dbg.output, "")
        self.assertFalse(dbg.is_terminated)


class TestConvenienceFunction(unittest.TestCase):
    """Test convenience functions."""

    def test_debug_function(self):
        """Test debug() convenience function."""
        dbg = debug(HELLO_CODE)

        self.assertIsInstance(dbg, MalbolgeDebugger)
        self.assertFalse(dbg.is_terminated)


class TestWatchpoints(unittest.TestCase):
    """Test watchpoint functionality."""

    def test_add_watchpoint(self):
        """Test adding a watchpoint."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        wp = dbg.add_watchpoint(100)

        self.assertEqual(wp.address, 100)
        self.assertTrue(wp.enabled)

    def test_remove_watchpoint(self):
        """Test removing a watchpoint."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        dbg.add_watchpoint(100)
        result = dbg.remove_watchpoint(100)

        self.assertTrue(result)
        self.assertEqual(len(dbg.list_watchpoints()), 0)


class TestRunTo(unittest.TestCase):
    """Test run_to functionality."""

    def test_run_to_address(self):
        """Test running to a specific address."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        state = dbg.run_to(5)

        self.assertEqual(state.c, 5)


class TestWriteHeat(unittest.TestCase):
    """Test memory write heat tracking (tui-web-architecture.md 4.1)."""

    def test_heat_empty_initially(self):
        """Loading the source into memory is not a write."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        self.assertEqual(dict(dbg.write_heat), {})
        self.assertEqual(dbg.get_write_heat(0, 4), [0, 0, 0, 0])

    def test_get_write_heat_never_written_is_zero(self):
        """Never-written addresses read as 0 instead of raising."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        for _ in range(20):
            dbg.step()

        # Far away from anything hello world touches.
        self.assertEqual(dbg.get_write_heat(50000, 3), [0, 0, 0])
        # Out of range on both ends is also 0, not an exception.
        self.assertEqual(dbg.get_write_heat(-3, 2), [0, 0])
        self.assertEqual(dbg.get_write_heat(3 ** 10 + 100, 2), [0, 0])

    def test_get_write_heat_window_shape(self):
        """The returned window is exactly `count` long, aligned on `start`."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        for _ in range(20):
            dbg.step()

        window = dbg.get_write_heat(0, 24)
        self.assertEqual(len(window), 24)
        for addr, heat in enumerate(window):
            self.assertEqual(heat, dbg.write_heat.get(addr, 0))

        self.assertEqual(dbg.get_write_heat(0, 0), [])
        self.assertEqual(dbg.get_write_heat(0, -1), [])

    def test_heat_accumulates(self):
        """Stepping produces writes, and heat only grows while stepping."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        previous = 0
        for _ in range(20):
            dbg.step()
            total = sum(dbg.write_heat.values())
            self.assertGreaterEqual(total, previous)
            previous = total
        self.assertGreater(previous, 0)

    def test_heat_matches_predicted_writes(self):
        """Per-step heat delta equals the writes preview_next_instruction predicts."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        checked = 0

        for _ in range(30):
            preview = dbg.preview_next_instruction()
            if preview['will_terminate']:
                break
            opcode = preview['opcode']
            before = sum(dbg.write_heat.values())
            dbg.step()
            delta = sum(dbg.write_heat.values()) - before

            if opcode == 4:
                # jmp encrypts the jump target, which the preview reports
                # against the pre-jump C; not a usable oracle.
                continue

            expected = len(preview['memory_changes'])
            if preview['will_encrypt']:
                expected += 1
            self.assertEqual(delta, expected, f"opcode {opcode}")
            checked += 1

        self.assertGreater(checked, 0)

    def test_step_back_decrements_heat(self):
        """One step forward then back leaves heat exactly as it was."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        for _ in range(15):
            dbg.step()

        before = dict(dbg.write_heat)
        dbg.step()
        self.assertNotEqual(dict(dbg.write_heat), before)

        dbg.step_back()
        self.assertEqual(dict(dbg.write_heat), before)

    def test_full_rewind_clears_heat(self):
        """Rewinding the whole timeline leaves no heat behind."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        for _ in range(25):
            dbg.step()

        while dbg.can_step_back:
            dbg.step_back()

        self.assertEqual(dbg.step_count, 0)
        self.assertEqual(dict(dbg.write_heat), {})

    def test_heat_after_rewind_and_replay_matches_fresh_run(self):
        """Heat depends on the timeline position, not on how it was reached."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        for _ in range(20):
            dbg.step()
        for _ in range(8):
            dbg.step_back()
        for _ in range(8):
            dbg.step()

        reference = MalbolgeDebugger(HELLO_CODE)
        for _ in range(20):
            reference.step()

        self.assertEqual(dict(dbg.write_heat), dict(reference.write_heat))

    def test_reset_clears_heat(self):
        """reset() clears heat outright."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        dbg.run()
        self.assertGreater(sum(dbg.write_heat.values()), 0)

        dbg.reset()
        self.assertEqual(dict(dbg.write_heat), {})
        self.assertEqual(dbg.get_write_heat(0, 4), [0, 0, 0, 0])

    def test_write_heat_mapping_is_read_only(self):
        """write_heat hands out a view, not a mutable counter."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        dbg.step()
        with self.assertRaises(TypeError):
            dbg.write_heat[0] = 99

    def test_heat_double_write_when_c_equals_d(self):
        """Both writes count when the rotr writeback and ENCRYPT share a cell.

        (99 + 34) % 94 == 39 (rotr), and rotate(99) == 33, which is inside the
        printable range, so ENCRYPT rewrites the same cell the writeback just
        touched. Reached here by construction: the sample programs never put
        C and D on one address at that moment, but nothing forbids it.
        """
        dbg = MalbolgeDebugger(HELLO_CODE)
        dbg._c = dbg._d = 34
        dbg._mem[34] = 99

        dbg.step()
        self.assertEqual(dbg.write_heat[34], 2)

        # ...and step_back must undo *both* writes, back to the pre-rotate
        # value rather than to the intermediate rotated one.
        dbg.step_back()
        self.assertEqual(dbg.read_memory_value(34), 99)
        self.assertEqual(dict(dbg.write_heat), {})

    def test_heat_malbolge20(self):
        """Heat works the same over Malbolge20's sparse memory."""
        dbg = MalbolgeDebugger(HELLO_CODE, config=MalbolgeConfig.malbolge20())
        for _ in range(20):
            dbg.step()

        self.assertGreater(sum(dbg.write_heat.values()), 0)
        self.assertEqual(dbg.get_write_heat(3 ** 19, 3), [0, 0, 0])

        before = dict(dbg.write_heat)
        dbg.step()
        dbg.step_back()
        self.assertEqual(dict(dbg.write_heat), before)

        while dbg.can_step_back:
            dbg.step_back()
        self.assertEqual(dict(dbg.write_heat), {})


class TestRunChunked(unittest.TestCase):
    """Test interruptible chunked run (tui-web-architecture.md 4.2)."""

    def test_yields_periodically(self):
        """A yield lands every `chunk` steps."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        chunks = dbg.run_chunked(chunk=10)

        self.assertEqual(next(chunks).step_count, 10)
        self.assertEqual(next(chunks).step_count, 20)
        self.assertEqual(next(chunks).step_count, 30)
        chunks.close()

    def test_final_state_matches_run(self):
        """The last yielded state is what run() would have returned."""
        chunked = MalbolgeDebugger(HELLO_CODE)
        states = list(chunked.run_chunked(chunk=10))

        reference = MalbolgeDebugger(HELLO_CODE)
        expected = reference.run()

        self.assertGreater(len(states), 1)
        self.assertEqual(states[-1], expected)
        self.assertEqual(chunked.output, reference.output)
        self.assertEqual(chunked.step_count, reference.step_count)

    def test_chunk_larger_than_program_yields_once(self):
        """A chunk bigger than the whole run still yields the stop state."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        states = list(dbg.run_chunked(chunk=100000))

        self.assertEqual(len(states), 1)
        self.assertEqual(states[0].stop_reason, StopReason.TERMINATED)
        self.assertEqual(dbg.output, "Hello World!")

    def test_invalid_chunk_raises_immediately(self):
        """chunk <= 0 is rejected at the call, not at the first next()."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        with self.assertRaises(ValueError):
            dbg.run_chunked(chunk=0)
        with self.assertRaises(ValueError):
            dbg.run_chunked(chunk=-5)
        self.assertEqual(dbg.step_count, 0)

    def test_stopping_midway_leaves_debugger_usable(self):
        """Abandoning the iterator does not corrupt debugger state."""
        source = _long_running_source()

        dbg = MalbolgeDebugger(source)
        for index, _state in enumerate(dbg.run_chunked(chunk=100)):
            if index == 2:
                break

        self.assertEqual(dbg.step_count, 300)
        self.assertFalse(dbg.is_terminated)
        self.assertTrue(dbg.can_step_back)

        # The debugger keeps stepping from exactly where it stopped.
        for _ in range(5):
            dbg.step()

        reference = MalbolgeDebugger(source)
        for _ in range(305):
            reference.step()

        self.assertEqual(dbg.step_count, 305)
        self.assertEqual(dbg.registers, reference.registers)
        self.assertEqual(dbg.output, reference.output)
        self.assertEqual(dict(dbg.write_heat), dict(reference.write_heat))
        self.assertEqual(dbg.read_memory(0, 200), reference.read_memory(0, 200))

    def test_resuming_with_run_after_stopping(self):
        """run() picks up correctly after an abandoned run_chunked()."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        for _state in dbg.run_chunked(chunk=5):
            break
        self.assertEqual(dbg.step_count, 5)

        state = dbg.run()
        self.assertEqual(state.stop_reason, StopReason.TERMINATED)
        self.assertEqual(dbg.output, "Hello World!")

    def test_step_back_after_stopping(self):
        """History survives an abandoned iteration."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        for _state in dbg.run_chunked(chunk=12):
            break

        dbg.step_back()
        self.assertEqual(dbg.step_count, 11)

        reference = MalbolgeDebugger(HELLO_CODE)
        for _ in range(11):
            reference.step()
        self.assertEqual(dbg.registers, reference.registers)
        self.assertEqual(dict(dbg.write_heat), dict(reference.write_heat))

    def test_breakpoint_stops_chunked_run(self):
        """Breakpoint semantics are the ones run() has."""
        chunked = MalbolgeDebugger(HELLO_CODE)
        chunked.add_breakpoint(5)
        state = list(chunked.run_chunked(chunk=1))[-1]

        reference = MalbolgeDebugger(HELLO_CODE)
        reference.add_breakpoint(5)
        expected = reference.run()

        self.assertEqual(state.stop_reason, StopReason.BREAKPOINT)
        self.assertEqual(state, expected)
        self.assertEqual(chunked.step_count, reference.step_count)

    def test_temporary_breakpoint_removed_by_chunked_run(self):
        """One-shot breakpoints are still consumed."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        dbg.add_breakpoint(5, temporary=True)
        state = list(dbg.run_chunked(chunk=100))[-1]

        self.assertEqual(state.stop_reason, StopReason.BREAKPOINT)
        self.assertEqual(len(dbg.list_breakpoints()), 0)

    def test_watchpoint_stops_chunked_run(self):
        """Watchpoint semantics are the ones run() has."""
        chunked = MalbolgeDebugger(HELLO_CODE)
        chunked.add_watchpoint(0)
        state = list(chunked.run_chunked(chunk=1))[-1]

        reference = MalbolgeDebugger(HELLO_CODE)
        reference.add_watchpoint(0)
        expected = reference.run()

        self.assertEqual(state.stop_reason, StopReason.WATCHPOINT)
        self.assertEqual(state, expected)

    def test_input_exhaustion_stops_chunked_run(self):
        """Running out of input stops both the same way."""
        chunked = MalbolgeDebugger(CAT_CODE, "ab")
        state = list(chunked.run_chunked(chunk=3))[-1]

        reference = MalbolgeDebugger(CAT_CODE, "ab")
        expected = reference.run()

        self.assertEqual(state, expected)
        self.assertEqual(chunked.output, reference.output)

    def test_chunked_run_on_terminated_debugger(self):
        """A finished program yields its terminal state once and stops."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        dbg.run()
        states = list(dbg.run_chunked(chunk=10))

        self.assertEqual(len(states), 1)
        self.assertEqual(states[0].stop_reason, StopReason.TERMINATED)

    def test_chunked_run_malbolge20(self):
        """Chunked run matches run() under Malbolge20 too."""
        config = MalbolgeConfig.malbolge20()
        chunked = MalbolgeDebugger(HELLO_CODE, config=config)
        states = list(chunked.run_chunked(chunk=10))

        reference = MalbolgeDebugger(HELLO_CODE, config=config)
        expected = reference.run()

        self.assertGreater(len(states), 1)
        self.assertEqual(states[-1], expected)
        self.assertEqual(chunked.output, reference.output)


class TestRunUnchanged(unittest.TestCase):
    """Pin run()'s behaviour now that it is built on run_chunked's engine."""

    def test_run_max_steps_stops_early(self):
        """max_steps still caps the number of steps executed."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        state = dbg.run(max_steps=10)

        self.assertEqual(state.step_count, 10)
        self.assertEqual(dbg.step_count, 10)
        self.assertFalse(dbg.is_terminated)
        self.assertEqual(state.stop_reason, StopReason.RUNNING)

    def test_run_resumes_past_breakpoint(self):
        """The first iteration skips the breakpoint check, so run() continues."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        dbg.add_breakpoint(5)

        first = dbg.run()
        self.assertEqual(first.stop_reason, StopReason.BREAKPOINT)

        second = dbg.run()
        self.assertEqual(second.stop_reason, StopReason.TERMINATED)
        self.assertEqual(dbg.output, "Hello World!")

    def test_run_fires_breakpoint_callback(self):
        """on_breakpoint still fires, once, with the breakpoint that hit."""
        hits = []
        dbg = MalbolgeDebugger(HELLO_CODE)
        dbg.add_breakpoint(5)
        dbg.on_breakpoint(lambda bp, state: hits.append((bp.address, state.c)))

        dbg.run()
        self.assertEqual(hits, [(5, 5)])

    def test_run_on_terminated_debugger_is_a_noop(self):
        """Calling run() again after termination changes nothing."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        dbg.run()
        steps = dbg.step_count

        state = dbg.run()
        self.assertEqual(dbg.step_count, steps)
        self.assertEqual(state.stop_reason, StopReason.TERMINATED)


class TestSeek(unittest.TestCase):
    """Test timeline seeking (tui-web-architecture.md 4.3)."""

    def test_initial_timeline(self):
        """Nothing executed yet: the timeline is a single point."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        self.assertEqual(dbg.max_step_reached, 0)
        self.assertEqual(dbg.seekable_range, (0, 0))

    def test_max_step_reached_is_a_high_water_mark(self):
        """Stepping back does not lower max_step_reached."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        for _ in range(20):
            dbg.step()
        self.assertEqual(dbg.max_step_reached, 20)

        for _ in range(5):
            dbg.step_back()
        self.assertEqual(dbg.step_count, 15)
        self.assertEqual(dbg.max_step_reached, 20)

    def test_reset_clears_max_step_reached(self):
        dbg = MalbolgeDebugger(HELLO_CODE)
        dbg.run()
        self.assertGreater(dbg.max_step_reached, 0)

        dbg.reset()
        self.assertEqual(dbg.max_step_reached, 0)
        self.assertEqual(dbg.seekable_range, (0, 0))

    def test_seekable_range_spans_whole_history(self):
        """With the window untouched, everything executed stays seekable."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        for _ in range(20):
            dbg.step()
        self.assertEqual(dbg.seekable_range, (0, 20))

    def test_seek_backwards(self):
        """Seeking back reproduces the state of a fresh replay."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        for _ in range(25):
            dbg.step()

        state = dbg.seek(10)
        reference = MalbolgeDebugger(HELLO_CODE)
        for _ in range(10):
            reference.step()

        self.assertEqual(state.step_count, 10)
        self.assertEqual(dbg.step_count, 10)
        self.assertEqual(dbg.registers, reference.registers)
        self.assertEqual(dbg.output, reference.output)
        self.assertEqual(dbg.read_memory(0, 200), reference.read_memory(0, 200))
        self.assertEqual(dict(dbg.write_heat), dict(reference.write_heat))

    def test_seek_forwards(self):
        """Seeking forward re-executes up to the target."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        for _ in range(25):
            dbg.step()
        dbg.seek(5)

        state = dbg.seek(20)
        reference = MalbolgeDebugger(HELLO_CODE)
        for _ in range(20):
            reference.step()

        self.assertEqual(state.step_count, 20)
        self.assertEqual(dbg.registers, reference.registers)
        self.assertEqual(dbg.output, reference.output)
        self.assertEqual(dict(dbg.write_heat), dict(reference.write_heat))

    def test_seek_to_current_step_is_a_noop(self):
        dbg = MalbolgeDebugger(HELLO_CODE)
        for _ in range(12):
            dbg.step()
        before = dbg.registers

        state = dbg.seek(12)
        self.assertEqual(state.step_count, 12)
        self.assertEqual(dbg.registers, before)

    def test_seek_to_zero(self):
        """Seeking to 0 unwinds the whole timeline."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        for _ in range(30):
            dbg.step()

        dbg.seek(0)
        fresh = MalbolgeDebugger(HELLO_CODE)
        self.assertEqual(dbg.step_count, 0)
        self.assertEqual(dbg.registers, fresh.registers)
        self.assertEqual(dbg.output, "")
        self.assertEqual(dict(dbg.write_heat), {})
        self.assertEqual(dbg.read_memory(0, 200), fresh.read_memory(0, 200))

    def test_seek_beyond_max_step_reached_raises(self):
        dbg = MalbolgeDebugger(HELLO_CODE)
        for _ in range(10):
            dbg.step()

        with self.assertRaises(ValueError):
            dbg.seek(11)
        # The failed seek left the debugger where it was.
        self.assertEqual(dbg.step_count, 10)

    def test_seek_negative_raises(self):
        dbg = MalbolgeDebugger(HELLO_CODE)
        for _ in range(10):
            dbg.step()
        with self.assertRaises(ValueError):
            dbg.seek(-1)

    def test_seek_below_history_window_raises(self):
        """Steps the history window has dropped are no longer seekable.

        The window is what makes seekable_range's lower bound non-zero; it is
        shrunk here rather than executing 10,000+ steps to reach it.
        """
        dbg = MalbolgeDebugger(HELLO_CODE)
        dbg._max_history = 5
        for _ in range(20):
            dbg.step()

        low, high = dbg.seekable_range
        self.assertEqual((low, high), (15, 20))

        with self.assertRaises(ValueError):
            dbg.seek(low - 1)
        with self.assertRaises(ValueError):
            dbg.seek(0)
        # Still exactly where it started, and the boundary itself works.
        self.assertEqual(dbg.step_count, 20)
        self.assertEqual(dbg.seek(low).step_count, low)

    def test_seek_after_dropping_out_of_window_then_forward(self):
        """Once rewound to the window floor, forward seeking still works."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        dbg._max_history = 5
        for _ in range(20):
            dbg.step()

        dbg.seek(15)
        state = dbg.seek(19)

        reference = MalbolgeDebugger(HELLO_CODE)
        for _ in range(19):
            reference.step()
        self.assertEqual(state.step_count, 19)
        self.assertEqual(dbg.registers, reference.registers)
        self.assertEqual(dbg.output, reference.output)

    def test_seek_after_termination(self):
        """A finished program can be scrubbed back and forward again."""
        dbg = MalbolgeDebugger(HELLO_CODE)
        dbg.run()
        final = dbg.max_step_reached
        self.assertEqual(dbg.seekable_range, (0, final))

        dbg.seek(final - 5)
        self.assertFalse(dbg.is_terminated)
        self.assertEqual(dbg.step_count, final - 5)

        dbg.seek(final)
        self.assertEqual(dbg.step_count, final)
        self.assertEqual(dbg.output, "Hello World!")

    def test_seek_malbolge20(self):
        """Seeking works over Malbolge20's sparse memory."""
        config = MalbolgeConfig.malbolge20()
        dbg = MalbolgeDebugger(HELLO_CODE, config=config)
        for _ in range(25):
            dbg.step()

        self.assertEqual(dbg.seekable_range, (0, 25))
        dbg.seek(9)

        reference = MalbolgeDebugger(HELLO_CODE, config=config)
        for _ in range(9):
            reference.step()

        self.assertEqual(dbg.step_count, 9)
        self.assertEqual(dbg.registers, reference.registers)
        self.assertEqual(dbg.output, reference.output)
        self.assertEqual(dict(dbg.write_heat), dict(reference.write_heat))
        # read_memory() slices, which SparseMemory does not support, so the
        # memory comparison goes cell by cell here.
        self.assertEqual([dbg.read_memory_value(a) for a in range(200)],
                         [reference.read_memory_value(a) for a in range(200)])

        with self.assertRaises(ValueError):
            dbg.seek(26)


if __name__ == '__main__':
    unittest.main()


class TestDebuggerFillSnapshot(unittest.TestCase):
    def test_read_order_and_reset_do_not_change_initial_fill(self):
        from malbolge.core import MalbolgeConfig
        from malbolge.debugger import MalbolgeDebugger
        for pre_read in (False, True):
            debugger = MalbolgeDebugger("D'", config=MalbolgeConfig.malbolge20())
            if pre_read:
                self.assertEqual(debugger.read_memory_value(2), 1743392216)
            debugger.step()
            self.assertEqual(debugger.read_memory_value(2), 1743392216)
            debugger.reset()
            self.assertEqual(debugger.read_memory_value(2), 1743392216)
