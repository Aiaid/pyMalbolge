# py→.mg Direct Backend (py2mg) Design Document

> [中文](py2mg-backend.zh.md) | **English**

> Module: `malbolge/compiler/py2mg.py`, exposing `compile_python_to_mg(source) -> str`.
> Wiring: `compile_python_to_mb(py, backend="direct")`, CLI `--backend=direct`.
> Compiled: 2026-07-21. This document describes **v0** (strictly aligned with the py2c v1 language
> subset; no new language features are added).

## 1. Motivation

The existing pipeline is two stages: Python --`py2c`--> Nagoya C subset --`c2mg`--> `.mg`. The C
layer exists to reuse the Nagoya reference compiler, but it imposes a batch of overhead that
**exists only to work around defects in the C subset** (see `docs/findings.md`):

- **Three-address expansion**: because the C subset has no operator-precedence handling of its own
  and the upstream bool type is broken, py2c splits every expression into three-address form and
  materializes bools as int 0/1, producing a large number of intermediate locals and copies.
- **"Every function treated as recursive"**: `c2mg` faithfully mirrors the reference
  implementation and hardcodes `is_recursive` to `True` (`check_recursive_call` computes real
  reachability and then discards it), so **every** function — including leaf functions, the
  injected `zzmul`/`zzdiv`/`zzmod`, and `main` — pays the full push/pop stack-protection cost.
- **Shared global temp pool → double-recursion bug (A2)**: `get_temporary_variable` always inserts
  into the global variable table (one shared FIFO free-list), and push/pop protection
  **excludes** temporaries, so an intermediate result held in a temp across two sibling recursive
  calls within one expression gets clobbered by the inner call.

The direct backend skips the C layer and emits `.mg` straight from the Python AST, changing only
the **frame strategy** while **reusing all of c2mg's validated codegen primitives** (arithmetic
`add`/`sub`, comparisons `lt`/`eq`/`not_`, `inc`/`dec`, logical `and`/`or`, stack `push_stack`/
`pop_stack`, `SWITCH`-based `if`/`while`, the call ABI). Because the arithmetic/comparison/call
sequences are byte-for-byte reused from c2mg, direct output is **computationally identical** to
the C path; the size difference comes only from the frame strategy and the removal of C-layer
overhead.

## 2. Reuse vs. Differences Overview

| Aspect | C path (py2c + c2mg) | Direct (py2mg) |
|---|---|---|
| Front end | Python→C (AST→C text), then C→.mg (re-lexed/re-parsed) | Python AST directly →.mg |
| Arithmetic/comparison/logic/call-ABI primitives | Implemented by c2mg | **Reused verbatim from c2mg's methods** |
| Three-address expansion | Always done | Not done (expressions evaluate naturally nested) |
| Bool materialization to int | Always done (control flow materializes 0/1) | Only in **value context**; `if`/`while` conditions feed `SWITCH` directly |
| Temp ownership | Global shared pool, declared as global `VAR` | **Private per function**, declared inside that function's `DEF` |
| Recursion determination | Hardcoded all `True` | **Real cycle detection**, only functions in a cycle are recursive |
| Frame-protection scope | Every function's non-static, non-temp locals | Only recursive functions: non-static locals **+ temps live across calls** |
| Multiply/divide/mod helpers | Injected by py2c as C functions, compiled by c2mg | **Lazily injected** as `.mg` routines from the same Python subset (only injected when actually used) |

## 3. Frame Layout and Call ABI

The call convention from c2mg (already verified byte-for-byte on 36/36 cases plus e2e) is reused
as-is, so the call/return/recursion-stack mechanism is isomorphic to the C path:

- **`.mg` routines take no parameters and return no value at the call-instruction level**; data is
  passed through global slots: the caller `copy`s the i-th actual argument into
  `ARG{i}@callee`, issues `CALL`, then `copy`s `RETURN_VALUE@callee` into a temp to obtain the
  result.
- At routine entry, `ARG{i}` (a static slot) is `copy`d into the parameter local; `return e`
  `copy`s `e` into the routine's own `RETURN_VALUE` (a static slot) and then `RETURN`s.
