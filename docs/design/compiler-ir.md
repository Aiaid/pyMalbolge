# Structured compiler IR and pass boundaries

> **English** | [中文](compiler-ir.zh.md)
>
> Status, 2026-10-09: LAL foundation and the opt-in semantic frontend are
> implemented, with accepted semantic passes; full variable SSA, new layout and
> LLVM/MLIR adapters remain planned.
> This document describes the new public architecture, independently of the
> private research notes. It makes no performance-improvement claim.

> Current-branch update, 2026-10-10: [O3 policy](compiler-optimization.md) now
> defaults whole-program compilation to auto selection and structured handoff.
> Explicit IR defaults to semantic; compat remains explicit. Target-interface
> integration passed local [combined acceptance](../notes/compiler-optimization-validation.json).
> The 2026-10-09 architecture and measurements remain their dated evidence.

## 1. First milestone and compatibility

The first milestone adds a structured, verified representation of the existing
Low-Level Assembly (LAL, `.mc`) boundary. It introduces named passes and
inspection artifacts while retaining the current assembler. The Python path is:

```text
Python subset → existing direct frontend → .mg → existing MG translator → .mc
  → structured LAL IR → explicit project pass pipeline → .mc → existing mc2mb → .mb
```

The original bridge remains available as `--ir-frontend=compat`. Explicit
`--backend=ir` now defaults to `semantic`, which lowers Python AST directly into semantic IR, with
expression SSA and explicit mutable slots. Its target lowering uses an
authoritative compatibility adapter. See [semantic-ir.md](semantic-ir.md);
full source-variable SSA/liveness remains future work.
The C and direct backends remain explicit choices. Whole-program O3 auto
compares direct with an applicable semantic candidate; see the policy above.
The accepted Python subset and its divergences remain governed by
[the subset specification](../specs/python-subset-spec.md).

The base package remains Python 3.8+ with no mandatory dependencies. IR support
is optional: `xdsl==0.69.0` belongs to the `ir` extra and requires Python 3.10+.
Importing interpreter/compiler/CLI modules must not load xDSL. Executing O3 auto
may load it lazily when available; explicit IR selection checks the runtime and
dependency and reports a clear installation error. A future dependency upgrade requires revalidation.

```sh
uv sync --extra ir --extra dev
uv run python -m malbolge compile examples/hello.py --backend=ir --ir-frontend=compat \
  --emit-ir /private/tmp/hello.ir --emit-mc /private/tmp/hello.mc \
  --passes verify-lal -o /private/tmp/hello.mb
```

Use Python 3.10+ for this example. `--passes` accepts a comma-separated sequence
of registered project pass names. The initial pipeline verifies LAL; it does
not request a new arithmetic or layout optimization.

## 2. What belongs in LAL IR

LAL operations represent declarations and executable structure rather than
one opaque string containing an entire program. Preserve declaration order,
labels, flag state/period, variable/value references, numbered cells, units and
routine/indirect bodies as structured fields and regions. The boundary must
cover the MC emitted by all existing `op_style`/`jmp_style` combinations,
including periodic flags used by indirect operations.

The current `lal` dialect provides `entry`, `flag`, `jflag`, `unit`,
`unit_label`, `unit_cell`, `routine`, `label`, `instruction`, `data` and `align`
operations plus a structured `target` attribute. Unit and routine bodies are
regions. Targets carry label, optional routine and subtraction separately.
Explicit unit offsets remain in source order: repeated/decreasing offsets
participate in legacy page-state accounting and must not be sorted away.

The parser resolves textual syntax into those operations; the verifier checks
operation-local constraints and module-level references; the emitter produces
assembler-consumable MC. Comments and whitespace need not round-trip byte for
byte. Declaration and instruction order, reference meaning, numeric values
and machine behavior must survive. Tests should compare canonical emitted MC,
assembler memory data and complete artifacts when identity is required.

The IR parser is stricter than the legacy regex parser. It rejects malformed,
truncated or unsupported declarations, duplicate symbols, invalid flag states
and unresolved references rather than silently ignoring them. It is not an
unrestricted replacement for every input the old parser tolerated. Some
constructs, including `ALIGN` and certain branch/address forms, are represented
explicitly while retaining known failures in the existing assembler's resolver.
Representation does not make those forms executable end to end; focused tests
retain that limitation rather than silently rewriting their memory layout.

