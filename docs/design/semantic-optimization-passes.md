# Explicit semantic optimization passes

> **English** | [中文](semantic-optimization-passes.zh.md)
>
> Status: arithmetic/dataflow/control and bounded expression emission accepted
> for the semantic default profile. Decimal output remains an opt-in experiment
> after target-size/runtime regression. Architecture baseline: `aabe099`.

## Pass contracts

| Name | Transformation | Required preservation |
|---|---|---|
| fold-arithmetic | Word-ring constant arithmetic, unary and resolved comparisons | Never fold zero-divisor errors away; inline only reached comparison producers |
| simplify-arithmetic | Neutral/annihilator arithmetic, divide/modulo by one | Operands have already evaluated; retain calls, reads and error-producing computations |
| lower-constant-multiply | Bounded binary/NAF/modular-negation addition chains | Exact modulo 3**20, one evaluation of the multiplicand; costly factors remain multiplication |
| simplify-control | Constant branches, resolved Boolean prefixes and false loops | Retain ordered reached regions; false-loop condition executes once |
| propagate-constants | Proven slot facts through sequential code and conservative joins | Unknown initial facts, global invalidation across calls, all loop writes killed before analysis |
| eliminate-pure-computation | Unused proven nontrapping computations | Retain stores/declarations, unproven reads, calls, I/O, name traps and possibly failing division |
| inline-pure-arithmetic | Explicit target-expression emission hint for adjacent add/sub chains | Exactly one use by the next add/sub in the same block, depth bounded; adapter independently rechecks hints |
| lower-decimal-output | Constant text or typed nonrecursive formatter calls | Existing SSA operand, print/input/error order, exact unsigned formatting, collision-free helper reuse |

Dataflow work is bounded; partial rewrites remain valid. Multiplication expansion
has an explicit operation budget. Stores and declarations are deliberately kept:
this is not full variable SSA or global dead-store elimination. The decimal
formatter uses bounded addition/subtraction loops and a single-digit fast path;
it does not use generic division, modulo, multiplication or recursion.
The expression-emission pass does not rewrite source evaluation: it removes
unnecessary target AST captures only after independently rechecked adjacency
and single-use proofs. Each chain has at most 16 inlined levels; a materialized
consumer may add one final AST level. Forged/stale markers never bypass proof.

Every pass runs through the existing verified runner. Source locations survive
rewrites, inputs are cloned by default, and before/after counts/digests can be
inspected. Semantic equivalence requires independent tests beyond structural
verification. Upstream optimization catalogs remain disabled.

## Backend boundary and comparison modes

The semantic target adapter disables the old direct frontend's arithmetic
folding, divide/modulo-by-one and small-multiply shortcuts. Those decisions now
belong to explicit semantic passes. The C/direct reference routes keep their
old defaults; naming/syntax checks, static control handling, literal output,
ABI/layout, assembler caches and VM implementation remain in their own layers.
Therefore an off comparison is **arithmetic-gated**, not a claim of a globally
unoptimized compiler.

The benchmark modes are:

- legacy_direct: unchanged direct source path.
- semantic_legacy: verification only, old target arithmetic enabled; reference
  for the architecture baseline.
- semantic_none: verification only, old target arithmetic disabled.
- semantic_passes: explicit arithmetic/dataflow/control candidate sequence.
- semantic_decimal: that sequence plus decimal output lowering.

The candidate order is defined in `semantic_passes.py`; repeated cleanup is
explicit in reports. Default promotion is a separate policy change after
behavior and performance acceptance. Host instruction encoding/packing caches
and runtime crazy lookup are implementation optimizations, not fake IR passes.

The accepted order is `OPTIMIZATION_PASSES` and is now the semantic default.
Use `--backend=ir --ir-frontend=semantic --opt-level 0` for verification only,
or `--opt-level 1` for the accepted profile. An explicit `--semantic-passes`
list is an alternative to a level. The raw frontend library API remains
unoptimized. Explicit `compat` retains the direct bridge. Whole-program O3
auto may select the accepted semantic candidate; explicit IR defaults to
semantic. C/direct arithmetic switches follow [the current policy](compiler-optimization.md).
`lower-decimal-output` is registered but absent from level 1. The accepted
profile does not claim universal speedup: neutral cases retain target structure,
and verification/analysis add small host overhead. The rejected decimal
candidate is retained explicitly for reproducible investigation.

## Reproducible acceptance

`scripts/benchmark_semantic_passes.py` provides fixed source/input/output and
input-consumption contracts, fresh child processes, rotated interleaving,
one cold compile shared by input workloads, and JSON/CSV checkpoints.

```sh
uv run --no-sync python scripts/benchmark_semantic_passes.py \
  --cases char_io literal_fold constant_propagation \
  --variants semantic_legacy semantic_none semantic_passes \
  --repeats 3 --warmups 1 --output /private/tmp/new-semantic-pass-comparison
```

Record compile wall/CPU, final MB bytes/hash and target runtime wall/CPU/steps
together. Include load/hardware context and source fingerprints. Warmups are
stored separately; OS caches are not forcibly flushed. Complete-repeat
intersections determine paired comparisons. A whole-child timeout has no VM
timing/step result; step-limited executions retain diagnostics but no completed
runtime sample. Do not sum shared compilation cost across workloads.

These measurements do not normalize hardware or background activity. Candidate
passes with correctness failures or unacceptable tradeoffs remain explicit
experiments. New layout/dispatch protocols and dynamic multiplication helper
redesign still require their separate invariant/termination investigations.