- **Single `RETURN_ADDR` slot + recursion stack**: `.mg`'s `RETURN` has only one `RETURN_ADDR`
  slot, so re-entry overwrites it. For **recursive callees**, `push_stack`/`pop_stack` around the
  `CALL` site save/restore `RETURN_ADDR@callee` (this is the 2017-paper mechanism; c2mg's
  `Block.generate` CALL handling already conditions on `f.is_recursive`, and the direct backend
  reuses it as-is). **Non-recursive callees produce no `RETURN_ADDR` saving at all** — a direct
  saving relative to the C path.

### 3.1 Per-Function Temporaries (the Key Structural Change)

The direct backend declares temporaries as **locals inside their owning `DEF`** (`TMP0`,
`TMP1`, ...) rather than globally. It has been empirically confirmed that `mg2mc` allocates
addresses for same-named local `VAR`s in different routines **independently per routine** (two
routines each writing `VAR a=…` end up as two distinct cells at runtime). Consequently:

- **Non-recursive cross-function calls are inherently safe**: if there is no cycle in the call
  chain, any functions simultaneously present on the stack are **distinct**, and their temps
  occupy **distinct** addresses that never collide — **no frame protection is needed at all**.
  This is the exact justification for "protect only recursive functions."
- Because c2mg's temps are globally shared, any cross-function call could theoretically collide,
  forcing full protection everywhere; the direct backend's per-function temps remove this
  precondition **at the mechanism level**.

### 3.2 Recursion Determination and Protection Scope

`check_recursive_call` is rewritten to use **real reachability**: a function is recursive iff it
can reach itself in the call graph (self-recursion or a mutual-recursion cycle). Only these
functions emit push/pop at entry/exit; the protected set is:

```
protect(F) = { F's non-static, non-temp locals } ∪ { temps live at some CALL site in F }
```

"Temps live across calls" is determined by **precise liveness tracking**: while lowering
expressions, a `_live` stack is maintained, and any temp held during evaluation of a subexpression
that may contain a `CALL` is recorded into `_cross_call_temps` for the function containing that
call. So in `fib(n-1)+fib(n-2)`, the temp holding the result of `fib(n-1)` gets registered as
live-across-call at the second `CALL` site → it is included in `FIB`'s entry/exit protection → the
inner recursive call pushes that cell along with everything else at its own entry (preserving the
outer activation record's value) and pops it back at exit. **Double recursion is therefore correct
at the mechanism level, not by dodging the issue via three-address rewriting** (the A2 fix; see
§5).

The temporary cells used by the push/pop machinery itself are allocated **fresh, after clearing
the free-list**, when generating the protection code, guaranteeing their names never fall inside
the already-snapshotted `protect(F)` (i.e., a cell is never written to at the same time it is
being pushed).

### 3.3 Generation Order

Mirrors `c2mg.parse_program`: first generate all routine bodies into a single `Generator` (this
process creates the new temps and new constants used by push/pop, and appends the flags they need
to `self.flags`), **then** emit the header (sorted global `VAR`s → `FLAG` → sorted `PROTO`),
finally concatenating everything. This way, per-function temps created during generation land
inside their own `DEF`, and new global constants/flags are picked up by the header. `main` can
never be called → never part of a cycle → **never protected**; for non-`main` routines whose body
doesn't end in `return`, an implicit `return 0` is appended (avoiding falling through to the
auto-appended `END`, which would terminate the whole program prematurely — see mg-spec §4.8).

## 4. Language Subset and v0 Trade-offs

Strictly aligned with py2c v1: int variables and arithmetic (`+ - * // %`, constant folding
mod 3^20), `while`, `if`/`elif`/`else`, `for`-`range`, chained comparisons, boolean `and`/`or`/
`not`, function definitions/calls/`return`, recursion (including double recursion and mutual
recursion), `putchar`/`getchar`/`ord`. Known v0 trade-offs (recorded in the module docstring):

- **`and`/`or` are non-short-circuiting**: reuses c2mg's bitwise `_logical_and`/`_logical_or`,
  which always evaluates both sides. This diverges from Python semantics only when a boolean
  operand **has side effects**; in the tested subset all boolean operands are pure value
  comparisons, so output is unaffected.
