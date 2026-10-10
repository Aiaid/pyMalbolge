# Optimization and results status

> **English** | [中文](optimization-status.zh.md)
>
> Snapshot: 2026-10-09. This inventory separates accepted code, explicit
> experiments and documented local prototypes. The detailed dated measurements
> live in the private companion's optimization overview; public validation
> records are linked below.

> Follow-up, 2026-10-10: the latest frozen working cohort, including the local
> target-interface prototype, passed all 123 independent real-image contracts
> before timing. All 36 cold compiles and 96 runtime combinations were attempted;
> 73 Python runs completed normally and 23 hit whole-child deadlines. Final
> source/image/state checks passed. [Acceptance summary](../notes/latest-corpus-validation.json)
> keeps working-cohort and one-pass limits explicit; it does not promote the
> prototype or establish a universal speed gain.

> Common-VM follow-up, 2026-10-10: the same frozen accepted MBs were regenerated
> and run with one pinned unmodified original C-O3 binary, including genuine
> original GCD. All 99 identities were attempted: 97 complete, 2 whole-child
> timeouts, no output failure; source/image/VM/cleanup audit passed. The direct
> GCD image is 276.78 MB versus the original 597.97 MB, with whole-child wall
> 9.11 versus 18.83 seconds in this pass. [Uniform-VM acceptance](../notes/common-vm-validation.json)
> keeps this artifact comparison separate from interpreter/default-engine work.

## Implemented layers

### Activation audit (2026-10-10)

The compiler defaults are `backend=c`, `ir_frontend=compat`,
`target_pipeline=text`, and `cluster/main`. The size/runtime tables compare
explicitly selected paths; their direct or semantic results are not the plain
compile command's default result.

| Work | Activation |
|---|---|
| C/direct arithmetic shortcuts, temporary/frame handling, MC layout/encoding caches, bootstrap storage/emission and shared Python VM primitives | Automatic in the applicable implementation; no extra optimization switch. |
| Direct Python→MG frontend | Select `--backend=direct`; its internal accepted optimizations then apply automatically. |
| Semantic IR and accepted named optimization profile | Select `--backend=ir --ir-frontend=semantic` and install the `ir` extra. The accepted profile is already the semantic default; `--opt-level=1` makes that choice explicit, while `0` selects verification only. `--backend=ir` alone retains the compat frontend. |
| Native structured LAL/image handoff | Select `--target-pipeline=structured`; default remains `text`. This is an interface experiment, not the cause of the direct frontend's smaller images. |
| Compilation cache | Supply `--cache-dir`; disabled by default. Cold benchmark measurements do not use it. |
| Decimal-output candidate and rejected bulk-NOP experiment | Excluded from accepted defaults; the decimal candidate requires explicit pass selection. |
| Target-AST initialization/loop/predicate prototype | In the current uncommitted semantic adapter, its three interface options default on inside that selected path. The frozen working benchmark includes it; it is still separate from committed source and from the named semantic profile. |
| Native VM / JIT | At committed code base `1a7b88b`, `run20` defaults to Python and native/JIT are explicit library engine choices. Current working code has a separately owned, uncommitted `auto` native-first batch policy; JIT remains explicit. Native install/build changes are also separately owned work. |

For the committed direct path:

```bash
uv run python -m malbolge compile program.py --backend=direct -o program.mb
```

For explicit semantic and structured selection:

```bash
uv sync --extra dev --extra ir
uv run --no-sync python -m malbolge compile program.py --backend=ir \
  --ir-frontend=semantic --opt-level=1 --target-pipeline=structured -o program.mb
```

The uniform artifact comparison always invokes its pinned original C binary
directly. Product engine defaults do not change that measurement cohort.

| Layer | Implemented work | Status and effect |
|---|---|---|
| Python→MG frontend | Direct lowering, per-function reusable temporaries, recursion graph, recursive-frame and live-temporary protection | Integrated; avoids the C representation and unnecessary nonrecursive self-frame protection. Calls to recursive callees can still require return-address/scratch preservation. |
| C/direct arithmetic | Constant folding, divide/modulo-one elimination, small literal multiply chains, on-demand arithmetic/decimal helpers | Integrated defaults; reduces generated operations when applicable while preserving evaluation, effects, errors and 20-trit ring behavior. |
| Semantic IR | Seven named arithmetic/dataflow/control/expression transformations, verified pass boundaries, source locations and independent semantic oracle | Accepted default profile when semantic frontend is explicitly selected; raw frontend API and opt-level 0 remain unoptimized/verification-only. |
| MG→LAL | Four existing deterministic styles and native dependency-free structured emitter | Explicit style choices; native target pipeline is an opt-in interface experiment. No automatic per-call-site cost selection yet. |
| LAL→MB | Version-aware movement search cache, opcode encoding tables, first-fit occupancy/key caching, compact paged source storage, streamed output and typed image handoff | Integrated host/storage improvements; some preserve image bytes and improve compiler overhead rather than target execution. Native handoff remains opt-in. |
| VM/debugger | Compact immutable source, periodic defaults, typed copy-on-write memory, grouped-trit crazy lookup, bounded byte I/O/execution and bounded history | Integrated runtime/storage work; interpreter throughput and target instruction counts are distinct metrics. |
| CLI/tooling | Atomic outputs, alias checks, integrity-checked content cache, stage metrics, reproducible fixed-workload benchmark and source audits | Integrated; warm cache behavior is separate from cold compiler performance. |

The compiler still defaults to the C frontend, IR defaults to compat, and the
target pipeline defaults to text. Semantic source passes and native lower
handoff are independent selections. Optional xDSL stays lazy; C/direct base
code keeps Python 3.8 support.

## Evidence and boundaries

- [Python QoS validation](../notes/python-qos-validation.json): language/runtime
  contracts, compact storage, real target execution, cache and package checks.
- [Semantic pass validation](../notes/semantic-pass-validation.json): accepted
  source transformations and their repeated compile/size/runtime comparisons.
- [Structured handoff validation](../notes/structured-lowering-validation.json):
  native interfaces, library/CLI/IR integration and HEAD-plus-owned-code
  regression independent of foreign local prototypes.
- [Target interface prototype validation](../notes/target-interface-validation.json):
  documented local experiment, not implementation integrated by this change.

Performance conclusions remain workload/cohort-specific. Constant identities,
expression folding and propagation can improve all three costs. Encoding and
packing caches primarily improve host compile work; VM lookup changes primarily
improve execution throughput. Native handoff establishes a common backend
interface without a demonstrated broad speed increase. Existing style choices
can alter image size and execution steps independently of that interface.

## Experiments and open work

The compact decimal output experiment remains excluded from the accepted
semantic profile after target cost regression. Bulk NOP emission was rejected
after a host-time regression. Generated-local initialization omission,
structured target loops and native while predicates remain another chat's
uncommitted prototype; its causal-ablation gains do not establish parity with
the original direct frontend. Full variable SSA/liveness, dynamic multiplication
redesign, cost-driven call-site styles, dispatch/flag minimization and new
layout/bootstrap strategies remain open.

The latest independent correctness gate resolves output and termination for
the fixed corpus, including the older timed-out C/direct images. Complete
Python execution times remain unavailable for the 23 censored rows in the
2026-10-09 Python cohort. The separate uniform-C-VM cohort has only C/semantic
`12!` censored; direct completes all 32 fixed corpus inputs.
Historical and focused test counts are not added together as a current
full-suite total.

Future generation optimizations may reduce MB bytes and steps. Their gate is
observable semantics, necessary machine invariants and complete compile-time,
image-size and execution-cost measurements. Equal bytes are an interface
regression check, not an optimization objective.
