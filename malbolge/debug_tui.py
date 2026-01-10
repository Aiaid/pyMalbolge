"""
Malbolge Debugger TUI - Terminal User Interface using Textual.

Usage:
    python -m malbolge.debug_tui <file.mal> [-i input]

Keybindings:
    s / ↓   - Step one instruction
    b / ↑   - Step back
    r       - Run until breakpoint
    B       - Toggle breakpoint at current address
    ← / →   - Scroll memory view left/right
    0       - Reset memory scroll to D pointer
    q       - Quit
    ?       - Show help
"""

try:
    from textual.app import App, ComposeResult
    from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
    from textual.widgets import Header, Footer, Static, DataTable, Label, RichLog
    from textual.binding import Binding
    from textual.reactive import reactive
    from textual import events
    HAS_TEXTUAL = True
except ImportError:
    HAS_TEXTUAL = False

import sys
from typing import Optional

try:
    from .debugger import MalbolgeDebugger, MalbolgeState, StopReason
except ImportError:
    from debugger import MalbolgeDebugger, MalbolgeState, StopReason


if HAS_TEXTUAL:

    def escape_markup(text: str) -> str:
        """Escape Rich markup special characters."""
        return text.replace("[", "\\[").replace("]", "\\]")

    class RegisterPanel(Static):
        """Panel showing register values."""

        def __init__(self, debugger: MalbolgeDebugger, **kwargs):
            super().__init__(**kwargs)
            self.debugger = debugger

        def update_display(self):
            state = self.debugger.get_state()
            a_char = chr(state.a % 256) if 32 <= (state.a % 256) <= 126 else '.'
            a_char = escape_markup(a_char)

            content = f"""[bold]Registers[/bold]
━━━━━━━━━━━━━━━━━━━━
[cyan]A[/cyan] = {state.a:>10} [dim]'{a_char}'[/dim]
[cyan]C[/cyan] = {state.c:>10} [dim](code)[/dim]
[cyan]D[/cyan] = {state.d:>10} [dim](data)[/dim]
━━━━━━━━━━━━━━━━━━━━
Step: {state.step_count}
History: {self.debugger.history_size}"""
            self.update(content)


    class DisassemblyPanel(Static):
        """Panel showing disassembled instructions."""

        def __init__(self, debugger: MalbolgeDebugger, **kwargs):
            super().__init__(**kwargs)
            self.debugger = debugger

        def update_display(self):
            state = self.debugger.get_state()
            disasm = self.debugger.disassemble(max(0, state.c - 8), 17)

            lines = ["[bold]Disassembly[/bold]", "━" * 30]

            for item in disasm:
                addr = item['address']
                char = escape_markup(item['char'])
                mnemonic = item['mnemonic']

                if item['is_current']:
                    line = f"[bold green]>>> {addr:5d}  {char}  {mnemonic:5s}[/bold green]"
                elif item['has_breakpoint']:
                    line = f"[red] *  {addr:5d}  {char}  {mnemonic:5s}[/red]"
                else:
                    line = f"    {addr:5d}  {char}  {mnemonic:5s}"

                lines.append(line)

            self.update("\n".join(lines))


    class MemoryPanel(Static):
        """Panel showing memory around data pointer with multi-column display."""

        ROWS_PER_COL = 16  # Rows per column
        COLS = 3  # Number of columns

        def __init__(self, debugger: MalbolgeDebugger, **kwargs):
            super().__init__(**kwargs)
            self.debugger = debugger
            self._mem_offset = 0  # Manual scroll offset from D pointer

        def scroll_left(self, amount: int = 16):
            """Scroll memory view left (show earlier addresses)."""
            self._mem_offset -= amount
            self.update_display()

        def scroll_right(self, amount: int = 16):
            """Scroll memory view right (show later addresses)."""
            self._mem_offset += amount
            self.update_display()

        def reset_scroll(self):
            """Reset scroll to center on D pointer."""
            self._mem_offset = 0
            self.update_display()

        def update_display(self):
            state = self.debugger.get_state()
            total_cells = self.ROWS_PER_COL * self.COLS
            half_cells = total_cells // 2

            # Calculate start address centered on D + offset
            center = state.d + self._mem_offset
            start_addr = center - half_cells
            # Clamp to valid memory range (0 to 3^10 - 1 = 59048)
            start_addr = max(0, min(59049 - total_cells, start_addr))

            ctx = self.debugger.get_memory_context(start_addr + half_cells, half_cells)
            # Get full range of memory
            all_values = []
            all_chars = []
            for i in range(total_cells):
                addr = start_addr + i
                if 0 <= addr < 59049:
                    val = self.debugger._mem[addr]
                    char = chr(val % 256) if 32 <= (val % 256) <= 126 else '.'
                else:
                    val = 0
                    char = '.'
                all_values.append(val)
                all_chars.append(char)

            offset_info = f" [dim](←→ offset: {self._mem_offset:+d})[/dim]" if self._mem_offset else ""
            lines = [f"[bold]Memory @ D={state.d}[/bold]{offset_info}"]

            # Build multi-column display
            for row in range(self.ROWS_PER_COL):
                row_parts = []
                for col in range(self.COLS):
                    idx = col * self.ROWS_PER_COL + row
                    addr = start_addr + idx
                    val = all_values[idx]
                    char = escape_markup(all_chars[idx])

                    is_d = addr == state.d
                    is_c = addr == state.c

                    marker = ""
                    if is_d and is_c:
                        marker = "DC"
                    elif is_d:
                        marker = "D "
                    elif is_c:
                        marker = "C "
                    else:
                        marker = "  "

                    if is_d:
                        cell = f"[bold cyan]{marker}{addr:5d} {val:5d} '{char}'[/bold cyan]"
                    elif is_c:
                        cell = f"[yellow]{marker}{addr:5d} {val:5d} '{char}'[/yellow]"
                    else:
                        cell = f"{marker}{addr:5d} {val:5d} '{char}'"

                    row_parts.append(cell)

                lines.append(" │ ".join(row_parts))

            lines.append("[dim]←/→[/dim] scroll  [dim]0[/dim] reset")
            self.update("\n".join(lines))


    class OutputPanel(Static):
        """Panel showing program output."""

        def __init__(self, debugger: MalbolgeDebugger, **kwargs):
            super().__init__(**kwargs)
            self.debugger = debugger

        def update_display(self):
            output = self.debugger.output
            if not output:
                display = "[dim](no output)[/dim]"
            else:
                # Show last 200 chars with proper escaping
                display = output[-200:]
                if len(output) > 200:
                    display = "..." + display
                # Escape for Rich
                display = escape_markup(display)

            content = f"""[bold]Output[/bold] ({len(output)} chars)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{display}"""
            self.update(content)


    class StatusBar(Static):
        """Status bar showing current state."""

        def __init__(self, debugger: MalbolgeDebugger, **kwargs):
            super().__init__(**kwargs)
            self.debugger = debugger
            self.message = ""

        def set_message(self, msg: str):
            self.message = msg
            self.update_display()

        def update_display(self):
            state = self.debugger.get_state()
            status = state.stop_reason.value.upper()

            if state.stop_reason == StopReason.BREAKPOINT:
                status_style = "[bold red]BREAKPOINT[/bold red]"
            elif state.stop_reason == StopReason.TERMINATED:
                status_style = "[bold yellow]TERMINATED[/bold yellow]"
            else:
                status_style = f"[green]{status}[/green]"

            msg_part = f" | {self.message}" if self.message else ""

            content = f"Status: {status_style} | Next: [cyan]{state.opcode_name}[/cyan]{msg_part}"
            self.update(content)


    class DebuggerApp(App):
        """Main Textual application for Malbolge debugger."""

        CSS = """
        Screen {
            layout: grid;
            grid-size: 2 3;
            grid-columns: 1fr 1fr;
            grid-rows: auto 1fr auto;
        }

        #header {
            column-span: 2;
            height: 3;
            background: $primary;
            color: $text;
            text-align: center;
            padding: 1;
        }

        #disasm-panel {
            border: solid $primary;
            padding: 1;
            height: 100%;
        }

        #memory-panel {
            border: solid $secondary;
            padding: 1;
            height: 100%;
        }

        #reg-panel {
            border: solid $accent;
            padding: 1;
        }

        #output-panel {
            border: solid $warning;
            padding: 1;
        }

        #status-bar {
            column-span: 2;
            height: 3;
            background: $surface;
            padding: 1;
        }

        #help-panel {
            column-span: 2;
            background: $surface;
            padding: 1;
        }
        """

        BINDINGS = [
            Binding("s", "step", "Step"),
            Binding("down", "step", "Step", show=False),
            Binding("b", "step_back", "Back"),
            Binding("up", "step_back", "Back", show=False),
            Binding("r", "run", "Run"),
            Binding("shift+b", "toggle_breakpoint", "Breakpoint"),
            Binding("left", "memory_scroll_left", "Mem←", show=False),
            Binding("right", "memory_scroll_right", "Mem→", show=False),
            Binding("0", "memory_reset_scroll", "MemReset", show=False),
            Binding("q", "quit", "Quit"),
            Binding("question_mark", "show_help", "Help"),
            Binding("h", "show_help", "Help"),
            Binding("escape", "clear_message", "Clear"),
        ]

        def __init__(self, debugger: MalbolgeDebugger):
            super().__init__()
            self.debugger = debugger
            self._panels = []

        def compose(self) -> ComposeResult:
            # Header with keybindings
            yield Static(
                "[bold]pyMalbolge Debugger[/bold]  "
                "[cyan]s/\u2193[/cyan]:Step  "
                "[cyan]b/\u2191[/cyan]:Back  "
                "[cyan]r[/cyan]:Run  "
                "[cyan]B[/cyan]:Bp  "
                "[cyan]\u2190/\u2192[/cyan]:Mem  "
                "[cyan]0[/cyan]:Reset  "
                "[cyan]q[/cyan]:Quit",
                id="header"
            )

            # Main panels
            yield DisassemblyPanel(self.debugger, id="disasm-panel")
            yield MemoryPanel(self.debugger, id="memory-panel")
            yield RegisterPanel(self.debugger, id="reg-panel")
            yield OutputPanel(self.debugger, id="output-panel")

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
            """Show help message."""
            self._set_status(
                "Keys: s/↓=step, b/↑=back, r=run, B=breakpoint, ←/→=mem scroll, 0=reset, q=quit"
            )

        def action_clear_message(self) -> None:
            """Clear status message."""
            self._set_status("")

        def action_quit(self) -> None:
            """Quit the application."""
            self.exit()


