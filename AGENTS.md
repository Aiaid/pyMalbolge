# AGENTS.md

Shared project guidance for coding agents working in this repository.

## Project Overview

pyMalbolge is a Python interpreter for the Malbolge esoteric programming language. It's a fork of https://github.com/Avantgarde95/pyMalbolge with fixes and additional features.

Supports multiple variants:
- **Original Malbolge**: 10 trits, 59,049 memory cells
- **Malbolge20**: 20 trits, ~3.48 billion memory cells (sparse memory)

## Commands

**Run all Python operations through `uv`.** Sync the development environment
with `uv sync --extra dev`; prefix interpreter and test commands with `uv run`.
Use `uv add` for project dependencies, `uv add --dev` for development
dependencies, and `uv build` for packages.

### Run interpreter on a file
```bash
# Original Malbolge
uv run python -m malbolge examples/hello.mal

# Malbolge20
uv run python -m malbolge --variant=malbolge20 program.mal
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
uv run python -m malbolge debug examples/hello.mal

# TUI debugger (requires textual)
uv run python -m malbolge debug --tui examples/hello.mal

# With variant
uv run python -m malbolge debug --variant=malbolge20 program.mal
```

### Compile Python to Malbolge20
```bash
uv run python -m malbolge compile foo.py -o foo.mb                    # default 'c' backend
uv run python -m malbolge compile foo.py --backend=direct -o foo.mb   # py->.mg direct backend
uv sync --extra dev --extra ir                                      # optional IR tools, Python 3.10+
uv run --no-sync python -m malbolge compile foo.py --backend=ir --emit-ir foo.mlir
uv run --no-sync python -m malbolge compile foo.py --backend=ir --emit-semantic-ir foo.semantic.mlir
uv run --no-sync python -m malbolge compile foo.py --backend=ir --ir-frontend=semantic -o foo.mb
uv run --no-sync python -m malbolge compile foo.py --backend=ir --opt-level=0 --emit-semantic-ir foo.raw.mlir
uv run python -m malbolge --variant=malbolge20 foo.mb                 # run the result
```
Bounded batch execution and opt-in compilation caching:
```bash
uv run python -m malbolge --variant=malbolge20 foo.mb --input '7' --max-steps 10000000 --max-output 1024 --eof sentinel --stats
uv run python -m malbolge compile foo.py -o foo.mb --cache-dir .cache/malbolge --stats
```
Execution budgets return exit 3; invalid instructions return exit 2. Metrics
are JSON on stderr; program output remains bytes on stdout. Use explicit
`--input`/`--input-file` for batch execution from a TTY.

Subset spec: `docs/specs/python-subset-spec.md`. Direct-backend design: `docs/design/py2mg-backend.md`.

### Run tests
```bash
uv run --no-sync pytest test/ -n auto     # ~6 min (parallel, via pytest-xdist)
uv run --no-sync pytest test/             # serial
uv run --no-sync pytest test/test_mg2mc.py -q          # single module
MALBOLGE_SLOW_TESTS=1 uv run --no-sync pytest test/    # + the gated slow cases
```
Historical test snapshot (2026-09-01): 592 pass / 8 skip. Re-run the relevant tests for current results. Serial `unittest discover` also works
(`uv run --no-sync python -m unittest discover -v test/`) but takes ~24 min,
and `test_py2c_diagnostics.py` needs pytest importable either way.

Latest local QoS acceptance (2026-10-08): full suite 710 passed / 14 skipped
plus 532 subtests; subsequent focused checks and portable VM execution are
recorded in `docs/notes/python-qos-validation.json`. CI is configured for
Python 3.8/3.12/3.13 but has not yet run on GitHub. The older test counts above
remain historical timing evidence.

### Build package
```bash
uv build
```

### Searching the repo

Use `rg` / `rg --files` for searches. `docs/research/` is gitignored because
it lives in a private companion repository. Name that directory explicitly
when searching research notes; a normal repository-wide search may skip it.
Do not copy private companion-repository contents or machine-specific paths
into public documentation without authorization. Check search exit codes:
1 means no matches, while 2 means the search failed.

## Architecture

### Core modules

