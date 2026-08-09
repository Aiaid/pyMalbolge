# The `.mg` (制御付き疑似命令列) Language Specification

> [中文](mg-spec.zh.md) | **English**

> This document was compiled by line-by-line verification against `ref/nagoya-ternary/scanner.ll`,
> `parser.yy`, `CodeBlock.cc`, `Routine.cc`, `Program.cc`, `Variable.cc`, `Radix.cc`,
> `Option.cc`/`main.cc`, and cross-checked item by item against five sources: the original 2016
> intermediate-language paper (Kawabe et al., "難読性の高い Malbolge コードを生成するコンパイラ
> のための中間言語" [An intermediate language for a compiler generating highly obfuscated Malbolge
> code], IEICE Tech. Rep. SS2016-12), the 2017 function-extension paper (Sakanashi et al.,
> "再帰呼び出しを持つ C 言語サブセットから Malbolge へのコンパイラ" [A compiler from a C subset
> with recursive calls to Malbolge], IEICE Tech. Rep. SS2017-18), `ref/nagoya-ternary/README.en.md`,
> and the `test/fixtures/nagoya/mg_*.mg` examples. Roughly 20 uncertain points of syntax were
> settled by actual compilation experiments using `ref/nagoya-ternary/parser` (the tool itself);
> see "Experimentally verified points of syntax" at the end and the notes in each section.
> It serves as the implementation basis for pyMalbolge's Python `.mg` (→ `.mc` low-level assembly)
> compiler back-end.
> Compiled on: 2026-07-20.

`.mg` is the file extension for "制御付き疑似命令列" (pseudo-instruction sequences with control,
hereafter "pseudo-instruction sequences"). It is the input language of the
`ref/nagoya-ternary/parser` tool, and compiles to "Low-Level Assembly" (LAL, `.mc`), which the
`ref/nagoya-lowass` toolchain then transforms into a runnable Malbolge20 program (`.mb`). For the
full pipeline see `scripts/mg2mb.sh`.

---

## 1. Lexical structure (from `scanner.ll`)

### 1.1 Identifiers and keywords

- Identifiers: `[a-zA-Z][0-9a-zA-Z_]*`, case-sensitive, unlimited length.
- The following are all **reserved-word tokens**, matched exactly and taking priority over the
  general identifier rule (under flex's longest-match semantics, only input **exactly as long as**
  the keyword is recognised as that keyword; longer identifiers such as `CON00` or `RETURN_VALUE`
  are still parsed as IDENT and are unaffected):
  `DEF VAR FLAG OPR ROT SET RESET END IF ELSE REPEAT BREAK SWITCH CASE0 CASE1
  CASE2 OUTPUT INPUT TRUE FALSE INF GOTO IND_OPR CALL RETURN PROTO FLIP CON0
  CON1 CON2 BASE RETURN_ADDR`.
  A variable or routine name therefore MUST NOT be **exactly** one of these words (including
  deceptively usable-looking names such as `CON0`, `BASE`, `RETURN_ADDR`), but `MyCon0`,
  `baseAddr` and the like are fine.
- The parser automatically prefixes user identifiers with `U_`
  (`escaped_ident: IDENT {$$ = "U_"+$1;}`) to avoid clashes with internal labels emitted into the
  low-level assembly. This is invisible at the `.mg` source level and needs no attention when
  writing code.

### 1.2 Numeric literals

The `number` production (`parser.yy:83-85`) accepts only two kinds of **literal**; no expressions,
operators or variables are supported:

| Notation | Regex (scanner.ll) | Semantics |
|---|---|---|
| Decimal | `[0-9]\|[1-9][0-9]*` | A single `0`, or a decimal number without leading zeros. **A multi-digit number with leading zeros such as `007` is a lexical error** (experimentally verified: it is split into the three tokens `0`/`0`/`7` and reported as `syntax error`). |
| Ternary | `[0-9]+t` | The trailing `t` is stripped and the rest interpreted by `Radix::to(s, 3)`: left to right, `sm = sm*3 + digit`. **⚠ The regex allows any `0-9` digit character, and the interpretation does not check that each digit is ≤ 2** — for example `39t` is accepted as a valid literal and evaluates to `3*3+9=18` (experimentally confirmed: no error, no warning). This is a trap where the notation is nominally "ternary" yet the lexer performs no digit-value validation at all; the Python implementation is advised to actively check that every digit ∈ {0,1,2} and raise an error rather than reproduce this oversight. |

Both notations yield a `long long` integer, with **no upper-bound check whatsoever** (`Radix.cc`
performs no overflow or range test anywhere). The "values are non-negative and ≤ 3^20-1" statement
in CLAUDE.md is a hardware constraint of the Malbolge20 word (20 trits), but **the `.mg` compiler
itself does not enforce it at all** — writing an out-of-range value silently produces wrong results,
and it is up to the user (or a future Python back-end) to police this. Negative literals are also
unsupported (neither the lexer nor the grammar has a unary minus).

### 1.3 Comments and whitespace

