# Guarded native NOP-block JIT

> **English** | [中文](native-jit.zh.md)
>
> Status: opt-in ARM64 experiment over the [native VM](native-vm.md).
> The default engine remains Python. This is guest Malbolge machine-code
> generation, independent of CPython's own JIT.

## Build and select

```sh
uv run python scripts/build_native_vm.py
```

```python
from malbolge import run20

result = run20(code, input_data=b"7\n", max_steps=10_000_000,
               max_output=4096, engine="jit")
```

The first emitter supports little-endian ARM64 macOS and Linux; macOS arm64 is
the locally exercised target. ARM64e, big-endian ARM64 and other architectures
report unavailable. Explicit JIT selection raises an error when unavailable;
unsupported guest operations use the native interpreter within the JIT engine.
The prototype retains the GIL and the native VM's signal/budget contracts.

## Actual code generation and guards

`_native_jit.h` emits actual ARM64 LDR/CMP/conditional-branch/MOVZ/STR/RET
instructions for canonical opcode 68 NOP blocks of 2, 4, 8, 16, 32 or 64 cells.
Each guest NOP still encrypts its own code cell. A guard checks each uint32 word
before its store. A changed instruction returns the exact completed prefix;
the first unexecuted instruction is then interpreted normally. Arithmetic,
indirection, jumps and I/O remain scalar in this first experiment.

Calls stay within one writable COW page, memory wrap, execution budget,
16,384-step signal quantum and counter range. The caller records only the
completed cells' write masks and unique non-source allocations. Registers and
step accounting advance exactly as individual interpretation would. Future
code writes, source resets and different memory objects are safe because the
generated functions inspect current words rather than trust source identity.

The process cache is bounded by a 1 MiB arena and 94 address residues times six
shape sizes. Code generation uses trusted fixed templates; guest bytes are data
and guards, not executable instructions. macOS uses MAP_JIT, thread write
protection and instruction-cache invalidation; Linux uses RW-to-RX protection.
No interpreter signatures or system security settings are modified. Mapping
failure is explicit, and capability is rechecked before dispatch after signal
callbacks. The arena is released at process exit.

The platform implementation follows [Apple's JIT guidance](https://developer.apple.com/documentation/apple-silicon/porting-just-in-time-compilers-to-apple-silicon)
and the [pthread API declarations](https://github.com/apple-oss-distributions/libpthread/blob/main/include/pthread/pthread.h).

## Metrics and validation

```python
from malbolge.core import MalbolgeConfig, parse_source
from malbolge.native import NativeMemory, run_memory

memory = NativeMemory(parse_source(code, MalbolgeConfig.malbolge20()))
result = run_memory(memory, b"7\n", jit=True, max_steps=10_000_000)
print(memory.jit_stats())
```

Last-run statistics report actual JIT blocks/steps, scalar steps, guard exits,
emitted blocks/bytes, emission CPU/wall and current process cache sizes.
`jit_steps + fallback_steps == result.steps`, including scalar HALT. Availability
and statistics queries do not map or generate code. Cold execution includes
arena preparation and code emission; zero-budget runs change no VM pages.

```sh
uv run --no-sync pytest test/test_native_jit.py test/test_native_vm.py -q
uv run --no-sync python scripts/benchmark_native_jit.py \
  --output-dir /tmp/native-jit-comparison --repeats 3
```

The comparison uses identical images/inputs in fresh sequential Python,
native, cold JIT, warm JIT and reference C workers. All modes must match output,
consumed input, HALT, steps/registers and full Python/native/JIT page state.
Machine-code coverage is recorded; zero-coverage timing is not a JIT speed claim.

One full traversal does not always stabilize the shape cache. Warm workers run
bounded fresh-memory warmup rounds until a pass emits no code, record every round
and their complete phase cost, then time another fresh memory. Accepted warm
samples emit no additional code. Translation cost is never subtracted from cold
totals, and warmup cost stays separate and visible. Synthetic NOP controls are
reported separately from existing compiled-program fixtures.

## Local acceptance, 2026-10-10

[Validation receipt](../notes/native-jit-validation.json): 160 focused tests,
one platform-conditional skip and six subtests passed. Independent review,
Clang analysis, Python 3.8.19 real-JIT/page/API checks and package exclusions
passed. The Linux RX-restoration failure path was hardened before final build;
it was statically reviewed on Darwin, not fault-injected on Linux.

Five modes, identical images, three cyclic fresh-process repetitions on macOS
arm64 / CPython 3.12.9. Medians below are execution CPU milliseconds:

| Case | Native | Cold JIT, emission included | Warm JIT | Reference C | Warm JIT coverage |
|---|---:|---:|---:|---:|---:|
| Hi | 0.814 | 1.465 | 1.142 | 2.450 | 42.0% |
| Byte echo | 0.376 | 0.804 | 0.523 | 1.575 | 41.7% |
| Repeated output | 1.065 | 1.837 | 1.480 | 2.882 | 42.2% |
| Function call | 2.200 | 3.555 | 3.241 | 5.325 | 41.2% |
| Synthetic million NOP/self-modification | 7.232 | 1.711 | 1.137 | 4.266 | 99.9999% |

The control's cold/warm totals improve on native by 4.23x/6.36x and on reference
C by 2.49x/3.75x. Its cold emission CPU is 0.087 ms; 47 templates contain 84,600
code bytes in the 1 MiB arena. The four small real fixtures regress by about
39–47% even when warm, and remain slower than native when cold. This experiment
is explicit opt-in; these results do not justify making it the default.

All 75 timed runs and their architectural/page gates passed. Warm fixture
caches required three fresh-memory training rounds; the control required two.
Training execution CPU totals were 3.871/1.857/4.831/10.360/2.952 ms respectively;
the report also retains whole training phase clocks including preparation and
state inspections. Accepted timed warm runs emitted zero new code. An earlier
one-pass warmup matrix was rejected and retained separately. The coordinated
sampling finished before the other session resumed its untimed initializer.

## Remaining work

This experiment does not yet translate general control flow or arithmetic.
Use same-image measurements to decide whether short NOP guards/shape promotion
help a workload before broadening trace ownership. Mixed traces need explicit
alias/side-effect guards and safe interpreter exits, plus separate compilation,
warmup, code-cache size and steady execution evidence.
