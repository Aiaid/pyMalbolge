"""
Malbolge Debugger CLI - Interactive command-line debugger interface.

Usage:
    python -m malbolge.debug_cli <file.mal> [-i input]

Commands:
    step, s [n]     - Step n instructions (default: 1)
    back, sb [n]    - Step back n instructions
    run, r          - Run until breakpoint or termination
    break, b <addr> - Set breakpoint at address
    delete, d <addr>- Delete breakpoint
    examine, x      - Examine memory
    registers, reg  - Show registers
    disassemble,dis - Disassemble instructions
    output, o       - Show program output
    tui             - Launch TUI mode
    help, h         - Show help
    quit, q         - Exit debugger
"""

import cmd
import sys
import os
from typing import Optional

try:
    from .debugger import MalbolgeDebugger, MalbolgeState, StopReason, Breakpoint
except ImportError:
    from debugger import MalbolgeDebugger, MalbolgeState, StopReason, Breakpoint


class DebugCLI(cmd.Cmd):
    """Interactive Malbolge debugger command-line interface."""

    intro = """
================================================================================
                        pyMalbolge Debugger v1.0
================================================================================
Type 'help' or '?' for available commands. Type 'help <cmd>' for details.
"""
    prompt = "(maldbg) "

    def __init__(self, source: str = None, input_data: str = "",
                 source_file: str = None):
        super().__init__()
        self.debugger: Optional[MalbolgeDebugger] = None
        self.source_file = source_file
        self._last_cmd = ""

        if source:
            self._load_source(source, input_data)

    def _load_source(self, source: str, input_data: str = "") -> bool:
        """Load source code into debugger."""
        try:
            self.debugger = MalbolgeDebugger(source, input_data)
            print(f"Loaded {self.debugger.source_length} instructions")
            return True
        except ValueError as e:
            print(f"Error: {e}")
            return False

    def _check_loaded(self) -> bool:
        """Check if a program is loaded."""
        if not self.debugger:
            print("No program loaded. Use 'load <file>' first.")
            return False
        return True

    def _format_state(self, state: MalbolgeState) -> str:
        """Format state for display."""
        # Status line
        status = state.stop_reason.value.upper()
        if state.stop_reason == StopReason.BREAKPOINT:
            status = f"BREAKPOINT at {state.c}"

        lines = [
            f"{'─' * 60}",
            f"Step: {state.step_count:<8} Status: {status}",
            f"{'─' * 60}",
            f"Registers:",
            f"  A = {state.a:<12} (0x{state.a:08x})",
            f"  C = {state.c:<12} (code pointer)",
            f"  D = {state.d:<12} (data pointer)",
            f"{'─' * 60}",
        ]

        # Current instruction
        if 33 <= state.raw_instruction <= 126:
            char = chr(state.raw_instruction)
            lines.append(
                f"Next: [{state.c}] '{char}' -> "
                f"opcode {state.effective_opcode} ({state.opcode_name})"
            )
        else:
            lines.append(f"Next: [{state.c}] (invalid/terminated)")

        # Output preview
        if state.output:
            preview = state.output[-40:]
            if len(state.output) > 40:
                preview = "..." + preview
            lines.append(f"Output: {repr(preview)}")

        return "\n".join(lines)

    def _format_memory_line(self, addr: int, val: int,
                            is_c: bool = False, is_d: bool = False,
                            has_bp: bool = False) -> str:
        """Format a single memory line."""
        char = chr(val) if 33 <= val <= 126 else '.'
        markers = []
        if is_c:
            markers.append("C")
        if is_d:
            markers.append("D")
        if has_bp:
            markers.append("*")

        marker_str = f" <-[{','.join(markers)}]" if markers else ""
        prefix = ">>>" if is_c else "   "

        return f"{prefix} [{addr:5d}] {val:5d} (0x{val:04x}) '{char}'{marker_str}"

    # ==================== File Operations ====================

    def do_load(self, arg):
        """load <file> [input] - Load a Malbolge source file."""
        parts = arg.split(maxsplit=1)
        if not parts:
            print("Usage: load <file> [input]")
            return

        filename = parts[0]
        input_data = parts[1] if len(parts) > 1 else ""

        try:
            with open(filename, 'r') as f:
                source = f.read()
            self.source_file = filename
            self._load_source(source, input_data)
        except IOError as e:
            print(f"Error reading file: {e}")

    def do_reload(self, arg):
        """reload - Reload current source file."""
        if not self.source_file:
            print("No file loaded")
            return

        try:
            with open(self.source_file, 'r') as f:
                source = f.read()
            # Preserve breakpoints
            bps = self.debugger.list_breakpoints() if self.debugger else []
            self._load_source(source, "")
            # Restore breakpoints
            for bp in bps:
                self.debugger.add_breakpoint(bp.address)
            print(f"Reloaded {self.source_file}")
        except IOError as e:
            print(f"Error: {e}")

    def do_input(self, arg):
        """input <text> - Set program input."""
        if not self._check_loaded():
            return
        self.debugger.set_input(arg)
        print(f"Input set: {repr(arg[:50])}{'...' if len(arg) > 50 else ''}")

    # ==================== Execution Control ====================

    def do_step(self, arg):
        """step [n] / s [n] - Execute n instructions (default: 1)."""
        if not self._check_loaded():
            return

        n = 1
        if arg:
            try:
                n = int(arg)
            except ValueError:
                print("Usage: step [n]")
                return

        state = None
        for i in range(n):
            state = self.debugger.step()
            if state.stop_reason == StopReason.TERMINATED:
                print(f"Program terminated after {i + 1} step(s)")
                break
            if state.stop_reason == StopReason.INPUT_EXHAUSTED:
                print(f"Input exhausted after {i + 1} step(s)")
                break

        if state:
            print(self._format_state(state))

    do_s = do_step

    def do_back(self, arg):
        """back [n] / sb [n] - Step back n instructions (default: 1)."""
        if not self._check_loaded():
            return

        n = 1
        if arg:
            try:
                n = int(arg)
            except ValueError:
                print("Usage: back [n]")
                return

        if not self.debugger.can_step_back:
            print("No history available for step back")
            return

        state = None
        for i in range(n):
            state = self.debugger.step_back()
            if state is None:
                print(f"Stepped back {i} instruction(s), no more history")
                break

        if state:
            print(self._format_state(state))
            print(f"(History: {self.debugger.history_size} entries remaining)")

    do_sb = do_back

    def do_next(self, arg):
        """next / n - Same as step (no step-over in Malbolge)."""
        self.do_step(arg)

    do_n = do_next

    def do_run(self, arg):
        """run [max_steps] / r - Run until breakpoint or termination."""
        if not self._check_loaded():
            return

        max_steps = -1
        if arg:
            try:
                max_steps = int(arg)
            except ValueError:
                print("Usage: run [max_steps]")
                return

        state = self.debugger.run(max_steps)
        print(self._format_state(state))

        if state.stop_reason == StopReason.BREAKPOINT:
            print(f"\nBreakpoint hit at address {state.c}")
        elif state.stop_reason == StopReason.TERMINATED:
            print(f"\nProgram terminated. Final output:")
            print(repr(self.debugger.output))
        elif state.stop_reason == StopReason.WATCHPOINT:
            print(f"\nWatchpoint triggered")

    do_r = do_run

    def do_continue(self, arg):
        """continue / c - Continue execution (same as run)."""
        self.do_run(arg)

    do_c = do_continue

    def do_until(self, arg):
        """until <address> / u - Run until reaching address."""
        if not self._check_loaded():
            return
        if not arg:
            print("Usage: until <address>")
            return

        try:
            address = int(arg)
        except ValueError:
            print("Invalid address")
            return

        state = self.debugger.run_to(address)
        print(self._format_state(state))

    do_u = do_until

    def do_reset(self, arg):
        """reset - Reset execution to beginning."""
        if not self._check_loaded():
            return
        self.debugger.reset()
        print("Execution reset to initial state")
        print(self._format_state(self.debugger.get_state()))

    # ==================== Breakpoint Management ====================

    def do_break(self, arg):
        """break <address> / b [address] - Set breakpoint or list all."""
        if not self._check_loaded():
            return

        if not arg:
            # List breakpoints
            bps = self.debugger.list_breakpoints()
            if not bps:
                print("No breakpoints set")
            else:
                print("Breakpoints:")
                for bp in bps:
                    status = "enabled" if bp.enabled else "disabled"
                    print(f"  {bp.address}: {status}, hits={bp.hit_count}")
            return

        try:
            address = int(arg)
        except ValueError:
            print("Invalid address")
            return

        bp = self.debugger.add_breakpoint(address)
        print(f"Breakpoint set at address {address}")

    do_b = do_break

    def do_delete(self, arg):
        """delete <address> / d <address> - Remove breakpoint."""
        if not self._check_loaded():
            return
        if not arg:
            print("Usage: delete <address> or 'delete all'")
            return

        if arg == "all":
            count = self.debugger.clear_breakpoints()
            print(f"Deleted {count} breakpoint(s)")
            return

        try:
            address = int(arg)
        except ValueError:
            print("Invalid address")
            return

        if self.debugger.remove_breakpoint(address):
            print(f"Breakpoint at {address} removed")
        else:
            print(f"No breakpoint at {address}")

    do_d = do_delete

    def do_enable(self, arg):
        """enable <address> - Enable breakpoint."""
        if not self._check_loaded():
            return
        if not arg:
            print("Usage: enable <address>")
            return

        try:
            address = int(arg)
        except ValueError:
            print("Invalid address")
            return

        result = self.debugger.toggle_breakpoint(address)
        if result is not None:
            if not result:  # Was enabled, now we need to enable it
                self.debugger.toggle_breakpoint(address)
            print(f"Breakpoint at {address} enabled")
        else:
            print(f"No breakpoint at {address}")

    def do_disable(self, arg):
        """disable <address> - Disable breakpoint."""
        if not self._check_loaded():
            return
        if not arg:
            print("Usage: disable <address>")
            return

        try:
            address = int(arg)
        except ValueError:
            print("Invalid address")
            return

        result = self.debugger.toggle_breakpoint(address)
        if result is not None:
            if result:  # Was disabled, now enabled - toggle back
                self.debugger.toggle_breakpoint(address)
            print(f"Breakpoint at {address} disabled")
        else:
            print(f"No breakpoint at {address}")

    # ==================== Watchpoints ====================

    def do_watch(self, arg):
        """watch <address> / w - Add memory watchpoint."""
        if not self._check_loaded():
            return

        if not arg:
            # List watchpoints
            wps = self.debugger.list_watchpoints()
            if not wps:
                print("No watchpoints set")
            else:
                print("Watchpoints:")
                for wp in wps:
                    status = "enabled" if wp.enabled else "disabled"
                    print(f"  {wp.address}: {status}, last={wp.last_value}")
            return

        try:
            address = int(arg)
        except ValueError:
            print("Invalid address")
            return

        self.debugger.add_watchpoint(address)
        print(f"Watchpoint set at address {address}")

    do_w = do_watch

    def do_unwatch(self, arg):
        """unwatch <address> - Remove memory watchpoint."""
        if not self._check_loaded():
            return
        if not arg:
            print("Usage: unwatch <address>")
            return

        try:
            address = int(arg)
        except ValueError:
            print("Invalid address")
            return

        if self.debugger.remove_watchpoint(address):
            print(f"Watchpoint at {address} removed")
        else:
            print(f"No watchpoint at {address}")

    # ==================== Memory Inspection ====================

    def do_examine(self, arg):
        """examine [address] [count] / x - Examine memory."""
        if not self._check_loaded():
            return

        parts = arg.split()
        state = self.debugger.get_state()

        if not parts:
            address = state.c
            count = 16
        elif len(parts) == 1:
            try:
                address = int(parts[0])
            except ValueError:
                print("Invalid address")
                return
            count = 16
        else:
            try:
                address = int(parts[0])
                count = int(parts[1])
            except ValueError:
                print("Usage: examine [address] [count]")
                return

        mem = self.debugger.read_memory(address, count)
        bps = {bp.address for bp in self.debugger.list_breakpoints()}

        print(f"Memory at {address}:")
        for i, val in enumerate(mem):
            addr = address + i
            line = self._format_memory_line(
                addr, val,
                is_c=(addr == state.c),
                is_d=(addr == state.d),
                has_bp=(addr in bps)
            )
            print(line)

    do_x = do_examine

    def do_disassemble(self, arg):
        """disassemble [start] [count] / dis - Disassemble instructions."""
        if not self._check_loaded():
            return

        parts = arg.split()
        start = None
        count = 15

        if len(parts) >= 1:
            try:
                start = int(parts[0])
            except ValueError:
                print("Invalid start address")
                return
        if len(parts) >= 2:
            try:
                count = int(parts[1])
            except ValueError:
                print("Invalid count")
                return

        disasm = self.debugger.disassemble(start, count)

        print("Disassembly:")
        for item in disasm:
            if item["is_current"]:
                prefix = ">>>"
            elif item["has_breakpoint"]:
                prefix = " * "
            else:
                prefix = "   "

            if item["opcode"] is not None:
                print(f"{prefix} [{item['address']:5d}] {item['char']:1s}  "
                      f"{item['mnemonic']:5s}  (raw={item['raw']}, op={item['opcode']})")
            else:
                print(f"{prefix} [{item['address']:5d}] .  DATA   (raw={item['raw']})")

    do_dis = do_disassemble

    def do_registers(self, arg):
        """registers / reg - Show register values."""
        if not self._check_loaded():
            return

        regs = self.debugger.registers
        state = self.debugger.get_state()

        print("Registers:")
        # A with character display if printable
        a_char = chr(regs['a'] % 256) if 32 <= (regs['a'] % 256) <= 126 else '.'
        print(f"  A = {regs['a']:10d} (0x{regs['a']:08x}) '{a_char}'")
        print(f"  C = {regs['c']:10d} (code pointer)")
        print(f"  D = {regs['d']:10d} (data pointer)")
        print(f"\nStep count: {state.step_count}")
        print(f"History entries: {self.debugger.history_size}")

    do_reg = do_registers

    def do_output(self, arg):
        """output / o - Show program output."""
        if not self._check_loaded():
            return

        output = self.debugger.output
        if not output:
            print("(no output)")
        else:
            print(f"Output ({len(output)} chars):")
            print(repr(output))
            print("\nRaw:")
            print(output)

    do_o = do_output

    def do_info(self, arg):
        """info - Show current execution state."""
        if not self._check_loaded():
            return
        state = self.debugger.get_state()
        print(self._format_state(state))

    do_i = do_info

    # ==================== TUI Mode ====================

    def do_tui(self, arg):
        """tui - Launch TUI mode (requires textual)."""
        if not self._check_loaded():
            return

        try:
            from .debug_tui import run_tui
            run_tui(self.debugger)
        except ImportError:
            print("TUI mode requires 'textual' library.")
            print("Install with: pip install textual")

    # ==================== Misc Commands ====================

    def do_history(self, arg):
        """history - Show step-back history info."""
        if not self._check_loaded():
            return
        print(f"History entries: {self.debugger.history_size}")
        print(f"Can step back: {self.debugger.can_step_back}")

    def do_source(self, arg):
        """source - Show source code info."""
        if not self._check_loaded():
            return
        print(f"Source file: {self.source_file or '(none)'}")
        print(f"Source length: {self.debugger.source_length} instructions")

    def do_quit(self, arg):
        """quit / q - Exit debugger."""
        print("Goodbye!")
        return True

    do_q = do_quit
    do_exit = do_quit

    def do_help(self, arg):
        """help [command] - Show help."""
        if not arg:
            print("""
Commands:
  Execution:
    step, s [n]       Step n instructions (default: 1)
    back, sb [n]      Step back n instructions
    run, r [max]      Run until breakpoint/termination
    continue, c       Continue execution
    until, u <addr>   Run until address
    reset             Reset to initial state

  Breakpoints:
    break, b [addr]   Set breakpoint or list all
    delete, d <addr>  Delete breakpoint ('all' to clear)
    enable <addr>     Enable breakpoint
    disable <addr>    Disable breakpoint

  Watchpoints:
    watch, w [addr]   Add watchpoint or list all
    unwatch <addr>    Remove watchpoint

  Inspection:
    examine, x [addr] [n]  Examine memory
    disassemble, dis       Disassemble instructions
    registers, reg         Show registers
    output, o              Show program output
    info, i                Show execution state

  File:
    load <file>       Load source file
    reload            Reload current file
    input <text>      Set program input

  Other:
    tui               Launch TUI mode
    history           Show step-back history
    source            Show source info
    help, h [cmd]     Show help
    quit, q           Exit

Type 'help <command>' for detailed help on a command.
""")
        else:
            super().do_help(arg)

    do_h = do_help

    def emptyline(self):
        """Repeat last command on empty line."""
        if self._last_cmd in ('step', 's', 'back', 'sb', 'next', 'n'):
            return self.onecmd(self._last_cmd)

    def precmd(self, line):
        """Save last command for repeat."""
        cmd = line.split()[0] if line.split() else ""
        if cmd:
            self._last_cmd = cmd
        return line

    def default(self, line):
        """Handle unknown commands."""
        print(f"Unknown command: {line}")
        print("Type 'help' for available commands.")


def main():
    """Command-line entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Malbolge Debugger',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s hello.mal              Debug hello.mal
  %(prog)s hello.mal -i "input"   Debug with input
  %(prog)s                        Start empty debugger
"""
    )
    parser.add_argument('file', nargs='?', help='Malbolge source file')
    parser.add_argument('-i', '--input', default='', help='Program input')
    parser.add_argument('-c', '--command', help='Execute commands and exit')

    args = parser.parse_args()

    cli = None
    if args.file:
        try:
            with open(args.file, 'r') as f:
                source = f.read()
            cli = DebugCLI(source, args.input, args.file)
        except IOError as e:
            print(f"Error reading file: {e}")
            sys.exit(1)
    else:
        cli = DebugCLI()

    if args.command:
        # Execute commands from -c argument
        for cmd in args.command.split(';'):
            cmd = cmd.strip()
            if cmd:
                cli.onecmd(cmd)
    else:
        try:
            cli.cmdloop()
        except KeyboardInterrupt:
            print("\nInterrupted. Goodbye!")


if __name__ == '__main__':
    main()
