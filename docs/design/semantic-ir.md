# Python frontend and semantic IR

> **English** | [中文](semantic-ir.zh.md)
>
> Status, 2026-10-09: the direct AST frontend, structured semantic dialect,
> independent execution oracle and explicit target adapter are implemented.
> Optimizing passes, full source-variable SSA and direct semantic-to-LAL
> lowering remain future work. This is an architecture milestone, not a
> performance result.

## 1. Two explicit frontend paths

The semantic path constructs IR before generating MG or MC:

```text
Python AST → shared normalization and source checks → pysem semantic IR
  → verified semantic passes → explicit target adapter → MG → MC
  → LAL IR → verified LAL passes → MC → existing assembler → MB
```

The adapter reconstructs ordered Python AST from the supplied semantic IR and
uses the existing direct backend to generate MG. It does not reuse original
source or store an AST inside an opaque IR operation. Editing semantic IR
changes downstream code and execution. A future target lowering can replace
the adapter without replacing this frontend.

The existing `--backend=ir` default retains `--ir-frontend=compat`, the original
direct→MG→MC→LAL bridge. Select the new frontend with
`--ir-frontend=semantic`. Requesting `--emit-semantic-ir` selects it implicitly
unless an incompatible frontend was explicitly selected. There is no silent
fallback when semantic source validation fails. Base C/direct paths retain
their optional-dependency independence.

```sh
uv sync --extra dev --extra ir
uv run --no-sync python -m malbolge compile demo.py --backend=ir \
  --emit-semantic-ir /private/tmp/demo.semantic.mlir
uv run --no-sync python -m malbolge compile demo.py --backend=ir \
  --ir-frontend=semantic --emit-ir /private/tmp/demo.lal.mlir \
  -o /private/tmp/demo.mb --stats
```

Both use the pinned optional xDSL environment and Python 3.10+. A frontend-only
IR export does not invoke the target adapter or generate MG/MC/MB.

The retained [example IR](../notes/semantic-ir-example.mlir) comes from:

```python
def next_byte(value):
    return value + 1
byte = getchar()
putchar(next_byte(byte))
```

The independent oracle and a real compiled MB both consumed `A` once and
output `B`. The file contains structured functions, slots, SSA arithmetic,
the call and I/O, with original source locations.

## 2. Representation and effect contracts

`pysem.word` has exactly 20 trits. Values lie in `[0, 3**20)`; addition,
subtraction and multiplication wrap in that domain. Floor division/modulo are
checked operations, with zero-divisor effects retained. The frontend does not
fold or strength-reduce valid arithmetic: `n * 17` remains a multiplication.

Expression results use SSA. Source variables remain explicit local/global
slots with load/store operations. Thus this milestone does not provide full
variable SSA, phi construction, whole-program liveness or an optimizer.
Program globals start at zero; locals require an executed binding. Parameters
are word-valued block arguments stored in their source slots.

| Structure | Represented semantics |
|---|---|
| Program/functions | Entry, declarations, parameters, locals, explicit globals and word/void/optional return contracts |
| Constants, loads/stores, binary/unary operations | Values separated from mutable locations; no implicit reevaluation |
| Boolean and comparison regions | Lazy operands, operand-returning `and`/`or`, single evaluation of chained middle operands |
| Conditional expressions and statements | Only the selected branch executes; values cannot leak across regions |
| While/range loops | Reevaluated condition region, captured range bounds, separate iterator state, signed constant step and descending `stop=-1` sentinel |
| Call/return/break/continue | Ordered actual values, direct symbols, explicit control transfer and loop scope |
| Byte and decimal I/O | `getchar`/`putchar`, literal/word output, checked decimal input with literal prompts |
| Unbound-name trap | Explicit effect for accepted statically unreachable unknown reads; never a fabricated zero-valued variable |

Memory, calls, I/O and checked errors are not advertised as pure. Statements
and expression producers execute in order. A later pass must preserve these
effects; structural verification alone cannot prove semantic equivalence.
The verifier checks word types/ranges, lexical SSA dominance, scope, arity,
region yields, control placement and reachable return contracts. Source
locations survive printed IR and reloading.

