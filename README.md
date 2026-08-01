# pyMalbolge

> **English** | [中文](https://github.com/Aiaid/pyMalbolge/blob/master/README.zh.md)

**Write Python. Get a running [Malbolge](https://en.wikipedia.org/wiki/Malbolge) program.**

pyMalbolge is a pure-Python compiler from a subset of Python to
[Malbolge20](https://www.trs.cm.is.nagoya-u.ac.jp/projects/Malbolge/), bundled
with interpreters for both Malbolge variants and a full-featured debugger.
No C++, flex, bison or Perl build dependencies — `pip install malbolge` and the
whole toolchain is there.

```python
def fib(n):
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)

putchar(48 + fib(6))
```

```console
$ python3 -m malbolge compile fib.py --backend=direct -o fib.mb
$ python3 -m malbolge --variant=malbolge20 fib.mb
8
```

Malbolge was designed in 1998 by Ben Olmstead to be as close to unprogrammable
as a language can get: every instruction is self-modifying, the opcode depends
on the instruction's own address, and arithmetic is a lookup-table "crazy"
operation on ternary digits. The first Malbolge program was not written but
*found*, by beam search, two years after the language appeared. This project is
about the other end of that history — compiling ordinary code into it.

- **Compiler** — Python subset → Malbolge20, two independent backends, fully deterministic output
- **Interpreters** — original Malbolge (10 trits) and Malbolge20 (20 trits, sparse memory)
- **Debugger** — breakpoints, watchpoints, step-back, memory inspection, disassembly; CLI and TUI
- **Verified** — the toolchain ports are byte-exact against the reference C++/Perl tools; 441 tests
- **Zero runtime dependencies** — `textual` only if you want the TUI debugger

## Installation

```bash
pip install malbolge          # compiler + interpreters + CLI debugger
pip install malbolge[tui]     # adds the TUI debugger (textual)
```

Requires Python 3.8+.

## Compiling Python to Malbolge20

### Command line

```bash
# Compile and run
python3 -m malbolge compile examples/hello.py -o hello.mb
python3 -m malbolge --variant=malbolge20 hello.mb

# Direct backend: skips the C layer, roughly half the output size on
# programs with control flow or functions, native double recursion
python3 -m malbolge compile examples/fib.py --backend=direct -o fib.mb

# Dump the intermediate stages
python3 -m malbolge compile prog.py --emit-c prog.c --emit-mg prog.mg --emit-mc prog.mc
```

### Python API

```python
from malbolge.compiler import compile_python_to_mb
from malbolge import eval20

mb = compile_python_to_mb('print("Hello, world!")')                   # 'c' backend
mb = compile_python_to_mb('print("Hello, world!")', backend="direct") # direct backend
print(eval20(mb))                                                     # Hello, world!

# Every stage is exposed individually:
from malbolge.compiler import (
    compile_python_to_c,    # Python subset -> Nagoya C subset
    compile_python_to_mg,   # Python subset -> .mg          (direct backend)
    translate_mg_to_mc,     # .mg -> .mc (LAL)              (port of nagoya-ternary)
    assemble_mc_to_mb,      # .mc -> .mb (Malbolge20)       (port of nagoya-lowass)
)
```

### Supported Python subset (v1)

Accepted: `int` variables and arithmetic (`+ - * // %`, constant-folded mod
3^20), `while` / `if` / `elif` / `else`, `for i in range(...)`, `break` /
`continue`, chained comparisons, short-circuit `and` / `or` / `not`,
conditional expressions (`a if c else b`, lazily evaluated), function
definitions and calls including mutual recursion, `global`, `putchar()` /
`getchar()` I/O, `ord()`, and `print()` with compile-time-constant arguments
(string literals, constant ints, all-constant f-strings, `sep=` / `end=`).
Docstrings are tolerated.

Rejected, with line-numbered `CompileError`s: negative literals and unary minus
(the value ring is unsigned mod 3^20), true division, runtime-valued `print()`
arguments, `chr`, runtime strings and f-strings, floats, `bool`, lists / dicts
/ sets, classes, `import`, `lambda`, comprehensions, nested functions, tuple
unpacking and keyword arguments.

The [normative specification](https://github.com/Aiaid/pyMalbolge/blob/master/docs/python-subset-spec.md)
covers the accepted-AST whitelist, all seventeen documented divergences from
CPython semantics, and the diagnostic contract.

## How the pipeline works

```
             py2c                c2mg            mg2mc            mc2mb
Python  ──────────► Nagoya C ──────────► .mg ──────────► .mc ──────────► .mb
subset      │        subset             pseudo-        LAL low-      Malbolge20
            │                            instrs         level asm
            └──────────────────────────►
                  py2mg (direct backend)
```

| Stage | What it is |
|---|---|
| `py2c` | **Ours.** Python AST → the Nagoya C subset. Lowers everything to three-address form, works around several defects in the downstream C compiler, and injects `zzmul` / `zzdiv` / `zzmod` library routines because the C subset has no `*`, `/` or `%`. |
| `py2mg` | **Ours.** Python AST → `.mg` directly, skipping the C layer. Reuses the verified codegen primitives but replaces the frame strategy: per-function temporaries, real recursion-cycle detection, and protection of exactly the temporaries live across calls. |
| `c2mg` | Pure-Python port of `nagoya-highlevel` (C subset → pseudo-instructions), reproduced bug-for-bug so that output stays byte-identical to the reference. |
| `mg2mc` | Pure-Python port of `nagoya-ternary` (pseudo-instructions → LAL). |
| `mc2mb` | Pure-Python port of `nagoya-lowass` (LAL → Malbolge20), replacing the two-stage Perl + C++ original. Padding is deterministic instead of time-seeded. |

Every port is checked byte-for-byte against the original tools on a fixture
corpus, and the two front-ends are cross-checked end to end: the same source
compiled through both backends must produce identical *program output*.

### Compared to the Nagoya toolchain

|  | Nagoya toolchain | pyMalbolge |
|---|---|---|
| Implementation | C++ / flex / bison / Perl | Pure Python |
| Getting it | Build from source locally | `pip install malbolge` |
| Source language | C subset | Python subset (the C subset path is kept as one backend) |
| `*` `/` `%` | Not in the C subset | Constant-folded, or emitted as library routines |
| `for` loops | `while` only | `for i in range(...)`, desugared to `while` |
| `break` / `continue` | Not available | Flag lowering, correct in nested loops |
| Chained comparisons, short-circuit `and`/`or` | — | Supported |
| Conditional expressions | — | `a if c else b`, lazily evaluated |
| Text output | `putchar` per character | `print()` with constant arguments, lowered to a putchar chain |
| Diagnostics | Parser errors | Line-numbered `CompileError` with a source excerpt |
| Inline double recursion (`f(n-1) + f(n-2)`) | Miscompiled from fib(4) up | Correct on both backends |
| Output determinism | `srand(time(NULL))` padding — deliberately different on every compile | Byte-for-byte reproducible |
| Backends | One | Two; the direct one roughly halves output size |
| Runtime | Reference C interpreter | Interpreters for both variants, plus a debugger |
| Last upstream commit | 2021 | Actively maintained |

Obfuscation was a design goal upstream — the pseudo-instruction layer is
*supposed* to emit something different each time. Trading that for determinism
is what makes reproducible builds and byte-exact conformance testing possible,
and it is the one place where this project deliberately diverges from the
original behaviour rather than reproducing it.

## Performance

Malbolge20 has no instructions in the usual sense. Addition alone is a
twenty-step loop over ternary digits, every cell rewrites itself after being
executed, and control flow is carried in a register. Compiled programs are
therefore *enormous* relative to their source and run slowly — this is inherent
to the target, not an artifact of this implementation.

Measured on an M-series Mac, CPython 3.9:

| Source | `.mb` size (`c`) | `.mb` size (`direct`) | Compile | Run | Steps |
|---|---|---|---|---|---|
| `print("Hello, world!")` | 3.47 MB | 3.47 MB | 1.8 s | 3.0 s | 735 K |
| `for i in range(3): putchar(65+i)` | 27.3 MB | 11.9 MB | 5.7 s | 9.5 s | 3.0 M |
| recursive `fib(6)` | 110.5 MB | 56.8 MB | 28.2 s | 53.8 s | — |

**Output size.** The direct backend is no help on straight-line code — the two
`hello` builds differ by under a kilobyte — but roughly halves anything with
control flow or function calls. Size is driven by call sites and loops, not by
the input's numeric values: a bootstrap of about 91 KB plus a few hundred KB
per `putchar` call site is typical.

**Compilation** is dominated by the final assembly stage, which runs at roughly
**0.5 s per MB of output** and is effectively linear in it. It did not start
that way: the address search in `mc2mb` was recursing without memoization,
which made assembly superlinear at about 40 s/MB and turned multi-MB programs
into multi-minute builds. Caching that search on `(d, pos, depth)` made it
about **100x faster with byte-identical output**.

**Execution** runs at roughly **240,000–320,000 instructions per second** under
CPython, measured end to end including startup and parsing the `.mb`. The
debugger is another 2–2.4x slower, because step-back records execution history.
Wall-clock time is superlinear in recursion depth even
though `.mb` size is not — deep recursion touches more of the address space,
and the sparse memory materializes blocks lazily as it goes.

Practically: small programs are fine, and anything with real recursion is a
patience exercise. Both are expected.

## Running Malbolge programs

```bash
python3 -m malbolge hello.mal                        # original Malbolge
python3 -m malbolge --variant=malbolge20 program.mb  # Malbolge20
python3 -m malbolge cat.mal -i "Hello World"         # feed stdin
```

```python
from malbolge import eval, eval20

eval('''(=<`#9]~6ZY32Vx/4Rs+0No-&Jk)"Fh}|Bcy?`=*z]Kw%oG4UUS0/@-ejc(:'8dc''')
# 'Hello World!'

eval('''(=BA#9"=<;:3y7x54-21q/p-,+*)"!h%B0/.~P<<:(8&66#"!~}|{zyxwvugJ%''', "abc123")
# 'abc123'

eval20(malbolge20_source, input_data)
```

> **Malbolge20 is not backward compatible.** Its `crazy()` operates on 20 trits
> and produces different results than the 10-trit original, so programs written
> for one variant will not run correctly on the other.

| | Original | Malbolge20 |
|---|---|---|
| Word size | 10 trits | 20 trits |
| Memory | 59,049 cells | ~3.48 billion cells |
| Memory model | Dense array | Sparse, lazily materialized |

## Debugger

```bash
python3 -m malbolge debug hello.mal                     # CLI, GDB-like
python3 -m malbolge debug --tui hello.mal               # TUI (needs textual)
python3 -m malbolge debug --variant=malbolge20 prog.mb
```

```
(maldbg) break 10       # Set breakpoint at address 10
(maldbg) run            # Run until breakpoint
(maldbg) step 5         # Step 5 instructions
(maldbg) back 2         # Step back 2 instructions
(maldbg) examine 0 20   # Examine memory at address 0
(maldbg) disassemble    # Show disassembly
(maldbg) registers      # Show register values
```

![TUI Debugger Screenshot](https://raw.githubusercontent.com/Aiaid/pyMalbolge/master/screenshots/tui.png)

TUI keys: `↓` step, `↑` step back, `r` run, `b` toggle breakpoint,
`←`/`→` scroll memory, `0` recentre on D, `h`/`?` help, `q` quit.

```python
from malbolge import MalbolgeDebugger
from malbolge.core import MalbolgeConfig

dbg = MalbolgeDebugger(source, input_data, config=MalbolgeConfig.malbolge20())
dbg.add_breakpoint(10)
state = dbg.step()       # one instruction
state = dbg.step_back()  # undo it
state = dbg.run()        # until the next breakpoint
print(dbg.registers, dbg.output)
print(dbg.disassemble(0, 10))
```

## The Malbolge landscape

Malbolge programming has followed two largely separate lines, and this project
sits at the end of the second one.

**Search, then hand-assembly (original Malbolge).** For years programs were
*generated* rather than written: Andrew Cooke's 2000 hello world came out of a
beam search, and Lou Scheffer's cryptanalysis — which found the 2-cycle in the
encryption table and showed systematic programming was possible at all — is
still the foundation everything else rests on. Because the original variant has
only 59,049 memory cells, printing fixed text remains the practical ceiling for
generators such as [zb3/malbolge-tools](https://github.com/zb3/malbolge-tools).
Matthias Lutter's **HeLL** assembly language and its **LMAO** assembler
(GPL-3) lifted that line to something writable by hand, and **LMFAO** targets
[Malbolge Unshackled](https://esolangs.org/wiki/Malbolge_Unshackled), Ørjan
Johansen's Turing-complete unbounded-memory variant. The most complex Malbolge
program in existence, Kamila Szewczyk's **MalbolgeLISP** — a LISP interpreter
of roughly 350 MB — was hand-written in that dialect.

**Compilation (Malbolge20).** Nagoya University worked the problem from the
other direction across roughly a decade, publishing on Turing-completeness,
SAT-assisted synthesis of trit-wise operations, and code-allocation decision
procedures, and in 2013 introducing **Malbolge20**: a 20-trit variant whose
larger word and address space make a real compiler feasible. Their toolchain
(MIT-licensed) is a three-stage descent — a C subset compiles to a
pseudo-instruction language, which lowers to the LAL low-level assembler, which
assembles to Malbolge20. Notably, the pseudo-instruction layer treats
*obfuscation as a feature*: the same input is meant to produce different output
on each compile.

**What this project adds.** The Nagoya stack is C++/flex/bison/Perl and needs a
local build; its last commit was in 2021. pyMalbolge reimplements all three
stages in pure Python, verified byte-for-byte against the originals, and puts a
Python front end on top — including `*`, `//` and `%`, which the upstream C
subset does not have, plus `for`-loops, chained comparisons, short-circuit
booleans and line-numbered diagnostics. The direct backend bypasses the C layer
entirely. Output is made deterministic rather than obfuscated, which is what
makes reproducible builds and byte-exact conformance testing possible in the
first place. Alongside that, it is a maintained modern runtime for both
variants with a real debugger.

## Documentation

Design notes and reverse-engineered language specifications live in
[`docs/`](https://github.com/Aiaid/pyMalbolge/blob/master/docs/README.md).
Every document exists in English (`<name>.md`) and Chinese (`<name>.zh.md`).

- [python-subset-spec](https://github.com/Aiaid/pyMalbolge/blob/master/docs/python-subset-spec.md) — normative spec for the accepted Python subset
- [py2mg-backend](https://github.com/Aiaid/pyMalbolge/blob/master/docs/py2mg-backend.md) — design of the direct `py → .mg` backend
- [highlevel-to-malbolge](https://github.com/Aiaid/pyMalbolge/blob/master/docs/highlevel-to-malbolge.md) — why the pipeline looks like this
- [mg-spec](https://github.com/Aiaid/pyMalbolge/blob/master/docs/mg-spec.md) — the `.mg` pseudo-instruction language, reverse-engineered from `ternary`
- [hell-spec](https://github.com/Aiaid/pyMalbolge/blob/master/docs/hell-spec.md) / [lmao-internals](https://github.com/Aiaid/pyMalbolge/blob/master/docs/lmao-internals.md) — HeLL and the LMAO assembler's algorithms
- [perf-baseline](https://github.com/Aiaid/pyMalbolge/blob/master/docs/perf-baseline.md) — profiling and the two hotspots that were fixed
- [toolchain-guide](https://github.com/Aiaid/pyMalbolge/blob/master/docs/toolchain-guide.md) — building the reference tools, for conformance work

## Development

```bash
pip install -e .[dev]
python3 -m pytest test/           # 441 tests
python3 -m pytest test/ -n auto   # ~2.6x faster with pytest-xdist
```

The reference tools under `ref/` are optional. When present, the end-to-end
tests build through them for speed and cross-check the results; when absent,
everything falls back to the pure-Python pipeline.

## Roadmap

- [x] Malbolge20 variant support (20 trits, sparse memory)
- [x] Debugger (CLI + TUI, with step-back)
- [x] Pure-Python port of the full Nagoya toolchain, byte-exact
- [x] Python front end, plus a direct `py → .mg` backend
- [ ] Compiler v2: signed integers, decimal `print()` / `input()`, arrays and strings via `IND_OPR`
- [ ] Malbolge Unshackled support (3-adic integers, variable rotation width, Unicode I/O)

## References

**The language**

- [Malbolge — Esolang](https://esolangs.org/wiki/Malbolge) · [Wikipedia](https://en.wikipedia.org/wiki/Malbolge)
- [Malbolge Unshackled — Esolang](https://esolangs.org/wiki/Malbolge_Unshackled) — the Turing-complete variant
- Lou Scheffer, [Introduction to Malbolge](http://www.lscheffer.com/malbolge.shtml) — the cryptanalysis that made programming possible

**Malbolge20 and the Nagoya toolchain** (MIT)

- [Project page](https://www.trs.cm.is.nagoya-u.ac.jp/projects/Malbolge/) — papers, online assemblers and interpreter
- [Toolchain sources](https://git.trs.css.i.nagoya-u.ac.jp/malbolge) — `highlevel` (C subset → `.mg`), `ternary` (`.mg` → LAL), `lowass` (LAL → Malbolge20), and the reference interpreter. Mirrored under `ref/` here for conformance testing only.
- Kato et al. (2013), *Malbolge with 20trits word length and its programming support tool*, IEICE — introduces Malbolge20
- Kanbe et al. (2016), *An intermediate language for a compiler generating highly obfuscated Malbolge codes*, IEICE SS2016 — the `.mg` layer
- Sakanashi et al. (2017), *A compiler that translates to Malbolge from a C-language subset containing recursive calls*, IEICE SS2017-18 — the C front end

**HeLL / LMAO line** (GPL-3)

- [lutter.cc/malbolge](https://lutter.cc/malbolge/) — HeLL, LMAO, LMFAO, HeLL-IDE and online tools
- [MalbolgeLISP](https://github.com/kspalaiologos/malbolge-lisp) — a LISP interpreter running on Malbolge Unshackled

**Generators**

- [zb3/malbolge-tools](https://github.com/zb3/malbolge-tools) — three generation strategies plus a web GUI
- [lutter.cc/unshackled](https://lutter.cc/unshackled/) — Unshackled reference implementation

**This project**

- Forked from [Avantgarde95/pyMalbolge](https://github.com/Avantgarde95/pyMalbolge)

## License

MIT. The HeLL fixtures under `test/fixtures/hell/` come from the GPL-3 LMAO
distribution and carry their own notice; they are used for conformance testing
only and are not part of the shipped package.
