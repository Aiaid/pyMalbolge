"""
Regression tests for the Textual TUI debugger.

These tests exist to prove that refactoring ``malbolge/debug_tui.py`` (e.g.
splitting it into a package) does not change observable behaviour.  To stay
useful across such a refactor they deliberately touch only:

* the public entry points ``DebuggerApp`` / ``run_tui`` / ``main``,
* the debugger state reachable through ``MalbolgeDebugger``'s public API,
* the *text* the app renders on screen.

Nothing here may assert on widget classes, CSS ids, or DOM layout: those are
exactly the things a refactor is allowed to move around.
"""

import asyncio
import functools
import os
import re
import sys
import unittest

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from malbolge.debugger import MalbolgeDebugger

try:
    import textual  # noqa: F401
    HAS_TEXTUAL = True
except ImportError:
    HAS_TEXTUAL = False

if HAS_TEXTUAL:
    from malbolge.debug_tui import DebuggerApp, run_tui, main


# Hello World (examples/hello.mal): terminates in 39 steps.
HELLO_CODE = '''(=<`#9]~6ZY32Vx/4Rs+0No-&Jk)"Fh}|Bcy?`=*z]Kw%oG4UUS0/@-ejc(:'8dc'''

# Cat program: echoes its input, then terminates.
CAT_CODE = '(=BA#9"=<;:3y7x54-21q/p-,+*)"!h%B0/.~P<<:(8&66#"!~}|{zyxwvugJ%'

# Enough input to keep the cat program busy past the run action's step limit.
LONG_INPUT = "a" * 2500

# A screen big enough that no panel gets clipped.
SCREEN_SIZE = (180, 60)

# Cells are rendered as "<addr> <value> '<char>'".
_MEMORY_CELL_RE = re.compile(r"(\d+)\s+(\d+) '")


# ==================== Helpers ====================

def rendered_chunks(app):
    """Text of every widget currently on screen, with markup stripped."""
    chunks = []
    for screen in app.screen_stack:
        for widget in screen.walk_children(with_self=True):
            try:
                rendered = widget.render()
            except Exception:  # pragma: no cover - containers may not render
                continue
            if rendered is None:
                continue
            text = str(rendered)
            if text:
                chunks.append(text)
    return chunks


def screen_text(app):
    """Everything the app shows right now, as one string."""
    return "\n".join(rendered_chunks(app))


def chunk_containing(app, marker):
    """The single rendered chunk that contains ``marker`` (a panel's text)."""
    for chunk in rendered_chunks(app):
        if marker in chunk:
            return chunk
    raise AssertionError(f"no rendered text contains {marker!r}")


def memory_addresses(app):
    """Addresses currently listed by the memory panel."""
    text = chunk_containing(app, "Memory @ D=")
    return [int(m.group(1)) for m in _MEMORY_CELL_RE.finditer(text)]


def drive(source=HELLO_CODE, input_data="", size=SCREEN_SIZE):
    """Run a test body inside a live ``DebuggerApp``.

    The wrapped body is a coroutine ``(self, pilot, app, debugger)``.  pytest
    here has no asyncio plugin, so each test owns its own event loop.
    """
    def decorator(body):
        @functools.wraps(body)
        def wrapper(self):
            async def runner():
                debugger = MalbolgeDebugger(source, input_data)
                app = DebuggerApp(debugger, input_data)
                async with app.run_test(size=size) as pilot:
                    await body(self, pilot, app, debugger)
            asyncio.run(runner())
        return wrapper
    return decorator


@unittest.skipUnless(HAS_TEXTUAL, "textual is not installed")
class TestDebuggerAppStartup(unittest.TestCase):
    """The app composes and shows the initial machine state."""

    @drive()
    async def test_initial_screen(self, pilot, app, debugger):
        text = screen_text(app)

        # Every panel is present...
        self.assertIn("Disassembly", text)
        self.assertIn("Registers", text)
        self.assertIn("Memory @ D=0", text)
        self.assertIn("Status:", text)

        # ...and shows the un-executed program.
        self.assertEqual(debugger.step_count, 0)
        self.assertIn("Step: 0", text)
        self.assertIn("(no output)", text)
        self.assertFalse(debugger.is_terminated)

    def test_public_entry_points_are_importable(self):
        # ``malbolge-tui`` and ``debug_cli --tui`` reach the TUI through these.
        self.assertTrue(callable(run_tui))
        self.assertTrue(callable(main))