The frontend uses CPython's syntax/symbol-table check, the shared normalizer
and AST-only diagnostic analyses. It does not instantiate or run the old
compiler to generate its IR. Flat tuples, basic print f-strings and keyword
binding become explicit, ordered semantic operations.
The AST-only analyses are currently method aliases from the direct frontend;
extracting them into a shared source-analysis module remains an architectural
cleanup, separately from target lowering and optimization.

## 3. Inspection and independent execution

Lazy APIs in `malbolge.compiler.ir` include:

| API | Purpose |
|---|---|
| `compile_python_to_semantic_ir(source)` | Verified source IR before target code generation |
| `compile_python_semantic_result(source, passes=None, snapshots=False)` | Semantic pass result, clone, reports and optional snapshots |
| `print_semantic(module)` / `parse_semantic(text)` | Deterministic inspectable IR, including source locations |
| `run_semantic(module, input_data=b'', ...)` | Independent dispatch of semantic operations, with operation/call/depth/output budgets |
| `lower_semantic_to_python_ast(module)` / `lower_semantic_to_mg(module)` | Authoritative compatibility representation / target MG |
| `compile_semantic_to_mc(module, ...)` | Adapter plus verified LAL target pipeline |

The oracle uses neither Python `exec`/AST reconstruction nor the old compiler
or target VM. It reports bytes, input consumption, globals, return value and
stop/budget/error status. Text input is UTF-8 encoded, as in the bounded target
VM; literal output uses the subset's byte-codepoint contract. Runtime decimal
input/division failures emit `error\n` once and stop the entry. Its operation
counts are oracle budgets, not Malbolge steps or performance measurements.

Semantic and LAL pass registries are separate. Initially they provide only
`verify-semantic` and `verify-lal`. The shared runner verifies input and every
pass output, cloning by default. Semantic reports contain IR bytes/counts and
digests, with no invented MC/MB cost before lowering. `--semantic-passes`
selects semantic passes; `--passes` continues to select LAL passes. Cache
identity includes frontend and both ordered selections. Cache hits report
their origin without pretending passes were executed again.

## 4. Compatibility limits and validation

The semantic frontend implements the documented scalar/control/I/O forms, but
it is deliberately opt-in while acceptance boundaries are being migrated:

- Unsupported syntax is rejected even inside statically dead branches. The
  legacy frontend sometimes skips such syntax while emitting a constant branch.
- A read before a local binding is rejected even if a module global has the
  same name; the legacy analysis can admit that case. Implicit function-global
  reads still require a module-bound name. Function-global writes only declare
  storage and do not extend implicit read admission.
- Constant zero-division source errors retain their original source location;
  dynamic division/input errors remain runtime operations. Explicit traps
  preserve supported unknown-name reads in accepted unreachable regions.
  Reaching such a trap after an IR edit raises a semantic execution diagnostic;
  it is not a fabricated value or a newly accepted reachable source read.
- The adapter introduces fresh captures, name mappings and an entry wrapper.
  It may produce different/larger target artifacts. Byte identity and speedup
  are not acceptance claims. Only domain-valid AST executions serve as a
  CPython cross-check; the IR oracle specifies ring and error behavior.
- Target protocol/layout still uses the existing MG/MC machinery and its
  documented LAL resolver limitations. Direct semantic→LAL and LLVM/MLIR
  adapters remain unimplemented.

Tests cover source IR without legacy generation, fixed workload outputs,
source-located diagnostics, mutation authority, ordered/lazy effects,
serialization and pass failures, plus representative real MB execution.
Machine-readable scope is in
[`semantic-ir-validation.json`](../notes/semantic-ir-validation.json).

This supplies a place for future analyses and backend-specific lowering.
Optimization candidates remain deferred until their separate semantic and
compile-size-runtime acceptance work is authorized.
