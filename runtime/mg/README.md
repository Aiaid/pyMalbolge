# .mg runtime library for a Python -> Malbolge20 compiler

A catalogue of **pseudo-instruction (`.mg`) code sequences** that implement ordinary
arithmetic and control on a machine whose only real operations are `crazy` and
`rotate`. Everything here is compiled through the Nagoya toolchain
(`scripts/mg2mb.sh`) and **cross-validated on two interpreters** — pyMalbolge
(`python3 -m malbolge --variant=malbolge20`) and the Nagoya reference C
interpreter (`ref/nagoya-malbolge20-interpreter/malbolge20`). "Verified py==C"
below means both produced byte-identical output.

Two provenance classes:

- **official** (`official/`) — extracted verbatim from the Nagoya C-subset
  compiler `ref/nagoya-highlevel` by compiling a tiny C program and capturing
  its `.mg` output. These are the authoritative templates and the recommended
  basis for a real code generator.
- **self-developed** (`primitives/`) — derived from first principles on the
  crazy/rotate algebra (before the C compiler source was available). Kept
  because they document the underlying algebra and because several (MOV, ZERO,
  IS_ZERO) are smaller / independent of the official ABI.

---

## 1. The machine, in one screen

`.mg` exposes a 20-trit accumulator **A** and memory cells (`VAR`s). The only
cell-mutating instructions are:

| instr | effect |
|-------|--------|
| `ROT X` | `t = rotr([X]); [X] = t; A = t` (rotate right 1 trit, IN PLACE, also into A) |
| `OPR X` | `t = crazy(A,[X]); [X] = t; A = t` (crazy of A and X, IN PLACE, into both) |
| `INPUT` / `OUTPUT` | `A = byte` / emit `A % 256` |
| `SWITCH X / CASE0/1/2` | 3-way branch on the **last trit** of X (constraints below) |
| `IF f/ELSE`, `SET/RESET/FLIP f`, `REPEAT n / REPEAT INF / BREAK`, `DEF/CALL/RETURN`, `IND_OPR` | control / flags / functions |

`crazy(a,d)` works trit-by-trit: `result_trit = T[d_trit][a_trit]` with

```
        a=0 a=1 a=2
T[d=0]:  1   0   0
T[d=1]:  1   0   2
T[d=2]:  2   2   1
```

### Constants CON0/CON1/CON2 are free and indestructible
`CON0=0`, `CON1=1743392200` (all-1 trits), `CON2=3486784400` (all-2 trits) are
built-in cells. All three are **rotation-invariant**, so `ROT CONk` is a pure
"load Ck into A" that never mutates the constant. And because we only ever `ROT`
them (never `OPR`), they stay pristine for the entire program — the backbone of
every idiom here.

### The per-trit maps you actually program with
Loading A with a constant then `OPR X` applies a fixed per-trit map to X
(**column map**, the useful direction — X is written, A becomes junk):

- `ROT CON0; OPR X` → `f0: {0,1}->1, 2->2`
- `ROT CON1; OPR X` → `f1: {0,1}->0, 2->2`
- `ROT CON2; OPR X` → `f2: swap(1,2), 0->0` (an involution)

`OPR K` with a *constant* K instead transforms A (**row map**, destroys K):
`r0=(1,0,0)`, `r1=(0,1,0→ swap(0,1))`, `r2=(2,2,1)`. Only `f2` and `r1` are
bijections; two transpositions generate all of S3, which is why arbitrary
per-trit permutations are reachable.

### SWITCH mechanics (read before using SWITCH by hand)
- SWITCH dispatches on the **last trit** of the cell, but ONLY when the cell's
  **upper 19 trits are all 2**. Raw data values mis-dispatch; see
  `primitives/normalize_switch.mg` for the macro that forces upper=2 while
  keeping the last trit.
- SWITCH **executes the switched cell as code**, and Malbolge re-encrypts every
  executed cell, so the cell is *consumed*. Writing a cell with `OPR` and then
  re-`SWITCH`ing it in a hand-rolled loop desyncs it and **crashes** (pyMalbolge
  halts, the C reference SIGSEGVs — observed). The official codegen avoids this
  by (a) doing the trit-by-trit work in a branchless `REPEAT 20` body of pure
  `OPR/ROT` and taking **one** SWITCH afterwards, or (b) re-deriving a dedicated
  switch cell (`CONST_3486784398`, upper=2/last=0) fresh on every pass. Follow
  the same discipline: **never loop “write-then-switch” on the same cell.**