| Module | Description |
|--------|-------------|
| `malbolge/core.py` | Shared components: `MalbolgeConfig`, `SparseMemory`, `DenseMemory`, `crazy()`, `rotate()` |
| `malbolge/malbolge.py` | Original Malbolge interpreter (10 trits) |
| `malbolge/malbolge20.py` | Malbolge20 interpreter (20 trits, sparse memory) |
| `malbolge/debugger.py` | Debugger with breakpoints, watchpoints, step-back, memory write-heat, chunked run, timeline seek |
| `malbolge/view/` | ViewModel layer: debugger state as plain JSON-serialisable data, shared by every renderer. Never imports textual. Contracts: `docs/design/tui-web-architecture.md` §3 |
| `malbolge/compiler/python_normalize.py` | Shared tuple/f-string normalization, keyword binding and return/error-callgraph contracts |
| `malbolge/compiler/decimal_io.py` | Shared decimal input/output helpers, injected on demand by both Python frontends |
| `malbolge/compiler/target_ast.py` | Uncommitted local prototype: explicit target AST roles and loop-condition preludes; documented in `docs/design/semantic-ir.md` |
| `malbolge/compiler/py2c.py` | Python subset -> Nagoya C subset (front-end, 'c' backend) |
| `malbolge/compiler/py2mg.py` | Python subset -> .mg directly ('direct' backend, smaller output, native double recursion) |
| `malbolge/compiler/c2mg.py` | C subset -> .mg (pure-Python port of nagoya-highlevel, bug-for-bug) |
| `malbolge/compiler/mg2mc.py` | .mg -> .mc LAL (port of nagoya-ternary) |
| `malbolge/compiler/mc2mb.py` | .mc -> .mb Malbolge20 (port of nagoya-lowass, deterministic padding) |
| `malbolge/compiler/ir/` | Optional xDSL semantic/LAL dialects, direct AST frontend, independent IR oracle, verified named passes and target compatibility adapter; see `docs/design/semantic-ir.md` and `docs/design/compiler-ir.md` |
| `malbolge/compiler/cli.py` | `uv run python -m malbolge compile` entry point |
| `malbolge/debug_cli.py` | CLI debugger interface |
| `malbolge/debug_tui.py` | TUI debugger (textual-based) |

### Key components

- **`MalbolgeConfig`**: Configuration for variants (trit_width, memory_size, etc.)
- **`SparseMemory`**: Compact immutable source, typed mutable pages, frozen periodic
  defaults and copy-on-write snapshots for Malbolge20
- **`DenseMemory`**: Full array memory for original Malbolge
- **`crazy(a, b, trit_width)`**: Ternary digit-by-digit lookup operation
- **`rotate(n, config)`**: Right-rotate ternary number
- **`ENCRYPT`**: Self-modifying code table (94 printable ASCII permutation)

### Important notes

- **Malbolge20 is NOT backward compatible** with original Malbolge programs. The 20-trit `crazy()` operation produces different results than 10-trit.
- Malbolge20 programs must be specifically written for the 20-trit environment.
- The `ir` extra pins xDSL for reproducibility. Keep optional IR imports lazy:
  the base interpreter and C/direct compiler support Python 3.8 without xDSL.
  IR passes must verify their input/output and use deterministic declaration
  order. Keep new performance transformations separate from architecture work;
  IR operation counts and digests are structural metrics, not speed claims.
- Semantic IR has SSA expression values and explicit mutable source slots;
  full variable SSA/dataflow is not yet implemented. Preserve lazy regions,
  call/input/output/error ordering and source locations. The semantic target
  adapter reconstructs Python AST from verified IR; do not reuse original
  source or silently fall back to the old frontend on unsupported inputs.
- Semantic optimization decisions belong to named passes. The accepted default
  profile is in `ir/semantic_passes.py`; `--opt-level=0` verifies only.
  The semantic target adapter disables duplicate legacy arithmetic shortcuts;
  C/direct references retain their defaults. Decimal output lowering is an
  explicit experiment, excluded from the accepted profile after regression.

## TODO

> The live, prioritized all-directions roadmap is `docs/research/roadmap.md`
> (private, not in the public repo); the next-phase design is
> `docs/research/mb-dialect-plan.md` (same). The lists below are the public
> summary.

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

- Signed integers and general runtime strings/objects
- Runtime unsigned decimal `print()`/`int(input([literal_prompt]))` support
  module/function scope; basic print f-strings, flat tuple assignment, simple
  keyword calls and descending ranges are implemented (see the subset spec)
- Arrays/strings via `IND_OPR` (design: `docs/research/iwagane-arrays.md` — private, not in the public repo)
- (Original-Malbolge generator via LMAO port remains shelved — GPL question, see `docs/design/hell-assembler-design.md` §6)

## References

- [Malbolge - Esolang](https://esolangs.org/wiki/Malbolge)
- [Malbolge Unshackled - Esolang](https://esolangs.org/wiki/Malbolge_Unshackled)
- [lutter.cc/unshackled](https://lutter.cc/unshackled/) - Reference implementation
- [TryItOnline/malbolge-unshackled](https://github.com/TryItOnline/malbolge-unshackled) - C implementation
