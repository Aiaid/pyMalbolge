# pyMalbolge

This is a fork from https://github.com/Avantgarde95/pyMalbolge

Simple [Malbolge](https://en.wikipedia.org/wiki/Malbolge) interpreter in Python with built-in debugger.

**Supports multiple variants:**
- **Original Malbolge** - 10 trits, 59,049 memory cells
- **Malbolge20** - 20 trits, ~3.48 billion memory cells (sparse memory)

## Installation

```bash
# Basic installation
pip install malbolge

# With TUI debugger support
pip install malbolge[tui]
```

## Usage

### Command Line

```bash
# Run a Malbolge program
python3 -m malbolge hello.mal

# Run with Malbolge20 variant
python3 -m malbolge --variant=malbolge20 program.mal

# Run with input (for programs that read stdin)
python3 -m malbolge cat.mal -i "Hello World"

# Start debugger (CLI)
python3 -m malbolge debug hello.mal

# Start debugger (TUI, requires textual)
python3 -m malbolge debug --tui hello.mal

# Debug with Malbolge20 variant
python3 -m malbolge debug --variant=malbolge20 program.mal
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

#### Malbolge20 API

```python
from malbolge import eval20

# Run code with 20-trit operations
result = eval20(code, input_data)
```

> **Note:** Malbolge20 uses 20-trit `crazy()` operations, which produce different results than the original 10-trit version. Programs written for original Malbolge will **not** work correctly in Malbolge20.

### Debugger API

```python
from malbolge import MalbolgeDebugger
from malbolge.core import MalbolgeConfig

# Create debugger instance (original Malbolge)
dbg = MalbolgeDebugger(source_code, input_data)

# Create debugger for Malbolge20
config = MalbolgeConfig.malbolge20()
dbg = MalbolgeDebugger(source_code, input_data, config=config)

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

## Malbolge Variants

| Feature | Original | Malbolge20 |
|---------|----------|------------|
| Word size | 10 trits | 20 trits |
| Memory | 59,049 cells | ~3.48 billion cells |
| Memory type | Dense array | Sparse (lazy) |
| Compatible | - | Not backward compatible |

## Changes from Original

### Fixed
- Integer division syntax (Python 3 compatibility)

### Added
- `eval()` function for inline evaluation
- **Malbolge20 support** with sparse memory
- Full-featured debugger with:
  - Breakpoints and watchpoints
  - Step-by-step execution
  - Step back (execution history)
  - Memory inspection
  - Disassembly view
  - CLI and TUI interfaces

## TODO
- [x] Support Malbolge20
- [ ] Support Malbolge Unshackled (Turing-complete variant)
- [ ] A simple Malbolge compiler/generator

## References

- [Malbolge - Esolang](https://esolangs.org/wiki/Malbolge)
- [Malbolge - Wikipedia](https://en.wikipedia.org/wiki/Malbolge)
- [Malbolge20 - Nagoya University](https://www.trs.cm.is.nagoya-u.ac.jp/projects/Malbolge/)

## License

MIT