Address words and custom unit calls whose labels start with a standard
instruction/unit prefix are rejected, including qualified address targets.
The legacy assembler dispatches by those prefixes, so a name such as
`JMP_BACK` could otherwise be emitted and reinterpreted as a different
instruction. Use an unambiguous label instead. This restriction also guards
against bare labels colliding with instruction names or declared unit symbols.

LAL IR is deliberately a machine/protocol layer. A flag or numbered cell is
not an inferred Python variable. Self-modifying instruction sequences must not
be treated as freely reorderable arithmetic. Structural verification checks
the representation; it does not prove source equivalence, termination or new
layout invariants.

## 3. Pass ownership and observable execution

Every shipping pass has a stable project name and explicit registration.
Execute it through the xDSL `ModulePass` interface, verify the input and the
result, and preserve an ordered snapshot/digest record. Reject unknown names
before running the pipeline. A verification-only pass is useful infrastructure:
it exposes the same boundary future transformations must satisfy.

| Pass class | Appropriate layer | Contract |
|---|---|---|
| Structural verification | LAL IR now; each future dialect | Shape, attributes, references and admissible machine values |
| Normalization/canonicalization | The dialect whose semantics justify the rule | Deterministic form; no hidden effects or error changes |
| Source-semantic optimization | Semantic IR; accepted bounded profile | Word arithmetic, ordered effects, error flow and conservative dataflow facts |
| Protocol optimization | LAL IR | Preserve flag transitions, instruction mutation and dispatch behavior |
| Layout/bootstrap transformation | Layout layer after LAL | Constructive placement/initialization invariants and artifact validation |
| Host implementation optimization | Parser, emitter, assembler or VM | Separate host speed from target-program behavior/cost |

Upstream optimization suites are not silently added to the shipping pipeline.
Reusing an upstream pass requires an explicit project adapter, applicability
review and validation of the actual dialect semantics. The first milestone
contains verification infrastructure only.

A snapshot identifies the ordered pass invocation and its before/after state.
A digest is a reproducibility signal, not a proof of equivalence. Record the
dependency version, pass order and options along with source/toolchain
fingerprints for retained evidence. The assembler consumes our MC emitter's
output; xDSL's generic printer is an inspection format, not the MB format.

Current API, imported lazily from `malbolge.compiler.ir`:

| API | Result |
|---|---|
| `parse_mc(text)` / `emit_mc(module)` | Verified structured LAL / canonical assembler MC |
| `parse_lal(text)` / `print_lal(module)` | Round-trip inspectable xDSL text |
| `verify_lal(module)` | Structure, ordered declarations, word bounds and scoped references |
| `run_pipeline(module, passes=None, snapshots=False)` | `PipelineResult`; clones the supplied module by default |
| `mc_to_ir_result(text, passes=None, snapshots=False)` | Parsed MC plus verified pass reports |
| `compile_python_ir_result(source, ..., snapshots=False)` | Compatibility frontend plus `PipelineResult` |
| `compile_python_to_ir(source, ...)` / `compile_python_via_ir_to_mc(source, ...)` | Verified module / canonical MC |

`passes=None` selects `verify-lal`. An empty library sequence explicitly selects
no passes while retaining input/output verification. The CLI rejects an empty
name in `--passes`; repeated valid names run in the requested order. A custom
library registry can introduce project passes; it is not a CLI plugin loader.

`PipelineResult.to_dict()` records `xdsl_version`, ordered pass names and
before/after reports. Each summary includes SHA-256 `ir_digest`/`mc_digest`,
total/per-name operation counts and `mc_bytes`. With `snapshots=True`, the
record also includes input and post-pass text. CLI `--stats` always identifies
the IR version and selected pass sequence under `ir`. A cold pipeline records
full reports and `cache_hit: false`; a cache hit records `cache_hit: true`,
`cached_stage: "ir"` or `"mb"`, and empty `reports` rather than fictional replay
results. A cached IR stage also records its current summary hashes/counts.
`--emit-ir` saves final IR rather than every intermediate snapshot.
IR dependency/version and ordered pass configuration are included in cache
identity. Cache integrity checks do not substitute for pass verification.