@unittest.skipUnless(HAS_TEXTUAL, "textual is not installed")
class TestStepping(unittest.TestCase):
    """down / up: single step and step back."""

    @drive()
    async def test_step_advances_execution(self, pilot, app, debugger):
        await pilot.press("down")
        await pilot.pause()

        self.assertEqual(debugger.step_count, 1)

        state = debugger.get_state()
        registers = chunk_containing(app, "Registers")
        self.assertIn("Step: 1", registers)
        self.assertRegex(registers, r"C\s*=\s*%d\b" % state.c)
        self.assertRegex(registers, r"D\s*=\s*%d\b" % state.d)

    @drive()
    async def test_step_back_restores_previous_state(self, pilot, app, debugger):
        for _ in range(3):
            await pilot.press("down")
        await pilot.pause()

        before = debugger.get_state()

        await pilot.press("down")
        await pilot.pause()
        self.assertEqual(debugger.step_count, before.step_count + 1)

        await pilot.press("up")
        await pilot.pause()

        after = debugger.get_state()
        self.assertEqual(after.step_count, before.step_count)
        self.assertEqual((after.a, after.c, after.d), (before.a, before.c, before.d))
        self.assertIn("Stepped back", screen_text(app))
        self.assertIn("Step: %d" % before.step_count, chunk_containing(app, "Registers"))

    @drive()
    async def test_step_back_without_history_reports_instead_of_crashing(
            self, pilot, app, debugger):
        await pilot.press("up")
        await pilot.pause()

        self.assertIn("No history available", screen_text(app))
        self.assertEqual(debugger.step_count, 0)
        self.assertTrue(app.is_running)


@unittest.skipUnless(HAS_TEXTUAL, "textual is not installed")
class TestRunning(unittest.TestCase):
    """r: run until a breakpoint or termination."""

    @drive()
    async def test_run_to_termination(self, pilot, app, debugger):
        await pilot.press("r")
        await pilot.pause()

        self.assertTrue(debugger.is_terminated)
        self.assertEqual(debugger.output, "Hello World!")

        text = screen_text(app)
        self.assertIn("Program terminated", text)
        self.assertIn("TERMINATED", text)
        self.assertIn("Hello World!", chunk_containing(app, "Out("))

    @drive()
    async def test_run_stops_at_breakpoint(self, pilot, app, debugger):
        # Walk to an address a few instructions in, mark it, rewind to the start.
        for _ in range(5):
            await pilot.press("down")
        await pilot.pause()
        target = debugger.get_state().c

        await pilot.press("b")
        await pilot.pause()
        for _ in range(5):
            await pilot.press("up")
        await pilot.pause()
        self.assertEqual(debugger.step_count, 0)

        await pilot.press("r")
        await pilot.pause()

        self.assertFalse(debugger.is_terminated)
        self.assertEqual(debugger.get_state().c, target)
        self.assertIn("Breakpoint at %d" % target, screen_text(app))

    @drive()
    async def test_run_stops_at_watchpoint(self, pilot, app, debugger):
        # Watchpoints have no keybinding, but the run action reports them.
        debugger.add_watchpoint(0)  # self-modifying code rewrites mem[0]

        await pilot.press("r")
        await pilot.pause()

        self.assertFalse(debugger.is_terminated)
        self.assertIn("Watchpoint triggered", screen_text(app))

    @drive()
    async def test_run_after_termination_reports_instead_of_crashing(
            self, pilot, app, debugger):
        await pilot.press("r")
        await pilot.pause()
        steps = debugger.step_count

        await pilot.press("r")
        await pilot.pause()

        self.assertIn("Program already terminated", screen_text(app))
        self.assertEqual(debugger.step_count, steps)
        self.assertTrue(app.is_running)

    @drive()
    async def test_step_after_termination_reports_instead_of_crashing(
            self, pilot, app, debugger):
        await pilot.press("r")
        await pilot.pause()
        steps = debugger.step_count

        await pilot.press("down")
        await pilot.pause()

        self.assertIn("Program already terminated", screen_text(app))
        self.assertEqual(debugger.step_count, steps)
        self.assertTrue(app.is_running)

    @drive(source=CAT_CODE, input_data=LONG_INPUT)
    async def test_run_stops_at_the_step_limit(self, pilot, app, debugger):
        # The cat program needs ~45 steps per input character, so this input
        # outlives the run action's internal 100k step budget (~0.5s).
        await pilot.press("r")
        await pilot.pause()

        self.assertFalse(debugger.is_terminated)
        self.assertEqual(debugger.step_count, 100000)
        self.assertIn("max steps reached", screen_text(app))

    @drive(source=CAT_CODE, input_data="hi")
    async def test_run_consumes_input_and_echoes_it(self, pilot, app, debugger):
        await pilot.press("r")
        await pilot.pause()

        self.assertEqual(debugger.output, "hi")
        self.assertIn("hi", chunk_containing(app, "Out("))
        # The input panel tracks how much of the input has been consumed.
        self.assertIn("In(2/2)", chunk_containing(app, "In("))


