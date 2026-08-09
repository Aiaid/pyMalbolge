# pyMalbolge Python Subset v1 Specification

> [中文](python-subset-spec.zh.md) | **English**

> Object of specification: `malbolge/compiler/py2c.py` (the front-end that
> translates the Python subset into the Nagoya high-level C subset, function
> `compile_python_to_c`). This document treats the **source-level behaviour** of
> that file as the single source of truth and checks every clause against it; it
> does not settle for the overview-level description in
> `docs/design/highlevel-to-malbolge.md` §5.
> Version: v1 (state at commit `02c0b82`, 957 lines). The diagnostic audit
> methodology and its full results are in the appendix.

## 0. Terminology and scope

- "accept": `compile_python_to_c(source)` returns a string (C source) without
  raising.
- "reject": raises `malbolge.compiler.CompileError`, carrying `lineno`/`col`
  and a readable `message`, and leaks no native Python traceback.
- This document covers **only the py2c front-end stage**. The downstream stages
  `c2mg.py` (→ .mg), `mg2mc.py` (→ .mc) and `mc2mb.py` (→ .mb) have their own
  error types (`C2MgError` etc.) and fall outside this specification. The
  diagnostic audit in the appendix does, however, flag cases where "py2c ought
  to have rejected the input but instead passed the error downstream", because
  that directly determines whether the user can make sense of the error.
- "value ring" refers to Malbolge20's arithmetic ring: every integer is reduced
  modulo `3**20` (`MOD = 3486784401`). It is a ring of non-negative integers
  with no notion of negative numbers.

---

## 1. Accepted set

### 1.1 Module-level (top-level) statements

`compile()` (`py2c.py:860-931`) dispatches on each top-level statement of
`ast.parse(source).body`:

| Top-level statement form | Handling |
|---|---|
| `ast.FunctionDef` | Registered as a user function (see §1.3); MUST NOT appear inside the synthesized `main()` |
| `Expr(Constant(str))` that is the **first** matching statement in the file | Module docstring, skipped (no code generated); in practice, however, this `elif` swallows *any* top-level string-constant expression statement, not just the first one — see the divergence table in §2 |
| `ast.Import` / `ast.ImportFrom` | Rejected: `"'import' is unsupported"` |
| `ast.ClassDef` | Rejected: `"class definitions are unsupported"` |
| Any other statement | Collected into `module_body` and compiled statement by statement as the body of the synthesized `main()` (subject to the statement subset in §1.2) |

A top-level function named `main` is not allowed (the compiler synthesizes
`main()` itself): `"define top-level code directly, not a main() function ..."`.

### 1.2 Statements

`compile_stmt` (`py2c.py:531-536`) looks up a `_stmt_<TypeName>` method by node
type name; if none is found the input is rejected (`"unsupported statement:
{TypeName}"`). The **implemented** (i.e. accepted) statement types are listed
below, each with its restrictions:

| AST node | Method | Accepted forms and restrictions |
|---|---|---|
| `Assign` | `_stmt_Assign` | Targets MUST all be bare `ast.Name` (otherwise reported by target type name: "unsupported assignment target: {Tuple|Attribute|Subscript|...}"); chained `a = b = c = expr` is supported (evaluated once, copied to the remaining targets) |
| `AnnAssign` | `_stmt_AnnAssign` | Target MUST be an `ast.Name`; the annotation itself is **entirely ignored** (no type checking); the bare form `x: int` with no initializer only declares and does not validate binding state (see divergence D9 in §2) |
| `AugAssign` | `_stmt_AugAssign` | Target MUST be a bare `ast.Name`; operators limited to `+= -= *= //= %=` (anything else reports "unsupported augmented operator"); `/=` gets its own "true division ... unsupported" message |
| `Expr` | `_stmt_Expr` | Only two valid payloads: a `putchar(x)` call (single argument, no keyword arguments) and any expression `lower()` accepts (evaluated, result discarded — including the pure no-op of a bare literal or bare variable name) |
| `If` | `_stmt_If` | `test` goes through condition materialisation (§1.4); `elif` is a nested `If` at the AST level and is therefore supported for free |
| `While` | `_stmt_While` | `while...else` is not supported (rejected); the condition is evaluated once at loop entry and once at the end of each iteration of the body |
| `For` | `_stmt_For` | Only the form `for <Name> in range(...)`; `for...else` is not supported; `range()`'s `start`/`stop` MAY be arbitrary expressions, but `step` MUST be a **compile-time positive integer literal** (`ast.Constant(int)`, non-negative, not a bool) |
| `Return` | `_stmt_Return` | A valueless `return` emits `return 0;`; a `return` with a value emits `return <expr>;`; **the "return outside a function" check is dead code — see semantic divergence D10 in §2** |
| `Pass` | `_stmt_Pass` | no-op |
| `Global` | `_stmt_Global` | MAY only appear inside a function body (the synthesized `main()` also counts as "inside a function body", so a module-level `global x` is syntactically accepted and semantically a no-op — see §2); **does not check whether the name collides with a parameter** (divergence D12 in §2) |
| `Break` | `_stmt_Break` | **Accepted since batch 1 (2026-07-23)**: only inside a loop body (`while`/`for`), implemented by flag lowering (each loop containing break/continue is given two flags, `skip` and `brk`, and every statement in the loop body is wrapped in an `if(skip==0)` guard); nested loops get independent flags, and `break` terminates only the innermost loop and skips the `for` step; use outside a loop is rejected: `"'break' outside loop"` |
| `Continue` | `_stmt_Continue` | As above; `continue` skips the rest of the current iteration, but the `for` step **still executes**; rejected outside a loop |
| `FunctionDef` (nested) | `_stmt_FunctionDef` | Unconditionally rejected: `"nested function definitions are unsupported"` |

Statement types not in the table above (nested `ClassDef`, nested
`Import`/`ImportFrom`, `Try`, `With`, `Assert`, `Delete`, `Raise`, `Match`,
`AsyncFunctionDef`, `TypeAlias`, etc.) all fall to `compile_stmt`'s generic
rejection branch: `"unsupported statement: {TypeName}"`.

### 1.3 Function definitions (`ast.FunctionDef`, top level)

`_register_function` (`py2c.py:933-947`) + `_compile_function`
(`py2c.py:811-858`):

- Only **simple positional parameters** are accepted: if any of
  `node.args.vararg` (`*args`), `kwarg` (`**kwargs`), `kwonlyargs` (`*, x`),
  `posonlyargs` (`x, /`), `defaults`/`kw_defaults` (default values) is
  non-empty, the definition is rejected: `"only simple positional parameters are
  supported ..."`.
- Both the function name and the parameter names MUST pass `check_var_name`
  (identifier rules, §1.6).
- Function names undergo a **case-insensitive uniqueness check**: two Python
  function names that are identical once upper-cased collide
  (`"function {!r} collides with {!r} (function names are case-insensitive in
  the target backend)"`), because the downstream backend upper-cases all
  function names.
- A function name whose upper-cased form lands in `RESERVED_FUNCS = {"MAIN",
  "PUTCHAR", "GETCHAR", "ZZMUL", "ZZDIV", "ZZMOD"}` is rejected; note, however,
  that the **lower-case originals** `main`/`putchar`/`getchar` are intercepted
  earlier by `check_var_name` (via `C_KEYWORDS`), so for those three
  `RESERVED_FUNCS` only fires on **case variants** (e.g. `Main`, `PUTCHAR`) —
  see the audit entry `sem_func_named_main_case_variant` in the appendix.
- Redefining the same function name is rejected: `"function {!r} is already
  defined"`.
- **Not checked**: parameter/return type annotations (ignored outright, neither
  validated nor reported), `decorator_list` (entirely ignored, divergence D11 in
  §2), `is_async` (`AsyncFunctionDef` is a distinct node type that does not match
  `ast.FunctionDef` and therefore falls to the generic statement rejection of
  §1.2).
- The statement subset inside a function body is the same as §1.2; nested `def`
  is not allowed (already listed in §1.2).
- All user functions are registered **before** any function body is compiled, so
  mutual calls are not constrained by definition order in the source (including
  direct and indirect recursion); the generated C source emits a forward
  prototype for every user function.

