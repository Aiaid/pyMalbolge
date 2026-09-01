"""Memory panel for the debugger TUI."""

from textual.widgets import Static

from ...debugger import MalbolgeDebugger
from .base import escape_markup


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
