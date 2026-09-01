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

import sys

from .panels.base import HAS_TEXTUAL

from ..debugger import MalbolgeDebugger, MalbolgeState, StopReason
from ..core import MalbolgeConfig, MalbolgeVariant


if HAS_TEXTUAL:
    # Everything below imports textual unconditionally, so it may only be
    # reached once ``HAS_TEXTUAL`` says the library is there.  Without it the
    # package still imports cleanly and ``run_tui`` / ``main`` print the
    # install hint, exactly as the single-file version did.
    from .panels.base import escape_markup
    from .panels.registers import RegisterPanel
    from .panels.disasm import DisassemblyPanel
    from .panels.memory import MemoryPanel
    from .panels.io import OutputPanel, InputPanel
    from .panels.teaching import TeachingPanel
    from .panels.status import StatusBar
    from .screens.help import HelpScreen
    from .app import DebuggerApp


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
    parser.add_argument('--variant', '-v',
                        choices=['malbolge', 'malbolge20'],
                        default='malbolge',
                        help='Malbolge variant (default: malbolge)')

    args = parser.parse_args()

    # Select configuration based on variant
    if args.variant == 'malbolge20':
        config = MalbolgeConfig.malbolge20()
    else:
        config = MalbolgeConfig.original()

    try:
        with open(args.file, 'r') as f:
            source = f.read()
    except IOError as e:
        print(f"Error reading file: {e}")
        sys.exit(1)

    try:
        debugger = MalbolgeDebugger(source, args.input, config=config)
    except ValueError as e:
        print(f"Error loading source: {e}")
        sys.exit(1)

    run_tui(debugger, args.input)