# docs index

> **English** | [中文](README.zh.md)

Prose documents have both an English version (`<name>.md`) and a Chinese
version (`<name>.zh.md`), kept in sync. Machine-readable measurement data is
shared between languages as one JSON file, without a duplicated translation.
The reverse-engineering notes were originally written in Chinese. Documents are grouped into subdirectories
by category; bilingual pairs always move together. Status markers: ✅ current /
🧊 shelved / 📌 historical snapshot (kept as-is with a superseding note).

## specs/ — language specifications

| Document | Status | Contents |
|---|---|---|
| [mg-spec.md](specs/mg-spec.md) | ✅ | `.mg` pseudo-instruction language spec (reverse-engineered from `ternary`, with experimental verification) |
| [hell-spec.md](specs/hell-spec.md) | ✅ | HeLL language spec (reverse-engineered from LMAO v0.6.0) |
| [python-subset-spec.md](specs/python-subset-spec.md) | ✅ | **Normative spec** for the accepted Python subset v1: per-AST-node acceptance whitelist, CPython divergences (D1–D19), diagnostic contract, audit appendix |

## design/ — designs and route decisions

| Document | Status | Contents |
|---|---|---|
| [highlevel-to-malbolge.md](design/highlevel-to-malbolge.md) | ✅ | Route decision: feasibility of high-level language → Malbolge, recommended pipeline, milestones, Python front end v1 and the direct backend |
| [py2mg-backend.md](design/py2mg-backend.md) | ✅ | Design of the direct `py → .mg` backend (`--backend=direct`): frame strategy, recursion-cycle detection, size comparison against the C path |
| [compiler-ir.md](design/compiler-ir.md) | ✅ | Optional structured LAL/semantic boundaries, verified pass infrastructure and migration milestones; variable SSA, optimization, layout and LLVM/MLIR remain future |
| [semantic-ir.md](design/semantic-ir.md) | ✅ | Direct Python AST frontend, typed semantic IR, independent execution oracle, explicit target adapter, CLI selection and diagnostic limits |
| [semantic-optimization-passes.md](design/semantic-optimization-passes.md) | ✅ accepted profile; decimal experimental | Named semantic arithmetic/dataflow/control/emission passes, target arithmetic gate, level 0/1 and complete comparison contracts |
| [hell-assembler-design.md](design/hell-assembler-design.md) | 🧊 | Design for a Python HeLL assembler (shelved fallback route; §6 covers the GPL question) |
| [tui-web-architecture.md](design/tui-web-architecture.md) | ✅ | Debugger UI architecture: three-layer split with a JSON-only `malbolge/view/` ViewModel shared by a Textual renderer and a (pending) Pyodide web build; the three backend APIs it needs; phasing and parallel boundaries |
| [tui-redesign/README.md](design/tui-redesign/README.md) | ✅ | The imported TUI redesign canvas (four artboards: current-state reproduction, density-maximised, teaching-oriented, 80×24) plus an offline-viewable `preview.html` |

## upstream/ — upstream reference and archaeology

| Document | Status | Contents |
|---|---|---|
| [toolchain-guide.md](upstream/toolchain-guide.md) | ✅ | Building and reproducing the external reference toolchain (platform pitfalls, determinism, verification conventions); no longer needed for compilation, kept for conformance cross-checking and archaeology |
| [lmao-internals.md](upstream/lmao-internals.md) | ✅ | Analysis of the LMAO assembler's internal algorithms (layout, bootstrap generation) |

## notes/ — engineering notes

| Document | Status | Contents |
|---|---|---|
| [compiler-ir-validation.json](notes/compiler-ir-validation.json) | 📌 | First LAL/pass foundation acceptance and source fingerprints; later frontend/integration changes are covered by semantic-ir-validation.json |
| [semantic-ir-validation.json](notes/semantic-ir-validation.json) | 📌 | Semantic architecture acceptance before pass promotion; later changes are covered by semantic-pass-validation.json |
| [semantic-pass-validation.json](notes/semantic-pass-validation.json) | ✅ | Committed pass/default acceptance; local target-interface experiments recorded separately |
| [target-interface-validation.json](notes/target-interface-validation.json) | 📌 | Local uncommitted prototype: target AST roles, defaults, regression and implementation fingerprints |
| [perf-baseline.md](notes/perf-baseline.md) | 📌 | Pre-QoS profiling baseline; its runtime representation/hotspot description is superseded by compact periodic memory and python-qos-validation.json |
| [fib-input-performance.json](notes/fib-input-performance.json) | 📌 | Pre-QoS 2026-10-08 shared measurement data: ordinary-Python Fibonacci, direct compilation, optimized C reference execution, CPython comparison, and a resource-bounded project Python CLI stop; bilingual interpretation is in the main README |
| [python-qos-audit.json](notes/python-qos-audit.json) | 📌 | Historical 11-group counterexamples; resolved by python-qos-validation.json, original evidence retained |
| [python-qos-validation.json](notes/python-qos-validation.json) | ✅ | Final local acceptance, native/portable VM evidence, fresh and retained artifacts, bounded runtime/storage, cache and assembly measurements; hosted CI is configured but not run |

Further research notes (the findings log, the `mb-dialect-plan` design, the
all-directions `roadmap`, the Nagoya array dissection, the ecosystem survey)
live in a private companion repository that is not part of this one; documents
here occasionally cite them by entry number.

Runtime library docs: [`runtime/mg/README.md`](../runtime/mg/README.md);
fixed Python benchmark programs and the CSV/JSON runner:
[`benchmarks/README.md`](../benchmarks/README.md);
test fixture provenance: `test/fixtures/hell/README.md` and
`test/fixtures/nagoya/README.md`.
