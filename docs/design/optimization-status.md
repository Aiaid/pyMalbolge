# Optimization and results status

> **English** | [中文](optimization-status.zh.md)
>
> Activation documentation refreshed: 2026-10-12; measurements retain their dates.
> This inventory separates accepted code, explicit
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

### Activation audit (2026-10-10, current branch)

The current integration defaults to `backend=auto`, O3, `target_pipeline=structured`
and `cluster/main`. Direct and the applicable accepted semantic candidate compete
by exact predicted final MB size before any bootstrap is generated; ties select
direct. See [the complete policy](compiler-optimization.md). Final combined
acceptance is tracked in [the integration receipt](../notes/compiler-optimization-validation.json).

Before this integration, the activation audit recorded C/compat/text defaults
and opt-in compilation caching. The dated performance tables above still describe
explicitly selected frozen paths; they do not measure a new auto-selection run.

| Work | Activation |
|---|---|
| Direct Python→MG frontend and arithmetic shortcuts | Direct is the required auto candidate; O1–O3 enable its shortcuts, O0 disables them. `--backend=direct` locks the frontend. |
| Semantic IR and accepted named profile | Optional O3 candidate when the supported IR environment exists; explicit IR defaults to semantic. O0 verifies only; optimized levels use the accepted profile. `--ir-frontend=compat` selects the original bridge. |
| Native structured LAL/image handoff | O2/O3 default; `--target-pipeline=text` is the explicit opt-out. Transport alone does not explain direct's smaller artifacts. |
| Compilation cache | O3 CLI uses a source-local automatic cache with a 64 MiB per-artifact threshold; `--no-cache` disables it and `--cache-dir` selects an explicit cache. Library compilation has no persistent cache. |
| C reference arithmetic, frames, MC layout/encoding caches, bootstrap storage/emission and shared Python VM primitives | Remain in their applicable implementations. C0 retains reference arithmetic intrinsics; it is not a no-optimization arithmetic baseline. |
| Target-AST initialization/loop/predicate interface | Integrated and locally accepted. All three controls are enabled in semantic O1–O3 and disabled in O0; final combined acceptance is separate from old prototype receipts. |
| Decimal-output candidate and rejected bulk-NOP experiment | Excluded from accepted defaults; the decimal candidate requires explicit pass selection. |
| Native VM | `run20` and Malbolge20 batch CLI default to auto: prefer a loadable native extension, otherwise Python. Original/legacy/debugger/terminal streaming paths retain Python. |
| Native packaging / JIT | Source-wheel builds attempt native; editable installs need a local build. Matching wheels need no compiler. JIT stays explicit; compiler O3 does not enable it. Full wheel-matrix acceptance remains pending. |

Default selection and explicit direct selection:

```bash
uv run python -m malbolge compile program.py -o program.mb --stats
uv run python -m malbolge compile program.py --backend=direct -o direct.mb
```

Explicit semantic selection:

```bash
uv sync --extra dev --extra ir
uv run --no-sync python -m malbolge compile program.py --backend=ir \
  --ir-frontend=semantic --opt-level=1 --target-pipeline=structured -o semantic.mb
```

The uniform artifact comparison always invokes its pinned original C binary
directly. Product engine defaults do not change that measurement cohort.

| Layer | Implemented work | Status and effect |
|---|---|---|
| Python→MG frontend | Direct lowering, per-function reusable temporaries, recursion graph, recursive-frame and live-temporary protection | Integrated; avoids the C representation and unnecessary nonrecursive self-frame protection. Calls to recursive callees can still require return-address/scratch preservation. |
| C/direct arithmetic | Constant folding, divide/modulo-one elimination, small literal multiply chains, on-demand arithmetic/decimal helpers | Integrated defaults; reduces generated operations when applicable while preserving evaluation, effects, errors and 20-trit ring behavior. |
| Semantic IR | Seven named arithmetic/dataflow/control/expression transformations, verified pass boundaries, source locations and independent semantic oracle | Accepted profile for the applicable O3 semantic candidate or explicit semantic frontend; raw frontend API and semantic O0 remain unoptimized/verification-only. |
| MG→LAL | Four existing deterministic styles and native dependency-free structured emitter | Styles remain explicit; native target handoff is the O2/O3 default. Auto compares frontends, not per-call-site styles. |
| LAL→MB | Version-aware movement search cache, opcode encoding tables, first-fit occupancy/key caching, compact paged source storage, streamed output and typed image handoff | Integrated host/storage improvements; some preserve image bytes and improve compiler overhead rather than target execution. Native handoff is the O2/O3 default. |
| VM/debugger | Compact immutable source, periodic defaults, typed copy-on-write memory, grouped-trit crazy lookup, bounded byte I/O/execution and bounded history | Integrated runtime/storage work; interpreter throughput and target instruction counts are distinct metrics. |
| CLI/tooling | Atomic outputs, alias checks, integrity-checked content cache, stage metrics, reproducible fixed-workload benchmark and source audits | Integrated; warm cache behavior is separate from cold compiler performance. |

The new default combines candidate selection and structured handoff while
keeping explicit controls for each. Optional xDSL stays lazy; the dependency-free
direct candidate and explicit C/direct paths retain Python 3.8 support. Size
selection does not establish a universal compile-time or runtime optimum.

## Evidence and boundaries

- [Native engine selection](../notes/native-engine-selection-validation.json):
  current auto/native/Python behavior and compatibility contracts.
- [Native packaging](native-packaging.md) and [TestPyPI receipt](../notes/testpypi-ci-validation.json):
  local macOS ARM64 and one hosted Linux x86-64 installed-artifact acceptance;
  the full configured platform matrix remains pending.
- [Python QoS validation](../notes/python-qos-validation.json): language/runtime
  contracts, compact storage, real target execution, cache and package checks.
- [Semantic pass validation](../notes/semantic-pass-validation.json): accepted
  source transformations and their repeated compile/size/runtime comparisons.
- [Structured handoff validation](../notes/structured-lowering-validation.json):
  native interfaces, library/CLI/IR integration and HEAD-plus-owned-code
  regression independent of foreign local prototypes.
- [Target interface prototype validation](../notes/target-interface-validation.json):
  the earlier local experiment, now followed by current-branch implementation integration.
- [Compiler policy integration](../notes/compiler-optimization-validation.json):
  final combined acceptance record for the new defaults and target interface.

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
structured target loops and native while predicates are integrated and locally
accepted; their earlier causal-ablation gains do not establish performance
parity with the direct frontend. Full variable SSA/liveness, dynamic multiplication
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
