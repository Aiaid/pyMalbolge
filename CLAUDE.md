# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

pyMalbolge is a Python interpreter for the Malbolge esoteric programming language. It's a fork of https://github.com/Avantgarde95/pyMalbolge with fixes and additional features.

## Commands

### Run interpreter on a file
```bash
python3 -m malbolge examples/hello.mal
```

### Use eval function programmatically
```python
from malbolge import eval
result = eval('''(=<`#9]~6ZY32Vx/4Rs+0No-&Jk)"Fh}|Bcy?`=*z]Kw%oG4UUS0/@-ejc(:'8dc''')
# With input:
result = eval('''(=BA#9"=<;:3y7x54-21q/p-,+*)"!h%B0/.~P<<:(8&66#"!~}|{zyxwvugJ%''', "input_string")
```

### Run tests
```bash
python3 -m pytest test/
# Or single test:
python3 -m pytest test/test_malbolge.py::TestEval::test_hello
```

### Build package
```bash
python3 -m build
```

## Architecture

The entire interpreter is in `malbolge.py` (single file). Key components:

- **Memory model**: Uses ternary (base-3) arithmetic with 3^10 memory cells
- **`crazy(a, b)`**: Implements the "crazy operation" - Malbolge's unique ternary operation
- **`rotate(n)`**: Rotates a ternary number right
- **`initialize(source, mem)`**: Loads source code into memory, validates characters, fills rest with crazy operation results
- **`interpret(mem)`**: Main execution loop with 8 valid opcodes (jmp, out, in, rotr, mov, crz, nop, end)
- **`eval(code, input)`**: Returns output as string instead of printing (added feature)

The `ENCRYPT` table handles instruction encryption after execution (self-modifying code characteristic of Malbolge).

## TODO (from README)

- Support Malbolge20 and Malbolge Unshackled
- Add debug mode
- A simple Malbolge compiler/generator
