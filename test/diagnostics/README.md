# Diagnostics for the .mb size-optimization investigation

Instruments, not tests. `pytest` collects nothing in this directory; the
tests that drive these modules are in `test/test_opt_counterexamples.py`.

Compiled Malbolge20 output is enormous — `print("foo")` is 1.06 MB — and two
attempts to shrink it looked correct after passing every test that existed at
the time. One was then falsified (§I2); the other's falsification was itself
retracted (§I3) once its counterexample was finally run against a baseline,
which is how the shipped compiler's own defect (§I7) surfaced. These modules
are what located all of it, kept runnable so the results stay reproducible.

| Module | What it does |
|---|---|
| `layout_tool.py` | Recovers mc2mb's address map (which flag lands where) by re-executing a source-rewritten copy of the compiler |
| `traced_run.py` | An instrumented copy of the Malbolge20 interpreter loop, with per-instruction and per-write hooks |
| `flag_trace.py` | Records and diffs flag event streams — the instrument behind finding I2 |
| `write_trace.py` | Finds which runtime write corrupted the code cell a program died on — the instrument behind findings I2's and I7's death mechanisms |
| `optpatch.py` | The two falsified transforms, applied on top of the shipped compiler rather than inside it |
| `evidence/` | `i2-flag-divergence.txt` (the original 2026-07-23 divergence window), `i2-death-mechanism.txt` (wild jump into data), `i7-halt-mechanism.txt` (bootstrap writing 0 into its own instruction stream) |

## Why the transforms live here and not in the compiler

Both transforms are wrong. Neither belongs in `malbolge/compiler/`, and the
shipped `mc2mb` must stay byte-exact against the reference toolchain — that
equivalence is what several other test modules assert. So `optpatch` applies
them from outside: option one rewrites the `.mc`, and option two re-executes a
source-rewritten copy of `mc2mb`. `malbolge/compiler/mc2mb.py` is never
modified and nothing here runs unless a diagnostic calls it.

The price is that `layout_tool` and `optpatch` both pattern-match against
`mc2mb.py` source lines, so they break if those lines move. Both raise on a
failed match rather than silently doing nothing, and `LayoutMap` in the test
module is the alarm.

## The two falsifications

**Option one (§I2)** — declare a `FLAG 1/2` as `0/2` and walk it to the target
state with `NEXT` at program entry. A `1/2` flag costs ~39,950 B because a
nonzero initial value has no legal instruction character under xlat1, so the
page is pushed into the indirect region and built at run time; `0/2` costs
~38 B. foo: 1.06 MB → 281 KB.

It passed the FLIP/SET/RESET/IF/REPEAT/SWITCH/CALL micro-matrix, the nagoya
corpus, and a 326-flag scaling sweep. It fails on recursion. Flag state is
advanced *jointly* by the ENCRYPT self-modification that follows execution and
by the crazy writes `NEXT` performs, and the cycle tables were chosen for that
joint orbit; the warm-up pushes the direct region's MOV_D byte off it. What
passed, passed because an orbit happened to close.

**Option two (§I3, falsification retracted)** — reserve indirect pages by
actual cell count instead of a flat 94 words per page. Only ~5 KB of the
79,900 B a flag pair costs is emitted; the rest is reservation. Corpus →
0.12–0.26×, foo → 243 KB.

This was recorded as falsified by `fib(2)` with a `while` loop. It is not:
that program passes under both builds, so the observation had no control. What
turned up instead is §I7 — the *shipped* compiler miscompiles some programs
while option two's layout compiles the same source correctly. The trigger is
not any source-level shape: `d(1)` fails with no loop, `d(2)` passes while
doing strictly more work, and the same 9,306-byte layout shift breaks a working
program in one case and fixes a broken one in the other. Option two is
therefore unfalsified, which by this project's own repeated lesson is not the
same as correct.

That lesson is what the main paper is built on: **passing the tests is not
being correct.** Layout invariants on a machine where execution mutates its
own code need a proof, and neither the two rejected transforms nor the shipped
layout has one.

## Usage

```python
from test.diagnostics import optpatch
from test.diagnostics.flag_trace import record, first_divergence, format_window

mc = open('foo.mc').read()
mc1 = optpatch.option_one(mc, flags={'FLAG10'})   # or option_two=True below

base, _ = record(optpatch.assemble(mc), mc)
var,  _ = record(optpatch.assemble(mc1), mc1)
i = first_divergence(base, var)
print(format_window(base, var, i))
```

Both tools also have command-line entry points:

```bash
python -m test.diagnostics.flag_trace base.mb base.mc var.mb var.mc
python -m test.diagnostics.write_trace fib2.mb fib2.mc
```

Runs are slow — pure Python, and these programs take millions of steps. The
`f1_recursion` pair is ~31 MB per side and a few minutes per trace; the
cheapest §I7 instance (`d1_fails`) is 53 MB and dies at 4.77M steps, which is
why it, not the fib case, is the one to iterate on.
