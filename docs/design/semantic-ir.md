# Python frontend and semantic IR

> **English** | [中文](semantic-ir.zh.md)
>
> Status, 2026-10-09: the direct AST frontend, structured semantic dialect,
> independent execution oracle and explicit target adapter are implemented.
> Accepted optimization passes are now available; full source-variable SSA
> and direct semantic-to-LAL lowering remain future work. Performance evidence
> is tracked separately from this architecture contract.

> Documentation-only checkpoint: the target-interface API described below is
> a locally tested, uncommitted prototype. This commit records its design and
> validation, not compiler integration or performance parity with direct.

## 1. Two explicit frontend paths

The semantic path constructs IR before generating MG or MC:

```text
Python AST → shared normalization and source checks → pysem semantic IR
  → verified semantic passes → explicit target adapter → MG → MC
  → LAL IR → verified LAL passes → MC → existing assembler → MB
```

The committed adapter reconstructs ordered Python AST from semantic IR,
serializes generated Python and uses the direct backend to generate MG. The
local target-interface prototype instead passes Python-shaped target AST
directly, removing the text round trip. Neither path reuses original source
or stores an AST inside an opaque IR operation. Editing semantic IR
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
  --opt-level 0 --emit-semantic-ir /private/tmp/demo.semantic.mlir
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
checked operations, with zero-divisor effects retained. The raw frontend does
not fold or strength-reduce valid arithmetic: `n * 17` remains a multiplication
before explicitly selected/default optimization passes.

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
| `lower_semantic_to_target_ast(module)` (local prototype) | Explicit backend contract preserving generated-local roles and loop condition preludes |
| `compile_semantic_to_mc(module, ...)` | Adapter plus verified LAL target pipeline |

The prototype backend contract lives in the uncommitted local
`compiler/target_ast.py` and has no xDSL
dependency. `TargetAST` carries generated local names explicitly per function;
`TargetWhile` carries ordered `condition_prelude` statements evaluated before
every test. Names are never classified by a prefix. Generated locals remain
ordinary stored variables protected by recursive frames, not allocator
temporaries. All ordinary syntax and definite-assignment checks still run.

`compile_target_ast_to_mg` accepts the structured contract. The independent
`skip_generated_initialization` and `structured_while` controls also exist on
`lower_semantic_to_mg` for representation comparisons: the former omits only
generated-local entry zero copies, and the latter avoids synthetic body breaks.
Source slots, parameter copies, source break/continue and error propagation
retain their contracts. The source Python entry remains separate.

`native_conditions` is a third, independent adapter control. A terminal
single comparison used only by the condition-region yield can become a
native predicate. Prefix and left/right operand computations still execute
in order using captured SSA values. Chained comparisons, additional uses and
other condition producers keep their word representation. Comparisons used
as numbers still produce 0/1; no boolean hint is trusted without inspecting
the current verified graph.

The local prototype enables all three interface controls. Passing all three as false
retains the legacy target representation for explicit comparisons; this does
not disable semantic optimization passes. Decimal algorithm selection remains
independent: the experimental decimal pass is not part of the default profile.

The structured target AST is not an ordinary executable Python AST: CPython
does not execute its extra prelude field. Use `to_legacy_ast` to explicitly
expand it for display or an ordinary-domain Python oracle, or use the original
`lower_semantic_to_python_ast` view. The semantic interpreter remains the
complete word/effect/error reference.

The oracle uses neither Python `exec`/AST reconstruction nor the old compiler
or target VM. It reports bytes, input consumption, globals, return value and
stop/budget/error status. Text input is UTF-8 encoded, as in the bounded target
VM; literal output uses the subset's byte-codepoint contract. Runtime decimal
input/division failures emit `error\n` once and stop the entry. Its operation
counts are oracle budgets, not Malbolge steps or performance measurements.

Semantic and LAL pass registries are separate. The semantic default is the
accepted [optimization profile](semantic-optimization-passes.md); level 0
selects only `verify-semantic`, while LAL defaults to `verify-lal`.
The shared runner verifies input and every
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
