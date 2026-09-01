"""Program output / input panels for the debugger TUI."""

from textual.widgets import Static

from ...debugger import MalbolgeDebugger
from .base import escape_markup


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