- Line comments: `#` to end of line (`#[^\n]+`). There are no block comments.
- Whitespace: spaces, tabs and newlines are all skipped and carry no significance for statement
  boundaries (unlike HeLL, where blank lines delimit blocks).

### 1.4 Unknown characters

For any character not matching the rules above, the scanner merely prints
`cannot handle such characters: %s` to stderr and **continues scanning** (this is not a fatal error;
it usually cascades into a genuine syntax error later).

---

## 2. Grammar (per `parser.yy`)

```ebnf
program              ::= global_var_flag_decl* prototype* routine+

global_var_flag_decl ::= var_decl
                        | "FLAG" IDENT "=" bool_const

prototype             ::= "PROTO" IDENT

routine               ::= "DEF" IDENT var_decl* block "END"

var_decl              ::= "VAR" IDENT "=" number          /* number: see 1.2, literals only */

block                 ::= statement*

statement              ::= "OPR" variable
                        | "ROT" variable
                        | "IND_OPR" variable
                        | "OUTPUT"
                        | "INPUT"
                        | "SET" flag
                        | "RESET" flag
                        | "FLIP" flag
                        | "IF" flag block "ELSE" block "END"
                        | "REPEAT" repeat_number block "END"
                        | "BREAK" [number]
                        | "SWITCH" variable case0 case1 case2 "END"
                        | "CALL" IDENT
                        | "RETURN"

repeat_number          ::= number | "INF"

case0                  ::= ("CASE0" block)?      /* absent = empty block; a CASE may be omitted */
case1                  ::= ("CASE1" block)?
case2                  ::= ("CASE2" block)?

variable                ::= variable_str
                          | variable_str "@" IDENT        /* cross-routine reference */
variable_str             ::= IDENT | "CON0" | "CON1" | "CON2" | "BASE" | "RETURN_ADDR"

flag                    ::= IDENT
```

**A crucial point that is easy to get wrong**: the tables in the 2016 and 2017 papers use `IFEND`,
`REPEATEND` and `SWITCHEND` as "conceptual" end markers, but those are merely mnemonic notation in
the prose of the papers — **the actual scanner/parser has no `IFEND`/`REPEATEND`/`SWITCHEND` tokens
at all** (they appear nowhere in `scanner.ll`). All four block forms — `IF...ELSE...END`,
`REPEAT...END`, `SWITCH...END`, `DEF...END` — **are terminated by the same single `END` keyword**,
with nesting resolved by the LALR grammar structure rather than by distinct keywords. When writing
`.mg` source, or building a lexer/grammar table in Python, there MUST be exactly one `END` token.
(Experimentally verified with `ref/nagoya-ternary/parser`: writing `SWITCHEND` yields
`syntax error`; only `END` is accepted.)

All three of CASE0/CASE1/CASE2 may be omitted (an omitted case is an empty block), and their order
is **forced** by the grammar to be `CASE0 → CASE1 → CASE2` (the productions are in fixed order).
They cannot be reordered, nor can a middle label be skipped while keeping the others out of order
(e.g. writing only CASE0/CASE2 with no CASE1 is fine — the empty production takes over — but the
CASE0 and CASE2 that *are* present must still appear in 0,1,2 physical order).

`prototypes` MUST appear as a group before **all** `routine`s (i.e. a `PROTO` cannot be sandwiched
between two `DEF`s). This is dictated by the grammar structure, not a style recommendation.

---

## 3. Program structure and scoping

### 3.1 Global vs. routine-local

- The top level of `program` (before all `DEF`s) admits two kinds of declaration: global `VAR`
  (which goes into an internal `GLOBAL` pseudo-routine) and global `FLAG`.
- **`FLAG` can only be declared at the top level** and cannot appear inside `DEF...END` — the
  grammar simply has no such production (experimentally verified:
  `DEF MAIN FLAG F = TRUE ... END` is an outright `syntax error`). All flags are inherently global.
- Inside a `DEF...END`, `VAR` declarations MUST **all be grouped at the very beginning of the
  routine, before any statement** (the `var_decl_list` production precedes `block`; they cannot be
  interleaved). Experimentally verified: writing `VAR X = 5` after an `OUTPUT` yields
  `syntax error` — it is not "allowed but scoped narrowly".
- Name resolution for variables (`parser.yy:150-160`): a bare `X` is looked up first among the
  current routine's locals, then in the global (`GLOBAL`) routine; if still not found it is an
  `Undefined variable` semantic error. **A local variable shadows a global of the same name.**
- To reference another routine's **local** variable, write `X@RoutineName`
  (`variable_str AT IDENT`). If the target routine has not yet declared that variable, the parser
  **creates a placeholder variable up front** (`is_defined=false`) and requires the routine to
  genuinely define it later with `VAR X = ...`; otherwise the final `generate()` stage reports
  `Variable 'X@RoutineName' is not defined.` This makes "MAIN references a variable declared later
  in SUB" a legal forward reference as far as the notation goes (experimentally verified).

### 3.2 Built-in global identifiers: `CON0` / `CON1` / `CON2` / `BASE` / `RETURN_ADDR`

