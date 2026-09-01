"""
Stylesheet for :class:`~malbolge.tui.app.DebuggerApp`.

Moved verbatim out of ``DebuggerApp.CSS``; only the leading indentation of the
block changed (CSS ignores it).
"""

DEBUGGER_CSS = """
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
