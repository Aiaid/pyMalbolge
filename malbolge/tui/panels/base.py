"""
Shared plumbing for the debugger TUI panels.

This module must stay importable without ``textual`` installed: it is what
``malbolge.tui`` consults to decide whether the rest of the package (all of
which does import textual unconditionally) may be imported at all.
"""

# The full import list is kept verbatim from the single-file version so the
# probe still fails (and HAS_TEXTUAL still goes False) on exactly the same
# broken installs it used to; the names themselves are unused here.
try:  # noqa: F401
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


def escape_markup(text: str) -> str:
    """Escape Rich markup special characters."""
    # Escape square brackets which are used for markup tags
    return text.replace('[', '\\[').replace(']', '\\]')
