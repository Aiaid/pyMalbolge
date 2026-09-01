"""Status bar for the debugger TUI."""

from textual.widgets import Static

from ...debugger import MalbolgeDebugger, StopReason


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
