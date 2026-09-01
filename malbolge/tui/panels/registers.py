"""Register panel for the debugger TUI."""

from textual.widgets import Static

from ...debugger import MalbolgeDebugger
from .base import escape_markup


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