These five are not user identifiers but dedicated lexer tokens (`scanner.ll:54-68`), corresponding
to global variables created automatically by the `Program` constructor (`Program.cc:3-17`)
(Malbolge20, 20-trit word):

| Name | Value | Notes |
|---|---|---|
| `CON0` | `0` | |
| `CON1` | `1743392200` | `= (3^20-1)/2`; used internally for `CALL`/`RETURN` address arithmetic |
| `CON2` | `3486784400` | `= 3^20-1`, i.e. the "all-2s value" with all 20 trits equal to 2; the legal operands of `SWITCH` are all adjacent to it (see 5.6) |
| `BASE` | `0` | |

An ordinary `.mg` program generally does not need to use them directly (they mainly exist as shared
constants borrowed by the compiler when generating `CALL`/`RETURN`/`SWITCH` code), but the grammar
does allow passing them to `ROT`/`OPR` like ordinary variables (`test/fixtures/nagoya/mg_e_call.mc`
shows the hand-written idiom `ROT CON2 / OPR CONST_x` for "subtracting via CON2", taken from
`sample/hello-transFrom-c.mg`). `RETURN_ADDR` is only meaningful in combination with `@RoutineName`
(referring to the variable in which some routine saves its return address); a bare `RETURN_ADDR`
(without `@`) refers to the *current* routine's own `RETURN_ADDR`, and only routines other than
`MAIN`/`GLOBAL` automatically get that variable (`Routine.cc:9-11`).

---

## 4. Instruction semantics

The semantics below are synthesised from tables 4/5 of the 2016 paper (basic pseudo-instructions +
control instructions), table 7 of the 2017 paper (including the function / `IND_OPR` extensions),
and the source implementation, with each item mapped onto the existing implementation in
`malbolge/core.py`. `A` denotes the Malbolge accumulator register; `X`/`[X]` denotes the current
value of the memory cell corresponding to variable `X`.

### 4.1 `ROT X` — rotate in place

**`A, [X] := rotr([X])`**: take the current value of `X`, apply Malbolge's native "right rotation"
(i.e. `rotate()` in `malbolge/core.py`, a cyclic right shift of the whole 20-trit word by one
position — not a shift by an arbitrary number of positions), and write the result **both** to the
`A` register and back to `X`'s memory cell (**modified in place**, not read-only).

⚠ `ROT X` therefore has a side effect: every `ROT` of the same variable inside a loop body rotates
its value permanently once more. The comments in `test/fixtures/nagoya/mg_d_repeat.mg` call this out
specifically — to output the same value repeatedly, do a single `ROT` outside the loop to get the
value into `A`, and use only `OUTPUT` (which leaves `A` untouched) inside the loop.

### 4.2 `OPR X` — the crazy operation

**`A, [X] := crazy(A, [X])`**, where `crazy` is the very same table as
`malbolge/core.py:crazy(a, b, trit_width)` (the ternary digit-wise truth table of Malbolge's native
`OPR`/`p` instruction), with `a=A` (old value) and `b=[X]` (old value). The result is likewise
**written back in place** to both `X` and `A`.

### 4.3 `INPUT` / `OUTPUT`

- `INPUT`: `A := getchar()`; EOF behaviour matches the underlying Malbolge20 interpreter (see the
  existing EOF handling in `malbolge/malbolge20.py`; it is not a new rule introduced at the `.mg`
  level).
- `OUTPUT`: `putchar(A)`, i.e. output the byte corresponding to `A mod 256`.
- Neither **modifies** any memory other than `A` (unlike `ROT`/`OPR`, which also modify a variable);
  this is exactly why the `mg_d_repeat.mg` example uses only `OUTPUT`, not `ROT`, inside the loop
  body.

### 4.4 `IND_OPR X` — indirect crazy operation (array / pointer access)

**`A, [[X]] := crazy(A, [[X]])`** (table 13 of the 2017 paper; note the **double indirection**
`[[X]]`, not `[X]`). The essential difference from `OPR X`: `OPR X` operates on variable `X`'s own
storage cell (an address fixed at compile time), whereas `IND_OPR X` **treats the value currently
stored in `X` as a memory address** and performs the crazy operation on the memory at that address.
This is the only instruction in `.mg` capable of "deciding at run time which memory cell to operate
on", and it is what arrays and stacks are built from (2017 paper §5–7: array indexing and the
`PUSH`/`POP` recursion stack are all syntactic sugar hand-written on top of `IND_OPR`; `.mg` itself
has no dedicated array or stack syntax). After execution, control flow jumps to `MAIN`'s entry and
loops back around (`PC := ENTRY@MAIN`); this implementation detail belongs to the LAL back-end and
`.mg` users need not care about it — only that this is the "heaviest" instruction in the current
implementation.

### 4.5 `FLAG` / `SET` / `RESET` / `FLIP` / `IF...ELSE...END`

- `FLAG name = TRUE|FALSE`: declares a global boolean flag; initial value `TRUE` → internal
  `FLAG_ON`, `FALSE` → internal `FLAG_OFF`.