@unittest.skipUnless(HAS_TEXTUAL, "textual is not installed")
class TestBreakpoints(unittest.TestCase):
    """b: toggle a breakpoint at the current code pointer."""

    @drive()
    async def test_toggle_adds_then_removes(self, pilot, app, debugger):
        address = debugger.get_state().c

        await pilot.press("b")
        await pilot.pause()

        self.assertEqual([bp.address for bp in debugger.list_breakpoints()], [address])
        self.assertIn("Breakpoint set at %d" % address, screen_text(app))

        await pilot.press("b")
        await pilot.pause()

        self.assertEqual(debugger.list_breakpoints(), [])
        self.assertIn("Breakpoint removed at %d" % address, screen_text(app))

    @drive()
    async def test_breakpoints_at_two_addresses_coexist(self, pilot, app, debugger):
        first = debugger.get_state().c
        await pilot.press("b")
        await pilot.press("down")
        await pilot.pause()
        second = debugger.get_state().c
        await pilot.press("b")
        await pilot.pause()

        self.assertNotEqual(first, second)
        self.assertEqual(
            sorted(bp.address for bp in debugger.list_breakpoints()),
            sorted([first, second]),
        )


@unittest.skipUnless(HAS_TEXTUAL, "textual is not installed")
class TestMemoryView(unittest.TestCase):
    """left / right / 0: scroll the memory panel and recentre it on D."""

    @drive()
    async def test_scroll_right_left_and_reset(self, pilot, app, debugger):
        base = memory_addresses(app)
        self.assertTrue(base, "memory panel rendered no cells")

        await pilot.press("right")
        await pilot.pause()
        once_right = memory_addresses(app)
        self.assertGreater(min(once_right), min(base))
        self.assertEqual(len(once_right), len(base))

        await pilot.press("right")
        await pilot.pause()
        twice_right = memory_addresses(app)
        self.assertGreater(min(twice_right), min(once_right))

        await pilot.press("left")
        await pilot.pause()
        self.assertEqual(memory_addresses(app), once_right)

        await pilot.press("0")
        await pilot.pause()
        self.assertEqual(memory_addresses(app), base)
        self.assertIn("Memory view reset to D pointer", screen_text(app))

    @drive()
    async def test_scrolling_does_not_execute_the_program(self, pilot, app, debugger):
        await pilot.press("right")
        await pilot.press("left")
        await pilot.press("0")
        await pilot.pause()

        self.assertEqual(debugger.step_count, 0)

    @drive()
    async def test_view_follows_data_pointer(self, pilot, app, debugger):
        for _ in range(10):
            await pilot.press("down")
        await pilot.pause()

        self.assertIn("Memory @ D=%d" % debugger.get_state().d,
                      chunk_containing(app, "Memory @ D="))


@unittest.skipUnless(HAS_TEXTUAL, "textual is not installed")
class TestHelpScreen(unittest.TestCase):
    """h / ? open the help modal; escape closes it."""

    @drive()
    async def test_help_opens_and_closes(self, pilot, app, debugger):
        self.assertNotIn("Debugger Help", screen_text(app))

        await pilot.press("h")
        await pilot.pause()
        help_text = screen_text(app)
        self.assertIn("Debugger Help", help_text)
        self.assertIn("Keybindings", help_text)
        self.assertIn("Opcode Table", help_text)

        await pilot.press("escape")
        await pilot.pause()
        self.assertNotIn("Debugger Help", screen_text(app))
        self.assertTrue(app.is_running)
        self.assertEqual(debugger.step_count, 0)

    @drive()
    async def test_question_mark_also_opens_help(self, pilot, app, debugger):
        await pilot.press("question_mark")
        await pilot.pause()
        self.assertIn("Debugger Help", screen_text(app))

        await pilot.press("escape")
        await pilot.pause()
        self.assertNotIn("Debugger Help", screen_text(app))


@unittest.skipUnless(HAS_TEXTUAL, "textual is not installed")
class TestStatusMessage(unittest.TestCase):
    """escape clears the status message when no modal is open."""

    @drive()
    async def test_escape_clears_status_message(self, pilot, app, debugger):
        await pilot.press("b")
        await pilot.pause()
        self.assertIn("Breakpoint set at", screen_text(app))

        await pilot.press("escape")
        await pilot.pause()
        self.assertNotIn("Breakpoint set at", screen_text(app))
        # The rest of the status bar survives.
        self.assertIn("Status:", screen_text(app))


@unittest.skipUnless(HAS_TEXTUAL, "textual is not installed")
class TestQuit(unittest.TestCase):
    """q leaves the app."""

    @drive()
    async def test_quit_stops_the_app(self, pilot, app, debugger):
        self.assertTrue(app.is_running)

        await pilot.press("q")
        await pilot.pause()

        self.assertFalse(app.is_running)


if __name__ == '__main__':
    unittest.main()
