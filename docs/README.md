# docs index

> [中文](README.zh.md) | **English**

Every document here exists in both languages: `<name>.md` (English) and
`<name>.zh.md` (Chinese). The two are kept in sync; the Chinese version is
the original for the reverse-engineering notes.

## Compiler stack

| Document | Contents |
|---|---|
| [highlevel-to-malbolge.md](highlevel-to-malbolge.md) | Route decision: feasibility of high-level language → Malbolge, recommended pipeline, milestones, Python front end v1 and the direct backend |
| [python-subset-spec.md](python-subset-spec.md) | **Normative spec** for the accepted Python subset v1: per-AST-node acceptance whitelist, CPython divergences (D1–D17), diagnostic contract, audit appendix |
| [py2mg-backend.md](py2mg-backend.md) | Design of the direct `py → .mg` backend (`--backend=direct`): frame strategy, recursion-cycle detection, size comparison against the C path |
| [perf-baseline.md](perf-baseline.md) | Profiling baseline: the two hotspots, root causes, before/after measurements, superlinearity fit |

## Language specs (reverse-engineered)

| Document | Contents |
|---|---|
| [mg-spec.md](mg-spec.md) | `.mg` pseudo-instruction language spec (reverse-engineered from `ternary`, with experimental verification) |
| [hell-spec.md](hell-spec.md) | HeLL language spec (reverse-engineered from LMAO v0.6.0) |
| [lmao-internals.md](lmao-internals.md) | Analysis of the LMAO assembler's internal algorithms (layout, bootstrap generation) |
| [hell-assembler-design.md](hell-assembler-design.md) | Design for a Python HeLL assembler (shelved fallback route; §6 covers the GPL question) |

## Research and background

| Document | Contents |
|---|---|
| [findings.md](findings.md) | **Research findings and contribution log** (paper material, continuously updated): upstream discoveries, this project's contributions, quantitative data, theoretical derivations, bug reproductions, improvement backlog, licensing |
| [malbolge-landscape.md](malbolge-landscape.md) | Ecosystem survey: historical timeline, tool lineage (generators / HeLL-LMAO / Nagoya), full list of Nagoya papers, survey methodology |
| [iwagane-arrays.md](iwagane-arrays.md) | Dissection of the unpublished 2018 Nagoya array implementation: `IND_OPR` front-end sugar, stride-2 constraint, `LOADI`/`STOREI` design recommendation |
| [toolchain-guide.md](toolchain-guide.md) | Building and reproducing the external reference toolchain (platform pitfalls, determinism, verification conventions) |

Runtime library docs are in [`runtime/mg/README.md`](../runtime/mg/README.md);
test fixture provenance is documented in `test/fixtures/hell/README.md` and
`test/fixtures/nagoya/README.md`.
