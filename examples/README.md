# Examples

## Python sources for the compiler

Compile these to Malbolge20 with `uv run python -m malbolge compile <file> -o out.mb`,
then run with `uv run python -m malbolge --variant=malbolge20 out.mb`.

| File | Demonstrates | Output |
|---|---|---|
| `hello.py` | `print()` with a constant argument | `Hello, world!` |
| `fib.py` | inline double recursion, runtime decimal input and complete decimal output | `F(n)`, e.g. input `10` → `55` |
| `countdown.py` | `for` / `range`, `break`, `continue`, `%` | `ACE` |

### Runtime Fibonacci input

`fib.py` is ordinary Python: it reads `n = int(input())`, checks
`0 <= n <= 47`, and calls `print(fib(n))`. The Fibonacci function retains
`fib(n - 1) + fib(n - 2)` to demonstrate inline double recursion. No explicit
byte-I/O helpers are needed in the source; the compiler supplies decimal
conversion when lowering `input()` and `print()`.

Valid inputs produce the same decimal result under CPython and the compiled
Malbolge20 program verified with the optimized C reference interpreter:

```bash
printf '10\n' | uv run examples/fib.py                              # 55 (CPython)
uv run python -m malbolge compile examples/fib.py --backend=direct -o fib.mb
printf '10\n' | uv run python -m malbolge --variant=malbolge20 fib.mb  # expected: 55
printf '0' | uv run python -m malbolge --variant=malbolge20 fib.mb      # expected: 0 (EOF)
```

The fresh post-QoS artifact is 285,466,345 bytes. Cold cached compilation
took 38.173 s wall time and a warm repeat 1.415 s, producing identical bytes.
Its bounded project Python CLI run at `n=0` terminated with `0\n` in
82.494 s wall time (82.410 s CLI metrics; 73,378,255 steps). Optimized native execution verified `n=12` →
`144` in 20.193 s and `n=20` → `6765` in 279.169 s. The
[validation report](../docs/notes/python-qos-validation.json) records exact
hashes, limits and process results.

The retained v2 artifact (277,965,145 bytes) separately verifies the storage
change: Python CLI `n=0` completed in 111.076 s at 0.846 GiB sampled peak RSS;
optimized native execution of that same file completed in 11.591 s at
1.086 GiB. Both returned `0\n`, exit 0, with empty stderr. Single-process
measurements include loading/initialization; do not mix these retained-image
figures with fresh compilation timings. See the
[README interpretation](../README.md#runtime-qos-2026-10-08).

The [pre-QoS measurements](../docs/notes/fib-input-performance.json) retain
the earlier ~278 MB image's compile/native timings and its Python CLI stop
at a 4 GiB RSS threshold. That representation limitation has been superseded
by compact source storage and typed copy-on-write pages; the old stop is a
historical bounded test, not a current failure or completed runtime.

The compiled program reads one unsigned ASCII decimal line, ending at LF or
EOF, with an optional leading `+` and surrounding ASCII whitespace. Leading
zeros and CRLF are accepted; CR alone is whitespace rather than a line
terminator. The compiler's conversion accepts values `0..3486784400` and
rejects empty, invalid, or overflowing input by writing `error` followed by
a newline and halting main. CPython instead raises its normal exceptions for
invalid conversion or empty EOF; the compiler does not implement those
exceptions or a runtime string object.

The source checks the smaller Fibonacci range and prints `error` for `n > 47`.
`F(0) = 0`, `F(1) = 1`, and `F(47) = 2971215073` fits the unsigned word;
`F(48)` exceeds it. Results are emitted in full decimal followed by a newline,
with no input prompt.

Double recursion takes exponential time: `0..47` is the arithmetic range,
not a practical performance range. Use small demonstration inputs such as
`6`, `7`, or `10`; large indices are impractical on the Malbolge20 interpreter.
Expect multi-MB `.mb` files and substantial compile/run times. The top-level
README's historical Fibonacci figures describe the original fixed-input
`fib(6)` source, without runtime decimal input/output.

## Hand-written Malbolge programs (original variant)

Run with `uv run python -m malbolge <file>`.

- `hello.mal` : from https://en.wikipedia.org/wiki/Malbolge#Example_Program
- `cat.mal` : from https://esolangs.org/wiki/malbolge#Cat
- `quine.mal` : from http://matthias-ernst.eu/malbolgequine.html
- `99bottles.mal` : from http://www.99-bottles-of-beer.net/language-malbolge-995.html
- `truth.mal` : from https://esolangs.org/wiki/Truth-machine#Malbolge
- `cat2.mal` : from https://commons.wikimedia.org/wiki/File:Malbolge_cat_program.png
