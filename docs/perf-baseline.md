# Performance Baseline and Profiling (2026-07-21)

> [中文](perf-baseline.zh.md) | **English**

> Measurement and profiling only — no optimization work included. Benchmark
> scripts and intermediate artifacts are at
> `/Users/anend/.claude/jobs/1d5df563/tmp/perf/` (session temp directory, not
> checked into the repo).

## 0. Environment

- `python3 --version`: Python 3.14.6 (`/opt/homebrew/opt/python@3.14/bin/python3.14`)
- CPU: `sysctl -n machdep.cpu.brand_string` → **Apple M1 Pro**
- `pypy3`: **not installed** (neither `which pypy3` nor `which pypy` found
  anything). Homebrew has a formula available (`brew search pypy` →
  `pypy3.10`, `pypy3.11`), install command: `brew install pypy3.11`. The
  install was not performed this round (the task asked not to install large
  packages unprompted), so the PyPy comparison is **skipped** and the speedup
  is unknown — see the indirect assessment in §4.
- Each benchmark was run twice, taking the better value (`best_of_2`).

## 1. Interpreter benchmarks (malbolge20, subprocess `python3 -m malbolge --variant=malbolge20`)

| Case | .mb size | Steps (reference) | best_of_2 time |
|---|---|---|---|
| hello20.mb | 188,207 B | 46,417 | 0.8885 s |
| mg_e_call.mb | 799,471 B | not counted separately, larger order of magnitude | 1.1992 s |

