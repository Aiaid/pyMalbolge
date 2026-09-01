"""Disassembly panel for the debugger TUI."""

from textual.widgets import Static

from ...debugger import MalbolgeDebugger
from .base import escape_markup


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
