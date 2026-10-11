# Optional native Malbolge20 VM

> **English** | [中文](native-vm.zh.md)
>
> Status: local extension prototype, preferred by default for Malbolge20 batch
> execution when available; Python is the fallback. JIT remains explicit opt-in.
> This document describes the execution layer; compiler lowering and target
> image generation are independent.

The first acceptance below is a dated native-only snapshot, recorded while
Python was still the default engine. Later optional
[guarded JIT work](native-jit.md) adds a separate engine; the original source
hashes and measurements remain historical evidence rather than current-binary
claims.

The Python package can keep its ordinary API while executing an entire batch
inside a C extension. The native boundary includes instruction dispatch,
registers, sparse memory, self-modification, byte input/output, and execution
budgets. No Python memory callback runs for each instruction.

## Build and use

From a source checkout with a C compiler and this interpreter's Python headers:

```sh
uv run --with setuptools --with wheel python scripts/build_native_vm.py
```

The binary is built for the Python selected by `uv`; build it again when changing
the interpreter ABI. The build adapter uses standard compiler discovery for
macOS, Linux and Windows; local acceptance is currently macOS ARM64. Source
installation can build a fresh native wheel automatically. Checkout binaries
remain ignored by Git and excluded from source archives; only freshly built
staged extensions enter native wheels. See [native packaging](native-packaging.md)
for modes, installed-artifact checks and the pending hosted CI matrix.

```python
from malbolge import run20

result = run20(code, input_data=b"7\n", max_steps=10_000_000,
               max_output=4096, eof="sentinel", engine="native")
print(result.output)
print(result.stop_reason, result.steps)
```

`run20` defaults to `engine="auto"`: it prefers the native VM and falls back to
Python if the extension is unavailable. `engine="python"`, `engine="native"`
and `engine="jit"` select an engine explicitly. Unavailable native/JIT selections
raise an error with build/platform guidance. Extensions are never built
at import or execution time, and `auto` never enables JIT. Installation-time
build behavior is controlled separately by `MALBOLGE_NATIVE_BUILD`.

The Malbolge20 CLI uses the same default for batch execution, including pipes
and redirected stdin without limits. Select `--engine auto|python|native|jit`:

```sh
uv run python -m malbolge --variant=malbolge20 program.mb --input '7' --stats
uv run python -m malbolge --variant=malbolge20 program.mb --engine python --input '7'
```

`--stats` reports the actual `engine` and `requested_engine`. Stdin attached to
a TTY with no batch options retains Python streaming interaction; explicit
native/JIT selection from a TTY requires `--input` or `--input-file`. `eval20`'s
legacy character API, the original variant and the debugger retain Python.

Default-selection validation is recorded separately in
[native engine selection](../notes/native-engine-selection-validation.json):
220 focused tests, one conditional skip and six subtests passed, including a
real default CLI run. Historical throughput measurements below were not rerun.

## Execution and memory contract

The native run returns the same `RunResult` shape as `core.run_memory`. It
preserves byte consumption, UTF-8 text input conversion, EOF value 59049,
sentinel/stop policy, pre-instruction budgets, HALT step accounting, unknown
effective-opcode no-ops, and encryption of the current C address after a jump.
ROT/CRZ writes to D=C are visible to the following encryption check.

Native memory retains detached immutable source and frozen periodic defaults.
Reads do not materialize pages. Writes create 4096-cell uint32 pages; snapshots
share pages until a write, and unique writes beyond the source retain the
Python allocation-count meaning. Byte and wide uint32 source are supported.
External writes are restricted to uint32; arbitrary Python integer memory is
still provided by `SparseMemory`. The execution variant is Malbolge20.

The first prototype retains the GIL and checks Python signals every 16,384
executed instructions. A running memory object rejects reentrant execution,
mutation, copy, and reinitialization from signal callbacks. Releasing the GIL
and integrating debugger stepping/history are separate future changes.

