"""Teaching panel (instruction help + execution preview) for the debugger TUI."""

from textual.widgets import Static

from ...debugger import MalbolgeDebugger, StopReason
from .base import escape_markup


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
