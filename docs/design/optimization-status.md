# Optimization and results status

> **English** | [中文](optimization-status.zh.md)
>
> Snapshot: 2026-10-09. This inventory separates accepted code, explicit
> experiments and documented local prototypes. The detailed dated measurements
> live in the private companion's optimization overview; public validation
> records are linked below.

## Implemented layers

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

The full workload benchmark has unresolved whole-child timeouts; compilation
success does not certify those targets' output or termination. Historical and
focused test counts are not added together as a current full-suite total.

Future generation optimizations may reduce MB bytes and steps. Their gate is
observable semantics, necessary machine invariants and complete compile-time,
image-size and execution-cost measurements. Equal bytes are an interface
regression check, not an optimization objective.