Prepared-memory APIs make the timing boundary explicit:

```python
from malbolge.core import MalbolgeConfig, parse_source
from malbolge.native import NativeMemory, run_memory

memory = NativeMemory(parse_source(code, MalbolgeConfig.malbolge20()))
result = run_memory(memory, b"7\n", max_steps=10_000_000)
pages = memory.export_pages()  # detached values and written masks for checks
```

Each run starts registers at zero, as `core.run_memory` does; memory keeps its
writes. This API does not claim resumable execution.

## Correctness and measurement

```sh
uv run --no-sync pytest test/test_native_vm.py test/test_runtime_qos.py -q
uv run --no-sync python scripts/benchmark_native_vm.py \
  --output-dir /tmp/native-vm-comparison --repeats 5
```

Tests compare results, instruction-boundary stops, page contents, written masks,
allocation counts, initialization defaults, and snapshot isolation against the
Python implementation. Actual MB fixtures cover the independent C reference
as well. The benchmark accepts output/input/HALT/step/register contracts before
timing fresh sequential workers on the same image and input.

Execution clocks exclude file loading, validation and eager initialization;
natural page allocation during execution remains included. Python/native result
construction is included; the C reference's final stdout flush is outside its
execution clock. The C timing copy only wraps the call to its unchanged execution
function; the independently instrumented correctness gate supplies no timing
evidence. Synthetic NOP/self-modification controls remain separate from existing
fixture comparisons. CPU and wall distributions are exploratory on a shared
machine, and are not compiler or image-size optimization claims.

### Local acceptance, 2026-10-10

This historical snapshot predates the `auto` default; Python was the default
and native execution was explicit. The measurements below are unchanged.

[Validation receipt](../notes/native-vm-validation.json): 105 focused tests and
6 subtests passed, independent C review and Clang static analysis passed, and
Python 3.8.19 built/executed three fixture result/page/API checks. Wheel/sdist
checks confirmed that local ABI binaries and private research were excluded.
This is local prototype acceptance, not a full-suite or hosted-CI claim.

Five fresh-process cyclic samples per engine on macOS arm64 / CPython 3.12.9:

| Same MB | Python CPU ms | Native CPU ms | Reference C CPU ms | Native speedup over C |
|---|---:|---:|---:|---:|
| Hi | 61.213 | 0.694 | 2.466 | 3.55x |
| Byte echo | 27.854 | 0.308 | 1.576 | 5.12x |
| Repeated output | 82.946 | 0.899 | 3.087 | 3.43x |
| Function call | 168.335 | 1.837 | 5.322 | 2.90x |
| Synthetic million NOP/self-modification | 652.489 | 6.641 | 4.298 | 0.65x |

All three correctness gates and all 75 timing samples were accepted; source,
image and binary hashes stayed stable. These small fixtures establish a real
native-core benefit, but do not establish a universal speedup. The NOP control
also shows that reference C dispatch can still be faster.

### Reference C and future JIT work

The reference `mem_manage` rebuilds a ten-trit local address; its audited `-O3`
arm64 assembly retains repeated integer/float conversions and multiply-adds.
Its arithmetic uses two-trit lookups across ten groups, and a new memory block
fills 59,049 cells. The new core uses integer page addressing, four-trit lookups,
and frozen periodic defaults. These are observed implementation differences;
their individual speed contributions have not been isolated by ablation.

This first native-only acceptance had no JIT; the later [NOP-block experiment](native-jit.md)
now supplies an explicit machine-code path. General native traces could reduce repeated
dispatch, address resolution and intermediate register traffic. It must guard
against instruction encryption and writes to future code through D, track exact
step/output/input boundaries, and safely return to interpretation when guards
fail. Coarse page invalidation on every instruction would erase much of the
benefit; self-modification-aware traces need a more selective design. Establish
optimized-interpreter baselines and separate translation/warmup from steady
execution before attributing a gain to JIT.