- **Flag period mechanism**: the `FLAG` concept at the LAL level itself supports periods
  `p ∈ {2,4,5,6,9}` (note on table 1 of the 2016 paper), with values `0..p-1` where `0` means `ON`
  (active) and the rest mean `OFF`; **each time the flag is checked (executed) by `IF`/`NEXT`, the
  internal counter goes `+1 mod p`**. But the `.mg` grammar itself **exposes only boolean
  `TRUE`/`FALSE` declarations**, and every flag the compiler generates for `.mg` (both user-declared
  ones and internal bookkeeping ones such as `FLAG_JMP`, `FLAG_CASE0..2`, `FLAG_REV_OPR_ROT`) has
  **period 2** (`Program.cc` creates all flags with `p=2`). In other words, `.mg`-level flags are
  always strictly two-valued; periods 4/5/6/9 are a LAL-level capability reserved for other
  (non-`.mg`) uses, and the `.mg` compiler never generates them.
- `SET flag`: forces the flag to `ON` regardless of its prior state. The implementation is a
  self-jump trick (figure 8 of the 2016 paper): `Label: IF flag; BRANCH Label`. Because each `IF`
  check automatically advances the flag by `+1 mod 2` (i.e. toggles it), this self-loop runs at most
  twice and necessarily exits with `flag=ON`: when `ON` it jumps to itself (checking again, becoming
  `OFF`); when `OFF` it does not jump, but that check has just toggled the flag back to `ON`, so the
  state on leaving the loop is invariably `ON`.
- `RESET flag`: implemented as "the same code as `SET` plus one extra `NEXT flag` at the end"
  (stated explicitly in §5.3 of the 2016 paper), i.e. first converge the flag to `ON` with the same
  self-loop, then toggle once explicitly to make it `OFF`.
- `FLIP flag`: translated directly into a single `NEXT flag` (`CodeBlock::flip`,
  `CodeBlock.cc:394`) — because `.mg` flags always have period 2, `NEXT` (counter +1 mod 2) is
  equivalent to an unconditional toggle. `FLIP` performs no check and no branch; it merely switches
  state, which is semantically different from `SET`/`RESET` (which converge to a definite state).
- `IF flag BLOCK1 ELSE BLOCK2 END`: executes `BLOCK1` when `flag` is `ON`, otherwise `BLOCK2`; both
  paths rejoin after `END`. **The `ELSE` branch MUST NOT be omitted** (the grammar has no production
  for an `IF` without `ELSE`; the only option is an empty block after `ELSE`).

### 4.6 `REPEAT n BLOCK END` / `BREAK [n]`

- `REPEAT n`: `n` is a compile-time constant (a decimal or ternary literal — **not a variable or
  expression**; the `repeat_number` production accepts only `number` or the keyword `INF`), and the
  body executes exactly `n` times. Code generation **does not simply unroll n copies**; instead `n`
  is decomposed into binary digits and a binary down-counter is built from `O(log2 n)` "counting
  flags", exploiting the "a flag advances by +1 on every check" property (`CodeBlock::repeat`,
  `CodeBlock.cc:246-300`; the principle is described in §5.4 of the 2016 paper). Hence code size
  does not blow up linearly for large `n`, and the loop body itself appears only once.
- `REPEAT INF`: an infinite loop; it MUST be exited via an internal `BREAK`, otherwise the code
  after `REPEAT...END` is never reached (it loops until the program is terminated externally).
- `BREAK` is equivalent to `BREAK 1` and exits the innermost `REPEAT`; `BREAK n` exits the `n`
  innermost nested `REPEAT`s (`n` is likewise a literal constant and MUST NOT be a variable). If `n`
  exceeds the actual nesting depth, the semantic error `There is no 'REPEAT' to break` is reported
  (**experimentally verified**: `REPEAT 5 { BREAK 2 }` — only one level of nesting yet `BREAK 2` —
  reproduces this error exactly). Nesting depth is counted **within a single `DEF...END` routine**
  (`Routine::num_of_repeat_nested`) and does not propagate across `CALL`.

### 4.7 `SWITCH X CASE0 ... CASE1 ... CASE2 ... END`

**Branches on the least significant trit of `X`** (the units digit, the last ternary digit): a trit
of 0/1/2 executes the block of `CASE0`/`CASE1`/`CASE2` respectively (an omitted CASE counts as an
empty block).

**Precondition (the "制約" [constraint] as stated in table 5 of the 2016 paper)**: **every** trit of
`X` other than the least significant one MUST be `2`. That is, for Malbolge20 (20 trits), the value
of `X` before `SWITCH` executes **can only be** one of the following three:

```
CON2 - 2 = 3486784398   (last trit = 0 → CASE0)
CON2 - 1 = 3486784399   (last trit = 1 → CASE1)
CON2     = 3486784400   (last trit = 2 → CASE2)
```