## 4. Verification and determinism gates

Use independent checks at the boundaries that can fail differently:

1. Parse/verify/emit/parse fixtures and generated MC from all four translator
   style combinations; include invalid shapes and unresolved references.
2. Require a verification-only IR bridge to preserve the existing assembler's
   parsed memory data and MB artifact for the acceptance fixtures.
3. Repeat canonical MC, IR snapshots and digests under different
   `PYTHONHASHSEED` values; pin an operation/digest expectation to the xDSL
   version so a dependency upgrade cannot silently reset the baseline.
4. Run representative compiled programs with the bounded VM and compare bytes,
   input consumption, termination/errors and executed steps where relevant.
5. Exercise the package without xDSL and the base Python floor. Optional IR
   syntax and imports must not leak into ordinary execution.

These checks validate their fixtures and environments. Byte identity under a
verification pass does not establish the correctness of a future transforming
pass. A later semantic optimization may legitimately emit different MC/MB;
then behavior, effects/errors and required machine invariants become the gate.
Performance acceptance measures cold compile wall/CPU time, final MB bytes and
produced-program runtime wall/CPU/steps together. MC size or IR operation count
alone is insufficient. Keep bootstrap work separate from program execution,
and classify whole-process timeouts separately from measured VM time.

## 5. Migration milestones

| Milestone | Status | Exit condition |
|---|---|---|
| Optional LAL IR foundation and Python compatibility bridge | Implemented | Structured operations, parser/emitter, verifier, named pass runner, deterministic inspection and CLI integration |
| High-level semantic dialect | Implemented | Typed word ring, ordered I/O/calls, lazy/control regions, return contracts and independent oracle; mutable slots remain |
| Python frontend emission into semantic IR | Implemented; explicit IR default and optional O3 candidate | Direct AST emission, source diagnostics, declared compatibility limits and authoritative target adapter; see semantic-ir.md |
| Dataflow and optimization passes | Bounded profile accepted | Named arithmetic/control/dataflow/emission passes; full variable SSA and liveness remain planned; see semantic-optimization-passes.md |
| Layout/bootstrap redesign | Planned | Constructive invariants, counterexample regression and per-artifact validation |
| MLIR/LLVM interoperability | Planned | Explicit type/effect/lowering adapter and a measured reason to add the boundary |

The semantic word type denotes the Malbolge20 unsigned word domain
(`0..3**20-1`, arithmetic modulo `3**20`) rather
than ordinary LLVM integer overflow semantics. A high-level model must retain
source evaluation order, input/output, call/global mutation, error guards,
return propagation and termination behavior before constant folding or dead
code removal is enabled. Choosing xDSL does not by itself create an MLIR or
LLVM backend; those adapters are separate engineering work.

No candidate optimization becomes implemented merely by appearing in this
table. Bring up each boundary with a small verified program first, then expand
coverage and introduce measured transformations one at a time.

## 6. Source map

Existing bridge components: [`py2mg.py`](../../malbolge/compiler/py2mg.py),
[`mg2mc.py`](../../malbolge/compiler/mg2mc.py),
[`mc2mb.py`](../../malbolge/compiler/mc2mb.py) and
[`cli.py`](../../malbolge/compiler/cli.py).
IR implementation: [`ir/lal.py`](../../malbolge/compiler/ir/lal.py),
[`ir/passes.py`](../../malbolge/compiler/ir/passes.py),
[`ir/bridge.py`](../../malbolge/compiler/ir/bridge.py) and its
[`lazy API`](../../malbolge/compiler/ir/__init__.py).
Focused dialect, pipeline and CLI contracts are in
[`test_lal_ir.py`](../../test/test_lal_ir.py),
[`test_ir_pipeline.py`](../../test/test_ir_pipeline.py) and
[`test_ir_cli.py`](../../test/test_ir_cli.py).
Benchmark usage and fixed workloads are in
[`benchmarks/README.md`](../../benchmarks/README.md).
