# pyMalbolge

> **English** | [中文](README.zh.md)

**Write Python. Get a running [Malbolge](https://en.wikipedia.org/wiki/Malbolge) program.**

pyMalbolge is a pure-Python compiler from a subset of Python to
[Malbolge20](https://www.trs.cm.is.nagoya-u.ac.jp/projects/Malbolge/), bundled
with interpreters for both Malbolge variants and a full-featured debugger.
The compiler and Python interpreter need no C++, flex, bison or Perl tools.
An optional C extension accelerates Malbolge20 batch execution; semantic IR
optimization is available through the optional `ir` extra.

**Start with Hello World.** From a source checkout, follow the
[installation instructions](#installation), then compile and run this small
example with an explicit execution budget:

```bash
uv run python -m malbolge compile examples/hello.py --no-cache -o hello.mb
uv run python -m malbolge --variant=malbolge20 hello.mb --engine python --input '' --max-steps 5000000 --max-output 64
# Hello, world!
```

To try the original Malbolge interpreter directly:

```bash
uv run python -m malbolge examples/hello.mal --input '' --max-steps 1000 --max-output 64
# Hello World!
```

The [browser debugger](web/README.md#running-it-locally) also runs original
Malbolge locally; the link includes build and startup instructions. It does
not run compiler-generated Malbolge20 programs.

The [Fibonacci example](examples/fib.py) uses ordinary Python input and
output alongside inline double recursion. The compiler supplies the decimal
conversion routines:

```python
def fib(n):
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)


n = int(input())
if 0 <= n <= 47:
    print(fib(n))
else:
    print("error")
```

Compile it once, then supply an index (newline or EOF ends the input):

```console
$ uv run python -m malbolge compile examples/fib.py --backend=direct -o fib.mb
$ printf '10\n' | uv run python -m malbolge --variant=malbolge20 fib.mb
55
```

The fresh artifact completes input `0` with the bounded project Python CLI;
the optimized C reference also verifies input `20` → `6765`. The retained
v2 image additionally completes below 1 GiB sampled RSS; see the [runtime measurements](#runtime-qos-2026-10-08).

The arithmetic range is `0..47`, but double recursion takes exponential time.
Use small demonstration inputs such as `6`, `7`, or `10`; large indices are
impractical on the Malbolge20 interpreter.

Malbolge was designed in 1998 by Ben Olmstead to be as close to unprogrammable
as a language can get: every instruction is self-modifying, the opcode depends
on the instruction's own address, and arithmetic is a lookup-table "crazy"
operation on ternary digits. The first Malbolge program was not written but
*found*, by beam search, two years after the language appeared. This project is
about the other end of that history — compiling ordinary code into it.

- **Compiler** — Python subset → Malbolge20, automatic O3 selection across Direct and applicable semantic IR; explicit C/direct paths and deterministic output
- **Interpreters** — original Malbolge (10 trits) and Malbolge20 (20 trits, sparse memory); native-first Malbolge20 batches with Python fallback
- **Debugger** — breakpoints, watchpoints, step-back, memory inspection, disassembly; CLI and TUI
- **Verified** — reference-port conformance fixtures, independent real-image execution checks and end-to-end tests; optimized paths preserve observable behavior
- **No mandatory Python dependencies** — optional `textual` for the TUI and `xdsl` for IR

## Installation

```bash
uv venv
uv pip install malbolge          # compiler + interpreters + CLI debugger
uv pip install 'malbolge[tui]'    # adds the TUI debugger (textual)
```

Requires Python 3.8+.

This README describes the current source checkout; an index release can lag
behind it. For the current checkout and its optional IR support:

```bash
uv sync --extra dev              # editable install for development
uv sync --extra dev --extra ir   # optional xDSL tools, Python 3.10+
```

Editable installs keep Python execution until a local native extension is
built. A matching native wheel already contains it; an ordinary source install
(`uv pip install .`) attempts a build with a C compiler and Python headers.
`MALBOLGE_NATIVE_BUILD=auto|required|disabled` controls source-wheel builds:
try native with Python fallback, require native, or build pure Python.
Imports and execution never build the extension. See
[native packaging](docs/design/native-packaging.md).

The 2026-10-10 [packaging receipt](docs/notes/native-packaging-validation.json)
records local macOS ARM64 checks; the [TestPyPI receipt](docs/notes/testpypi-ci-validation.json)
records a hosted CPython 3.12 Linux x86-64 build, upload and installed-wheel
check. These do not establish acceptance of the full platform matrix or a
production PyPI native release.

### Current defaults

| Operation | Default | Explicit control |
|---|---|---|
| Whole-program compilation | O3/auto; compare Direct and applicable semantic IR by predicted final MB bytes | `--backend` (`c`, `direct`, `ir`), `-O0`–`-O3` |
| Target handoff | Structured LAL records and memory image at O2/O3, without xDSL on C/direct | `--target-pipeline=text` |
| Compilation cache | O3 CLI source-local cache, 64 MiB per artifact; no persistent library cache | `--no-cache`, `--cache-dir` |
| Malbolge20 byte API and batch CLI | `auto`: native when loadable, otherwise Python | `--engine` (`python`, `native`, `jit`) / `run20(engine=...)` |
| Original Malbolge, debugger, `eval20()` and terminal streaming without batch options | Python | Native/JIT applies to Malbolge20 batches |

JIT remains an explicit ARM64 experiment. Compiler O3 and the runtime engine
are independent choices. Detailed activation and evidence are in
[optimization status](docs/design/optimization-status.md).

## Compiling Python to Malbolge20

### Command line

```bash
# Compile with automatic O3 selection and run
uv run python -m malbolge compile examples/hello.py -o hello.mb
uv run python -m malbolge --variant=malbolge20 hello.mb

# Direct backend: skips the C layer, roughly half the output size on
# programs with control flow or functions, native double recursion
uv run python -m malbolge compile examples/fib.py --backend=direct -o fib.mb

# Inspect the automatic selection; disable optimization or caching explicitly
uv run python -m malbolge compile examples/fib.py -o fib.mb --stats
uv run python -m malbolge compile examples/fib.py -O0 --no-cache -o fib.mb

# Dump the intermediate stages
uv run python -m malbolge compile prog.py --emit-c prog.c --emit-mg prog.mg --emit-mc prog.mc

# Inspect semantic IR after installing the ir extra
uv run --no-sync python -m malbolge compile prog.py --backend=ir --emit-semantic-ir prog.semantic.mlir
```

Compilation defaults to `-O3 --backend=auto`: compare Direct with the accepted
semantic candidate when the optional IR environment is available, then generate
the smaller final MB through the structured target handoff. Explicit backend,
IR frontend and target-pipeline choices remain authoritative. `-O0` disables
optional transforms; `--backend=c` retains the reference C frontend, including
its existing intrinsics. See [compiler optimization policy](docs/design/compiler-optimization.md).

Without a supported IR installation, auto uses Direct. `--stats` reports the
selected backend, candidate sizes and any skipped semantic candidate; the
selection minimizes predicted image size, not measured execution time.
`--emit-c` infers the C path when no backend is given, and IR exports infer
the IR path, so diagnostic exports can change the selected frontend.

O3 CLI compilation automatically caches stages under the source directory's
`.cache/malbolge`, with a 64 MiB limit per cached artifact. `--no-cache` disables
this; `--cache-dir` explicitly enables unrestricted artifact caching. Keys include
content, toolchain, resolved optimization policy, styles and Python version;
corrupt entries are rebuilt. Output paths are checked
before compilation, including source/symlink/hardlink and multi-output
collisions. Writes use atomic replacement, and the CLI streams the final `.mb`
rather than retaining it as a full intermediate string. File/encoding failures
produce concise diagnostics.

### Python API

```python
from malbolge.compiler import compile_python_to_mb
from malbolge import run20

mb = compile_python_to_mb('print("Hello, world!")')                   # automatic O3
mb = compile_python_to_mb('print("Hello, world!")', backend="direct") # direct backend
result = run20(mb, max_steps=5_000_000, max_output=1024)               # auto engine
print(result.output.decode("utf8"), end="")                            # Hello, world!

# Every stage is exposed individually:
from malbolge.compiler import (
    compile_python_to_c,    # Python subset -> Nagoya C subset
    compile_python_to_mg,   # Python subset -> .mg          (direct backend)
    translate_mg_to_mc,     # .mg -> .mc (LAL)              (port of nagoya-ternary)
    assemble_mc_to_mb,      # .mc -> .mb (Malbolge20)       (port of nagoya-lowass)
)
```

### Supported Python subset (v1)

Accepted: unsigned `int` variables and arithmetic (`+ - * // %`, modulo
`3**20`); conditions and loops, `break`/`continue`; lazy `and`/`or` returning
operand values and lazy chained comparisons; conditional expressions;
functions and mutual recursion with captured argument values; simple keyword
calls; flat fixed-arity tuple assignment/swaps; descending literal-step
`range()`; byte I/O and `ord()`; decimal `int(input([literal_prompt]))` in
module or function scope; `print()` mixing unsigned integer values, literal
strings and basic runtime integer f-strings, with literal `sep=`/`end=`.

Earlier operands and RHS values are captured before later side effects.
Range bounds are frozen and iteration uses a hidden iterator. Input failure
and dynamic division/remainder by zero unwind through callers; main prints
`error` once and halts. A function that may return None may be called for its
side effects, but its result is rejected in scalar contexts.

Rejected with source-located `CompileError`s: general signed integers (the
explicit range-bound/step literals are exceptions), true division, runtime
string/object values, raw string-valued `input()`, general `int(...)`,
f-string conversions/format specifications or f-strings outside `print()`,
nested/arbitrary tuple unpacking, starred/default arguments, classes,
imports, comprehensions and nested functions. See the specification for
unsigned range boundaries and conservative assignment/return checks.

The [normative specification](docs/specs/python-subset-spec.md)
covers the accepted-AST whitelist, the documented divergences from
CPython semantics, and the diagnostic contract.

## How the pipeline works

```
Python subset ── py2c ──► Nagoya C ── c2mg ──► MG
       ├──────── py2mg (direct) ──────────────► MG
       └── semantic IR + accepted passes ────► target AST ── py2mg ──► MG

MG ── mg2mc ──► ordered LAL ── mc2mb ──► memory image ──► Malbolge20 (.mb)
                     └──────── textual .mc/.data import/export ────────┘
```

| Stage | What it is |
|---|---|
| `py2c` | **Ours.** Python AST → the Nagoya C subset. Lowers everything to three-address form, works around several defects in the downstream C compiler, and injects `zzmul` / `zzdiv` / `zzmod` library routines because the C subset has no `*`, `/` or `%`. |
| `py2mg` | **Ours.** Python AST → `.mg` directly, skipping the C layer. Reuses the verified codegen primitives but replaces the frame strategy: per-function temporaries, real recursion-cycle detection, and protection of exactly the temporaries live across calls. |
| Semantic IR | Optional Python AST → typed semantic IR → verified named passes → explicit target AST adapter. O3 considers the applicable accepted profile; `--backend=ir` selects it explicitly. |
| `c2mg` | Pure-Python port of `nagoya-highlevel` (C subset → pseudo-instructions), reproduced bug-for-bug so that output stays byte-identical to the reference. |
| `mg2mc` | Pure-Python port of `nagoya-ternary` (pseudo-instructions → LAL). |
| `mc2mb` | Pure-Python port of `nagoya-lowass` (LAL → Malbolge20), replacing the two-stage Perl + C++ original. Padding is deterministic instead of time-seeded. |

Reference-port conformance fixtures compare bytes under controlled styles and
padding. Optimized frontends and structured handoffs are also checked for exact
output, consumed input, errors and termination against independent execution.
An optimization may change image bytes and steps while preserving that contract.

### Compared to the Nagoya toolchain

|  | Nagoya toolchain | pyMalbolge |
|---|---|---|
| Implementation | C++ / flex / bison / Perl | Pure Python |
| Getting it | Build from source locally | `uv pip install malbolge` or a source checkout |
| Source language | C subset | Python subset (the C subset path is kept as one backend) |
| `*` `/` `%` | Not in the C subset | Constant-folded, or emitted as library routines |
| `for` loops | `while` only | `for i in range(...)`, desugared to `while` |
| `break` / `continue` | Not available | Flag lowering, correct in nested loops |
| Chained comparisons, short-circuit `and`/`or` | — | Supported |
| Conditional expressions | — | `a if c else b`, lazily evaluated |
| Text output | `putchar` per character | `print()` with runtime unsigned integers and static strings; decimal helpers injected on demand |
| Decimal input | Manual character parsing | Module/function `int(input([literal_prompt]))`, with explicit unsigned range/error semantics |
| Diagnostics | Parser errors | Line-numbered `CompileError` with a source excerpt |
| Inline double recursion (`f(n-1) + f(n-2)`) | Miscompiled from fib(4) up | Correct on both backends |
| Output determinism | `srand(time(NULL))` padding — deliberately different on every compile | Byte-for-byte reproducible |
| Backends | One | C/direct plus optional semantic IR; O3 selects the smaller applicable candidate |
| Runtime | Reference C interpreter | Python for both variants; optional native Malbolge20 VM and explicit JIT; debugger |
| Last upstream commit | 2021 | Actively maintained |

Obfuscation was a design goal upstream — the pseudo-instruction layer is
*supposed* to emit something different each time. Trading that for determinism
is what makes reproducible builds and byte-exact conformance testing possible.
Controlled port-conformance paths retain reference behavior; optimized paths
are judged by program semantics and machine invariants rather than byte identity.

## Performance

Malbolge20 has no instructions in the usual sense. Addition alone is a
twenty-step loop over ternary digits, every cell rewrites itself after being
executed, and control flow is carried in a register. Compiled programs are
therefore *enormous* relative to their source and run slowly — this is inherent
to the target. Compiler lowering and execution-engine choices both affect those
costs and are measured separately.

### Current optimization and native execution

O3 selects by final image size and uses the structured target handoff. The
[integration receipt](docs/notes/compiler-optimization-validation.json) records
selection, image identity and independent execution contracts. The
[benchmark guide](benchmarks/README.md) separates cold compilation, MB bytes
and execution, including a comparison on one fixed reference VM.

The [native VM acceptance](docs/notes/native-vm-validation.json) records five
fresh-process samples per engine on macOS ARM64 / CPython 3.12.9. Median CPU
times for the same images were:

| Same image | Python CPU ms | Native CPU ms | Reference C CPU ms |
|---|---:|---:|---:|
| Hi | 61.213 | 0.694 | 2.466 |
| Byte echo | 27.854 | 0.308 | 1.576 |
| Repeated output | 82.946 | 0.899 | 3.087 |
| Function call | 168.335 | 1.837 | 5.322 |
| Synthetic million NOP/self-modification | 652.489 | 6.641 | 4.298 |

These small fixtures show a native-core benefit, with reference C still faster
on the synthetic NOP case. They are dated measurements, not a rerun of the
current binary or a universal speed claim. The [JIT experiment](docs/design/native-jit.md)
regressed on the four real fixtures and remains explicit. The older Fibonacci
and Python-only timings below retain their original source, artifact and engine
boundaries; they do not describe today's automatic compile/run combination.

### Runtime QoS (2026-10-08)

The [final validation report](docs/notes/python-qos-validation.json) records
the fresh **285,466,345-byte** Fibonacci artifact and its exact hash. Cold
cached compilation took **38.173 s** wall time (**37.974 s** CLI metrics);
a warm repeat took **1.415 s** wall (**1.212 s** CLI metrics) and produced
identical bytes. These are whole fresh compilations, not final-stage timings.
This predates O3's automatic 64 MiB cache cap; reproducing the large-image warm
cache case requires an explicit `--cache-dir`.

| Fresh artifact execution | Whole-process time | Verified result |
|---|---|---|
| Bounded project Python CLI, `n=0` | 82.494 s | `0\n`, 73,378,255 steps, terminated |
| Optimized C reference, `n=12` | 20.193 s | `144\n` |
| Optimized C reference, `n=20` | 279.169 s | `6765\n` |

The Python CLI reported 82.410 s internally; its whole-process wall time
above also includes interpreter startup.

For a controlled runtime-storage comparison, the retained v2 image
(**277,965,145 bytes**, SHA-256 `8fb3450ddb660aaad5f15731f7ef96366b3d4189a96fdd7a65f00c56d7ac2969`)
also completed input `0` in both interpreters on M1 Pro/32 GiB:

| Retained v2 interpreter | Whole-process time | Sampled peak RSS | Result |
|---|---|---|---|
| Project Python CLI | 111.076 s | 0.846 GiB | `0\n`, exit 0, empty stderr |
| Optimized C reference | 11.591 s | 1.086 GiB | `0\n`, exit 0, empty stderr |

The two retained-image runs were monitored at 4 GiB; neither reached that threshold.
Compact immutable source, typed mutable pages and COW snapshots replace the
old per-cell dictionary. Frozen initialization fill makes execution, copies,
reset and memory inspection agree; debugger history uses deque/output-length
deltas. These are single whole-process samples, including loading and setup.

On the same **retained `.mc`**, final compact-mapping assembly/write took
**35.853 s**, with an isolated peak of **144.0 MiB**, reproducing v2 byte for
byte. This is about 12.5% slower than the earlier 31.875 s streamed stage,
with substantially less memory. Historical full v2 compilation was
103.432 s (its old `mc2mb` stage was 103.073 s). These stage-only results
must not be presented as fresh frontend-to-program compilation times.
For a separate helper-size case, literal `x * 3` lowered to 32,223 MC bytes
instead of 204,296, an **84.2% reduction**; this is not a general speedup.

### Pre-QoS runtime-input Fibonacci baseline (2026-10-08)

On an Apple M1 Pro with 32 GiB RAM, macOS 27.0 and CPython 3.12.9, the final
ordinary-Python example compiled through the pure-Python `direct` backend in
**103.43 s**, producing **277,965,145 bytes** (about 278 MB, decimal).
The optimized C reference interpreter (`-O3`) completed these single
whole-process trials, including program loading and initialization:

| Input `n` | 0 | 6 | 7 | 10 | 12 | 16 | 20 |
|---|---|---|---|---|---|---|---|
| C reference time (s) | 11.430 | 11.562 | 12.073 | 13.921 | 18.044 | 51.507 | 276.136 |

Its cumulative child-process max RSS was about **1.085 GiB**, not a separate
peak for each input. Running the same Python source directly under CPython
at `n=10` took **0.019145 s**, the median of five whole-process trials
including interpreter startup.

In this **pre-QoS baseline**, the project Python CLI did not complete: at `n=0`, the benchmark stopped
it at its 4 GiB RSS threshold after **44.498 s**, with a sampled peak of
**4.212 GiB** (sampling overshot the threshold) and no output. This was a
resource-limit stop, not a timeout or a completed runtime; it does not
establish how much memory a completed run would require. The old
per-source-cell dictionary representation caused a storage bottleneck; the
compact-memory result above supersedes this limitation. These original
measurement figures remain unchanged as historical evidence.

The [pre-QoS shared measurement data](docs/notes/fib-input-performance.json) contains
samples, environment details and validation outputs. These results use the
`direct` backend. The `c` backend also passed native runs for `0`, `10`, and
invalid input; its artifact is 572,759,579 bytes and compiled in 283.06 s.

### Historical baselines

Historical measurements on an M-series Mac, CPython 3.9. The `fib(6)` row
uses the original fixed-input recursive source, without the runtime decimal
parser or formatter in the current `examples/fib.py`:

| Source | `.mb` size (`c`) | `.mb` size (`direct`) | Compile | Run | Steps |
|---|---|---|---|---|---|
| `print("Hello, world!")` | 3.47 MB | 3.47 MB | 1.8 s | 3.0 s | 735 K |
| `for i in range(3): putchar(65+i)` | 27.3 MB | 11.9 MB | 5.7 s | 9.5 s | 3.0 M |
| fixed-input recursive `fib(6)` (historical) | 110.5 MB | 56.8 MB | 28.2 s | 53.8 s | — |

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

### Historical comparison against the reference toolchain

Compiling the same `print("Hello, world!")` — identical C input, identical
`.mg` and `.mc` intermediates — through the Nagoya tools and through this port:

| Stage | Nagoya (C++ / bison / Perl) | pyMalbolge (pure Python) |
|---|---|---|
| C subset → `.mg` | 0.028 s | <0.001 s |
| `.mg` → `.mc` | 0.030 s | 0.003 s |
| `.mc` → `.mb` | 3.49 s | 1.72 s |
| **Total** | **3.55 s** | **1.72 s** |

The Python port is about **2x faster end to end**, which is not a statement
about Python. Assembly dominates the pipeline, and its inner address search is
memoized here and is not upstream — the same change that took this stage from
roughly 40 s/MB to 0.5 s/MB. Everything else is fast enough that the language
gap never shows up.

Both toolchains emit **exactly 3,467,473 bytes**. About 69% of those bytes
differ, and all of them are padding: cells the program never executes, which
upstream fills from `srand(time(NULL))` and this port fills deterministically.
The two binaries behave identically, and each one runs correctly on the other
project's interpreter.

Where the reference implementation does win decisively is execution. On the
same `.mb`:

| Interpreter | Time |
|---|---|
| Nagoya reference (C) | 0.16 s |
| pyMalbolge (CPython) | 3.07 s |

That historical **19x gap** compares reference C with the older Python path;
it does not include this project's native extension. Current Malbolge20 batches
prefer the native VM when installed. Use `--engine=python` to reproduce Python
measurements; the debugger keeps Python stepping and history. Reference tools
remain useful for independent correctness checks and controlled comparisons.

## Running Malbolge programs

```bash
uv run python -m malbolge hello.mal                        # original Malbolge
uv run python -m malbolge --variant=malbolge20 program.mb  # Malbolge20
uv run python -m malbolge cat.mal -i "Hello World"         # feed stdin
```

```python
from malbolge import eval, eval20

eval('''(=<`#9]~6ZY32Vx/4Rs+0No-&Jk)"Fh}|Bcy?`=*z]Kw%oG4UUS0/@-ejc(:'8dc''')
# 'Hello World!'

eval('''(=BA#9"=<;:3y7x54-21q/p-,+*)"!h%B0/.~P<<:(8&66#"!~}|{zyxwvugJ%''', "abc123")
# 'abc123'

eval20(malbolge20_source, input_data)
```

### Batch execution limits and metrics

```bash
uv run python -m malbolge --variant=malbolge20 program.mb --input '7' \
  --eof sentinel --max-steps 10000000 --max-output 1024 --stats
# Raw bytes instead of text input:
uv run python -m malbolge --variant=malbolge20 program.mb --input-file input.bin --stats
```

`--input` encodes UTF-8; `--input-file` supplies raw bytes. Explicit input,
limits or `--stats` select batch execution. For Malbolge20, a pipe or redirected
stdin also selects batch execution, including unlimited runs. A TTY with batch
limits or metrics but no input option supplies empty EOF. Use `--input` for an interactive
shell's batch command. `--eof sentinel|stop` sets the EOF policy.

Malbolge20 batches default to `--engine auto`: use the native VM when its local
extension is available, otherwise use Python. `--engine python|native|jit`
selects an engine explicitly; unavailable native/JIT selections report an
error. JIT is never selected automatically. Source installation now attempts
a native build through the package's wheel hook; an installed native wheel
already contains the extension. `MALBOLGE_NATIVE_BUILD=auto|required|disabled`
controls automatic fallback, mandatory compilation or a pure Python build.
Editable installs do not compile native code. To build in a developer checkout:

```bash
uv run --with setuptools --with wheel python scripts/build_native_vm.py
uv run python -m malbolge --variant=malbolge20 program.mb --engine native --input '7' --stats
```

Metrics are one JSON object on stderr, including the actual `engine` and
`requested_engine`, while program bytes stay on stdout. Exit status is 3 for a
resource budget, 2 for an invalid instruction, and 0 for termination or input
exhaustion. With stdin attached to a TTY and no batch options, execution retains
Python's streaming interaction. Explicit native/JIT selection from a TTY
requires `--input` or `--input-file`. The original variant and debugger retain
Python execution. See [native VM](docs/design/native-vm.md) and
[explicit JIT](docs/design/native-jit.md) for build and platform details.

### Bounded byte-oriented execution

```python
from malbolge import run20

result = run20(malbolge20_source, b"7\n", max_steps=10_000_000,
             max_output=1024, eof="sentinel")
print(result.output)       # bytes
print(result.to_dict())    # counts, registers and stop reason
```

Limits accept nonnegative integers or `None`; zero is a real zero budget.
Stop reasons distinguish termination, invalid instruction, exhausted input,
step limit and output limit. An output limit stops before a byte would exceed
the cap. Text passed to this new API is encoded as UTF-8 and consumption is
counted in bytes. Legacy `eval()` retains its text/codepoint input behavior
and default EOF-stop policy; the new API defaults to the variant's EOF
sentinel. The original interpreter exposes the same API in
`malbolge.run` (also exported with `run20` and `RunResult`).

`run20` defaults to `engine="auto"`, preferring the native VM and falling back
to Python when the extension is unavailable. Pass `engine="python"`,
`engine="native"` or `engine="jit"` for an explicit choice; unavailable native
or JIT engines raise an error. Importing or running the package never invokes
a compiler or enables JIT. Legacy `eval20()` retains its Python character-oriented API.

> **Malbolge20 is not backward compatible.** Its `crazy()` operates on 20 trits
> and produces different results than the 10-trit original, so programs written
> for one variant will not run correctly on the other.

| | Original | Malbolge20 |
|---|---|---|
| Word size | 10 trits | 20 trits |
| Memory | 59,049 cells | ~3.48 billion cells |
| Memory model | Dense array | Immutable source + typed copy-on-write pages |

## Debugger

```bash
uv run python -m malbolge debug hello.mal                     # CLI, GDB-like
uv run python -m malbolge debug --tui hello.mal               # TUI (needs textual)
uv run python -m malbolge debug --variant=malbolge20 prog.mb
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
[`docs/`](docs/README.md).
Prose documents have English (`<name>.md`) and Chinese (`<name>.zh.md`)
versions; both share the machine-readable JSON receipts.

- [optimization-status](docs/design/optimization-status.md) — default, explicit and experimental optimization status
- [compiler-optimization](docs/design/compiler-optimization.md) — O0–O3, automatic selection, structured handoff and caching
- [semantic-ir](docs/design/semantic-ir.md) / [semantic passes](docs/design/semantic-optimization-passes.md) — optional verified frontend and accepted transforms
- [native-vm](docs/design/native-vm.md) / [native-jit](docs/design/native-jit.md) — execution engines and same-image measurements
- [native-packaging](docs/design/native-packaging.md) — source builds, wheel compatibility and TestPyPI acceptance
- [examples](examples/README.md) / [benchmarks](benchmarks/README.md) — runnable examples, fixed workloads and measurement boundaries

- [python-subset-spec](docs/specs/python-subset-spec.md) — normative spec for the accepted Python subset
- [py2mg-backend](docs/design/py2mg-backend.md) — design of the direct `py → .mg` backend
- [highlevel-to-malbolge](docs/design/highlevel-to-malbolge.md) — why the pipeline looks like this
- [mg-spec](docs/specs/mg-spec.md) — the `.mg` pseudo-instruction language, reverse-engineered from `ternary`
- [hell-spec](docs/specs/hell-spec.md) / [lmao-internals](docs/upstream/lmao-internals.md) — HeLL and the LMAO assembler's algorithms
- [perf-baseline](docs/notes/perf-baseline.md) — historical profiling baseline; current measurements are in the QoS report
- [toolchain-guide](docs/upstream/toolchain-guide.md) — building the reference tools, for conformance work

## Development

```bash
uv sync --extra dev
uv run --no-sync pytest test/
uv run --no-sync pytest test/ -n 2
```

The reference tools under `ref/` are optional. When present, the end-to-end
tests build through them for speed and cross-check the results; when absent,
everything falls back to the pure-Python pipeline.

Local QoS acceptance also includes a final focused 207-test run (128
subtests) and portable execution of both compiler backends on the project VM
(2 tests/2 subtests). The [audit snapshot](docs/notes/python-qos-audit.json)
is resolved by the [validation report](docs/notes/python-qos-validation.json),
without rewriting its original counterexamples.

The later 2026-10-10 [compiler integration receipt](docs/notes/compiler-optimization-validation.json)
records **2,788 passed, 29 skipped and 3,610 subtests** for its full working-tree
run, including separately owned native work. A subsequent focused run overlaps
it; counts are dated acceptance evidence and must not be added together.

[CI configuration](.github/workflows/qos.yml) covers Python 3.8/3.12/3.13
and a separate portable semantic job. Python 3.8/3.13 smoke checks passed
locally; as of 2026-10-08 the workflow has not been pushed or run on GitHub.
Native wheel CI and the completed TestPyPI trial have separate scope and
receipts in [native packaging](docs/design/native-packaging.md).

## Roadmap

- [x] Malbolge20 variant support (20 trits, sparse memory)
- [x] Debugger (CLI + TUI, with step-back)
- [x] Pure-Python port of the full Nagoya toolchain, byte-exact
- [x] Python front end, plus a direct `py → .mg` backend
- [x] Unsigned decimal input/output, basic print f-strings, flat tuple swaps and simple keyword calls
- [x] Semantic IR with verified named passes, O3 automatic selection and structured target handoff
- [x] Native-first Malbolge20 batches, Python fallback and explicit guarded ARM64 JIT
- [x] Native source-wheel hook, wheel CI configuration and one hosted TestPyPI installation check
- [ ] Complete hosted native-wheel platform matrix and production release validation
- [ ] Compiler v2: signed integers, general runtime objects/strings and arrays via `IND_OPR`
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

- Started as a fork of [Avantgarde95/pyMalbolge](https://github.com/Avantgarde95/pyMalbolge).
  The interpreter has since been rewritten from scratch and none of the original
  source remains; the `.mal` examples and Ben Olmstead's public-domain reference
  interpreter under `ref/` are all that carried over.

## License

MIT. The HeLL fixtures under `test/fixtures/hell/` come from the GPL-3 LMAO
distribution and carry their own notice; they are used for conformance testing
only and are not part of the shipped package.
