"""The Textual application that drives the Malbolge debugger TUI."""

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import ScrollableContainer, Vertical
from textual.widgets import Static

from ..debugger import MalbolgeDebugger, StopReason
from .panels.disasm import DisassemblyPanel
from .panels.io import InputPanel, OutputPanel
from .panels.memory import MemoryPanel
from .panels.registers import RegisterPanel
from .panels.status import StatusBar
from .panels.teaching import TeachingPanel
from .screens.help import HelpScreen
from .theme import DEBUGGER_CSS


class DebuggerApp(App):
    """Main Textual application for Malbolge debugger."""

    CSS = DEBUGGER_CSS

    BINDINGS = [
        Binding("down", "step", "Step", priority=True),
        Binding("up", "step_back", "Back", priority=True),
        Binding("r", "run", "Run"),
        Binding("b", "toggle_breakpoint", "Breakpoint"),
        Binding("left", "memory_scroll_left", "Mem←", show=False),
        Binding("right", "memory_scroll_right", "Mem→", show=False),
        Binding("0", "memory_reset_scroll", "MemReset", show=False),
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "show_help", "Help"),
        Binding("h", "show_help", "Help"),
        Binding("escape", "clear_message", "Clear"),
    ]

    def __init__(self, debugger: MalbolgeDebugger, input_data: str = ""):
        super().__init__()
        self.debugger = debugger
        self.input_data = input_data

    def compose(self) -> ComposeResult:
        # Header
        yield Static(
            "[bold]pyMalbolge Debugger[/bold]  "
            "[cyan]↓[/cyan]:Step  "
            "[cyan]↑[/cyan]:Back  "
            "[cyan]r[/cyan]:Run  "
            "[cyan]b[/cyan]:Bp  "
            "[cyan]←/→[/cyan]:Mem  "
            "[cyan]h[/cyan]:Help  "
            "[cyan]q[/cyan]:Quit",
            id="header"
        )

        # Row 2: Disassembly | Memory
        yield DisassemblyPanel(self.debugger, id="disasm-panel")
        yield MemoryPanel(self.debugger, id="memory-panel")

        # Row 3: Left (Reg+IO) | Teaching (scrollable)
        yield Vertical(
            RegisterPanel(self.debugger, id="reg-panel"),
            OutputPanel(self.debugger, id="output-panel"),
            InputPanel(self.debugger, self.input_data, id="input-panel"),
            id="left-bottom"
        )
        yield ScrollableContainer(
            TeachingPanel(self.debugger, id="teaching-panel"),
            id="teaching-scroll"
        )

        # Status bar
        yield StatusBar(self.debugger, id="status-bar")

    def on_mount(self) -> None:
        """Initialize panels after mount."""
        self._refresh_all()

    def _refresh_all(self) -> None:
        """Refresh all panels."""
        self.query_one("#disasm-panel", DisassemblyPanel).update_display()
        self.query_one("#memory-panel", MemoryPanel).update_display()
        self.query_one("#reg-panel", RegisterPanel).update_display()
        self.query_one("#output-panel", OutputPanel).update_display()
        self.query_one("#input-panel", InputPanel).update_display()
        self.query_one("#teaching-panel", TeachingPanel).update_display()
        self.query_one("#status-bar", StatusBar).update_display()

    def _set_status(self, msg: str) -> None:
        """Set status bar message."""
        self.query_one("#status-bar", StatusBar).set_message(msg)

    def action_step(self) -> None:
        """Step one instruction."""
        if self.debugger.is_terminated:
            self._set_status("Program already terminated")
            return

        state = self.debugger.step()
        self._refresh_all()

        if state.stop_reason == StopReason.TERMINATED:
            self._set_status("Program terminated")
        elif state.stop_reason == StopReason.INPUT_EXHAUSTED:
            self._set_status("Input exhausted")

    def action_step_back(self) -> None:
        """Step back one instruction."""
        if not self.debugger.can_step_back:
            self._set_status("No history available")
            return

        self.debugger.step_back()
        self._refresh_all()
        self._set_status(f"Stepped back (history: {self.debugger.history_size})")

    def action_run(self) -> None:
        """Run until breakpoint or termination."""
        if self.debugger.is_terminated:
            self._set_status("Program already terminated")
            return

        # Run with a reasonable max to prevent hanging
        state = self.debugger.run(max_steps=100000)
        self._refresh_all()

        if state.stop_reason == StopReason.BREAKPOINT:
            self._set_status(f"Breakpoint at {state.c}")
        elif state.stop_reason == StopReason.TERMINATED:
            self._set_status("Program terminated")
        elif state.stop_reason == StopReason.WATCHPOINT:
            self._set_status("Watchpoint triggered")
        else:
            self._set_status("Stopped (max steps reached)")

    def action_toggle_breakpoint(self) -> None:
        """Toggle breakpoint at current address."""
        state = self.debugger.get_state()
        addr = state.c

        if self.debugger.remove_breakpoint(addr):
            self._set_status(f"Breakpoint removed at {addr}")
        else:
            self.debugger.add_breakpoint(addr)
            self._set_status(f"Breakpoint set at {addr}")

        self._refresh_all()

    def action_memory_scroll_left(self) -> None:
        """Scroll memory view left."""
        self.query_one("#memory-panel", MemoryPanel).scroll_left()

    def action_memory_scroll_right(self) -> None:
        """Scroll memory view right."""
        self.query_one("#memory-panel", MemoryPanel).scroll_right()

    def action_memory_reset_scroll(self) -> None:
        """Reset memory scroll to center on D."""
        self.query_one("#memory-panel", MemoryPanel).reset_scroll()
        self._set_status("Memory view reset to D pointer")

    def action_show_help(self) -> None:
        """Show help screen."""
        self.push_screen(HelpScreen())

    def action_clear_message(self) -> None:
        """Clear status message."""
        self._set_status("")

    def action_quit(self) -> None:
        """Quit the application."""
        self.exit()