This is no coincidence: in code generation, `SWITCH X` simply `JMP`s to the memory address of the
variable `X` itself (`Instruction::JMP(var_label_inst)` inside `CodeBlock::switch_statement`,
`CodeBlock.cc:313`), relying on the fixed-cell technique at the Malbolge / low-level-assembly level
whereby "three literals adjacent to the all-2s value, when executed as instructions, happen to
produce a three-way branch after the xlat2 transformation" (the same idea as `immutable_nops`/SNOP
in §3.1 of `docs/specs/hell-spec.md` — both exploit the fact that certain byte values have well-defined
behaviour under the xlat2 table). **Neither `.mg` nor `ref/nagoya-ternary/parser` checks this
constraint statically at all** — code where `X` holds some other value still compiles, and only at
run time produces "予測不能な動作" (the 2016 paper's own wording: unpredictable behaviour — not a
crash and not an error, but taking an undefined branch / executing undefined memory contents). The
usual idiom in `.mg` source is therefore to set `X` to exactly one of the three values above using
`ROT`/`OPR` first, and put `SWITCH X` immediately afterwards.

**The value of `X` after a `CASE` runs**: since `SWITCH` works by "jumping into `X`'s memory address
and executing what is there (after the xlat2 transformation)", and since that cell is
self-modified by xlat2 after every instruction Malbolge executes, **once `SWITCH` has finished, the
"all-2s value + last trit" encoding originally stored in `X` has been destroyed and is no longer a
meaningful ordinary variable value**. The `.mg` grammar does not stop you from applying `ROT`/`OPR`
to the same `X` after `SWITCH X ... END`, but semantically it MUST be treated as undefined unless
`X` is explicitly reset to a known value with `ROT`/`OPR`.

`SWITCH` may be nested arbitrarily inside `REPEAT`/`IF` and vice versa (see the experiments in
§5.2).

### 4.8 `DEF name ... END` / `PROTO name` / `CALL name` / `RETURN`

- A program MUST have exactly one `DEF MAIN`; it is the program entry point (`Program::generate()`
  unconditionally emits `PROGRAM_START_TO ENTRY@MAIN`). **The `.mg` compiler does not check whether
  `MAIN` is actually defined** — omitting `DEF MAIN` still compiles successfully (exit code 0, no
  diagnostics), it just leaves `ENTRY@MAIN` as a dangling reference in the generated `.mc`, which
  the subsequent `.mc → .data` assembly stage will most likely reject or turn into garbage
  (experimentally verified: with a single `DEF FOO` and no MAIN, the top of the `.mc` still hard-codes
  `PROGRAM_START_TO ENTRY@MAIN` while the whole output contains no `ROUTINE MAIN{` block at all).
- `PROTO name`: declares a routine prototype (allowing it to be referenced by `CALL`/`@name` before
  its actual `DEF`). **All `PROTO`s MUST appear as a group before all `DEF`s** (dictated by the
  grammar structure; see §2).
- **Forward-call rule**: calling a routine that is *physically written later* requires a `PROTO`
  first, otherwise it is an `Undefined routine` semantic error (experimentally verified). Calling a
  routine *physically written earlier* (already `DEF`ed) needs no `PROTO` (experimentally verified).
- ⚠ **A `PROTO` that is never followed by an actual `DEF` is not a compile error — the `parser`
  simply crashes (SIGSEGV, exit code 139)** — experimentally reproduced (`PROTO FOO` + `CALL FOO`
  with no `DEF FOO` anywhere). The Python back-end MUST perform its own static check that "every
  `PROTO` has a matching `DEF`" and MUST NOT rely on the reference implementation's error handling
  (it performs no such check at all).
- **Functions take no parameters and return no value** (an explicit design trade-off, 2017 paper
  §4.1): no data is passed between `CALL` and `RETURN`; passing data requires manual reads and
  writes through global variables or `variable@RoutineName`.
- **Recursion is unsafe**: `RETURN` is implemented by storing "the address after the call site" in
  the **single** `RETURN_ADDR` variable dedicated to that routine, then reading it back with `DJMP`
  (dynamic jump) to return (2017 paper §4). The grammar does nothing to prevent a routine from
  calling itself or a call chain from forming a cycle (experimentally verified:
  `DEF SUB { CALL SUB; RETURN }` compiles with no warning), but since there is only one storage slot
  for `RETURN_ADDR`, **re-entry (recursion / cycles) overwrites the outer return address before the
  outer call has returned**, causing a return to the wrong location. This is precisely why the 2017
  paper introduces, at a higher level (the C-subset compiler, not `.mg` itself), a hand-written stack
  built on `IND_OPR` (`PUSH`/`POP`, figure 17 of the paper) to support genuine recursion — the `.mg`
  language itself has no built-in recursion support, and writing recursion means implementing your
  own call stack.
- **`RETURN` inside `MAIN` means "terminate the program", not "return to the caller"**:
  `CodeBlock::func_return` (`CodeBlock.cc:385-392`) special-cases `routine->name == MAIN_ROUTINE` —
  only in a non-`MAIN` routine does `RETURN` compile to a `DJMP` back to the call site; **inside
  `MAIN`'s own body, `RETURN` compiles to an unconditional `END` (terminating the entire program)**.
  This matches the intuition of C's `return` from `main()`, but it means `MAIN` cannot be used as an
  ordinary routine that can be `CALL`ed and "return" normally.