---

## 2. Primitive catalogue

| primitive | file | source | cost (instr) | verified |
|-----------|------|--------|--------------|----------|
| READ (A:=[X], nondestructive) | `primitives/read.mg` | self | 4 | py==C |
| ZERO ([X]:=0) | `primitives/zero.mg` | self | 6 | py==C |
| SET_C1 ([X]:=all-ones) | `primitives/zero.mg` | self | 6 | py==C |
| LOAD_CONST (compile-time) | — (`VAR X = K`) | both | 0 | trivial |
| MOV (DST:=SRC exact, SRC kept) | `primitives/mov.mg` | self | 22 | py==C |
| NORMALIZE_FOR_SWITCH | `primitives/normalize_switch.mg` | self | 14 | py==C |
| IS_ZERO (branchless fold) | `primitives/iszero.mg` | self | ~534 | py==C |
| ADD (c=a+b) | `official/add.mg` | official | REPEAT 20 body | py==C |
| SUB (c=a-b) | `official/sub.mg` | official | REPEAT 20 body | py==C |
| INC (a++) | `official/inc.mg` | official | REPEAT 20 body | py==C |
| DEC (a--) | `official/dec.mg` | official | REPEAT 20 body | py==C |
| CMP `<` `<=` `>` `>=` `==` `!=` | `official/{lt,le,gt,ge,eq,ne}.mg` | official | REPEAT 20 + 1 SWITCH | py==C |
| MUL (repeated add) | `official/mul.mg` | official (via C) | O(b) adds | py==C |
| DIV (repeated sub) | `official/div.mg` | official (via C) | O(quotient) subs | py==C |
| recursion / stack | `official/fib.mg` | official | — | see §5 caveat |

### Official primitive shape
The official add/sub/compare all share one shape (see `official/add.mg`,
`official/lt.mg`):
1. copy the two operands into working temps `TEMP0..TEMP3` with the
   `ROT CON1; OPR Ti; OPR Ti; OPR Tj; OPR Tj` load idiom and a
   `ROT CON2; OPR src; ROT CON2; OPR src` read;
2. a `REPEAT 20` body of pure `OPR/ROT` that walks the trits (`ROT TEMP0`
   advances one trit per pass; ADD additionally rotates a carry-select mask
   `CONST_2905653667`) — this is the **branchless carry**;
3. ADD/SUB leave the result in a temp and copy it out; the comparisons finish
   with a **single** `SWITCH TEMP1` whose CASE0/1/2 are `<`/`=`/`>` (each
   comparator wires the three cases to the right boolean).

`CONST_2905653667` is the ADD carry mask; `CONST_3486784398/9` are the
upper=2 switch cells (`3486784398` = last 0, `3486784399` = last 1).

---

## 3. Register / calling convention (recommended for the Python codegen)

Adopt the official ABI so generated fragments compose:

- **Globals**: `CON0/1/2` (built-in). Emit the constant pool the official
  compiler uses when a fragment needs it: `CONST_1743392201`,
  `CONST_2905653667`, `CONST_3486784398`, `CONST_3486784399`, plus one
  `CONST_<k>` per distinct literal `k`.
- **Scratch**: `TEMP0..TEMP3` for arithmetic (add/sub/compare use up to 4);
  IS_ZERO/MOV additionally use `ACC`, `ZC1`, `ZC2`, `TMP`, `K1=1743392201`,
  `K3=2`. Treat all temps as caller-clobbered.
- **User variables**: prefix `u_` (official convention), e.g. `VAR u_a = 7`.
- **Booleans / conditions** live in `FLAG`s (e.g. `TEMP_FLAG0`); a comparison
  sets a flag via its SWITCH cases, then `IF flag / ELSE / END` branches.
- **Functions**: `PROTO f` then `DEF f ... END`; call with `CALL f`; each frame
  declares `VAR ARG0`, `VAR RETURN_VALUE`, locals; a shared `VAR STACK_TOP =
  3486784381` plus `IND_OPR` implements the recursion stack.

