# Small Python benchmark corpus

> [中文](README.zh.md) | **English**

These ordinary Python programs provide repeatable correctness and performance
inputs for the Python → C/MG → MC → Malbolge20 → VM pipeline. They use normal
`int(input())` and `print()` calls and run unchanged under CPython. They are a
small test library, not a general Python conformance suite or a speed claim.

From the repository root, start with either a quick lowering check or the tiny
VM baseline:

```bash
uv run --no-sync python scripts/benchmark_pipeline.py \
  --manifest benchmarks/manifest.json --suite standard --stop-after mc
uv run --no-sync python scripts/benchmark_pipeline.py \
  --suite smoke
```

`manifest.json` is the source of truth for program paths, fixed ASCII stdin,
expected ASCII stdout, execution budgets, and suite membership. Paths are
relative to the manifest. The corpus contains **12 programs and 32 workloads**:

A workload may also declare `expected_input_consumed` (a nonnegative byte
count). The target must consume exactly that many bytes; matching stdout alone
does not satisfy this contract.

| Tier | Programs | Workloads | Coverage |
| --- | ---: | ---: | --- |
| `smoke` | 2 | 2 | Literal output; folded arithmetic |
| `standard` | 8 | 24 | Decimal echo; summation; branches; Euclid GCD; iterative Fibonacci; factorial; literal and dynamic multiplication |
| `stress` | 2 | 6 | Double-recursive Fibonacci; mutual recursion |

`smoke` selects the two tiny programs. `standard` includes smoke and standard
programs (10 programs, 26 workloads); `all` includes every tier. Each input
program has `zero`, `small`, and `medium` workloads. These labels describe
relative input sizes within that program, not comparable work across programs.

For exact case selection or an independent CPython run:

```bash
# Select exact program IDs; use either backend explicitly for comparisons.
uv run --no-sync python scripts/benchmark_pipeline.py \
  --manifest benchmarks/manifest.json --cases fibonacci_iterative fibonacci_recursive \
  --backends direct --workloads small --runtime

# Run an individual source directly under CPython.
printf '10\n' | uv run --no-sync python benchmarks/programs/fibonacci_iterative.py
```

The runner compiles each selected source once per compilation sample and uses
the resulting image for all of that program's selected workloads. Runtime
workloads start with fresh VM memory. Use the runner's `--help` for repetition,
artifact, backend, and profiling options. Full assembly and VM runs are separate
from the quick lowering check; recursive workloads are intentionally opt-in
through `all` or exact case selection. Full suites assemble potentially large
MB artifacts and execute bootstrap and decimal-I/O helpers for every workload;
their cost can greatly exceed a CPython run of these short sources.

Results are `summary.csv` (one row per workload) and `report.json` (full stage
metrics and hashes). Without `--output-dir` the runner creates a fresh temporary
directory and prints its location; specify a new directory to keep a named run.
Compilation columns repeat the shared compilation cost across inputs; do not
sum them across workloads. `--workloads small` selects just the small inputs.
The default is one sample; use `--repeats 3` for timing comparisons. There is no
aggregate score or timing pass threshold. No SPEC benchmark code is included.

Normal MB runs benchmark all three required quantities by default:
**cold compilation time, final MB file size, and produced-program runtime**.
The CSV also provides the stage-time sum, VM execution time, exact steps and
steps per second. `run_seconds` includes image read, validation, initialization
and execution, excluding process startup; full process timing is in JSON.
Use fixed-input runtime as the main speed comparison: steps/second measures VM
throughput and can change with the instruction mix. `--stop-after mc` is
explicitly a lowering check and has no final-image or target-runtime result.

Compilation and runtime also record current-process CPU time separately from
wall time. Hardware/Python details and before/after load/power context are in
JSON; unavailable probes remain unknown. Context collection is outside the
measured intervals. CPU time excludes scheduler waiting but still depends on
hardware, frequency, thermal and cache effects: these reports are not hardware
normalized. A single pass on a busy Mac is an exploratory baseline; stronger
A/B comparisons use repeated interleaved samples on a quiet same machine.

The existing Python examples have their own `examples.json` manifest. Use
`--manifest benchmarks/examples.json --suite all` to select all three.
The six original `.mal` examples target a different machine variant and are
documented separately in `examples/README.md`.

## What to measure

1. Establish correctness by comparing each workload with its fixed CPython
   output. A subprocess CPython baseline includes interpreter startup; label it
accordingly. Do not treat the oracle's validation time as a VM speed sample.
   Before timing a changed compiler, separately validate its actual MB images
   against an independent interpreter: exact stdout, consumed input, errors
   and normal termination. A step/output budget stop or child timeout remains
   unvalidated until diagnosed and completed under justified bounds.
2. Measure compiler stages independently: Python frontend (and C → MG on the
   `c` backend), MG → MC, assembly/bootstrap generation, and MB emission. Record
   source and artifact hashes, sizes, backend, environment, and repetitions.
