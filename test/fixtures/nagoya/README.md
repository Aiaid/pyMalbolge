# Nagoya Malbolge20 test fixtures

`hello20.mb` is the sample program from the Nagoya University Malbolge20
reference interpreter:

- **Source**: https://git.trs.css.i.nagoya-u.ac.jp/malbolge/malbolge20-interpreter
  (`sample/hello20.mb`)
- **License**: MIT (Copyright (c) Nagoya Univ.)
- **Project page**: https://www.trs.css.i.nagoya-u.ac.jp/projects/Malbolge/

It was produced by the Nagoya LAL-for-Malbolge20 toolchain and prints
`HelloWorld` (46,417 steps). It serves as a conformance check that
pyMalbolge's Malbolge20 interpreter (EOF value, block-based sparse memory
initialization) matches the reference implementation.

## `mg_*` fixtures: .mg -> .mc -> .mb pipeline

The `mg_*.mg` / `mg_*.mc` / `mg_*.mb` triples are original programs
written against the Nagoya pseudo-instruction language (.mg), compiled
through the full Nagoya toolchain down to runnable Malbolge20 (.mb):

```
.mg --[ref/nagoya-ternary/parser]--> .mc --[ref/nagoya-lowass/parse_mc2.pl + init]--> .mb
```

- **Source**: written for this repo, following the .mg grammar in
  `ref/nagoya-ternary/parser.yy` / `scanner.ll` and the syntax examples in
  `ref/nagoya-ternary/README.en.md`.
- **Compiler**: `ref/nagoya-ternary` (pseudo-instructions -> LAL) and
  `ref/nagoya-lowass` (LAL -> Malbolge20), both MIT-licensed, Nagoya
  University. See `scripts/mg2mb.sh` for the exact pipeline wrapper.
- **Compile command** used to produce the checked-in `.mc`/`.mb` files:
  `scripts/mg2mb.sh -s 1 mg_NAME.mg mg_NAME.mb` (style flags `-m -c`,
  i.e. "return to main control flow" + "OUTPUT/INPUT/SET/RESET as shared
  modules"). The `.mg -> .mc` step is fully deterministic for this
  flag/seed combination. The final `.data -> .mb` step
  (`ref/nagoya-lowass/init/init`) is **not** byte-reproducible -- it
  fills unused/padding memory cells with a wall-clock-time-seeded
  pseudo-random opcode (see `init.cpp`'s "unset region" loop) -- so the
  exact bytes of these `.mb` files are a one-time snapshot, not
  something `scripts/mg2mb.sh` will reproduce identically on a re-run.
  This only affects padding cells the program never executes; observed
  program behavior is unaffected and was cross-checked against
  `ref/nagoya-malbolge20-interpreter/malbolge20` (the reference C
  interpreter) before being committed.
- Cross-validated: each fixture's `.mb` produces byte-identical stdout
  between pyMalbolge (`python3 -m malbolge --variant=malbolge20`) and the
  Nagoya reference C interpreter.

| Fixture | .mg source idea | stdin | expected stdout |
|---|---|---|---|
| `mg_a_minimal` | `DEF MAIN OUTPUT END` -- smoke-tests the pipeline with a single unconditional `OUTPUT` (no `ROT`, so the byte is whatever the A register defaults to). | (none) | `b'\xde'` |
| `mg_b_hi` | Two `VAR`s holding `3*ascii` for `'H'`/`'i'`, each loaded via `ROT` then `OUTPUT` -- same encoding trick as `ref/nagoya-ternary/sample/hello.mg`. | (none) | `b'Hi'` |
| `mg_c_echo` | `DEF MAIN INPUT OUTPUT END` -- reads one byte from stdin and echoes it. | `b'Q'` | `b'Q'` |
| `mg_d_repeat` | `REPEAT 3 OUTPUT END` followed by `REPEAT INF OUTPUT BREAK END`, after a single `ROT` loads `'A'` into the A register once before the loop. Exercises `REPEAT`/`BREAK`/`REPEAT INF`. Note: `ROT X` rotates `X` *in place* (writes the rotated value back to memory as well as into A), so repeatedly `ROT`-ing the same variable inside a loop changes its value every iteration -- this fixture avoids that by `ROT`-ing once and only `OUTPUT`-ing (which does not mutate A) inside the loop. | (none) | `b'AAAA'` |
| `mg_e_call` | `PROTO SUB` / `DEF MAIN CALL SUB END` / `DEF SUB ROT X OUTPUT RETURN END` -- exercises `CALL`/`RETURN` across routines. | (none) | `b'X'` |

### Skipped .mg features

`SWITCH`/`CASE0`/`CASE1`/`CASE2`, `IF`/`ELSE` (flag-based conditionals),
`IND_OPR`, and `FLIP` are supported by the grammar but were not exercised
by these fixtures (kept to a minimal, progressively-complex set per the
task scope). `GOTO` is a lexer/parser token but has **no** grammar rule
using it anywhere in `parser.yy` -- it is reserved/unimplemented in this
version of the translator, not just unused by these fixtures.