- Function names follow c2mg's convention of **uppercasing** (`fib`→`FIB`); locals get a `u_`
  prefix. Name-validity checks match py2c (rejecting the `zz` prefix, C keywords, and reserved
  `main`/`putchar`/`getchar`).

## 4.1 Diagnostic Contract (aligned with `docs/python-subset-spec.md` §3; does not replicate py2c's defects)

py2mg is a **brand-new front end** (it does not reuse py2c's AST-processing code), so it can
directly avoid the silent-mistranslation (class C) defects recorded in `tmp/subset-spec/defects.md`.
Every rejection raises `Py2MgError`, carrying an accurate `lineno` and source snippet from the
**original Python source**, with no bare traceback:

| Defect | py2c behavior | py2mg behavior |
|---|---|---|
| C1 top-level `return` | Silently accepted (dead-code judgment) | Rejects `'return' outside function` (the `_is_main` branch of `_stmt_Return`, not a dead-code check) |
| C2 bare-annotation-then-read `x: int` | Silently zero-initializes | Bare annotation does not bind (`_collect_assigned`); reading raises `name 'x' is not defined` |
| C3 uninitialized `x += 1` | Silently zero-initializes | Definite-assignment analysis raises `name 'x' may be used before assignment` |
| C4 decorators | Ignored | Rejects `function decorators are unsupported` |
| C5 `global x` with parameter named `x` | Silently accepted | Rejects `name 'x' is parameter and global` |
| D6-D9 read after assignment inside a conditional/loop | No definite-assignment analysis, silently mistranslated | **Flow-sensitive definite-assignment analysis**: `if` takes the intersection of both branches' bindings; bindings made inside a `while`/`for` body do not count as bound after the loop; raises `may be used before assignment` |
| D13 function named `print`/`range`/`ord`/`chr` | Can be defined; calls are misrouted by the builtin-dispatch branch | Rejected at registration time: `collides with a builtin` |

**Definite-assignment analysis** (`_check_definite_assignment`) is a simple flow-sensitive pass
mirroring CPython's rule: a name's read must be bound on **every path that reaches that read**.
`if`/`else` takes the intersection of the two branches' binding sets (if a branch always
`return`s, only the other branch's set is used); `while`/`for` bodies may execute zero times, so
assignments made inside the loop body do not count as bound after the loop (likewise for the `for`
loop variable). Functions may read a global that is "assigned later at module level" (it is bound
at call time at runtime, consistent with CPython), so forward references to globals are not
falsely rejected.

## 5. Mechanism-Level Fix for the A2 Double-Recursion Bug (Verified)

`return fib(n-1) + fib(n-2)`: the direct backend does **not** perform three-address rewriting and
evaluates naturally nested — the return value of `fib(n-1)` is held in temp `t`, and `_live` keeps
`t` live while evaluating `fib(n-2)`, so the second `CALL FIB` site registers `t` into `FIB`'s
cross-call protection set. Running the direct-backend output for `fib(5)` produces output `A`
(fib(5)=5, +60), matching expectations — double recursion is correct. Compare
`docs/findings.md` §A2: the hand-written C inline double recursion was mistranslated upstream
(fib(4)=2), whereas the direct backend eliminates this bug at the mechanism level, with no
dependence on py2c's three-address guard.

## 6. Size Comparison Data

Method: each test case is generated to `.mg` via both paths, then assembled to `.mb` via
`scripts/mg2mb.sh -s 1` (the ref toolchain), and run with both the reference C interpreter and
pyMalbolge. **Output is byte-exact** (the `out` column below); the `.mb` bytes themselves are not
required to match.

| Case | `.mg` lines c / direct | `.mb` bytes c / direct | direct/c | Outputs match across backends |
|---|---|---|---|---|
| putchar_hi | 20 / 19 | 585,997 / 585,151 | 1.00 | ✓ `Hi` |
| echo_getchar | 113 / 34 | 5,065,849 / 1,258,379 | **0.25** | ✓ `Q` |
| if_else | 269 / 108 | 12,125,907 / 4,695,019 | **0.39** | ✓ `Z` |
| for_range | 586 / 253 | 27,335,859 / 11,912,339 | **0.44** | ✓ `ABC` |
| while_countdown | 619 / 287 | 28,927,937 / 13,604,715 | **0.47** | ✓ `CBA` |
| multiply_folded | 14 / 13 | 383,803 / 382,957 | 1.00 | ✓ `A` |
| recursion_single | 1,790 / 802 | 81,805,475 / 37,875,891 | **0.46** | ✓ `A` |
| recursion_fib (**double recursion**) | 2,407 / 1,201 | 110,468,331 / 56,839,263 | **0.51** | ✓ `A` |
| runtime_multiply | 2,495 / 1,283 | 115,190,985 / 61,438,401 | **0.53** | ✓ `0` (note) |
| runtime_divmod | 3,389 / 1,806 | 156,944,657 / 86,842,371 | **0.55** | ✓ `CC` |
| mutual_recursion | 2,674 / 1,251 | 121,641,641 / 58,327,753 | **0.48** | ✓ `A` |

> `.mb` byte counts were collected by assembling with `scripts/mg2mb.sh -s 1` (the ref toolchain)
> and running on the reference C interpreter; putchar_hi and echo_getchar were additionally
> cross-checked on pyMalbolge, and the double-recursion case recursion_fib was also run directly
> on pyMalbolge to confirm output `A`. The `out` column means **the two paths' own runs produce
> byte-identical output**.

**Summary**:

- The direct path's `.mb` is **no larger than** the C path's on every tested case; cases with
  control flow/functions/recursion are typically **40-75% smaller**.
- Main sources of savings: (a) real recursion analysis — non-recursive functions (including
  `main`, `zzmul`, etc.) get **zero** push/pop; (b) `if`/`while` conditions feed `SWITCH`
  directly, avoiding py2c's bool→int 0/1 control-flow materialization; (c) no three-address
  intermediate locals or copies.
- The two cases with **near-parity** size (putchar_hi, multiply_folded) have no function calls,
  no control flow, and a folded multiplication, so both paths generate nearly identical primitive
  sequences — as expected.
- **Lesson from `multiply_folded`**: an early implementation pre-scanned the AST and injected the
  helper whenever `* // %` appeared anywhere, so `9*7` — even though it got constant-folded away —
  still injected 1000+ lines of `ZZMUL` for nothing (`.mb` briefly hit 49.7 MB). Switching to
  **lazy injection** (only registering the helper for compilation when a call to it is actually
  emitted) brought it back down to 382 KB, on par with the C path.
- Note: `runtime_multiply` (`n*m+48-42`, n=6, m=7) produces `'0'` (=48) on both backends,
  byte-identical between them; this is in fact the correct value (the expected byte in the
  collection script had erroneously been written as `T`, unrelated to the program itself).

## 7. Acceptance

- Unit tests: `test/test_py2mg.py` (generated structure, recursion analysis, frame strategy,
  mg2mc acceptance, error rejection), 27 cases, pure Python with no external dependencies.
- Dual-backend differential e2e: `test/test_py2mg_e2e.py`, each case compiled to `.mb` via both
  paths and run, output byte-exact (including double-recursion fib and mutual recursion). Uses a
  fast build path when the ref toolchain is available.
- Zero breakage to existing behavior: `--backend` defaults to `c`, `compile_python_to_mb` defaults
  to `backend="c"`; py2c/c2mg/mg2mc/mc2mb are unchanged.

## 8. Open Issues / Future Work

- **`and`/`or` short-circuiting**: v0 is non-short-circuiting; semantics diverge from Python in
  scenarios with side-effecting operands (see §4). v1 could materialize short-circuiting via
  nested `SWITCH`.
- **Tightening the protection set further**: currently a recursive function protects "all
  non-static locals"; a liveness analysis restricted to "only locals live across calls" could
  further shrink recursive-function size (temps are already precise; locals are still
  conservative).
- **mg+ array dialect**: out of scope for v0; a hook for the direct backend is reserved for the
  array phase (`IND_OPR`-based hand-written stack/indexing).
