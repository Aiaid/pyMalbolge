# pyMalbolge

This is a fork from https://github.com/Avantgarde95/pyMalbolge

Simple [Malbolge](https://en.wikipedia.org/wiki/Malbolge) interpreter in Python with built-in debugger.

## Installation

```bash
# Basic installation
pip install malbolge

# With TUI debugger support
pip install malbolge[tui]
```

## Usage

### Command Line

![TUI Debugger Screenshot](screenshots/cli.png)

```bash
# Run a Malbolge program
python3 -m malbolge hello.mal

# Run with input (for programs that read stdin, like cat.mal)
python3 -m malbolge cat.mal -i "Hello World"

# Start CLI debugger
python3 -m malbolge.debug_cli hello.mal

# Start CLI debugger with input
python3 -m malbolge.debug_cli cat.mal -i "Hello World"

# Start TUI debugger (requires textual)
python3 -m malbolge.debug_tui hello.mal

# Start TUI debugger with input
python3 -m malbolge.debug_tui cat.mal -i "Hello World"
```

### Python API

```python
from malbolge import eval

# Hello World
eval('''(=<`#9]~6ZY32Vx/4Rs+0No-&Jk)"Fh}|Bcy?`=*z]Kw%oG4UUS0/@-ejc(:'8dc''')
# Output: Hello World!

# Cat program with input
eval('''(=BA#9"=<;:3y7x54-21q/p-,+*)"!h%B0/.~P<<:(8&66#"!~}|{zyxwvugJ%''', "abc123")
# Output: abc123
```

### Debugger API

```python
from malbolge import MalbolgeDebugger

# Create debugger instance
dbg = MalbolgeDebugger(source_code, input_data)

# Set breakpoints
dbg.add_breakpoint(10)

# Step execution
state = dbg.step()      # Execute one instruction
state = dbg.step_back() # Undo last instruction
state = dbg.run()       # Run until breakpoint

# Inspect state
print(dbg.registers)    # {'a': 0, 'c': 5, 'd': 45}
print(dbg.output)       # Program output so far
print(dbg.disassemble(0, 10))  # Disassemble instructions
```

## Debugger

### CLI Debugger

Interactive command-line debugger similar to GDB.

```
(maldbg) break 10       # Set breakpoint at address 10
(maldbg) run            # Run until breakpoint
(maldbg) step 5         # Step 5 instructions
(maldbg) back 2         # Step back 2 instructions
(maldbg) examine 0 20   # Examine memory at address 0
(maldbg) disassemble    # Show disassembly
(maldbg) registers      # Show register values
(maldbg) output         # Show program output
(maldbg) help           # Show all commands
```

### TUI Debugger

Visual terminal-based debugger with split-screen interface.

![TUI Debugger Screenshot](screenshots/tui.png)

**Keybindings:**
- `↓` - Step one instruction
- `↑` - Step back
- `r` - Run until breakpoint
- `b` - Toggle breakpoint at current address
- `←` / `→` - Scroll memory view left/right
- `0` - Reset memory scroll to D pointer
- `h` / `?` - Show help
- `q` - Quit

## Changes from Original

### Fixed
- Integer division syntax (Python 3 compatibility)

### Added
- `eval()` function for inline evaluation
- Full-featured debugger with:
  - Breakpoints and watchpoints
  - Step-by-step execution
  - Step back (execution history)
  - Memory inspection
  - Disassembly view
  - CLI and TUI interfaces

## TODO
- Support Malbolge20 and Malbolge Unshackled
- A simple Malbolge compiler/generator

## License

MIT
