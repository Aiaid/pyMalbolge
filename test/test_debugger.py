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


# Hello World program
HELLO_CODE = '''(=<`#9]~6ZY32Vx/4Rs+0No-&Jk)"Fh}|Bcy?`=*z]Kw%oG4UUS0/@-ejc(:'8dc'''

# Cat program (echoes input) - note the escaped backslash
CAT_CODE = '(=BA#9"=<;:3y7x54-21q/p-,+*)"!h%B0/.~P<<:(8&66#"!~}|{zyxwvugJ%'


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


if __name__ == '__main__':
    unittest.main()
