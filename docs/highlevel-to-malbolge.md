# High-Level Language → Malbolge Feasibility Study

> [中文](highlevel-to-malbolge.zh.md) | **English**

> A survey of prior work and a practical path for compiling a high-level language (e.g. Python) to HeLL/Malbolge.
> 2026-07-20. Conclusion: feasible, and Nagoya University already has a prior-art stack that can be reused; the recommended target is Malbolge20.

## 1. Landscape of Prior Work (by Abstraction Layer)

### The Nagoya University Stack (Target: Malbolge20, MIT License)

Follow-on work to Iizawa's 2005 99-bottles paper, continuing through 2017, this is **the only public work that achieves "C-style language → Malbolge"**:

| Layer | Language/Tool | Status |
|---|---|---|
| C subset (with recursive calls) | `highlevel` (C subset → pseudo-instructions) | **Source public, MIT** (an unlinked repo discovered via the GitLab API in 2026-07, see §1.1); capabilities exceed the 2017 paper: +/-, all comparisons, booleans, ++/--, +=/-=, recursion, arrays; multiplication/division still missing |
| Pseudo-instruction language (.mg) | `ternary` (pseudo-instructions → LAL translator) | **Source public, MIT**; supports DEF/CALL/RETURN, IF/ELSE, SWITCH/CASE, REPEAT/BREAK/INF, GOTO, VAR, arrays (IND_OPR), INPUT/OUTPUT |
| LAL (low-level assembly, .mc) | `lowass` (LAL → Malbolge20) | **Source public, MIT** (Perl two-pass + C++ init) |
| Malbolge20 runtime | reference interpreter (C, chunked lazy initialization) | **Source public, MIT**; pyMalbolge has been aligned with it and passes conformance (hello20.mb) |

Repositories: `git.trs.css.i.nagoya-u.ac.jp/malbolge/{highlevel,highlevel-examples,ternary,lowass,malbolge20-interpreter}`
(local clones live under `ref/nagoya-*/`, gitignored).

### 1.1 Correction and Follow-Up Findings (2026-07-20)

