"""Modal help screen for the debugger TUI."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import ScrollableContainer
from textual.screen import ModalScreen
from textual.widgets import Static


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
