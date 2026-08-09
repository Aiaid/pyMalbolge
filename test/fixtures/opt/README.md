# Counterexamples for the size-optimization investigation

Programs that pin down the findings in §I. Some break the layout transforms in
`test/diagnostics/optpatch.py`; some break the *shipped* compiler; one is kept
precisely because it breaks nothing.

| File | Breaks | Why this shape |
|---|---|---|
| `f1_recursion.py` | option one (§I2) | One level of recursion. Converting a single numbered flag — `FLAG10`, where the original doubling search landed — is enough. |
| `fib3_in_loop.py` | **the shipped compiler** (§I7) | One known-failing program. Do not read the name as the characterization — see below. |
| `d1_fails.py` / `d2_passes.py` | **the shipped compiler** (§I7) | The pair that rules out every source-level explanation: `d(1)` fails with *no loop*, `d(2)` passes while doing strictly more work. They differ by one constant, 9,306 bytes. |
| `fib2_loop.py` | nothing | Kept as the control that retracted §I3: it was recorded as option two's counterexample, but it passes under *both* builds. |
| `foo.mg`, `foo.mc` | neither | `print("foo")` — the cost model's headline case, and the program that made both transforms look correct. |

`foo.mg` / `foo.mc` are checked in as intermediates rather than regenerated
from `.py` so that the fast tests do not depend on the front end: they are the
fixed input the layout tests measure against. Sizes for `foo`:

| Build | .mb bytes |
|---|---|
| baseline | 1,061,167 |
| option one | 280,967 |
| option two | 243,461 |

The `.py` files are compiled through `py2mg` → `mg2mc` by the slow tests
(`MALBOLGE_SLOW_TESTS=1`), producing 31–65 MB programs that run for millions
of steps.

They are also written in the compiler's Python subset, not full Python — see
`docs/specs/python-subset-spec.md`. Running them under CPython works and prints the
same thing, which is a useful sanity check on the fixture itself.

## What §I7 is not

`fib3_in_loop.py` was the first failing program found, and "recursion inside a
loop" was the first description of the defect. That description is wrong.
Measured since: linear recursion in a loop never fails at any depth or
iteration count tried; two calls in one expression never fails; `d(1)` fails
with no loop at all; and `d(2)` passes while doing strictly more of the same
work as `d(1)`.

What tracks the failures is layout position. The same 9,306-byte shift — one
extra constant word, which moves the whole unit and routine layout up by 9,306
cells while preserving mod-94 and mod-3 alignment — breaks a working program in
one case and fixes a broken one in the other. Correctness is not monotone in
size, depth, call count, or any source-level shape tested.

So these fixtures are samples of a failure mode, not a specification of it. Do
not generalize from their shapes; add measurements instead.
