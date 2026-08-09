# docs index

> **English** | [中文](README.zh.md)

Every document in this directory has both an English version (`<name>.md`) and
a Chinese version (`<name>.zh.md`), kept in sync; the reverse-engineering notes
were originally written in Chinese. Documents are grouped into subdirectories
by category; bilingual pairs always move together. Status markers: ✅ current /
🧊 shelved / 📌 historical snapshot (kept as-is with a superseding note).

## specs/ — language specifications

| Document | Status | Contents |
|---|---|---|
| [mg-spec.md](specs/mg-spec.md) | ✅ | `.mg` pseudo-instruction language spec (reverse-engineered from `ternary`, with experimental verification) |
| [hell-spec.md](specs/hell-spec.md) | ✅ | HeLL language spec (reverse-engineered from LMAO v0.6.0) |
| [python-subset-spec.md](specs/python-subset-spec.md) | ✅ | **Normative spec** for the accepted Python subset v1: per-AST-node acceptance whitelist, CPython divergences (D1–D17), diagnostic contract, audit appendix |

## design/ — designs and route decisions

| Document | Status | Contents |
|---|---|---|
| [highlevel-to-malbolge.md](design/highlevel-to-malbolge.md) | ✅ | Route decision: feasibility of high-level language → Malbolge, recommended pipeline, milestones, Python front end v1 and the direct backend |
| [py2mg-backend.md](design/py2mg-backend.md) | ✅ | Design of the direct `py → .mg` backend (`--backend=direct`): frame strategy, recursion-cycle detection, size comparison against the C path |
| [hell-assembler-design.md](design/hell-assembler-design.md) | 🧊 | Design for a Python HeLL assembler (shelved fallback route; §6 covers the GPL question) |

## upstream/ — upstream reference and archaeology

| Document | Status | Contents |
|---|---|---|
| [toolchain-guide.md](upstream/toolchain-guide.md) | ✅ | Building and reproducing the external reference toolchain (platform pitfalls, determinism, verification conventions); no longer needed for compilation, kept for conformance cross-checking and archaeology |
| [lmao-internals.md](upstream/lmao-internals.md) | ✅ | Analysis of the LMAO assembler's internal algorithms (layout, bootstrap generation) |

## notes/ — engineering notes

| Document | Status | Contents |
|---|---|---|
| [perf-baseline.md](notes/perf-baseline.md) | ✅ | Profiling baseline: the two hotspots and their root causes (hotspot #1 fixed, hotspot #2 still open) |

Further research notes (the findings log, the `mb-dialect-plan` design, the
all-directions `roadmap`, the Nagoya array dissection, the ecosystem survey)
live in a private companion repository that is not part of this one; documents
here occasionally cite them by entry number.

Runtime library docs: [`runtime/mg/README.md`](../runtime/mg/README.md);
test fixture provenance: `test/fixtures/hell/README.md` and
`test/fixtures/nagoya/README.md`.