- **The C front end's source is in fact public**: the GitLab group `malbolge` holds 5 repositories in total; `highlevel` (C subset → .mg) and `highlevel-examples` are not linked from the project homepage and can only be discovered via the GitLab API. This document's earlier conclusion that "the front-end source is not public" is retracted.
- `highlevel` kept evolving after the 2017 paper: subtraction, the full set of comparison operators, boolean operations, and compound assignment are all implemented (partially clearing the paper's "今後の課題" / future-work section); in 2018-03 Iwagane (岩金) added array support (with no accompanying paper). Only multiplication/division are still missing.
- **End-to-end verification**: `highlevel-examples/while.c` (while + comparison + ++) compiles through highlevel → ternary → lowass into a 5.8MB .mb; pyMalbolge outputs `abcde` in 3.6 seconds, byte-exact with the reference C interpreter — the four-stage pipeline is usable today.
- Research-line activity: code activity stops in 2021-01, papers stop in 2017-08, and the homepage has long read "under construction"; Sakai (酒井) himself is still active but has moved to other research directions. Judged dormant, with no team carrying it forward.
Project page: https://www.trs.css.i.nagoya-u.ac.jp/projects/Malbolge/
(roughly 8 IEICE technical reports between 2010–2017, in Japanese, PDFs downloadable).

### The HeLL/LMAO Lineage (Target: Original Malbolge + Unshackled, GPL-3)

- HeLL + LMAO (original), LMFAO (Unshackled): assembler-level tooling, no high-level language front end.
- MalbolgeLISP (Kamila Szewczyk, 2020-21): a 350MB LISP interpreter, **hand-written** in a HeLL dialect (a cryptanalysis-style method), not the output of a compiler.
- See `docs/hell-spec.md`, `docs/lmao-internals.md`, `docs/hell-assembler-design.md` for details.

### Revised Conclusion

The earlier judgment that "the high-level-language front end is a blank spot" was inaccurate: Nagoya did build a C-subset compiler. The real gaps are: **(a)** the C front end's source was not public (only the paper was); **(b)** there is no Python front end at all; **(c)** the Nagoya stack lacks a modern, actively maintained runtime — which is exactly where pyMalbolge fits.

## 2. This Round's Verification (pyMalbolge Can Now Serve as the Nagoya Stack's Runtime)

- `hello20.mb` (an artifact of the Nagoya LAL toolchain) runs on pyMalbolge: it outputs `HelloWorld` in 46,417 steps and 0.6 seconds, matching the reference C interpreter (commit 57b7f10).
- Two deviations from the reference implementation were fixed along the way: A=59049 on EOF (not 3^20-1); SparseMemory was changed to the same chunked lazy-initialization scheme as the reference implementation (a per-trit seed jump table — the jump table we derived independently from the crazy table matches its hard-coded num0/num1 tables exactly).

## 3. Feasibility Assessment

- **Original Malbolge (59,049 cells) is not a suitable compilation target**: measured, LMAO's adder example (decimal addition only) already occupies 55.7K cells ≈ 94% of memory. It's only good enough for toy text generators.
- **Malbolge20 is the right target**: with a 3^20 address space, the Nagoya stack proves that a C subset (with recursion) can be compiled and deployed; pyMalbolge can now run its output.
- **"Real Python" is infeasible, but a Python subset is feasible**: objects/closures/exceptions/bignums are beyond reasonable engineering effort; integer variables, while/if, functions (recursion), one-dimensional arrays, and character I/O map one-to-one onto the pseudo-instruction layer's capabilities.
- **License is clean**: all three Nagoya repositories are MIT, with none of LMAO's GPL-contagion concerns.

## 4. Recommended Path

```
Python subset (.py)
   │  ← the only new component we need to write (pure Python)
   ▼
Pseudo-instruction language (.mg)
   │  ternary (off-the-shelf, MIT; can be Pythonized later)
   ▼
LAL (.mc)
   │  lowass (off-the-shelf, MIT; can be Pythonized later)
   ▼
Malbolge20 (.mb)
   │  pyMalbolge (already ready)
   ▼
Run / debug (TUI debugger supports --variant=malbolge20)
```

### Milestones

- **P1 Get the pipeline working**: build ternary + lowass, get `.mg → .mc → .mb → pyMalbolge` running end to end, and land examples in `test/fixtures/` (pseudo-instruction-layer conformance).
- **P2 Learn the language + build the front end**: study ternary's grammar files and the 2016/2017 papers closely (Japanese, needs translation), define the Python subset, write the `python → .mg` compiler.
- **P3 End to end**: compile hello / loops / recursive fib from Python source to Malbolge20 and verify by running them in the test suite.
- **P4 Full pure-Python toolchain (complete)**: all three of highlevel/ternary/lowass ported to pure Python (`malbolge/compiler/{c2mg,mg2mc,mc2mb}.py`), verified against the C/C++/Perl originals via byte-exact (or behavioral) differential comparison; `compile_python_to_mb()` runs the entire chain in a single call, with no external build dependency and full determinism end to end. The `ref/` tools are downgraded to conformance-testing use only. See `docs/findings.md` B6 for details.

### Relationship to the HeLL Assembler Plan

The LMAO porting plan in `docs/hell-assembler-design.md` **is retained but downgraded to a backup option** (serving original Malbolge's research value); the main line shifts to the Nagoya stack, for these reasons: the target (Malbolge20) has ample memory, a clean license, ready-made high-level components, and pyMalbolge has a clear, unique position in that ecosystem (the only modern runtime + debugger).

## 5. Python Front End (v1 Implemented)

`malbolge/compiler/` implements the last piece of this path: a transpiler from the **Python subset → the Nagoya high-level C subset**. After P4, the three downstream stages are also all pure-Python ports within this package (verified against the reference implementation via byte-exact differential comparison, see `docs/findings.md` B6); the complete pipeline is self-contained, deterministic, and free of external dependencies:

```
Python subset (.py)
   │  py2c.py (stdlib ast)                     ┐
   ▼                                           │ py2mg.py (direct backend,
Nagoya high-level C subset (.c)                │ skips the C layer, see §5.1)
   │  c2mg.py (pure-Python port of highlevel)  │
   ▼                                           ┘
Pseudo-instructions (.mg) ◄────────────────────┘
   │  mg2mc.py (ternary port)
   ▼
LAL (.mc)
   │  mc2mb.py (lowass port, deterministic padding)
   ▼
Malbolge20 (.mb) → run / debug with pyMalbolge
```

### Usage

```bash
# Transpile to C only (defaults to stdout; --emit-mg/--emit-mc can export intermediate layers)
python3 -m malbolge compile prog.py --emit-c prog.c

# Full pipeline producing a runnable .mb (pure Python, no ref/ tools needed)
python3 -m malbolge compile prog.py -o prog.mb
python3 -m malbolge --variant=malbolge20 prog.mb

# Direct backend: skips the C layer, output is typically 46-75% smaller, natively supports double recursion
python3 -m malbolge compile prog.py --backend=direct -o prog.mb
```

```python
from malbolge.compiler import compile_python_to_c, compile_python_to_mb
c_source = compile_python_to_c("putchar(72)\nputchar(105)\n")
mb = compile_python_to_mb(source, backend="direct")   # direct backend
```

### 5.1 Direct Backend (py2mg, v0 Implemented)

`py2mg.py` generates `.mg` directly from the Python AST, reusing c2mg's already-validated code-generation primitives, but swaps out the stack-frame strategy: each function's temporaries are declared inside its own `DEF`, real recursion-cycle detection is performed (c2mg treats all recursion as worst-case), and only temporaries that survive across a call are protected. As a result, **double recursion `fib(n-1) + fib(n-2)` is correct by construction** — it eliminates upstream bug A2 at the root, rather than sidestepping it via three-address form. On programs with control flow/functions, the output is 46-75% smaller than the `c` backend, and never larger. See `docs/py2mg-backend.md` for the design document; the two backends' language subsets are strictly identical, and e2e testing does a byte-exact differential comparison of program output.

### Supported Python Subset

- Integer variables, assignment, multi-target assignment `a = b = expr`; augmented assignment `+= -= *= //= %=`.
- `if / elif / else`; `while` (including truthiness testing `while x:`); `for i in range(n) / range(a,b) / range(a,b,step)` (step must be a positive integer literal, desugared to while).
- Function `def` (positional parameters, `return`, recursion, mutual recursion); `global` declares a write to a global variable.
- `break` / `continue` (flag lowering: each loop level gets a `skip`/`brk` flag pair, statements are guarded by `if(skip==0)`, nested loops don't interfere with each other, and a for loop's step still executes on `continue`).
- Conditional expression `a if c else b` (lowered to a temporary + a real if/else, lazily: only the selected branch's side effects occur).
- Arithmetic `+ - * // %`; comparisons `== != < > <= >=` (including chained `a < b < c`); booleans `and / or / not` (short-circuiting).
- Builtins: `putchar(x)`, `getchar()`, `ord('c')` (constant-folded at compile time); `print()` — arguments must be compile-time constants (string literals, foldable integer expressions, f-strings whose every part is constant; `sep=`/`end=` must be constant strings), lowered to a chain of putchar calls.
- Constant expressions are folded at compile time mod 3^20 (e.g. `9 * 7 + 2` → `65`).
- Docstrings are tolerated (only as the **first** statement of a module / function body).

### Explicit Capability Boundaries (friendly errors, with line numbers and source snippets)

- **No negative numbers**: unary minus / negative literals are rejected (the value ring mod 3^20 has no negatives; `3 - 5` folds to a large positive number, and `x < 0` is always false).
- **No true division**: `/` and `/=` are rejected, with a hint to use `//` instead.
- **`print()` only accepts constants**: arguments whose value is only known at runtime (variables, function return values) are always rejected, with the error pointing to `putchar`; integers are rendered as decimal using their folded mod-3^20 value.
- Not supported: `chr`, runtime strings / f-strings, floats, lists / dicts / sets, classes, `import`, `lambda`, comprehensions, nested functions, tuple-unpacking assignment, keyword arguments.
- Identifiers must start with a letter, and non-ASCII identifiers are rejected; the `zz` prefix is reserved for compiler internals; variables sharing a name with a C keyword (`int`/`while`/`main`/`putchar`/…) are rejected; function names get upper-cased in the backend, and same-name (case-insensitive) collisions are rejected.

### Implementation Notes (Why It's Designed This Way)

The backend C subset has several confirmed pitfalls (found through testing); the transpiler is designed around them:

- **No operator precedence**: `a < b && c` parses as `a < (b && c)`. So every expression is unconditionally lowered to three-address form (each statement has at most one binary operation, with operands that are bare variables or literals).
- **`bool` / `true` / `false` are broken**: internal constants have the same value as `TRUE_VAL`/`FALSE_VAL` and are registered as `INT`; the constant cache is named by value, which causes boolean literals to get the wrong type and assigning to a bool variable to raise "Type mismatch". So the transpiler **never emits `bool`/`true`/`false`**; booleans are always materialized as `int` 0/1 through control flow (`flag = 0; if(cond){ flag = 1; }`, then `while(flag != 0)` / `if(flag != 0)`).
- **No `* / %` operators**: the C-subset library functions `zzmul` (double-and-add, ~32 additions), `zzdiv` / `zzmod` (long division) are injected on demand and emitted only when actually used; division by zero returns 0 to avoid infinite loops. These library functions' algorithms have been exhaustively regression-tested via a pure-Python port (see `test/test_py2c.py::TestHelperAlgorithms`).
- **Identifiers must start with a letter**, **local declarations must precede statements**, and **declarations can only be initialized with literals**: so all local / temporary variables are declared up front, with all initialization done via runtime assignment; module-level variables are declared as top-level globals (so functions can read them), with their initial values assigned inside the generated `main()`.

### Tests

- `test/test_py2c.py`: pure transpilation unit tests (no dependency on ref tools) — emission structure, constant folding, temporary-variable expansion, library-function injection, error cases, library-function algorithm regression.
- `test/test_py2c_e2e.py`: two layers, both auto-skipped when the ref tools are absent — a parser-acceptance layer (the generated C passes `ref/nagoya-highlevel/parser`) and a full-pipeline end-to-end layer (Python → `.mb`, then run and assert on the output). End-to-end assertions prefer the **C reference interpreter** (`ref/nagoya-malbolge20-interpreter/malbolge20`, 15-100x faster than pyMalbolge), with pyMalbolge additionally cross-checked for matching output on two small cases, hi / echo.

### Known Trade-offs

- The runtime `zzmul` / `zzdiv` / `zzmod` are correct but expensive on Malbolge20 (a single multiplication's `.mb` can reach ~100MB and take minutes to run). **Constants that fold at compile time incur no runtime cost for multiplication/division/modulo**; so the e2e multiplication test cases go through constant folding, with the runtime library functions' correctness guaranteed by the pure-Python exhaustive regression described above. Programs with user-defined functions blow up noticeably in size on this toolchain (a single function alone can reach ~50MB).
- **An upstream recursive-code-generation bug, and how this front end sidesteps it**: when hand-written C **inlines two recursive CALLs in the same expression** (the classic `return fib(n-1) + fib(n-2)`), the code highlevel generates gives wrong results starting at fib(4) (fib(4) comes out 2 instead of 3; the second CALL fails to preserve the first call's intermediate result on the stack); pyMalbolge agrees with the official C reference interpreter, confirming this is an **upstream compiler** bug. **This front end is unaffected**: since "no operator precedence" already requires lowering every expression to three-address form, the transpiler never generates an inlined double CALL — it emits `t0 = f(a); t1 = f(b); r = t0 + t1;` instead. Testing (with the C reference interpreter) confirms this form gives **correct** results: the classic Python double recursion `fib(n-1)+fib(n-2)` compiles to fib(4)=3, fib(5)=5, both correct. In other words, the three-address decomposition happens to sidestep this upstream bug as a side effect. **The direct backend (§5.1) doesn't produce this bug in the first place**: it does its own recursion-cycle detection and cross-call liveness protection, and doesn't rely on the accidental sidestep from three-address form.
- **Size**: programs with user-defined functions blow up noticeably on the `c` backend; switching to `--backend=direct` is typically 46-75% smaller. See `docs/findings.md` §I for the `.mb`-size cost model and optimization investigation.