### 1.4 Expressions

`lower()` handles the following node types, expanded as described below. Node
types not listed here (`List`, `Dict`, `Set`, `Tuple`,
`ListComp`/`SetComp`/`DictComp`/`GeneratorExp`, `Lambda`, `Attribute`,
`Subscript`, `Slice`, `Starred`, `NamedExpr`, `Yield`/`YieldFrom`, `Await`,
etc.) all fall to the generic rejection: `"unsupported expression:
{TypeName}"`. `JoinedStr` (f-string) is the one exception: it is accepted
**only in `print()` argument position** (all parts MUST be compile-time
constants, see §1.7); everywhere else it keeps the "unsupported expression:
JoinedStr" rejection.

| AST node | Accepted form |
|---|---|
| `Constant` | See the constants sub-table in §1.5 |
| `Name` (`Load` context) | Accepted once it passes `check_var_name`; **binding is not checked** (divergences D6/D7/D8/D9 in §2); other contexts such as `Store`/`Del` reaching this point report "unsupported name context" (a theoretical branch — in practice assignment targets take separate paths such as `_stmt_Assign` and never come through here) |
| `BinOp` | See the operator sub-tables in §1.5; constant expressions that can be folded at compile time are folded directly into integer literals (mod 3**20), otherwise the expression is lowered to three-address form (at most one binary operation) |
| `UnaryOp` | `+x` returns `lower(x)` unchanged; `not x` goes through condition materialisation; `-x`/`~x` are rejected (see §1.5) |
| `BoolOp` (`and`/`or`) | Condition materialisation, short-circuit evaluation, implemented with nested `if/else` |
| `Compare` | Condition materialisation; comparators limited to `< <= > >= == !=` (see §1.5); chained comparisons `a < b < c` are supported (lowered to `(a<b) && (b<c)`, each operand evaluated exactly once); `is`/`is not`/`in`/`not in` are rejected while iterating `node.ops`, i.e. **before any operand is lowered**, so an illegal operand cannot produce an unrelated error message |
| `Call` | See the built-ins in §1.7 and user function calls in §1.3 |
| `IfExp` (`a if c else b`, new in batch 1) | Materialised as a temp plus a real two-branch `if/else`, with **lazy evaluation**: only the side effects of the selected branch (e.g. function calls) occur |

**Condition materialisation**: any expression with boolean semantics
(comparisons, boolean operations, `not`, the `test` of `while`/`if`) is never
stored into a variable as a "comparison result value". Instead, control flow of
the shape `flag = 0; if(cond){ flag = 1; }` materialises the result into an
`int` variable taking the value 0 or 1. This works around the known breakage of
the downstream C subset's `bool`/`true`/`false` type system (see
`docs/design/highlevel-to-malbolge.md` §5, "Implementation notes").

### 1.5 Constant and operator sub-tables

**Constants (`ast.Constant`)**, `_const()` (`py2c.py:261-278`):

| Python value type | Handling |
|---|---|
| `bool` (`True`/`False`) | Folded to the integers `1`/`0` (no `bool`/`true`/`false` is emitted, see §2) |
| `int`, `v >= 0` | Folded to `v % MOD` |
| `int`, `v < 0` | Rejected (see the "negative numbers" paragraph below) |
| `str` | Rejected in general expression position: `"string literals are unsupported ..."`. **Two exceptions** (batch 1): the single-character argument of `ord('c')`; string literals in `print()` argument / `sep=` / `end=` position (expanded at compile time, see §1.7). See also the docstring position rule in §1.2: the first bare string of a module or function body is silently ignored |
| `float` | Rejected: `"floating-point values are unsupported"` |
| Others (`bytes`, `complex`, `Ellipsis`, `None`, …) | Rejected, falling to the generic branch `"unsupported constant: {!r}"` |

**Binary operators (`ast.BinOp.op`)**, `_binop`/`_fold`/`_binop_emit`
(`py2c.py:280-333`):