- **A routine body that "runs off the end" without an explicit `RETURN` does not perform a safe
  implicit return — it terminates the whole program**: at the end of every `DEF...END`,
  `Routine::end()` (`Routine.cc:248-252`) always appends an unconditional `END` instruction to the
  end of the routine's main code block. If the routine ends with an explicit `RETURN`, this appended
  `END` is unreachable dead code (verified against the compilation output of
  `test/fixtures/nagoya/mg_e_call.mg`); but **if the routine falls through to `END` without a
  closing `RETURN`**, that appended `END` is genuinely executed — **terminating the entire program
  there instead of returning to the caller** (experimentally reproduced: after `DEF SUB {OUTPUT}` is
  `CALL`ed, the `LABEL1: END` generated at the end of `SUB` really is reachable code). Therefore
  **every routine other than `MAIN` MUST end with an explicit `RETURN`** — a hard constraint that is
  never checked syntactically but whose violation causes the program to "mysteriously exit early" at
  run time.

---

## 5. Nesting rules (experimentally verified)

Compiling straight to `.mc` with `ref/nagoya-ternary/parser -s 1 <file.mg>` and checking for syntax
or semantic errors (without running the full `.mg → .mb` pipeline) verified the following:

1. **`REPEAT`/`IF`/`SWITCH`/nested `REPEAT` may be nested inside one another arbitrarily**,
   including four levels deep
   (`REPEAT { IF { REPEAT { SWITCH { CASE1: REPEAT {...} END } END } END } END }`)
   — compiles without error, producing 185 lines of `.mc`.
2. `BREAK n` correctly exits the right number of nesting levels
   (`REPEAT 5 { REPEAT 5 { BREAK 2 } }` is error-free); exceeding the actual nesting depth reports
   `There is no 'REPEAT' to break`.
3. `VAR` declaration order: within a routine, all `VAR`s MUST be declared before any statement,
   otherwise `syntax error`.
4. `FLAG` may only be declared globally (top level); writing it inside `DEF...END` is a
   `syntax error`.
5. `CALL` may only reference a routine that has already been `DEF`ed, or one declared with `PROTO`;
   with neither, it is an `Undefined routine` semantic error.
6. `variable@RoutineName` may reference a variable **not yet declared** inside a target routine that
   is itself **not yet defined** but already `PROTO`ed (a placeholder with deferred checking) —
   experimentally verified.
7. A missing `RETURN` at the end of a routine (other than `MAIN`) makes the program genuinely
   terminate there rather than return to the caller (see §4.8).
8. A `PROTO` never followed by a `DEF` causes the parser to SIGSEGV rather than exit with an error.
9. **Decimal literals MUST NOT have leading zeros** (`007` → `syntax error`); ternary literals are
   not checked for digits ≤ 2 (`39t` silently evaluates to `18`).
10. **An important engineering fact**: whether the error is syntactic or semantic
    (`Undefined variable`, `Undefined routine`, `Variable ... already defined`,
    `There is no 'REPEAT' to break`, `Undefined flag`, etc.), **`ref/nagoya-ternary/parser` always
    exits with status 0** — errors are only printed to stderr, and `main.cc` never checks the return
    value of `parser.parse()`. The current `set -euo pipefail` in `scripts/mg2mb.sh` therefore
    **cannot catch** these errors (the exit code is 0), and if the upstream `.mg` has a semantic
    error the script silently passes an empty or truncated `.mc` to the next stage. **If the Python
    compiler were to reuse the fragile "inspect the stderr text" approach, it would be better off
    raising exceptions directly**; this is both a warning to future users of `scripts/mg2mb.sh` and
    a cautionary example the Python back-end's API design should avoid.

---

## 6. Known boundaries (from facts already confirmed in the project + this round of verification)

- `GOTO` is a token declared in both scanner and parser (`scanner.ll:36`, `parser.yy:25`), but
  **no production in `parser.yy` uses it** — it is a pure reserved word, completely unusable in the
  current version; writing `GOTO` is an outright `syntax error` (it is not even consumed into a
  reducible non-terminal).
- Functions (`DEF`) take no parameters and return no value (see §4.8).
- Values should in theory be non-negative and `≤ 3^20-1` (the Malbolge20 one-word upper bound), but
  **the compiler performs no range or sign checking whatsoever**; out-of-range values and negative
  notation (for which there is no literal syntax in the first place) are entirely the user's own
  responsibility.
- `.mg` has exactly one "cross-module" mechanism — `variable@RoutineName`. There is no `import`,
  namespace or file-inclusion syntax; one `.mg` source file is the entire program.

---

## 7. Minimal examples of each feature

The following five already exist in the repository, have been validated through the complete
`.mg→.mc→.mb` pipeline and their output compared against the reference C interpreter (detailed
cross-validation records are in `test/fixtures/nagoya/README.md`). They cover
`OUTPUT`/`VAR`+`ROT`/`INPUT`/`REPEAT`+`BREAK`/`CALL`+`RETURN`:

| Feature | File |
|---|---|
| Minimal `OUTPUT` | `test/fixtures/nagoya/mg_a_minimal.mg` |
| `VAR` + `ROT` + `OUTPUT` | `test/fixtures/nagoya/mg_b_hi.mg` |
| `INPUT` + `OUTPUT` | `test/fixtures/nagoya/mg_c_echo.mg` |
| `REPEAT n` / `REPEAT INF` + `BREAK` | `test/fixtures/nagoya/mg_d_repeat.mg` |
| `PROTO` + `CALL` + `RETURN` | `test/fixtures/nagoya/mg_e_call.mg` |

The following additionally cover `IF`/`SWITCH`/`FLAG`/`IND_OPR`/nesting (they are not compiled into
repository fixtures and serve only to illustrate the syntax; they have been verified to compile with
`ref/nagoya-ternary/parser`):

```
# IF / ELSE / SET / RESET / FLIP
FLAG F = TRUE
DEF MAIN
  IF F
    OUTPUT
  ELSE
    INPUT
  END
  RESET F
  FLIP F        # F is back to ON now
END
```

```
# SWITCH: X must first be set to one of CON2-2 / CON2-1 / CON2
VAR X = 3486784399   # = CON2 - 1, last ternary digit is 1
DEF MAIN
  SWITCH X
  CASE0
    OUTPUT
  CASE1
    INPUT
    OUTPUT
  CASE2
    OUTPUT
    OUTPUT
  END
END
```

```
# IND_OPR: treat a variable's "value" as an address for indirect access (the basis of arrays/stacks)
VAR PTR = 0     # assigned some real address at run time
DEF MAIN
  IND_OPR PTR   # A, [[PTR]] := crazy(A, [[PTR]])
END
```

```
# Nesting: REPEAT around IF around REPEAT around SWITCH (verified to compile)
VAR X = 300
FLAG F = TRUE
DEF MAIN
  REPEAT 2
    IF F
      REPEAT 3
        SWITCH X
        CASE0
          OUTPUT
        CASE1
          REPEAT 2
            OUTPUT
          END
        CASE2
          OUTPUT
        END
      END
    ELSE
      OUTPUT
    END
  END
END
```

---

## 8. Pitfalls the Python compiler back-end must watch for

1. **`END` is the only block-terminating keyword.** Do not copy the `IFEND`/`REPEATEND`/`SWITCHEND`
   notation from the papers' tables into a lexer table — that is merely the papers' mnemonic prose;
   those three tokens do not exist in the real grammar (see §2).
2. **The ternary literal `NNNt` must not be parsed as loosely as the reference implementation does**:
   the reference accepts any `0-9` digit character and blindly computes `sm=sm*3+digit` without
   checking that each digit is ≤ 2. The Python implementation should explicitly reject digits other
   than 0/1/2 at the lexical/syntactic level rather than reproduce this known implementation bug.
3. **Decimal literals MUST NOT have leading zeros** (except a lone `0`); the Python implementation
   should reject spellings like `0123` in the lexer rather than discovering the problem later during
   numeric conversion.
4. **The absence of range/sign checking** is a known defect of the reference implementation and
   should not be copied; the Python back-end should actively validate that literals in `VAR`,
   `REPEAT n`, `BREAK n`, etc. fall within `[0, 3^20-1]` (or the word-size bound of the corresponding
   variant).
5. **The `SWITCH` "all trits but the last are 2" constraint is a purely run-time contract, and the
   reference implementation performs no static checking at all.** If the Python back-end wants to be
   safer than the reference, it may either (a) leave it unchecked (compatible behaviour), or
   (b) do a best-effort static analysis warning on "whether the most recent write to `X` before
   `SWITCH X` obviously comes from `CON2±{0,1,2}`" — but completeness cannot be guaranteed (the value
   may come from run-time sources such as `INPUT` or `IND_OPR`).
6. **Recursive `CALL`s are not rejected by the reference implementation, but are semantically wrong**
   (see §4.8). If the Python back-end is meant to serve as the back-end for a "future Python→.mg
   compiler", and that higher-level compiler may generate recursive calls, the decision must be made
   now: either reject recursive call graphs at the `.mg` level (statically detect cycles in the
   `CALL` graph and error out, stricter than the reference implementation), or automatically
   introduce the explicit `IND_OPR`-based stack of 2017 paper §7 when generating `CALL`/`RETURN`
   code. Pick one; do not quietly let recursion through unhandled.
7. **Every non-`MAIN` routine MUST end with an explicit `RETURN`**, otherwise the whole program is
   terminated prematurely when the routine is called (see item 6 of §4.8). This is a trap the
   reference implementation lets you fall into, with "the program mysteriously exits early" as the
   consequence; the Python back-end should at minimum issue a compile-time warning (ideally an
   error).
8. **Every `PROTO` MUST have a matching `DEF`**, otherwise the reference implementation segfaults
   outright; the Python implementation MUST perform this static check and give a clear error message
   rather than exposing end users to a low-level crash.
9. **A missing `DEF MAIN` is not an error but a silently generated dangling reference** — the Python
   back-end should actively check that "the program has exactly one `DEF MAIN`" and report a clear
   error when it is missing or duplicated.