3. Measure MB read/validation, VM memory initialization, and execution
   independently. Bootstrap, decimal parsing/formatting, and program work all
   contribute to execution; tiny workloads make those fixed costs visible.
4. Compare unprofiled repeated runs under the same environment. Profiling and
   instruction tracing are diagnostic samples with their own overhead.

Runtime input keeps the main calculations from folding into constants. The
two smoke cases deliberately measure the constant path. Fibonacci implementations
use identical inputs and outputs. Multiplication variants use identical numeric
operands and outputs; the dynamic variant reads one extra input line, so total
execution time includes extra decimal parsing. Separate that cost before
attributing a difference to multiplication itself.

Every listed workload stays within nonnegative, non-overflowing CPython and
Malbolge20 integer semantics (`0 <= value < 3**20`). Factorial stops at `12!`;
GCD guards its divisor; recursive subtraction follows a base-case guard. Only
the listed valid inputs are part of the oracle contract. Arbitrary negative,
malformed, missing, overflowing, or very large inputs are outside this corpus.
Step/time budgets bound work; they are not performance acceptance thresholds.
No hardcoded timing threshold or unmeasured speed improvement is asserted.

## Validation

```bash
# Manifest, all CPython/MG/MC checks and both backends' tiny real VM cases.
uv run --no-sync pytest test/test_benchmark_corpus.py -q
```

Frontend/MC acceptance does not establish runtime equivalence for the larger
programs. Use a full benchmark runtime run to verify the MB execution of those
workloads on the current compiler and VM.

## Target pipeline and correctness-only reference

The runner deliberately keeps explicit `direct`/`c` backends and
`--target-pipeline text` as its defaults; it does not exercise the product
compiler's O3/auto selection. Runtime calls `core.run_memory` on Python, so
product native-first selection does not change this benchmark engine. Use the
separate `benchmark_native_vm.py` / `benchmark_native_jit.py` runners for engine
comparisons. Record these boundaries with every result.

`--target-pipeline text` remains the runner default. Use
`--target-pipeline structured` for the native MG → LAL records → memory image
handoff. The `ir` backend requires the optional IR dependencies and defaults to
the semantic frontend in this runner; `--ir-frontend compat` selects the older
compatibility frontend explicitly. Record these choices with every cohort.

```bash
uv sync --extra dev --extra ir
uv run --no-sync python scripts/benchmark_pipeline.py \
  --suite smoke --backends c direct ir \
  --target-pipeline structured --ir-frontend semantic --discard-images
```

`--diagnostic-exports` produces inspectable MC/data files with separately
labelled export costs. Native assembly consumes the typed records/image.

`scripts/verify_mb_reference.py` builds a bounded, correctness-only copy of the
pinned upstream Malbolge20 C interpreter. It requires that reference source
and a C compiler. Its counters and bounds verify actual byte output, input
consumption and HALT; instrumented-reference time is never a speed result.
For a previously compiled literal-output image (`Hi` plus newline):

```bash
uv run --no-sync python scripts/verify_mb_reference.py build \
  --output-dir /tmp/malbolge-reference-gate
uv run --no-sync python scripts/verify_mb_reference.py verify \
  --binary /tmp/malbolge-reference-gate/malbolge20-reference-gate \
  --image path/to/literal-output.mb --expected-output-hex 48690a \
  --expected-consumed 0 --max-steps 5000000 --max-output 4096 --timeout 30
```

Run correctness acceptance separately before the full timed matrix. The runner
records attempted and normally completed workloads independently. Incomplete
runs keep diagnostics and stop classifications, with complete CPU/wall/step
metrics blank in CSV and excluded from timing summaries. A whole-child timeout
does not supply a complete VM duration or its lower bound. Compilation is still
counted once per program/backend/style/repetition, shared across inputs.

## Fixed native VM artifact comparison

`scripts/benchmark_fixed_vm.py` measures accepted MBs with one pinned,
unmodified original C `-O3` binary. Every backend must use the same native
manifest and the same per-input deadline. The manifest records actual source,
binary and build provenance; the receipt binds the full image fingerprint to
an independently passed reference gate and exact input/output contract.

```bash
uv run --no-sync python scripts/benchmark_fixed_vm.py \
  --binary path/to/interpreter-O3 --native-manifest path/to/native-manifest.json \
  --image path/to/literal-output.mb --receipt path/to/accepted-receipt.json \
  --input-hex '' --expected-output-hex 48690a --timeout 30
```

The CLI rejects missing or mismatched evidence before starting the native
process. Timings include the whole child (startup, reading, initialization and
execution); image hashing and gate verification occur before the clock starts.
Complete CPU uses that child's user+system resource usage. The unmodified VM
has no internal execution clock or instruction counter, so previously accepted
reference steps are labelled separately. Censored samples keep complete clocks
null and supply no VM-time lower bound. Cold compile timing, MB bytes and
interpreter throughput remain separate measurements.