| Operator | Accepted? | Notes |
|---|---|---|
| `+` `-` | Yes | Emitted directly as `+`/`-`; the result is reduced mod 3**20 (subtraction relies on Python `%`'s non-negative semantics, which matches the value ring naturally) |
| `*` | Yes | Computed directly when compile-time foldable; otherwise the `zzmul` helper is injected on demand (doubling method, ~32 additions) |
| `//` | Yes | As above, injecting `zzdiv` (long division); **during constant folding**, division by zero is rejected (`"integer division or modulo by zero"`); **at runtime** (non-constant), division by zero is not rejected — `zzdiv` is defined to return 0 (see §2) |
| `%` | Yes | Same as `//`, injecting `zzmod`; modulo by zero is rejected during constant folding, and at runtime returns the dividend itself (`zzmod` semantics) |
| `/` | No | Rejected: `"true division '/' is unsupported; use floor division '//' ..."` |
| `**` `&` `\|` `^` `<<` `>>` | No | Rejected: `"unsupported binary operator: {Pow|BitAnd|BitOr|BitXor|LShift|RShift}"` |

**Unary operators (`ast.UnaryOp.op`)**, `_unaryop` (`py2c.py:335-349`):

| Operator | Accepted? | Notes |
|---|---|---|
| `+x` | Yes | Passed through unchanged |
| `not x` | Yes | Condition materialisation |
| `-x` | No | Rejected: `"unary minus is unsupported: the value ring has no negatives ..."`; the literal `-5` is likewise `UnaryOp(USub, Constant(5))` in the AST, takes the same path and produces the same message |
| `~x` | No | Rejected: `"bitwise '~' is unsupported"` |

**Comparison operators (`ast.Compare.ops`)**, `_CMP_OP` (`py2c.py:451-454`):

`< <= > >= == !=` are accepted; `is`, `is not`, `in`, `not in` are rejected
(`"comparison operator {Is|IsNot|In|NotIn} is unsupported"`).

**Negative numbers**: v1 **statically rejects** negatives on both paths —
literals and the unary minus (the value ring has no notion of "negative" to
begin with; `3 - 5` folds to a very large positive number rather than -2). There
is no other route to producing a negative value (subtraction results themselves
are unconstrained; only literal operands of an operator are blocked).

### 1.6 Identifier rules

`check_var_name` (`py2c.py:190-206`) applies uniformly to variable names,
parameter names, function names (function names additionally pass through
`check_func_name`) and names declared `global`:

1. MUST be non-empty, the first character MUST satisfy `isalpha()`, and **the
   whole string MUST satisfy `isascii()`** (unicode identifiers are legal at the
   Python 3 syntax level but are rejected here: `"identifier {!r} is not a valid
   C identifier"`).
2. Apart from the first character, every character MUST be `isalnum()` or an
   underscore, and the whole string MUST still be ascii (overlapping with the
   previous rule — this is the same ascii constraint validated a second time).
3. The case-insensitive `zz` prefix is reserved for the compiler's internal
   temporaries and helper functions (`zzt0`, `zzmul`, …): any user identifier
   with `name.lower().startswith("zz")` is rejected
   (`"identifier {!r} is reserved (names starting with 'zz' are used
   internally by the compiler)"`) — `zz`, `ZZ`, `Zz` and `zZ` all match.
4. An exact (case-sensitive) match against `C_KEYWORDS = {"int", "bool", "true",
   "false", "if", "else", "while", "return", "static", "main", "putchar",
   "getchar"}` is rejected (`"identifier {!r} collides with a C keyword in the
   target backend"`). Note that this is an **exact string match**: `INT`,
   `While_` and `Main` (case variants) are not covered — case variants of
   `main`/`putchar`/`getchar` are instead handled by `RESERVED_FUNCS` from §1.3
   (function names only), or are not restricted at all (variable-name case).
5. Additional checks for function names: see the case-insensitive uniqueness
   check and `RESERVED_FUNCS` in §1.3.

**Unrestricted** (legal) examples: `print`, `range`, `ord`, `chr`, `while_` and
`INT` (all caps) are all legal as **variable names**; but using these built-in
call names as **function names** leads to the "definable but not callable" trap
— see §2 and the appendix `defects.md` B3-B6.

### 1.7 Built-in functions (available only inside `Call` nodes)

`_call()` (`py2c.py:351-398`) dispatches on the callee name (which MUST be a
bare `ast.Name` — "only direct function calls are supported (no methods or
computed callees)"):

| Call form | Accepted? | Notes |
|---|---|---|
| `putchar(x)` | Only as the statement `putchar(x)` (handled specially by `_stmt_Expr`); single argument, no keyword arguments | Using it as an expression value (`y = putchar(x)`) is rejected: `"putchar() returns nothing and cannot be used as a value"` |
| `getchar()` | Yes | Zero arguments, no keyword arguments (otherwise `"getchar() takes no arguments"`) |
| `ord(c)` | Yes, but `c` MUST be a **compile-time literal** and a string constant of length exactly 1 (`ast.Constant(str)`); folded to `ord(c) % MOD` at compile time | A non-literal argument reports "... (evaluated at compile time)"; length ≠ 1 reports "expects a single character" |
| `chr(x)` | No | Rejected: `"chr() is unsupported; emit characters with putchar(codepoint)"` |
| `print(...)` | **Partially accepted since batch 1 (2026-07-23)**: compile-time constant arguments only | Accepted: string literals, constant-foldable int expressions, f-strings whose parts are all constant (parts may be text, foldable ints, or string literals; a part with a conversion or `format_spec` is rejected); `sep=`/`end=` accept constant strings only (defaults `" "`/`"\n"`); with no arguments only `end` is emitted. Rendering: the rendered arguments are joined with `sep`, `end` is appended, and the result is emitted character by character with putchar; an int renders as the decimal form of its folded mod-3**20 value (see D17 in §2); a character codepoint > 255 is rejected. **Runtime (non-constant) arguments are rejected**, with a message pointing to putchar and noting support in a future version; `print()` used as an expression value is rejected |
| `range(...)` | Only as a `for` loop header | Calling `range(...)` in any other expression position is rejected: `"range() is only valid in a 'for' loop header"` |
| User function name | Yes | MUST already be registered in `self.functions`; keyword arguments are not allowed; the argument count MUST match the parameter count exactly (otherwise "{}() takes {} argument(s) but {} given") |
| Any other name (unregistered user function) | No | `"call to undefined function {!r}"` |

**Trap** (detailed in §2 and the appendix): the six names
`putchar`/`getchar`/`ord`/`chr`/`print`/`range` are matched in `_call()`
**before** the check for "is this a registered user function". If a user names
their own function `print`/`range`/`ord`/`chr` (`putchar`/`getchar` are stopped
earlier, at registration, by `RESERVED_FUNCS`), the definition itself succeeds,
but **every** call to it is intercepted by the built-in special case and
produces a misleading error that has nothing to do with the name collision.

---

## 2. Semantic divergence table (versus CPython)

> Numbering note: `D1`-`D16` in this section is this document's own divergence
> numbering; it is a separate scheme from `defects.md`'s independently numbered
> `C1`-`C5` (silently-accepted defects) and `B1`-`B6` (poor-diagnostic-quality
> defects) — `defects.md` orders defects by severity, whereas this table orders
> divergences by CPython semantic topic (covering both "design divergences" and
> "defects", only the latter corresponding to `defects.md` entries). Rows marked
> as defects give the corresponding `defects.md` number in the notes column.

| # | Topic | CPython semantics | py2c v1 semantics | Classification |
|---|---|---|---|---|
| D1 | Integer ring | Arbitrary-precision signed integers | All integers live in the non-negative ring `mod 3**20`; the results of `+ - *`, literals and `ord()` results are all reduced | Design divergence (documented) |
| D2 | Negative numbers | Supported | Unary minus and negative literals are **statically rejected**; there is no legal route to producing a negative value | Design divergence (documented) |
| D3 | `/` vs `//`/`%` | `/` is true division returning a float; `//`/`%` use floor semantics for negatives | Only `//`/`%` exist, performing long division on non-negative integers; `/` is rejected outright | Design divergence (documented) |
| D4 | `bool` type | A distinct type; `True`/`False` are singletons | `bool`/`true`/`false` are never emitted (the downstream type system is known to be broken); boolean literals fold to `1`/`0`; the results of comparisons and boolean operations exist only in "materialised into an int variable" form and cannot be used as a standalone type | Design divergence (works around a downstream bug, documented) |
| D5 | `getchar`/`putchar` and EOF | No corresponding built-ins; requires `sys.stdin`/`sys.stdout` | `getchar()` reads one character encoding, `putchar(x)` writes one character according to the encoding of `x`; **the EOF return value is not specified at the py2c level** — `getchar()` merely emits a call to the downstream `getchar()` C function, and the concrete EOF semantics are decided by the runtime (Malbolge20 reference implementation: `A=59049`, per the internal research log — private, not in this repo — B1); py2c itself performs no EOF-related conversion or validation | Design divergence + documentation gap (the v1 documentation does not mention the EOF value, see the TODO in the "Version notes" section) |
| D6 | Reading an unbound variable (function scope) | `NameError`/`UnboundLocalError` (at runtime) | **Fixed (2026-07-22)**: the `Name` (Load) branch of `lower(Name)` now queries a "definitely assigned" set advanced in actual compilation order (`self.bound`; reads inside functions additionally admit any name already assigned at module level, see `_is_bound`); on a miss it raises `CompileError` ("name {!r} is used before it is assigned") with the accurate original Python line number and the identifier spelled exactly as the user wrote it — see `defects.md` B1/B2 (fixed) | Fixed (2026-07-22, formerly a class-B defect) |
| D7 | Reading an unbound variable (module scope) | Same as above | **Fixed (2026-07-22)**: same mechanism as D6; inside the synthesized `main()` there is no fallback admission of "names already assigned at module level" (because `main()` *is* the sequential execution of module-level code), so the check is strictly in declaration order | Fixed (2026-07-22, formerly a class-B defect) |
| D8 | Augmented-assignment target MUST be bound | `x += 1` with `x` undefined is a `NameError` | **Fixed (2026-07-22)**: `_stmt_AugAssign` queries the "definitely assigned" set before generating `x += ...;` and rejects an unbound target (see `defects.md` C3, fixed) | Fixed (2026-07-22, formerly a class-C defect) |
| D9 | Bare type annotation `x: int` | Does not bind the name (only writes `__annotations__`); a subsequent read is a `NameError` | **Fixed (2026-07-22)**: the bare-annotation branch no longer calls `_bind_target`; it only validates identifier legality and establishes no binding, so subsequent reads fall into the same check path as D6/D7 (see `defects.md` C2, fixed) | Fixed (2026-07-22, formerly a class-C defect) |
| D10 | `return` outside a function | `SyntaxError: 'return' outside function` (at compile time, raised by the bytecode compiler rather than `ast.parse`) | **Fixed (2026-07-22)**: `_stmt_Return` now tests `self.in_main` (previously the always-false dead code `self.locals is None`), so a top-level `return` is now accurately rejected (see `defects.md` C1, fixed) | Fixed (2026-07-22, formerly a class-C defect and once the most severe one) |
| D11 | Decorators | Actually transform the function object | **Fixed (2026-07-22)**: `_register_function` now inspects `decorator_list` and rejects any non-empty decorator list (see `defects.md` C4, fixed) | Fixed (2026-07-22, formerly a class-C defect) |
| D12 | `global x` where `x` is also a parameter | `SyntaxError: name 'x' is parameter and global` | **Fixed (2026-07-22)**: `_stmt_Global` now compares against `self.params` and rejects on a match (see `defects.md` C5, fixed) | Fixed (2026-07-22, formerly a class-C defect) |
| D13 | `range(...)`/`print(...)`/`ord(...)`/`chr(...)` as user function names | Legal, shadowing the built-in; calls go to the user function | **Fixed (2026-07-22)**: `check_func_name` gained a `BUILTIN_CALL_NAMES` reserved-word check that rejects at the function **registration** stage with an accurate line number, instead of letting it through to the call site where an off-topic error would be reported (see `defects.md` B3-B6, fixed) | Fixed (2026-07-22, formerly a class-B defect) |
| D14 | Missing `return` at the end of a function | Implicit `return None`; if the caller uses the result as an integer, a runtime `TypeError` follows | The C function body has no trailing `return` statement, which under C semantics is undefined behaviour (if the return value is used); py2c neither statically checks "does every path return" nor injects a fallback `return 0;` | Known design gap (neither a CompileError nor a silent mistranslation, but a pass-through of C undefined behaviour; clarifying it or injecting a fallback `return` is recommended for v1.x, see the "Version notes" section) |
| D15 | Identifiers: non-ASCII / leading underscore | Legal (Python 3 identifier rules) | Rejected (only `[a-zA-Z][0-9a-zA-Z_]*`, entirely ASCII, is accepted) | Design divergence (downstream C lexical restriction, documented) |
| D16 | Module docstring skipping rule | A string constant is a docstring only as the **first** statement (bare string statements elsewhere are merely evaluated and discarded — semantically equivalent but conceptually different) | **Tightened (2026-07-23, batch 1)**: only the **first** bare string of a module or function body is silently ignored as a docstring, aligning with CPython's docstring concept; bare string statements anywhere else are now **rejected** (CPython evaluates and discards them) — this moves from "over-broad acceptance" to "explicit rejection" and counts as a design divergence (a bare string has no producible effect in this subset, so rejecting beats staying silent) | Design divergence (since 2026-07-23, documented) |
| D17 | `print()` rendering of constant integers | `print(3-5)` outputs `-2` (signed decimal) | Constant folding happens in the non-negative ring mod 3**20, so `print(3-5)` outputs `3486784398` (divergence D1 surfacing in print rendering); ordinary non-negative constants match CPython | Design divergence (a corollary of D1, documented; will disappear together with D2 once signed integers land) |

**A verified "looks like a divergence, measurably isn't" counter-example**
(methodology record): a function coexisting with a module-level global variable
of the same name (`def foo(): ...` followed by `foo = 5`) appears to be a
duplicate declaration in the generated C source, but the downstream `c2mg`
emits them separately as `FOO` (function) and `u_foo` (variable), which do not
conflict; the full-pipeline result matches CPython's actual output. **Do not**
judge correctness from the surface shape of the intermediate C code alone —
always verify downstream, or run the full pipeline and diff against CPython.

---

## 3. Diagnostic contract

This section states **normative requirements** on the current state of py2c v1.
D6/D7/D8/D9/D10/D11/D12/D13 found by the appendix audit (`defects.md`'s C1-C5
and B1-B6) formerly violated requirement 1 below; all of them were fixed on
2026-07-22 (see the "Fixed" notes on the corresponding rows of the §2 divergence
table and `defects.md`). The `TestKnownDefects` class in
`test/test_py2c_diagnostics.py` has since flipped all the corresponding xfails
into real assertions that act as a regression lock.

1. **Any input outside the accepted set of §1 MUST be rejected with a
   `CompileError` carrying an accurate `lineno` that locates the original Python
   source** (via `node.lineno`, inherited from the AST node that triggered the
   rejection). "Accurate" means: the line number points at a line of Python
   source the user can read and that is genuinely where the problem is — not a
   line number in a generated intermediate C/`.mg`/`.mc` file.
2. **No native Python traceback may leak**: apart from the `SyntaxError` raised
   by `ast.parse`, which `compile()` explicitly catches and wraps into a
   `CompileError` (see `py2c.py:860-868`), no uncaught native exception
   (`AttributeError`/`KeyError`/`IndexError`/`TypeError`, …) may escape to the
   caller during compilation — any such exception is counted as a class-B defect
   ("bare exception leak") by this audit.
3. **No silent mistranslation**: an input outside the accepted set MUST NOT be
   accepted by `compile_python_to_c` without an exception and turned into C code
   that is structurally valid but behaviourally wrong (the class-C defects this
   document repeatedly refers to); likewise, an input that *is* in the accepted
   set with well-defined semantics MUST NOT produce code inconsistent with the
   §2 divergence table of this specification.
4. **Error message format convention** (`CompileError._render()`,
   `py2c.py:130-143`):
   ```
   compile error (line <N>): <message>
       <the source line, stripped>
       <a caret ^ aligned to col, if col_offset is available>
   ```
   `<message>` SHOULD: (a) state exactly **which** rule of the accepted set was
   violated; (b) suggest an alternative spelling where possible (e.g. "use `//`
   instead of `/`"); (c) use the identifier as the user actually wrote it in the
   source, never a compiler-internal rename (such as `u_foo` or `zzt0`) — D6/D7
   formerly violated this and were fixed on 2026-07-22 (both the `CompileError`
   message and the line number are now taken from the original `ast.Name` node,
   with no internal renaming in between).
5. **Scope boundary of the diagnostics**: this contract constrains only the
   `compile_python_to_c` front-end stage. If an illegal input is wrongly let
   through by py2c and can only be rejected by a downstream stage
   (`c2mg`/`mg2mc`/`mc2mb`), then even if the downstream stage also gives a
   structured exception (`C2MgError` etc.) rather than a bare traceback, this
   still violates requirement 1 ("MUST be rejected by py2c itself, with an
   accurate Python source line number") and counts as a class-B, not class-A,
   defect.

---

## 4. Version notes

### v1 (current implementation, `py2c.py`) status

- See §1 for the complete accepted set and §2 for the divergence table.
- 2026-07-22: D6/D7/D8/D9/D10/D11/D12/D13 (`defects.md` C1-C5, B1-B6) were all
  fixed. How:
  - `_Compiler` gained a set of "definitely assigned" names advanced in
    **actual compilation order** (`self.bound`, `_is_bound()`), queried
    uniformly at the `Name` (Load) read points in `lower()` and in
    `_stmt_AugAssign`'s target pre-check; a miss is rejected
    (`"name {!r} is used before it is assigned"`). User functions additionally
    admit any name already assigned at module level (`self.module_globals`, a
    one-shot pre-scan of `module_body` inside `compile()`), because reading a
    module-level global without a `global` declaration is legal in CPython; the
    synthesized `main()` *is* the module-level code and does not get this
    admission, so it MUST be checked strictly in assignment order (this is the
    fix criterion for D6/D7/D8/D9). This is a simplified (approximate) version
    of the definite-assignment analysis proposed in `defects.md`: it advances
    linearly in real compilation order and performs no intersection across
    `if`/`while`/`for` branches (so it still cannot catch finer conditional
    binding errors such as "assigned only in one branch, then read
    unconditionally") — a downgrade explicitly endorsed in `defects.md`'s
    root-cause summary, bought in exchange for full compatibility with py2c's
    existing "compile sequentially and report at the first problem encountered"
    behaviour, changing neither the position nor the wording of any existing
    class-A diagnostic test.
  - The bare type annotation (`x: int`) branch no longer calls `_bind_target`
    (D9).
  - `_stmt_Return` tests `self.in_main` instead of the always-false
    `self.locals is None` (D10).
  - `_register_function` rejects a non-empty `decorator_list` (D11).
  - `_stmt_Global` compares against `self.params` to catch parameter-name
    collisions (D12).
  - `check_func_name` gained a `BUILTIN_CALL_NAMES = {"putchar", "getchar",
    "ord", "chr", "print", "range"}` reserved-word check that rejects at the
    function registration stage (D13).
  - Regression tests: in the `TestKnownDefects` class of
    `test/test_py2c_diagnostics.py`, all 6 former `xfail(strict)` cases were
    flipped into real assertions; the existing legal-program cases in
    `test/test_py2c.py` and `test/test_c2mg.py` are all unchanged (none of them
    relied on these formerly silently-accepted inputs).
- D14 (missing return path) and D5 (EOF semantics undocumented at the py2c
  level) remain "gaps" rather than confirmed mistranslations; adding a note or a
  lightweight check in v1.x is recommended, and neither is in scope for this
  round of fixes.
- 2026-07-23: **batch-1 syntactic sugar** was implemented in `py2c.py` (the 'c'
  backend) and `py2mg.py` (the 'direct' backend) in lock-step under the same
  semantic contract; both backends produce identical program output for the same
  source (verified by a dual-backend e2e diff):
  1. `print()` with constant arguments (strings / foldable ints / all-constant
     f-strings, `sep=`/`end=`; see §1.7 and D17 in §2);
  2. f-strings (in print argument position only, all-constant parts);
  3. `ord('x')` (verified that the existing implementation already met the
     contract; tests added to lock it down);
  4. the conditional expression `a if c else b` (temp + if/else
     materialisation, lazy evaluation);
  5. `*= //= %=` (verified that py2c already supported them, tests added; py2mg
     brought in line);
  6. `break`/`continue` (flag lowering, independent per nesting level, rejected
     outside a loop);
  7. the docstring position rule (module/function body first statement only, see
     the D16 tightening in §2).
  This batch is **pure front-end expansion**; no new runtime primitive was
  added. The `py2mg` side is additionally constrained by the SWITCH
  self-modification trap recorded in the internal research log (private, not in
  this repo), A3: flags must use branch-free accumulation plus a single SWITCH.

### v2 planned items (**reserved fields** — none of the capabilities below are
currently in the accepted set; any input attempting to use them **MUST continue
to be rejected under the §3 diagnostic contract** until the corresponding
feature is actually implemented. Relaxing one of these checks before
implementation without updating this document and the §1 accepted-set tables in
the same change counts as introducing a new class-C defect.)

- **Signed integer semantics**: introduce an explicit two's-complement
  convention or a sign-bit representation, lifting the static rejection in the
  "negative numbers" paragraph of §1.5 and in D2 of §2.
- **Runtime decimal `print`/`input`**: batch 1 (2026-07-23) already supports
  **constant** print; decimal output of **runtime values** (a divmod-10 loop)
  and `input()` parsing are still reserved and need new runtime support.
- ~~**`break`/`continue`**~~ implemented in batch 1 (2026-07-23), see §1.2.
- **Arrays / runtime strings**: `Subscript`/`Slice` and string **variables** are
  all still rejected (§1.4, §1.5; string **literals** were opened up in print/ord
  position by batch 1); the dissection of the array mechanism and the
  LOADI/STOREI design proposal are in the internal Nagoya array dissection
  notes (private, not in this repo).
- Whenever an item in this list moves from "reserved, MUST be rejected" to
  "implemented, part of the accepted set", the same change MUST: update the
  corresponding subsection of §1 in this document, add or remove the
  corresponding row in §2, and confirm in `defects.md` that no new D6-D13-style
  definite-assignment-analysis hole is introduced (especially for arrays and strings: once
  `Subscript` reads and writes exist, the scope of the definite-assignment
  analysis for "reading an unbound variable" MUST be widened accordingly to
  "is this array element / slice initialised", or the D6-D9 class of problems
  will simply recur).

---

## Appendix: diagnostic audit results table

Audit method: 137 probe cases were constructed (covering every category of
unsupported AST node in §1, every confirmed or suspected semantic divergence in
§2, and boundary values) and fed one by one to `compile_python_to_c`. Cases that
were "silently accepted but semantically suspect" were additionally fed to
`compile_c_to_mg` and to the full pipeline `compile_python_to_mb`, run on
pyMalbolge, and diffed against the result of executing an equivalent or
near-equivalent source directly with CPython `exec()`, in order to establish
whether a behavioural fork really exists (methodology reference: the lesson of
the internal research log (private, not in this repo), A4 — you cannot draw a
conclusion merely because an intermediate artifact "looks suspicious").

Classification: A = correctly rejected; B = rejected but with poor quality (see
requirements 4/5 of the §3 contract); C = silently accepted but semantically
wrong; D = correctly accepted.

**Total 137 cases: A=101, B=6, C=6, D=24.**

Script and corpus: `/Users/anend/.claude/jobs/1d5df563/tmp/subset-spec/probe.py`
(re-runnable: `python3 probe.py --summary` for the summary, `python3 probe.py`
for per-case detail, `python3 probe.py --export-md <path>` to re-export the
table below). Detailed reproductions and fix proposals for the 6 class-B and 6
class-C defects are in `defects.md` in the same directory (cross-referenced from
§2 and §3).

> **Fixed (2026-07-22)**: the table below is a historical snapshot of `py2c.py`
> from *before* the fixes (deliberately not refreshed with
> `probe.py --export-md`, so as to preserve the original record of the audit
> process). The defects behind the following 12 case IDs have all been fixed;
> re-running `compile_python_to_c` today yields a `CompileError` (rather than the
> "OK (compiled)" or the wrong line number/wording recorded in the table). See
> rows D6-D13 of the §2 divergence table and `defects.md`:
> `ast_decorator_property`, `ast_decorator_staticmethod` (C4),
> `sem_undefined_var_read_toplevel`, `sem_undefined_var_read_func` (B1/B2),
> `sem_stray_return_toplevel` (C1), `sem_unbound_augassign` (C3),
> `sem_bare_annassign_then_read` (C2), `sem_func_named_range_shadow`,
> `sem_func_named_print_shadow`, `sem_func_named_ord_shadow`,
> `sem_func_named_chr_shadow` (B3-B6), `sem_global_shadows_param` (C5).
> Regression tests: `test/test_py2c_diagnostics.py::TestKnownDefects`.

<!-- AUDIT_TABLE_START -->
| ID | Input summary | Expected | Actual | Notes |
|---|---|---|---|---|
| `ast_class_toplevel` | `class C: ⏎     pass` | A | CompileError@L1 | ClassDef at module level -> explicit rejection. |
| `ast_class_nested` | `def f(): ⏎     class C: ⏎         pass ⏎     return 1 ⏎ p...` | A | CompileError@L2 | ClassDef inside a function body -> generic 'unsupported statement'. |
| `ast_import` | `import os ⏎ putchar(65)` | A | CompileError@L1 | Import -> explicit rejection. |
| `ast_importfrom` | `from os import path ⏎ putchar(65)` | A | CompileError@L1 | ImportFrom -> explicit rejection (shares the Import branch). |
| `ast_lambda` | `f = lambda x: x + 1` | A | CompileError@L1 | Lambda -> generic 'unsupported expression'. |
| `ast_nested_function` | `def outer(): ⏎     def inner(): ⏎         return 1 ⏎     ...` | A | CompileError@L2 | Nested FunctionDef -> explicit rejection. |
| `ast_closure_free_var` | `def make(): ⏎     y = 1 ⏎     def add(x): ⏎         retur...` | A | CompileError@L3 | Closures require nested defs, same path as ast_nested_function. |
| `ast_generator_func` | `def gen(): ⏎     yield 1 ⏎ putchar(65)` | A | CompileError@L2 | yield -> Expr(Yield) at stmt level, generic 'unsupported expression'. |
| `ast_generator_expr` | `a = (i for i in range(3))` | A | CompileError@L1 | GeneratorExp -> generic 'unsupported expression'. |
| `ast_try_except` | `try: ⏎     x = 1 ⏎ except Exception: ⏎     x = 2 ⏎ putcha...` | A | CompileError@L1 | Try -> generic 'unsupported statement'. |
| `ast_with` | `with open('f') as fh: ⏎     x = 1 ⏎ putchar(x)` | A | CompileError@L1 | With -> generic 'unsupported statement'. |
| `ast_assert` | `x = 1 ⏎ assert x == 1 ⏎ putchar(65)` | A | CompileError@L2 | Assert -> generic 'unsupported statement'. |
| `ast_del` | `x = 1 ⏎ del x ⏎ putchar(65)` | A | CompileError@L2 | Delete -> generic 'unsupported statement'. |
| `ast_nonlocal` | `def outer(): ⏎     x = 1 ⏎     def inner(): ⏎         non...` | A | CompileError@L3 | nested def is hit first (nonlocal only legal inside nested scope anyway). |
| `ast_decorator_property` | `@property ⏎ def foo(x): ⏎     return x ⏎ putchar(foo(65))` | C | OK (compiled) | decorator_list on a top-level FunctionDef is never inspected by _register_function/_compile_function -- silently dropped. Real CPython: '... |
| `ast_decorator_staticmethod` | `@staticmethod ⏎ def foo(x): ⏎     return x ⏎ putchar(foo(...` | C | OK (compiled) | Same root cause as ast_decorator_property; staticmethod happens to stay directly-callable on CPython >=3.10 so this particular decorator ... |
| `ast_starargs_def` | `def f(*args): ⏎     return 1 ⏎ putchar(f(1, 2))` | A | CompileError@L1 | vararg -> explicit rejection. |
| `ast_kwargs_def` | `def f(**kw): ⏎     return 1 ⏎ putchar(f())` | A | CompileError@L1 | kwarg -> explicit rejection. |
| `ast_default_arg` | `def f(x=1): ⏎     return x ⏎ putchar(f())` | A | CompileError@L1 | defaults -> explicit rejection. |
| `ast_kwonly_arg` | `def f(*, x): ⏎     return x ⏎ putchar(f(x=1))` | A | CompileError@L1 | kwonlyargs -> explicit rejection. |
| `ast_posonly_arg` | `def f(x, /): ⏎     return x ⏎ putchar(f(65))` | A | CompileError@L1 | posonlyargs -> explicit rejection. |
| `ast_starargs_call` | `def f(a, b): ⏎     return a + b ⏎ args = (1, 2) ⏎ putchar...` | A | CompileError@L3 | Starred in call args -> Starred hits lower()'s generic branch (tuple literal 'args = (1,2)' errors first). |
| `ast_kwargs_call` | `def f(a): ⏎     return a ⏎ putchar(f(a=65))` | A | CompileError@L3 | keyword arg in user call -> explicit rejection. |
| `ast_float_literal` | `x = 3.14 ⏎ putchar(65)` | A | CompileError@L1 | float Constant -> explicit rejection. |
| `ast_str_literal` | `s = 'hi' ⏎ putchar(65)` | A | CompileError@L1 | str Constant (len != 1 case is separate; plain assignment) -> explicit rejection. |
| `ast_bytes_literal` | `b = b'hi' ⏎ putchar(65)` | A | CompileError@L1 | bytes Constant falls through _const()'s bool/int/str/float checks to the generic 'unsupported constant: {!r}' fallback -- correct line, u... |
| `ast_list_literal` | `a = [1, 2, 3] ⏎ putchar(65)` | A | CompileError@L1 | List -> generic 'unsupported expression'. |
| `ast_dict_literal` | `a = {1: 2} ⏎ putchar(65)` | A | CompileError@L1 | Dict -> generic 'unsupported expression'. |
| `ast_set_literal` | `a = {1, 2} ⏎ putchar(65)` | A | CompileError@L1 | Set -> generic 'unsupported expression'. |
| `ast_tuple_literal` | `a = (1, 2) ⏎ putchar(65)` | A | CompileError@L1 | Tuple -> generic 'unsupported expression'. |
| `ast_tuple_unpack_assign` | `a, b = 1, 2 ⏎ putchar(a)` | A | CompileError@L1 | Tuple assignment target -> explicit rejection with node-type name. |
| `ast_starred_assign_target` | `a, *b = 1, 2, 3 ⏎ putchar(a)` | A | CompileError@L1 | Starred target inside a Tuple target -> caught by the same Tuple check (message says 'Tuple', not 'Starred', but still an explicit, corre... |
| `ast_fstring` | `x = 65 ⏎ putchar(f'{x}')` | A | CompileError@L2 | JoinedStr -> generic 'unsupported expression' (inside putchar's arg). |
| `ast_negative_literal` | `x = -5 ⏎ putchar(65)` | A | CompileError@L1 | Constant(-5) parses as UnaryOp(USub, Constant(5)) -> unary-minus path. |
| `ast_unary_negative_var` | `x = 5 ⏎ y = -x ⏎ putchar(65)` | A | CompileError@L2 | UnaryOp(USub) on a non-literal -> explicit rejection. |
| `ast_power_op` | `x = 2 ** 10 ⏎ putchar(65)` | A | CompileError@L1 | Pow -> generic 'unsupported binary operator: Pow'. |
| `ast_bitand` | `x = 5 & 3 ⏎ putchar(65)` | A | CompileError@L1 | BitAnd -> generic 'unsupported binary operator'. |
| `ast_bitor` | `x = 5 \| 3 ⏎ putchar(65)` | A | CompileError@L1 | BitOr -> generic 'unsupported binary operator'. |
| `ast_bitxor` | `x = 5 ^ 3 ⏎ putchar(65)` | A | CompileError@L1 | BitXor -> generic 'unsupported binary operator'. |
| `ast_lshift` | `x = 5 << 1 ⏎ putchar(65)` | A | CompileError@L1 | LShift -> generic 'unsupported binary operator'. |
| `ast_rshift` | `x = 5 >> 1 ⏎ putchar(65)` | A | CompileError@L1 | RShift -> generic 'unsupported binary operator'. |
| `ast_invert` | `x = 5 ⏎ y = ~x ⏎ putchar(65)` | A | CompileError@L2 | Invert ('~') -> explicit rejection. |
| `ast_is` | `x = 1 ⏎ if x is 1: ⏎     putchar(65)` | A | CompileError@L2 | Is comparator not in _CMP_OP -> explicit rejection, checked before any operand is lowered. |
| `ast_is_not` | `x = 1 ⏎ if x is not 1: ⏎     putchar(65)` | A | CompileError@L2 | IsNot -> same path. |
| `ast_in` | `x = 1 ⏎ if x in (1, 2): ⏎     putchar(65)` | A | CompileError@L2 | In -> caught before operand lowering, so the Tuple literal never gets a chance to also error; message names the comparator. |
| `ast_not_in` | `x = 1 ⏎ if x not in (1, 2): ⏎     putchar(65)` | A | CompileError@L2 | NotIn -> same path. |
| `ast_walrus` | `if (n := 5) > 0: ⏎     putchar(n)` | A | CompileError@L1 | NamedExpr -> generic 'unsupported expression'. |
| `ast_ternary_ifexp` | `x = 5 ⏎ y = 1 if x > 0 else 0 ⏎ putchar(65)` | A | CompileError@L2 | IfExp -> generic 'unsupported expression'. |
| `ast_subscript_read` | `a = 5 ⏎ x = a[0] ⏎ putchar(65)` | A | CompileError@L2 | Subscript -> generic 'unsupported expression'. |
| `ast_subscript_assign` | `a = 5 ⏎ a[0] = 1 ⏎ putchar(65)` | A | CompileError@L2 | Subscript assignment target -> explicit rejection. |
| `ast_slice` | `a = 5 ⏎ x = a[1:2] ⏎ putchar(65)` | A | CompileError@L2 | Slice inside Subscript -> same generic Subscript rejection. |
| `ast_attribute_read` | `import sys ⏎ putchar(sys.maxsize)` | A | CompileError@L1 | 'import' rejected first; this only reaches Attribute handling if import were legal. Left in the corpus to document ordering. |
| `ast_attribute_read_no_import` | `class Dummy: ⏎     pass ⏎ x = Dummy.attr ⏎ putchar(65)` | A | CompileError@L1 | class rejected first (same reasoning); genuine Attribute-only probe is ast_attribute_assign below. |
| `ast_attribute_assign` | `a = 5 ⏎ a.x = 1 ⏎ putchar(65)` | A | CompileError@L2 | Attribute assignment target -> explicit rejection. |
| `ast_yield_from` | `def gen(): ⏎     yield from range(3) ⏎ putchar(65)` | A | CompileError@L2 | YieldFrom -> generic 'unsupported expression'. |
| `ast_async_def` | `async def f(): ⏎     return 1 ⏎ putchar(65)` | A | CompileError@L1 | AsyncFunctionDef isn't ast.FunctionDef -> falls to module_body, then compile_stmt finds no _stmt_AsyncFunctionDef -> generic 'unsupported... |
| `ast_await` | `async def f(): ⏎     x = await g() ⏎     return x ⏎ putch...` | A | CompileError@L1 | Same AsyncFunctionDef path fires before Await is ever examined. |
| `ast_match_stmt` | `x = 1 ⏎ match x: ⏎     case 1: ⏎         putchar(65) ⏎   ...` | A | CompileError@L2 | Match -> generic 'unsupported statement'. |
| `ast_raise` | `raise ValueError('x') ⏎ putchar(65)` | A | CompileError@L1 | Raise -> generic 'unsupported statement'. |
| `ast_ellipsis` | `x = ... ⏎ putchar(65)` | A | CompileError@L1 | Ellipsis is ast.Constant(value=Ellipsis) in modern ast; falls through _const()'s bool/int/str/float checks to the generic 'unsupported co... |
| `ast_complex_literal` | `x = 3j ⏎ putchar(65)` | A | CompileError@L1 | complex Constant -> same generic 'unsupported constant' fallback. |
| `ast_type_alias` | `type IntList = int ⏎ putchar(65)` | A | CompileError@L1 | PEP 695 'type' statement (3.12+) -> TypeAlias node has no _stmt_ handler -> generic 'unsupported statement' (skipped automatically on int... |
| `ast_docstring_module` | `"""doc""" ⏎ putchar(65)` | D | OK (compiled) | Module docstring -> explicitly skipped in compile(). |
| `ast_docstring_func` | `def f(): ⏎     '''doc''' ⏎     return 1 ⏎ putchar(f())` | D | OK (compiled) | Function-level bare string Expr -> _stmt_Expr's Constant branch is a no-op, same as CPython (docstring, no side effect). |
| `ast_bare_int_stmt` | `5 ⏎ putchar(65)` | D | OK (compiled) | Bare int literal statement -> _stmt_Expr's Constant branch, no-op, matches CPython (expression statement evaluated and discarded). |
| `ast_bare_name_stmt` | `x = 5 ⏎ x ⏎ putchar(65)` | D | OK (compiled) | Bare Name expression statement -> lower(Name) returns the name, no code emitted, discarded; matches CPython's no-op semantics for a defin... |
| `sem_undefined_var_read_toplevel` | `putchar(never_assigned)` | B | OK (compiled) | lower(Name) only calls check_var_name (identifier *shape* validation); it never checks the name is actually bound anywhere -- same root c... |
| `sem_undefined_var_read_func` | `def foo(): ⏎     return undefined_var ⏎ putchar(foo())` | B | OK (compiled) | Same missing check as above, but py2c ITSELF silently accepts this (compile_python_to_c returns C source with no CompileError -- see actu... |
| `sem_stray_return_toplevel` | `return 5 ⏎ putchar(65)` | C | OK (compiled) | 'return' outside a function is a SyntaxError in real CPython (raised by the bytecode compiler, not by ast.parse -- ast.parse('return 5') ... |
| `sem_unbound_augassign` | `x += 1 ⏎ putchar(x)` | C | OK (compiled) | _stmt_AugAssign never checks that the target was previously bound -- _bind_target just declares it. Real CPython: NameError: name 'x' is ... |
| `sem_bare_annassign_then_read` | `x: int ⏎ putchar(x)` | C | OK (compiled) | Bare annotation (`x: int`, no value) only *declares intent* in real Python -- it does not bind x. _stmt_AnnAssign's `node.value is None` ... |
| `sem_call_undefined_function` | `putchar(bar(1))` | A | CompileError@L1 | Call to a name not in self.functions -> explicit rejection. |
| `sem_call_undefined_function_no_call_paren` | `bar ⏎ putchar(65)` | D | OK (compiled) | Bare Name 'bar' (not a call) -- same as ast_bare_name_stmt: no check, no emitted code, silently a no-op. Included to show the asymmetry: ... |
| `sem_wrong_argcount_too_few` | `def f(a, b): ⏎     return a + b ⏎ putchar(f(1))` | A | CompileError@L3 | Argument count mismatch -> explicit rejection with counts in the message. |
| `sem_wrong_argcount_too_many` | `def f(a, b): ⏎     return a + b ⏎ putchar(f(1, 2, 3))` | A | CompileError@L3 | Same check, too many. |
| `sem_duplicate_function` | `def f(): ⏎     return 1 ⏎ def f(): ⏎     return 2 ⏎ putch...` | A | CompileError@L3 | Second registration of the same name -> explicit rejection. |
| `sem_function_case_collision` | `def foo(): ⏎     return 1 ⏎ def FOO(): ⏎     return 2 ⏎ p...` | A | CompileError@L3 | Upper-cased collision -> explicit rejection, names both functions. |
| `sem_function_case_collision_partial` | `def zAp(): ⏎     return 1 ⏎ def Zap(): ⏎     return 2 ⏎ p...` | A | CompileError@L3 | Same check with mixed-case names that upper-case identically. |
| `sem_zz_prefix_var_lower` | `zzx = 5 ⏎ putchar(zzx)` | A | CompileError@L1 | Reserved zz-prefix -> explicit rejection. |
| `sem_zz_prefix_var_upper` | `ZZfoo = 5 ⏎ putchar(ZZfoo)` | A | CompileError@L1 | check is name.lower().startswith('zz') -> case-insensitive, catches ZZ/Zz/zZ too. |
| `sem_zz_prefix_mixed` | `zZbar = 5 ⏎ putchar(zZbar)` | A | CompileError@L1 | Mixed-case zz prefix. |
| `sem_var_named_main` | `main = 5 ⏎ putchar(main)` | A | CompileError@L1 | 'main' is in C_KEYWORDS -> explicit rejection. |
| `sem_var_named_putchar` | `putchar = 5 ⏎ putchar(putchar)` | A | CompileError@L1 | 'putchar' is in C_KEYWORDS -> explicit rejection (fires on the assignment target before the call is even reached). |
| `sem_var_named_getchar` | `getchar = 5 ⏎ putchar(getchar)` | A | CompileError@L1 | 'getchar' is in C_KEYWORDS. |
| `sem_func_named_main` | `def main(): ⏎     return 1 ⏎ putchar(65)` | A | CompileError@L1 | 'main' is in C_KEYWORDS, so check_func_name's check_var_name() call catches it before the RESERVED_FUNCS check is ever reached -> message... |
| `sem_func_named_main_case_variant` | `def Main(): ⏎     return 1 ⏎ putchar(65)` | A | CompileError@L1 | Case variant 'Main' is NOT in C_KEYWORDS (exact-match, case-sensitive) so it reaches check_func_name's RESERVED_FUNCS check, which IS cas... |
| `sem_func_named_putchar` | `def putchar(x): ⏎     return x ⏎ putchar(65)` | A | CompileError@L1 | Same pre-emption as sem_func_named_main: 'putchar' is in C_KEYWORDS, caught there first. |
| `sem_func_named_getchar` | `def getchar(): ⏎     return 1 ⏎ putchar(65)` | A | CompileError@L1 | Same pre-emption for 'getchar'. |
| `sem_func_named_range_shadow` | `def range(x): ⏎     return x + 1 ⏎ putchar(range(65))` | B | CompileError@L3 | 'range' is not in RESERVED_FUNCS/C_KEYWORDS, so defining a function named 'range' is *accepted* at registration -- but _call() dispatches... |
| `sem_func_named_print_shadow` | `def print(x): ⏎     return x ⏎ putchar(print(65))` | B | CompileError@L3 | Same shadowing defect for 'print' (also not reserved at registration time). |
| `sem_func_named_ord_shadow` | `def ord(x): ⏎     return x ⏎ putchar(ord(65))` | B | CompileError@L3 | Same shadowing defect for 'ord': the user function registers fine, but every call is intercepted by the builtin ord() dispatch and fails ... |
| `sem_func_named_chr_shadow` | `def chr(x): ⏎     return x ⏎ putchar(chr(65))` | B | CompileError@L3 | Same shadowing defect for 'chr'. |
| `sem_func_global_name_collision` | `def foo(): ⏎     return 1 ⏎ foo = 5 ⏎ putchar(foo)` | D | OK (compiled) | Function 'foo' and a later module-level variable 'foo' are both accepted; empirically verified this is a FALSE ALARM for a defect -- c2mg... |
| `sem_return_missing_path` | `def f(x): ⏎     if x > 0: ⏎         return 1 ⏎ putchar(f(5))` | D | OK (compiled) | Function with a conditional return and no fallthrough return -- compiles; C leaves the return value of the fallthrough path unspecified (... |
| `sem_keyword_arg_call` | `def f(a, b): ⏎     return a + b ⏎ putchar(f(a=1, b=2))` | A | CompileError@L3 | keywords on a user call -> explicit rejection. |
| `sem_range_zero_args` | `for i in range(): ⏎     putchar(65)` | A | CompileError@L1 | range() arg count check. |
| `sem_range_four_args` | `for i in range(1, 2, 3, 4): ⏎     putchar(65)` | A | CompileError@L1 | range() arg count check. |
| `sem_range_kwargs` | `for i in range(stop=3): ⏎     putchar(65)` | A | CompileError@L1 | range() keywords -> explicit rejection. |
| `sem_range_var_step` | `n = 2 ⏎ for i in range(0, 10, n): ⏎     putchar(65)` | A | CompileError@L2 | Non-literal step -> explicit rejection. |
| `sem_break_in_loop` | `x = 1 ⏎ while x: ⏎     putchar(65) ⏎     break` | A | CompileError@L4 | break -> unconditionally rejected, even in an otherwise-legal loop (matches doc: 'the target backend has no break/continue'). |
| `sem_continue_in_loop` | `for i in range(3): ⏎     continue ⏎     putchar(65)` | A | CompileError@L2 | continue -> unconditionally rejected. |
| `sem_getchar_with_args` | `putchar(getchar(1))` | A | CompileError@L1 | getchar() arity check. |
| `sem_putchar_zero_args` | `putchar()` | A | CompileError@L1 | putchar() arity check. |
| `sem_putchar_two_args` | `putchar(65, 66)` | A | CompileError@L1 | putchar() arity check. |
| `sem_putchar_as_value` | `x = putchar(65) ⏎ putchar(66)` | A | CompileError@L1 | putchar() used in an expression context (not a bare Expr stmt) -> explicit rejection. |
| `sem_ord_non_literal_arg` | `x = 65 ⏎ putchar(ord(x))` | A | CompileError@L2 | ord() argument must be a literal (compile-time folded), not a variable -> explicit rejection naming the compile-time-evaluation requirement. |
| `sem_ord_multichar` | `putchar(ord('AB'))` | A | CompileError@L1 | ord() with len != 1 -> explicit rejection naming the value. |
| `sem_ord_empty_string` | `putchar(ord(''))` | A | CompileError@L1 | ord('') -> same len-check path (0 != 1). |
| `sem_chr_call` | `putchar(chr(65))` | A | CompileError@L1 | chr() -> explicit rejection. |
| `sem_print_call` | `print(65)` | A | CompileError@L1 | print() -> explicit rejection. |
| `sem_true_division` | `x = 10 ⏎ putchar(x / 2)` | A | CompileError@L2 | '/' -> explicit rejection naming '//' as the fix. |
| `sem_true_division_augassign` | `x = 10 ⏎ x /= 2 ⏎ putchar(65)` | A | CompileError@L2 | '/=' -> explicit rejection. |
| `sem_division_by_zero_const` | `putchar(5 // 0)` | A | CompileError@L1 | Constant-folded division by zero -> explicit rejection (distinct from the runtime zzdiv/zzmod helper, which returns 0 instead of trapping). |
| `sem_modulo_by_zero_const` | `putchar(5 % 0)` | A | CompileError@L1 | Same for modulo. |
| `sem_global_outside_function` | `global x ⏎ x = 1 ⏎ putchar(x)` | D | OK (compiled) | 'global' at true module level: CPython treats this as a syntactically legal (if pointless) no-op, not a SyntaxError -- ast.parse and comp... |
| `sem_global_shadows_param` | `x = 1 ⏎ def foo(x): ⏎     global x ⏎     return x ⏎ putch...` | C | OK (compiled) | In real CPython, `global x` naming a parameter is a SyntaxError at compile time ("name 'x' is parameter and global"). py2c's _stmt_Global... |
| `bnd_mod_minus_1` | `putchar(3486784400)` | D | OK (compiled) | 3**20 - 1 is the largest representable ring value; folds unchanged. |
| `bnd_mod_exact` | `x = 3486784401 ⏎ putchar(x % 100 + 30)` | D | OK (compiled) | 3**20 exactly wraps to 0 under the mod-3**20 fold (v % MOD in _const). |
| `bnd_mod_plus_1` | `x = 3486784402 ⏎ putchar(x % 100 + 30)` | D | OK (compiled) | 3**20 + 1 wraps to 1. |
| `bnd_huge_literal` | `x = 10000000000000000000000000000000000000000000000000000...` | D | OK (compiled) | A 100-digit literal -- Python ints are bignums so this is just an expensive-looking but correct '% MOD' fold; no overflow anywhere in the... |
| `bnd_empty_function_body_pass` | `def f(): ⏎     pass ⏎ putchar(f())` | D | OK (compiled) | Empty body via explicit 'pass'; f() implicitly returns 0 (see sem_return_missing_path note) -- accepted either way. |
| `bnd_empty_source` | `` | D | OK (compiled) | Empty file -> module_body is [] -> synthesized main() body becomes [ast.Pass()] (the 'or [ast.Pass()]' fallback) -> compiles to a no-op m... |
| `bnd_only_comment` | `# just a comment` | D | OK (compiled) | Comment-only file -> tree.body is empty after parsing -> same Pass-fallback path as bnd_empty_source. |
| `bnd_only_whitespace` | `` | D | OK (compiled) | Whitespace-only file -> same as above. |
| `bnd_only_docstring` | `"""just a docstring, no code"""` | D | OK (compiled) | Sole statement is the module docstring, explicitly skipped in compile() -> module_body stays empty -> Pass fallback. |
| `id_nonascii` | `変数 = 5 ⏎ putchar(変数)` | A | CompileError@L1 | Unicode identifier is valid Python 3 syntax but fails the ascii() check in check_var_name. |
| `id_leading_underscore` | `_x = 5 ⏎ putchar(_x)` | A | CompileError@L1 | Leading underscore fails name[0].isalpha(). |
| `id_single_underscore` | `_ = 5 ⏎ putchar(_)` | A | CompileError@L1 | Single underscore, same isalpha() check on the first (only) char. |
| `id_python_keyword_class` | `class = 5 ⏎ putchar(65)` | A | CompileError@L1 | 'class' is a Python keyword -> SyntaxError at ast.parse, wrapped as a CompileError with 'Python syntax error' message. |
| `id_print_as_varname` | `print = 5 ⏎ putchar(print)` | D | OK (compiled) | 'print' is not in C_KEYWORDS -- legal as a plain variable name as long as it's never *called* (calling it hits the builtin dispatch, see ... |
| `id_c_keyword_int` | `int = 5 ⏎ putchar(int)` | A | CompileError@L1 | 'int' is in C_KEYWORDS. |
| `id_c_keyword_while` | `while_ = 5 ⏎ putchar(while_)` | D | OK (compiled) | Trailing underscore avoids the exact-match C_KEYWORDS check ('while_' != 'while') -- legal. |
| `ctrl_chained_comparison` | `x = 5 ⏎ if 0 < x < 10: ⏎     putchar(65)` | D | OK (compiled) | Chained comparison desugars to (0<x) && (x<10); documented behaviour. |
| `ctrl_and_or_shortcircuit` | `x = 5 ⏎ if x > 0 and x < 10: ⏎     putchar(65) ⏎ if x < 0...` | D | OK (compiled) | and/or -> nested if/else short-circuit lowering; documented. |
| `ctrl_not_operator` | `x = 0 ⏎ if not x: ⏎     putchar(65)` | D | OK (compiled) | 'not' on a condition -> _materialize_cond handles UnaryOp(Not). |
| `ctrl_augassign_all_ops` | `x = 10 ⏎ x += 1 ⏎ x -= 1 ⏎ x *= 2 ⏎ x //= 2 ⏎ x %= 3 ⏎ pu...` | D | OK (compiled) | All five supported augmented-assignment operators on a properly-initialised variable. |
| `ctrl_multi_target_assign` | `a = b = c = 65 ⏎ putchar(a) ⏎ putchar(b) ⏎ putchar(c)` | D | OK (compiled) | a = b = c = expr -> computed once into 'a', copied to 'b'/'c'; documented multi-target assignment support. |
<!-- AUDIT_TABLE_END -->