Code-gen an expression the way the C compiler does: compute subexpressions into
`TEMP`s, apply the matching `official/*.mg` body, store into the destination
`u_`-variable with MOV/the official copy-out idiom.

---

## 4. mul / div

The C compiler does not emit `*` or `/`, but it emits `while`, `+`, `-`, and
comparisons, so multiplication and division are obtained **through the official
toolchain** by writing them in the C subset (`official/mul.c`, `official/div.c`)
and compiling. Both verified py==C (6*7=42, 42/6=7).

- `mul.c`: `while(i<b){ c=c+a; i=i+1; }` — O(b) additions.
- `div.c`: `while(a>=b){ a=a-b; q=q+1; }` — O(quotient) subtractions.

For a real compiler, replace the linear loops with **shift-add / compare-subtract
by doubling** (O(20) additions/compares) — the team's suggested approach; only
ADD and CMP are needed, both of which are verified here. The linear versions are
the correctness reference to diff against.

---

## 5. Verified test vectors

Run `tests/run.py` to reproduce (drives `.mg -> .mb` and runs both interpreters).

| program | input | output | meaning |
|---------|-------|--------|---------|
| `tests/t_read.mg` | — | `0xC8` | READ V=200 |
| `tests/t_zero.mg` | — | `0x00` | ZERO of 12345 |
| `tests/t_setc1.mg` | — | `0xC8` | SET_C1 (=C1 mod 256) |
| `tests/t_mov.mg` | — | `bf bf 8d 37` | MOV of a low/mid/high-trit value, dumped at rot 0/7/14 (+ src preserved) |
| `tests/t_iszero_0.mg` | — | `Z` | IS_ZERO(0)=zero |
| `tests/t_iszero_1.mg` | — | `N` | IS_ZERO(1)=nonzero |
| `tests/t_iszero_59049.mg` | — | `N` | IS_ZERO(3^10)=nonzero |
| `official/add.mg` | — | `0x0C` | 7+5=12 |
| `official/sub.mg` | — | `0x12` | 30-12=18 |
| `official/inc.mg` / `dec.mg` | — | `A` | 64++ / 66-- = 65 |
| `official/{lt,le,gt,ge,eq,ne}.mg` | — | `Y` | comparison true branch |
| `official/mul.mg` | — | `*` | 6*7=42 |
| `official/div.mg` | — | `0x07` | 42/6=7 |

IS_ZERO was additionally checked in `tests/mgsim.py` (a cycle-accurate `.mg`
simulator that matches the interpreter) against **every** single-trit value
(all 20 positions, trit 1 and 2) plus randoms — all classified correctly.

### Step-count / performance note
pyMalbolge is ~15-100x slower than the C reference. Observed pyMalbolge wall
times: add/compare ~2-3s, mul(6*7) ~8s, div(42/6) ~9s, IS_ZERO ~13s. The
branchless `REPEAT 20` bodies compile to multi-hundred-KB / multi-MB `.mb`
files. Budget accordingly (and prefer the C reference for bulk validation).

### Recursion caveat — official double-recursion under-counts past depth 3
The official recursive template (`official/fib.mg`, `fib(n)=fib(n-1)+fib(n-2)`)
compiles and runs, and the two interpreters agree byte-for-byte, but the result
is only correct for shallow recursion:

| n | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 10 |
|---|---|---|---|---|---|---|---|----|
| got    | 0 | 1 | 1 | 2 | **2** | **4** | **4** | **16** |
| expect | 0 | 1 | 1 | 2 |  3 |  5 |  8 |  55 |

Base cases and `fib(≤3)` are exact; it starts under-counting at `fib(4)`. The
pattern (a contribution of the second recursive call getting dropped) is
consistent with the compiled stack save/restore not surviving the *second*
`CALL` in `a()+b()`. Since both interpreters agree, this is behaviour of the
**Nagoya compiler's generated code**, not of pyMalbolge. Single-level, non-
recursive `CALL/RETURN` works (`test/fixtures/nagoya/mg_e_call`), and simple
tail-style iteration via `while` works (mul/div above). **Flagged as unresolved
in the official templates — do not rely on non-trivial recursion until root-
caused.** (A Python compiler can side-step it by using an explicit heap/stack
for call frames rather than the emitted `IND_OPR` stack, or by lowering
recursion to iteration where possible.)