def run_tui(debugger: MalbolgeDebugger) -> None:
    """Run the TUI debugger."""
    if not HAS_TEXTUAL:
        print("TUI mode requires the 'textual' library.")
        print("Install with: pip install textual")
        return

    app = DebuggerApp(debugger)
    app.run()


def main():
    """Command-line entry point for TUI debugger."""
    if not HAS_TEXTUAL:
        print("TUI mode requires the 'textual' library.")
        print("Install with: pip install textual")
        sys.exit(1)

    import argparse

    parser = argparse.ArgumentParser(
        description='Malbolge Debugger TUI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Keybindings:
  s/↓   Step one instruction
  b/↑   Step back
  r     Run until breakpoint
  B     Toggle breakpoint at current address
  ←/→   Scroll memory view left/right
  0     Reset memory scroll to D pointer
  q     Quit
  ?/h   Show help

Examples:
  %(prog)s hello.mal              Debug hello.mal
  %(prog)s hello.mal -i "input"   Debug with input
"""
    )
    parser.add_argument('file', help='Malbolge source file')
    parser.add_argument('-i', '--input', default='', help='Program input')

    args = parser.parse_args()

    try:
        with open(args.file, 'r') as f:
            source = f.read()
    except IOError as e:
        print(f"Error reading file: {e}")
        sys.exit(1)

    try:
        debugger = MalbolgeDebugger(source, args.input)
    except ValueError as e:
        print(f"Error loading source: {e}")
        sys.exit(1)

    run_tui(debugger)


if __name__ == '__main__':
    main()
