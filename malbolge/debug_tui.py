"""
Malbolge Debugger TUI - Terminal User Interface using Textual.

Usage:
    python -m malbolge.debug_tui <file.mal> [-i input]

Keybindings:
    ↓       - Step one instruction
    ↑       - Step back
    r       - Run until breakpoint
    b       - Toggle breakpoint at current address
    ← / →   - Scroll memory view left/right
    0       - Reset memory scroll to D pointer
    h / ?   - Show help
    q       - Quit
"""

try:
    from textual.app import App, ComposeResult
    from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
    from textual.widgets import Header, Footer, Static, DataTable, Label, RichLog
    from textual.binding import Binding
    from textual.reactive import reactive
    from textual.screen import ModalScreen
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
        # Escape square brackets which are used for markup tags
        return text.replace('[', '\\[').replace(']', '\\]')

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
            # Show 11 instructions with current instruction in the middle (position 5)
            num_instructions = 11
            middle = num_instructions // 2  # 5
            start_addr = max(0, state.c - middle)
            disasm = self.debugger.disassemble(start_addr, num_instructions)

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

        ROWS_PER_COL = 8  # Rows per column
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
                # Show last 100 chars with proper escaping
                display = output[-100:]
                if len(output) > 100:
                    display = "..." + display
                display = escape_markup(display)

            content = f"[bold]Out[/bold]({len(output)}): {display}"
            self.update(content)


    class InputPanel(Static):
        """Panel showing program input status."""

        def __init__(self, debugger: MalbolgeDebugger, input_data: str, **kwargs):
            super().__init__(**kwargs)
            self.debugger = debugger
            self.input_data = input_data

        def update_display(self):
            if not self.input_data:
                self.update("[bold]In[/bold]: [dim](none)[/dim]")
                return

            consumed = self.debugger._input_pos
            total = len(self.input_data)
            remaining = self.input_data[consumed:consumed+20]
            remaining = escape_markup(remaining)
            if len(self.input_data) - consumed > 20:
                remaining += "..."

            self.update(f"[bold]In[/bold]({consumed}/{total}): [green]{remaining}[/green]")


    class TeachingPanel(Static):
        """Combined panel showing instruction help and execution preview (scrollable)."""

        def __init__(self, debugger: MalbolgeDebugger, **kwargs):
            super().__init__(**kwargs)
            self.debugger = debugger

        def _format_ternary(self, digits: list, highlight_pos: int = -1) -> str:
            """Format ternary digits for display (MSB first)."""
            result = []
            for i in range(9, -1, -1):
                d = digits[i]
                if i == highlight_pos:
                    result.append(f"[bold yellow]{d}[/bold yellow]")
                else:
                    result.append(str(d))
            return " ".join(result)

        def update_display(self):
            state = self.debugger.get_state()
            preview = self.debugger.preview_next_instruction()

            lines = []

            if state.stop_reason == StopReason.TERMINATED:
                lines.append("[bold]Teaching[/bold]")
                lines.append("[dim]Program terminated[/dim]")
                self.update("\n".join(lines))
                return

            # === Part 1: Instruction Help ===
            opcode_calc = preview.get('opcode_calculation', {})
            opcode = preview.get('opcode', -1)
            help_info = self.debugger.get_opcode_help(opcode)

            if opcode_calc:
                mem_c = opcode_calc.get('mem_c', 0)
                mem_c_char = escape_markup(opcode_calc.get('mem_c_char', '?'))
                c = opcode_calc.get('c', 0)
                lines.append(f"[bold cyan]({mem_c}+{c})%94={opcode}[/bold cyan] [dim]'{mem_c_char}'[/dim]")

            if help_info:
                syntax = help_info['syntax'].replace('[', '\\[')
                desc = help_info['description'].replace('[', '\\[')
                lines.append(f"[bold green]{help_info['name']}[/bold green] {syntax}")
                lines.append(f"[dim]{desc}[/dim]")
            lines.append("─" * 32)

            # === Part 2: Execution Preview ===
            if preview.get('will_terminate'):
                lines.append("[bold red]Will terminate[/bold red]")

            # Register changes
            reg_changes = preview.get('register_changes', {})
            if reg_changes:
                lines.append("[yellow]Registers:[/yellow]")
                for reg, (old, new) in reg_changes.items():
                    if old != new:
                        lines.append(f"  {reg.upper()}: {old} -> [green]{new}[/green]")

            # Memory changes
            mem_changes = preview.get('memory_changes', {})
            if mem_changes:
                lines.append("[yellow]Memory:[/yellow]")
                for addr, (old, new) in mem_changes.items():
                    lines.append(f"  \\[{addr}]: {old} -> [green]{new}[/green]")

            # Encryption info with detailed calculation
            if preview.get('will_encrypt'):
                enc_addr = preview.get('encrypt_address', 0)
                enc_val = preview.get('encrypted_value', 0)
                old_val = self.debugger._mem[enc_addr]
                old_char = (chr(old_val) if 32 <= old_val <= 126 else '.').replace('[', '\\[')
                new_char = (chr(enc_val) if 32 <= enc_val <= 126 else '.').replace('[', '\\[')
                enc_index = old_val - 33
                lines.append(f"[yellow]Encrypt mem\\[{enc_addr}]:[/yellow]")
                lines.append(f"  ENCRYPT\\[{old_val}-33] = ENCRYPT\\[{enc_index}]")
                lines.append(f"  '{old_char}'({old_val}) -> '{new_char}'({enc_val})")

            # === Part 3: Detailed Calculations ===
            calc_details = preview.get('calculation_details')
            if calc_details:
                calc_type = calc_details.get('type', '')

                if 'a_ternary' in calc_details:  # Crazy operation
                    lines.append("─" * 32)
                    lines.append("[yellow]Crazy Operation:[/yellow]")
                    lines.append("[dim]TABLE: a\\b│0 1 2[/dim]")
                    lines.append("[dim]    0│1 0 0  1│1 0 2  2│2 2 1[/dim]")

                    a_val = calc_details['a']
                    b_val = calc_details['b']
                    result = calc_details['result']
                    lines.append(f"a={a_val} b={b_val}")

                    a_tern = calc_details['a_ternary']
                    b_tern = calc_details['b_ternary']
                    r_tern = calc_details['result_ternary']
                    lines.append(f"[dim]a:[/dim]{self._format_ternary(a_tern)}")
                    lines.append(f"[dim]b:[/dim]{self._format_ternary(b_tern)}")
                    lines.append(f"[dim]r:[/dim]{self._format_ternary(r_tern)}")
                    lines.append(f"[bold]= {result}[/bold]")

                elif 'original_ternary' in calc_details:  # Rotate
                    lines.append("─" * 32)
                    lines.append("[yellow]Rotation:[/yellow]")
                    original = calc_details['original']
                    result = calc_details['result']
                    lsb = calc_details['lsb']

                    orig_tern = calc_details['original_ternary']
                    rot_tern = calc_details['rotated_ternary']
                    lines.append(f"[dim]Before:[/dim]{self._format_ternary(orig_tern, 0)}")
                    lines.append(f"[dim]After: [/dim]{self._format_ternary(rot_tern, 9)}")
                    lines.append(f"LSB({lsb})->MSB [bold]= {result}[/bold]")

                elif calc_type == 'output':
                    char = escape_markup(calc_details.get('char', '?'))
                    lines.append(f"[yellow]Output:[/yellow] '{char}' ({calc_details.get('ascii', 0)})")

                elif calc_type == 'input':
                    char = escape_markup(calc_details.get('char', '?'))
                    lines.append(f"[yellow]Input:[/yellow] '{char}' ({calc_details.get('ascii', 0)})")

                elif calc_type == 'input_exhausted':
                    lines.append("[red]Input exhausted![/red]")

                elif calc_type == 'mov':
                    note = calc_details.get('note', '').replace('[', '\\[')
                    lines.append(f"[yellow]Move:[/yellow] {note}")

            self.update("\n".join(lines))


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


    class HelpScreen(ModalScreen):
        """Modal help screen with Malbolge reference."""

        BINDINGS = [
            Binding("escape", "close_help", "Close", priority=True),
            Binding("q", "close_help", "Close", priority=True),
            Binding("h", "close_help", "Close", priority=True),
        ]

        DEFAULT_CSS = """
        HelpScreen {
            align: center middle;
            background: rgba(0, 0, 0, 0.7);
        }

        HelpScreen > ScrollableContainer {
            width: 70;
            height: 80%;
            background: $surface;
            border: thick $primary;
            padding: 1 2;
        }
        """

        def compose(self) -> ComposeResult:
            help_text = """\
[bold cyan]══ pyMalbolge Debugger Help ══[/bold cyan]

[bold yellow]─ Keybindings ─[/bold yellow]
 [cyan]↓[/cyan]     Step one instruction
 [cyan]↑[/cyan]     Step back (undo)
 [cyan]r[/cyan]     Run until breakpoint/end
 [cyan]b[/cyan]     Toggle breakpoint at C
 [cyan]←[/cyan]/[cyan]→[/cyan]   Scroll memory view
 [cyan]0[/cyan]     Reset memory to D
 [cyan]h[/cyan]/[cyan]?[/cyan]   Show this help
 [cyan]q[/cyan]     Quit debugger

[bold yellow]─ Malbolge Architecture ─[/bold yellow]
 Memory: 59049 (3^10) cells
 Values: 0 to 59048

 Registers:
  [cyan]A[/cyan]  Accumulator
  [cyan]C[/cyan]  Code pointer
  [cyan]D[/cyan]  Data pointer

[bold yellow]─ Opcode Table ─[/bold yellow]
 Opcode = (mem\\[C\\] + C) % 94

 [cyan] 4[/cyan] jmp   C = mem\\[D\\]
 [cyan] 5[/cyan] out   print(A % 256)
 [cyan]23[/cyan] in    A = getchar()
 [cyan]39[/cyan] rotr  rotate mem\\[D\\], A=mem\\[D\\]
 [cyan]40[/cyan] mov   D = mem\\[D\\]
 [cyan]62[/cyan] crz   crazy(A,mem\\[D\\])
 [cyan]68[/cyan] nop   (nothing)
 [cyan]81[/cyan] end   halt

 After: C++, D++, encrypt mem\\[C\\]

[bold yellow]─ Crazy Table ─[/bold yellow]
 Per-trit (10 trits):
      b: 0  1  2
   a┌───────────
   0│  1  0  0
   1│  1  0  2
   2│  2  2  1

[bold yellow]─ Rotate ─[/bold yellow]
 rot(n) = 3^9*(n%3) + n//3
 LSB wraps to MSB

[bold yellow]─ Encrypt ─[/bold yellow]
 mem\\[C\\] = ENCRYPT\\[mem\\[C\\]-33\\]

 [dim]5z\\]&gqtyfr$(we4{{WP)H-Zn,
 \\[%\\\\3dL+Q;>U!pJS72FhOA1CB
 6v^=I_0/8|jsb9m<.TVac`uY*
 MK'X~xDl}}REokN:#?G"i@[/dim]

[bold green]── ESC/q/h to close ──[/bold green]
"""
            yield ScrollableContainer(Static(help_text))

        def action_close_help(self) -> None:
            self.dismiss()


    class DebuggerApp(App):
        """Main Textual application for Malbolge debugger."""

        CSS = """
        Screen {
            layout: grid;
            grid-size: 2 4;
            grid-columns: 1fr 1fr;
            grid-rows: auto 1fr 1fr auto;
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

        #left-bottom {
            height: 100%;
            border: solid $accent;
            padding: 1;
        }

        #reg-panel {
            height: auto;
        }

        #io-panel {
            height: auto;
        }

        #output-panel {
            height: auto;
        }

        #input-panel {
            height: auto;
        }

        #teaching-scroll {
            border: solid $success;
            height: 100%;
        }

        #teaching-panel {
            padding: 1;
        }

        #status-bar {
            column-span: 2;
            height: 3;
            background: $surface;
            padding: 1;
        }
        """

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


def run_tui(debugger: MalbolgeDebugger, input_data: str = "") -> None:
    """Run the TUI debugger."""
    if not HAS_TEXTUAL:
        print("TUI mode requires the 'textual' library.")
        print("Install with: pip install textual")
        return

    app = DebuggerApp(debugger, input_data)
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

    run_tui(debugger, args.input)


if __name__ == '__main__':
    main()