10. **Do not rely on the reference implementation's process exit code to judge success** — it returns
    0 for all syntax and semantic errors, and the only reliable signal is whether stderr is non-empty,
    or (better) that the Python back-end's own compiler propagates errors via exceptions instead of
    imitating this "always exit 0" behaviour.
11. **`FLAG` may only be declared globally, and `VAR`s must precede all statements** — both are pure
    syntactic restrictions, and the Python AST/parser should treat them as hard grammar-production
    constraints rather than deferring them to a semantic-checking phase.
12. **Variable scoping is a two-level lookup (current routine → global) plus explicit
    `@RoutineName` cross-routine references**; there is no more elaborate nested scoping, and locals
    shadow globals of the same name. The Python back-end's symbol table needs only those two levels
    (a per-routine dict plus a global dict) together with a by-name lookup of "other routines" (for
    `@`); no general scope chain is required.
13. The output of `ref/nagoya-ternary/parser` (the specific branch/flag naming in the `.mc`, the
    `-m`/`-d`/`-c`/`-i` style choices, the random seed) is a **non-normative implementation detail**;
    different `-s` seeds and style flags produce functionally equivalent but byte-different `.mc`.
    The `.mg` language specification itself (the scope of this document) is independent of these code
    generation details, and a future Python back-end is entirely free to adopt its own simpler or
    deterministic code generation strategy, as long as `.mg` language semantics are preserved — a
    bit-for-bit reproduction of the reference implementation's generation style is not required.

---

## 9. Open questions

- **The precise run-time mechanism of `IND_OPR`** (the `PC := ENTRY@MAIN` part of table 13, i.e. how
  control returns to the original program position afterwards) depends on the "fixed cell + fixed
  values in the data module" technique described in 2017 paper §5–6 and implemented only at the
  `ref/nagoya-lowass` (LAL→Malbolge20 assembler) level. This document verified only the input/output
  semantics visible at the `.mg` level (`A,[[X]]:=crazy(A,[[X]])`), and did not go through the byte
  layout of the `IND_OPR` cell in `ref/nagoya-lowass` line by line — if the Python back-end wants to
  reimplement `IND_OPR` code generation itself (rather than copying this fixed-cell technique), it
  will need a separate study of the `ref/nagoya-lowass` source or figure 14 / table 15 of the 2017
  paper.
- **The code-generation details of `REPEAT n`'s binary down-counter** (which flag corresponds to
  which bit, the initialisation order of `SET`/`RESET`) are described here only at a high level with
  a citation to the source (2016 paper §5.4); the generated `.mc` was not verified line by line
  against that algorithm description. This is an implementation detail of LAL back-end code
  generation and does not affect the semantics of the `.mg` language itself ("REPEAT n executes
  exactly n times" is behaviour already verified end-to-end via the `mg_d_repeat` fixture); it leaves
  room only on the question of "whether to copy this particular optimisation".
- **Whether the `3^20-1` upper bound is implicitly checked in other Nagoya tools
  (`ref/nagoya-lowass`)** is unverified — this document only confirmed that `ref/nagoya-ternary`
  (the `.mg→.mc` step) does no checking, which does not imply that later pipeline stages have no
  bounds checks at all (though judging by the comments in `scripts/mg2mb.sh`, the behaviour of the
  `init` tool on out-of-range values in the `.data→.mb` stage is likewise undocumented).
- **The exact error text of `variable_str AT IDENT` when the target routine was never defined as any
  routine at all (neither `PROTO` nor `DEF`)** was not tested across every permutation; only "target
  routine does not exist at all" → `Undefined routine` was verified (via the `call_statement` path).
  The error text on the `variable ... AT IDENT` path is inferred to be identical, since both consult
  `program->routines`, but no separate experiment was run for the specific combination
  `variable@nonexistent_routine` to confirm the error text.

---

## References

- `ref/nagoya-ternary/scanner.ll`, `parser.yy`, `CodeBlock.cc`, `Routine.cc`,
  `Program.cc`, `Variable.cc`, `Radix.cc`, `Option.cc`, `main.cc`, `define.h`
- `ref/nagoya-ternary/README.en.md`
- 河邉翔平・酒井正彦・西田直樹・関浩之, "難読性の高い Malbolge コードを生成する
  コンパイラのための中間言語", 電子情報通信学会技術報告, Vol.116, No.127,
  SS2016-12, pp.105-110 (2016).
- 坂梨元軌・河邉翔平・酒井正彦・西田直樹・橋本健二, "再帰呼び出しを持つ C 言語
  サブセットから Malbolge へのコンパイラ", 電子情報通信学会技術報告, Vol.117,
  No.136, SS2017-18, pp.145-150 (2017).
- `test/fixtures/nagoya/README.md`, `test/fixtures/nagoya/mg_*.mg`
- `docs/specs/hell-spec.md` (sister document: the HeLL/LMAO language specification; `SWITCH`'s fixed-cell
  jump technique shares its origin with the `immutable_nops` idea in its §3.1)