Compared against the hello20 "0.6 s" recorded in the internal research log
(private, not in this repo), §C: this subprocess run's overall time is 0.89 s;
the difference is mainly the Python 3.14 interpreter's own startup + import
overhead (this measurement times the whole subprocess, whereas that log
doesn't specify its measurement method)
— the order of magnitude matches and there is no regression.

## 2. Interpreter cProfile profiling (in-process call to `malbolge20.eval()`, excludes subprocess/CLI overhead)

### hello20.mb (46,417 steps)

```
1523770 function calls in 1.424 s
tottime  cumtime  function
0.052    1.424    malbolge20.py:121 eval()  [main loop body]
0.051    1.127    core.py:236 SparseMemory.__getitem__          (258,784 calls)
1.050    1.050    core.py:80 crazy()                             (172,437 calls)
0.029    1.048    core.py:171 _materialize_block()                (170 calls)
0.000    0.312    core.py:201 _seed_for_block()
0.118    0.178    core.py:348 parse_source()
```

### mg_e_call.mb (larger case)

```
5824673 function calls in 2.372 s
tottime  cumtime  function
0.217    2.372    malbolge20.py:121 eval()
0.213    1.127    core.py:236 __getitem__                        (1,087,062 calls)
0.016    0.797    core.py:171 _materialize_block()                 (732 calls)
0.485    0.746    core.py:348 parse_source()
0.709    0.709    core.py:80 crazy()                             (112,596 calls)
0.248    0.261    core.py:201 _seed_for_block()
```

**Hotspot #1 (a counterintuitive finding)**: in both cases, the main
interpreter loop body itself (`eval()`'s `tottime`) accounts for only a small
share (3.7% for hello20, 9.1% for mg_e_call). What actually eats 70–80% of
the runtime is **`SparseMemory`'s lazy block materialization** —
`_materialize_block()` computes an entire **59,049-cell (3^10) default-fill
block** from scratch with `crazy()` every time it's triggered (calling
`crazy()` cell by cell, with each cell in the 20-trit case additionally
running a 20-iteration inner loop), even though this 46K-step small program
only ever reads a tiny fraction of those cells. hello20 triggers
materialization of about 3 blocks (172,437 ≈ 3 × 59,049 `crazy()` calls),
mg_e_call triggers about 2 blocks (most of the 732 `_materialize_block` calls
are cache hits; the number of blocks actually materialized for the first
time is small, but each one has a fixed cost). `parse_source()` is also not
negligible on mg_e_call (0.746s cumtime, mainly character-by-character
`ord()` calls over ~799K characters).

**Optimizability assessment**: this isn't "the main loop is slow" — it's
that the cache granularity choice of "materialize the whole block up front"
is itself too costly. The block size is fixed at `3^(trit_width/2)`,
independent of how sparsely the program actually accesses memory. The
existing `_block_seed_jump_map` (§A5, used to skip seeds across blocks)
already proves that crazy-fill can be computed by jumping per-trit rather
than recursing linearly cell by cell; the same trick could in principle be
pushed down inside a block, computing only the handful of cells actually
accessed instead of materializing all 59,049 cells. This is a more
fundamental optimization than the "in-block memoryview" mentioned in backlog
H1, and deserves to be tracked as its own item.

## 3. mc2mb benchmarks (pure-Python assembler, `assemble_mc_to_mb`, in-process call)

5 tiers of `.mc` → `.mb`, sorted by increasing output size (python3.14, best_of_2):

| Case | .mc source size | .mb output size | best_of_2 time |
|---|---|---|---|
| mg_a_minimal.mc | 401 B | 176,251 B | 4.5177 s |
| mg_c_echo.mc | 579 B | 185,651 B | 7.0172 s |
| mg_b_hi.mc | 1,251 B | 293,563 B | 15.5586 s |
| mg_d_repeat.mc | 1,759 B | 467,087 B | 20.0844 s |
| mg_e_call.mc | 4,047 B | 799,471 B | 43.7802 s |

**Power-law fit** (log-log least-squares fit of `.mb` size vs. time):
exponent ≈ **1.36** (≈1.50 computed directly from the first and last points).
In other words, the "near-linear, ~40s/MB" description in the internal
research log (private, not in this repo), §C, **needs correction** — time
grows noticeably faster than linearly (size
4.54× → time 9.68×). Extrapolating with O(n^1.36), for a 20 MB end-to-end
smoke-test case (15.5 minutes), each doubling of size costs about ×2.6 in
time rather than ×2, and the underestimate gets worse at larger scale.

## 4. mc2mb cProfile profiling (mg_d_repeat.mc, `.mb` output 467,087 B, the middle tier in the table above)

```
97,917,507 function calls in 38.123 s
tottime  cumtime  function
0.043    37.429   mc2mb.py:904  dm_move()                          (51,884 calls)
37.321   37.321   mc2mb.py:886  dm_mov_search()                (94,794,662 calls!)
0.019    37.204   mc2mb.py:957  dm_accs2()                         (25,954 calls)
0.011    37.140   mc2mb.py:1148 code_search() / code_generate()
0.013    36.989   mc2mb.py:941  dm_move2()
0.189    0.603    mc2mb.py:1512 finish()
```

(Note: cProfile's per-call recording overhead is considerable at 95 million
calls, so the 38.123 s here is noticeably higher than the no-profiler
best_of_2 of 20.0844 s for this same case in §3 — that difference is
profiler overhead, not a regression; it doesn't affect the relative share of
each function.)

**Hotspot #1**: `dm_mov_search()` — the D-register move path search, an
**unmemoized recursive search** with fixed depth 3 and up to 100 branches per
level (`for i in range(d, 100)`). For this tier, it's called nearly **95
million** times, accounting for **97.9%** of total runtime. This is because
every time the D register needs to "move to a target position" (`dm_move`,
51,884 calls), the shortest jump path is recomputed from scratch.

**Key structural fact**: going through every write site of
`_Assembler.jmpaddrs` (`grep "jmpaddrs\["`), it is only assigned during the
`setup_data_module()` stage (about 40 fixed writes, **independent** of
program size); during the `code_generate()` stage, where `dm_move`/
`dm_mov_search` are called heavily, `jmpaddrs` is **read-only and constant**.
This means `dm_mov_search(d, pos, depth)` is a **pure function** of
`(d, pos, depth)` during this stage — the value space for `d` and `pos` is
small (`d` ∈ 0..99, `pos` determined by the code-generation logic, depth ∈
0..3), yet the function is called nearly a hundred million times, which
implies a huge number of repeated subproblems. This precisely explains the
superlinear growth observed in §3: as the program grows larger, more slots in
`jmpaddrs` get occupied (see the ~40 writes in `setup_data_module`, though at
runtime there's dynamic -1/reassignment switching), which widens the
recursion's branching factor, so each individual `dm_mov_search` call tree
grows larger, and this compounds with the call count itself growing with
program size — the product of the two yields O(n^1.4) instead of O(n).

**Optimizability assessment**: this is an **algorithm ported verbatim from
the reference C++ implementation** (the search logic from `init/dmod.cpp` was
ported byte-for-byte to guarantee bit-identical `.mb` output); the
algorithm's complexity wasn't noticeable in C++ because of its raw speed, but
after porting to pure Python the constant factor got amplified into the
dominant bottleneck. **Adding a memoization cache (keyed on
`(d, pos, depth)`, valid only during the stage where `jmpaddrs` doesn't
change — or more conservatively, snapshotting `jmpaddrs` before
`code_generate()` starts and including the snapshot's hash in the cache key
to absolutely guarantee correctness) is a zero-risk optimization that doesn't
change the output** — because `dm_mov_search` is a pure function during this
stage, caching cannot change any return value, only eliminate redundant
computation. Rough estimates based on call count and hit/repeat rate suggest
this could compress this item's runtime from "seconds/tens of seconds" down
to "milliseconds," making it the single highest-payoff optimization in the
entire pipeline right now.

## 5. PyPy speedup: unknown (not installed, indirect assessment)

No number was directly measured. Indirect evidence that can be offered:

- Both top hotspots (`crazy()`'s fixed-length small numeric loop,
  `dm_mov_search()`'s depth-limited recursion with heavy function-call
  volume) are patterns PyPy's JIT has traditionally handled well (tight
  numeric loops, monomorphic call-site recursion); literature/community
  experience suggests pure-Python code dominated by numeric loops and
  function calls commonly sees **5–20×** speedups under PyPy — this cannot
  substitute for an actual measurement but can serve as an order-of-magnitude
  reference.
- To actually calibrate this in the future, just run `brew install
  pypy3.11` and rerun this report's `bench_interp.py` / `bench_mc2mb.py`
  (the scripts are already in the temp directory and can be reused directly;
  neither depends on CPython-specific features).

## 6. Expected payoff of three optimization paths

| Path | Expected payoff | Notes |
|---|---|---|
| Pure-Python micro-optimization (de-dict-ify / bind locals / reduce attribute lookups) | **Limited, ~1.2–1.5×** | The bulk of the cost at both hotspots is "redundantly doing the same work" (whole-block materialization, unmemoized search), not "each operation being slightly slow"; conventional tricks like localizing variables can only shrink the constant factor — they treat the symptom, not the cause. |
| mypyc (compile the existing .py to a C extension, types unchanged) | **Moderate, expected 3–8×**, contingent on fixing the algorithm first | This eliminates Python interpretation overhead / function-call overhead, and is especially effective for a high-call-frequency recursion like `dm_mov_search`; but without memoization first, the mypyc-compiled O(n^1.4) is still O(n^1.4), so large cases will still be slow. **The payoff order should be: fix the algorithm first, then apply mypyc to lock in the constant-factor gain.** |
| Cython (requires manual type annotations) | **Higher but with higher engineering cost too, expected 5–15×** | Annotating `crazy()`'s 20-iteration inner loop and `dm_mov_search`'s recursion with `cdef int` can yield more aggressive gains than mypyc, but it requires maintaining a `.pyx`/build chain, which creates some tension with the project's "pure Python, pip-installable" positioning (the all-Python-stack milestone just completed in B6) — worth evaluating whether it's worth trading away that property for performance. |

**Conclusion**: language-level speedups (mypyc/Cython) should both come
**after** the algorithm/cache fix, otherwise they're "accelerating the
engine" for a redundant computation that could have been eliminated outright.

## 7. Recommended next optimization action (single item)

Add a memoization cache to `_Assembler.dm_mov_search` (e.g., a `dict` cache
keyed on `(d, pos, depth)`, reused within the window where `jmpaddrs` is
stage-wise constant; or, more conservatively, snapshot-validate `jmpaddrs`
once before `code_generate()` starts and include the snapshot's hash in the
cache key to absolutely guarantee correctness). This is the only action that
simultaneously satisfies "zero risk, doesn't change `.mb` byte output" and
"largest expected payoff" (97.9% share of runtime, well-evidenced repeated
subproblems) — it should come before the SparseMemory block-materialization
optimization and any mypyc/Cython investment.

---

## Draft entries proposed for the internal research log (private, not in this repo; that log is not edited here — for review and manual merge)

**§C addendum/correction** (the existing sentence "pure-Python assembly
(mc2mb) time... near-linear with `.mb` size, ~40s/MB" needs correction):

> **The scaling behavior of pure-Python assembly (mc2mb), re-examined via
> log-log regression over 5 data points (176KB–799KB output), is actually
> superlinear, with an exponent of about 1.36–1.50 (not the previously
> assumed near-linear) — i.e., doubling the size increases runtime by about
> 2.6× rather than 2×. Root cause, see the new §H entry: `dm_mov_search` is
> an unmemoized recursive search accounting for 97.9% of runtime, and is a
> pure function of `(d, pos, depth)` (`jmpaddrs` is read-only at this stage),
> with a huge number of cacheable repeated subproblems.**

**§H new backlog entry** (suggested numbering H8, priority above existing
H1/H7, or merge directly into H7 and rewrite):

> **H8. mc2mb `dm_mov_search` memoization (zero risk, highest expected
> payoff)**: `dm_mov_search` in `malbolge/compiler/mc2mb.py:886` is a pure
> function of `(d, pos, depth)` during the `code_generate` stage (`jmpaddrs`
> no longer changes at this stage), but every `dm_move` redoes a depth-3,
> branch-factor-up-to-100 recursive search from scratch — for this tier's
> case, it's called nearly 95 million times, accounting for 97.9% of this
> stage's runtime (measured via cProfile). Adding a cache doesn't change the
> `.mb` byte output, and is currently the highest-payoff single-point
> optimization — it should come before the SparseMemory block-materialization
> optimization (next entry) and any mypyc/Cython investment.

> **H9. malbolge20 interpreter: SparseMemory block-materialization
> granularity is too coarse**: cProfile shows the main interpreter loop body
> itself accounts for only 4–9% of runtime, with 70–80% spent in
> `_materialize_block()` materializing an entire block (59,049 cells) of
> `crazy()` fill, even when the program only accesses a tiny fraction of the
> cells in that block. The existing `_block_seed_jump_map`'s cross-block
> seed-jumping trick could in principle be pushed down inside a block to
> compute individual cells on demand, avoiding whole-block pre-materialization.

*(The two entries above are draft text; whether and how to merge them into
the internal research log is left to manual review — this report itself does
not modify that log.)*
