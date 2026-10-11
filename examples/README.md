# Examples

> [中文](README.zh.md) | **English**

## Python sources for the compiler

| File | Demonstrates | Input | Output |
|---|---|---|---|
| `hello.py` | Constant string `print()` | None | `Hello, world!\n` |
| `countdown.py` | `for` / `range`, `break`, `continue`, `%`, `putchar()` | None | `ACE` (no newline) |
| `fib.py` | Double recursion, decimal `int(input())` and integer `print()` | `6\n` | `8\n` |

Compilation now defaults to O3/auto, comparing Direct with an applicable
semantic candidate. Both explicit `c` and `direct` backends compile all three
examples to Malbolge20. Use separate filenames for comparisons:

```bash
uv run python -m malbolge compile examples/hello.py -o hello-auto.mb --stats
uv run python -m malbolge --variant=malbolge20 hello-auto.mb --input '' --stats

uv run python -m malbolge compile examples/hello.py --backend=c -o hello-c.mb
uv run python -m malbolge compile examples/hello.py --backend=direct -o hello-direct.mb
uv run python -m malbolge --variant=malbolge20 hello-direct.mb --input '' --max-steps 400000000 --max-output 4096 --stats

uv run python -m malbolge compile examples/countdown.py --backend=direct -o countdown.mb
uv run python -m malbolge --variant=malbolge20 countdown.mb --input '' --max-steps 400000000 --max-output 4096 --stats

printf '6\n' | uv run examples/fib.py  # CPython: 8
uv run python -m malbolge compile examples/fib.py --backend=direct -o fib.mb
uv run python -m malbolge --variant=malbolge20 fib.mb --input '6' --max-steps 400000000 --max-output 4096 --stats
```

The bounded commands return exit 3 when a budget is reached. `--stats`
reports metrics on stderr while program output stays on stdout. Malbolge20
batches default to native when available, otherwise Python; `--stats` identifies
the actual engine. Use `--engine=python` to compare with the dated Python
measurements below. JIT requires explicit selection. The CLI's
explicit `--input '6'` ends at EOF; decimal conversion also accepts `6\n`.
The comments in older sources may show historical commands or an older
constant-only `print()` restriction; the current subset also supports
unsigned integer decimal output. See the [Python subset spec](../docs/specs/python-subset-spec.md).

## Historical comparison after the 2026-10-08 performance work

This explicit-backend Python-VM snapshot predates O3/auto and native-first
batch defaults. Its sizes and times do not describe current automatic selection.

| Source | Backend | MB bytes | Compiler stages, baseline → current (s) | Current VM total (s) | Executed steps |
|---|---|---:|---:|---:|---:|
| `hello.py` | `c` | 3,467,473 | 0.468 → 0.424 | 0.666 | 736,373 |
| `hello.py` | `direct` | 3,466,627 | 0.484 → 0.648 | 0.670 | 735,114 |
| `countdown.py` | `c` | 159,275,293 | 21.339 → 18.682 | 53.333 | 58,129,606 |
| `countdown.py` | `direct` | 68,019,999 | 8.418 → 8.012 | 21.310 | 23,342,300 |
| `fib.py` | `c` | 590,717,433 | 85.153 → 67.112 | 169.320 | 180,551,521 |
| `fib.py` | `direct` | 285,466,345 | 38.008 → 32.505 | 79.654 | 85,110,921 |

All six VM runs terminated with the exact outputs in the first table; Fibonacci used `6\n`. Limits were 400,000,000 steps, 4,096 output bytes and 480 s per process. Compiler time is the sum of independently timed stages, excluding diagnostic/artifact writes except MB emission; this avoids a redundant baseline evidence parse in early child-process totals. The separate native C-reference check of the same C-backend Fibonacci image also returned `8\n` (exit 0, empty stderr).

These are fresh, uncached, single samples. The compiler baseline predates
this performance work, while its VM already uses the same grouped-trit
runtime as the current compiler's runtime. Every example/backend produced
identical `.mg`, `.mc`, `.data`, and `.mb` SHA-256 fingerprints before and
after the compiler changes. Runtime measurements execute each current image
once with the current project Python VM; they do not measure an old/new VM
speedup. Concurrent benchmark activity makes small wall-time differences
noisy. Parse/layout, bootstrap generation and emission are measured
separately; loading and validation are included in total runtime.

Direct-backend images are 42.7% of the C image for countdown and 48.3% for Fibonacci. The performance changes themselves preserve image sizes.

Rerun the existing examples through both backends using the [benchmark runner](../benchmarks/README.md):

```bash
uv run python scripts/benchmark_pipeline.py --manifest benchmarks/examples.json --suite all --runtime --output-dir /private/tmp/pymalbolge-examples-new
```

The separate small Python corpus covers more algorithms and fixed input sizes; use `--suite smoke --runtime` for a tiny start or `--suite all --stop-after mc` for a broad lowering check.

## Fibonacci input and practical range

`fib.py` reads `n = int(input())`, checks `0 <= n <= 47`, and prints `fib(n)`.
Its `fib(n - 1) + fib(n - 2)` expression demonstrates double recursion.
The compiler supplies decimal conversion; no byte-I/O helpers are required
in the source.

The compiled program reads one unsigned ASCII decimal line, ending at LF or
EOF, with an optional leading `+` and surrounding ASCII whitespace. Leading
zeros and CRLF are accepted; CR alone is whitespace. Conversion accepts
`0..3486784400`; empty, invalid or overflowing input prints `error\n` and
halts main. CPython instead raises its usual exceptions for invalid
conversion or empty EOF. Runtime strings and Python exceptions are outside
the compiler subset.

The source prints `error\n` for `n > 47`. `F(0) = 0`, `F(1) = 1`, and
`F(47) = 2971215073` fits the unsigned word; `F(48)` overflows it. Output is
complete decimal followed by a newline, with no prompt.

Double recursion takes exponential time. `0..47` is the arithmetic range;
small inputs such as `6` are practical demonstration cases. Compiled images
can be hundreds of MB, and much of execution initializes the generated
program before running the Python logic.

The [QoS validation report](../docs/notes/python-qos-validation.json) retains
earlier storage, caching and native-reference measurements, including larger
Fibonacci inputs. The [pre-QoS report](../docs/notes/fib-input-performance.json)
records the superseded Python representation's 4 GiB stop. These are
historical evidence, distinct from the fresh comparison above. The top-level
README's old fixed-input `fib(6)` figures also describe an earlier source
without runtime decimal conversion.

## Hand-written Malbolge programs (original variant)

Run with `uv run python -m malbolge <file>`. These target original Malbolge;
they are not Malbolge20 compiler output.

- `hello.mal`: from https://en.wikipedia.org/wiki/Malbolge#Example_Program
- `cat.mal`: from https://esolangs.org/wiki/malbolge#Cat
- `quine.mal`: from http://matthias-ernst.eu/malbolgequine.html
- `99bottles.mal`: from http://www.99-bottles-of-beer.net/language-malbolge-995.html
- `truth.mal`: from https://esolangs.org/wiki/Truth-machine#Malbolge
- `cat2.mal`: from https://commons.wikimedia.org/wiki/File:Malbolge_cat_program.png
