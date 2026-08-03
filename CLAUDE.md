# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

pyMalbolge is a Python interpreter for the Malbolge esoteric programming language. It's a fork of https://github.com/Avantgarde95/pyMalbolge with fixes and additional features.

Supports multiple variants:
- **Original Malbolge**: 10 trits, 59,049 memory cells
- **Malbolge20**: 20 trits, ~3.48 billion memory cells (sparse memory)

## Commands

**Run everything through `uv`.** The dev environment lives in `.venv`
(`uv venv --python 3.14 && uv pip install -e ".[dev]"`); `pytest` is not
installed in the system interpreter, so a bare `python3 -m pytest` fails.
Prefix commands with `uv run` — the `python3 -m malbolge ...` forms below are
what an end user types after installing the package.

### Run interpreter on a file
```bash
# Original Malbolge
python3 -m malbolge examples/hello.mal

# Malbolge20
python3 -m malbolge --variant=malbolge20 program.mal
```

### Use eval function programmatically
```python
# Original Malbolge
from malbolge import eval
result = eval('''(=<`#9]~6ZY32Vx/4Rs+0No-&Jk)"Fh}|Bcy?`=*z]Kw%oG4UUS0/@-ejc(:'8dc''')

# Malbolge20
from malbolge import eval20
result = eval20(code)

# With input:
result = eval('''(=BA#9"=<;:3y7x54-21q/p-,+*)"!h%B0/.~P<<:(8&66#"!~}|{zyxwvugJ%''', "input_string")
```

### Debug mode
```bash
# CLI debugger
python3 -m malbolge debug examples/hello.mal

# TUI debugger (requires textual)
python3 -m malbolge debug --tui examples/hello.mal

# With variant
python3 -m malbolge debug --variant=malbolge20 program.mal
```

### Compile Python to Malbolge20
```bash
python3 -m malbolge compile foo.py -o foo.mb                    # default 'c' backend
python3 -m malbolge compile foo.py --backend=direct -o foo.mb   # py->.mg direct backend
python3 -m malbolge --variant=malbolge20 foo.mb                 # run the result
```
Subset spec: `docs/python-subset-spec.md`. Direct-backend design: `docs/py2mg-backend.md`.

### Run tests
```bash
uv run --no-sync pytest test/ -n auto     # ~6 min (parallel, via pytest-xdist)
uv run --no-sync pytest test/             # serial
uv run --no-sync pytest test/test_mg2mc.py -q          # single module
MALBOLGE_SLOW_TESTS=1 uv run --no-sync pytest test/    # + the gated slow cases
```
462 pass / 5 skip as of 2026-08-02. Serial `unittest discover` also works
(`uv run --no-sync python -m unittest discover -v test/`) but takes ~24 min,
and `test_py2c_diagnostics.py` needs pytest importable either way.

### Build package
```bash
uv build
```

## Architecture

### Core modules

| Module | Description |
|--------|-------------|
| `malbolge/core.py` | Shared components: `MalbolgeConfig`, `SparseMemory`, `DenseMemory`, `crazy()`, `rotate()` |
| `malbolge/malbolge.py` | Original Malbolge interpreter (10 trits) |
| `malbolge/malbolge20.py` | Malbolge20 interpreter (20 trits, sparse memory) |
| `malbolge/debugger.py` | Debugger with breakpoints, watchpoints, step-back |
| `malbolge/compiler/py2c.py` | Python subset -> Nagoya C subset (front-end, 'c' backend) |
| `malbolge/compiler/py2mg.py` | Python subset -> .mg directly ('direct' backend, smaller output, native double recursion) |
| `malbolge/compiler/c2mg.py` | C subset -> .mg (pure-Python port of nagoya-highlevel, bug-for-bug) |
| `malbolge/compiler/mg2mc.py` | .mg -> .mc LAL (port of nagoya-ternary) |
| `malbolge/compiler/mc2mb.py` | .mc -> .mb Malbolge20 (port of nagoya-lowass, deterministic padding) |
| `malbolge/compiler/cli.py` | `python3 -m malbolge compile` entry point |
| `malbolge/debug_cli.py` | CLI debugger interface |
| `malbolge/debug_tui.py` | TUI debugger (textual-based) |

### Key components

- **`MalbolgeConfig`**: Configuration for variants (trit_width, memory_size, etc.)
- **`SparseMemory`**: Lazy-loading memory for large address spaces (Malbolge20)
- **`DenseMemory`**: Full array memory for original Malbolge
- **`crazy(a, b, trit_width)`**: Ternary digit-by-digit lookup operation
- **`rotate(n, config)`**: Right-rotate ternary number
- **`ENCRYPT`**: Self-modifying code table (94 printable ASCII permutation)

### Important notes

- **Malbolge20 is NOT backward compatible** with original Malbolge programs. The 20-trit `crazy()` operation produces different results than 10-trit.
- Malbolge20 programs must be specifically written for the 20-trit environment.

## TODO

### Completed
- [x] Support Malbolge20
- [x] Add debug mode (CLI + TUI)
- [x] Python -> Malbolge20 compiler: pure-Python toolchain ports (c2mg/mg2mc/mc2mb) + py2c front-end + py2mg direct backend (see `docs/research/findings.md` B5/B6/B8 — private, not in the public repo)

### Pending: Malbolge Unshackled

Malbolge Unshackled is a Turing-complete variant with unbounded memory. Implementation requires:

1. **3-adic integer representation**
   ```python
   class TriadicInt:
       def __init__(self, trits: list, leading_trit: int):
           self.trits = trits  # Finite part
           self.leading = leading_trit  # 0, 1, or 2, repeats infinitely left
   ```

2. **Variable rotation width**
   - Initial width: at least 10 trits
   - Grows when D register width exceeds half of rotation width
   - Growth rule is implementation-defined

3. **Unicode I/O** (not mod 256)
   - Output: A register value is Unicode codepoint (when leading trit is 0)
   - Input: Read Unicode char, store codepoint
   - EOF: Represented as `...22` (leading trit 2)

4. **Unbounded memory initialization**
   - Extend the 6-cell period pattern to all addresses using mod 6 remainders

### Pending: Compiler v2

- Signed integers, decimal `print()`/`input()`, `break`/`continue`
- Arrays/strings via `IND_OPR` (design: `docs/research/iwagane-arrays.md` — private, not in the public repo)
- (Original-Malbolge generator via LMAO port remains shelved — GPL question, see `docs/hell-assembler-design.md` §6)

## References

- [Malbolge - Esolang](https://esolangs.org/wiki/Malbolge)
- [Malbolge Unshackled - Esolang](https://esolangs.org/wiki/Malbolge_Unshackled)
- [lutter.cc/unshackled](https://lutter.cc/unshackled/) - Reference implementation
- [TryItOnline/malbolge-unshackled](https://github.com/TryItOnline/malbolge-unshackled) - C implementation
