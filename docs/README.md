# docs index

> **English** | [中文](README.zh.md)

Prose documents have both an English version (`<name>.md`) and a Chinese
version (`<name>.zh.md`), kept in sync. Machine-readable measurement data is
shared between languages as one JSON file, without a duplicated translation.
The reverse-engineering notes were originally written in Chinese. Documents are grouped into subdirectories
by category; bilingual pairs always move together. Status markers: ✅ current / ⚠️ partially outdated /
🧊 shelved / 📌 historical snapshot (kept as-is with a superseding note).

For current behavior, start with [compiler policy](design/compiler-optimization.md),
[optimization status](design/optimization-status.md), [native VM](design/native-vm.md)
and [packaging](design/native-packaging.md). Dated receipts describe their recorded
checkout and tests; they are not a current full-suite count or a fresh benchmark.

The [current implementation and release boundaries](current-status.md) summarize
source versus release status, the Original-only browser, backend differences
and work that remains experimental or unimplemented (checked 2026-11-10).

For fixed-input checks of an installed candidate, start with the
[public experiment runner and manifests](../benchmarks/osp/README.md).
Its local validation is separate from any later release or platform matrix.

## specs/ — language specifications

| Document | Status | Contents |
|---|---|---|
| [mg-spec.md](specs/mg-spec.md) | ✅ | `.mg` pseudo-instruction language spec (reverse-engineered from `ternary`, with experimental verification) |
| [hell-spec.md](specs/hell-spec.md) | 📌 upstream reference; port shelved | HeLL language spec (LMAO v0.6.0), not a shipped pyMalbolge compiler input |
| [python-subset-spec.md](specs/python-subset-spec.md) | ✅ | **Normative spec** for the accepted Python subset v1: per-AST-node acceptance whitelist, CPython divergences (D1–D19), diagnostic contract, audit appendix |

## design/ — designs and route decisions

| Document | Status | Contents |
|---|---|---|
| [native-jit.md](design/native-jit.md) | ✅ local opt-in experiment | Actual guarded ARM64 NOP code generation, exact exits/COW/budgets, cold versus warm evidence and short-fixture regressions |
| [native-packaging.md](design/native-packaging.md) | ✅ 30 native wheels published; Apple Silicon pending | Native source-build hook, ABI/platform tags, installed acceptance, production hashes and remaining macOS ARM64 compatibility work |
| [native-vm.md](design/native-vm.md) | ✅ native-first batch default | Python API over a native Malbolge20 execution/memory core; correctness, snapshots, local build, same-image measurements and guarded-JIT scope |
| [highlevel-to-malbolge.md](design/highlevel-to-malbolge.md) | ⚠️ route current; subset/measurements historical | Route decision: feasibility of high-level language → Malbolge, recommended pipeline, milestones, Python front end v1 and the direct backend |
| [optimization-status.md](design/optimization-status.md) | ✅ dated snapshot | All optimization layers, accepted/default versus opt-in/local prototype status, evidence links and remaining limits |
| [compiler-optimization.md](design/compiler-optimization.md) | ✅ current O3 policy | Automatic applicable candidate selection, exact final-size prediction, O0–O3 controls, explicit locks and cache/error boundaries |
| [py2mg-backend.md](design/py2mg-backend.md) | ✅ | Design of the direct `py → .mg` backend (`--backend=direct`): frame strategy, recursion-cycle detection, size comparison against the C path |
| [compiler-ir.md](design/compiler-ir.md) | ✅ | Optional structured LAL/semantic boundaries, verified pass infrastructure and migration milestones; full variable SSA/liveness, new layout and LLVM/MLIR remain future |
| [semantic-ir.md](design/semantic-ir.md) | ✅ | Direct Python AST frontend, typed semantic IR, independent execution oracle, explicit target adapter, CLI selection and diagnostic limits |
| [semantic-optimization-passes.md](design/semantic-optimization-passes.md) | ✅ accepted profile; decimal experimental | Named semantic arithmetic/dataflow/control/emission passes, target arithmetic gate, level 0/1 and complete comparison contracts |
| [structured-lowering.md](design/structured-lowering.md) | ✅ O2/O3 default | Dependency-free MG→LAL→memory-image→MB handoff, optional xDSL adaptation, explicit text selection and behavioral optimization gate |
| [hell-assembler-design.md](design/hell-assembler-design.md) | 🧊 | Design for a Python HeLL assembler (shelved fallback route; §6 covers the GPL question) |
| [tui-web-architecture.md](design/tui-web-architecture.md) | ✅ Web implemented; TUI redesign partial | JSON-only ViewModels and backend APIs, implemented/deployed Original-only Pyodide debugger, remaining Textual renderer migration and historical phasing |
| [tui-redesign/README.md](design/tui-redesign/README.md) | ✅ | The imported TUI redesign canvas (four artboards: current-state reproduction, density-maximised, teaching-oriented, 80×24) plus an offline-viewable `preview.html` |

## upstream/ — upstream reference and archaeology

| Document | Status | Contents |
|---|---|---|
| [malbolge-reference.md](upstream/malbolge-reference.md) | ✅ source-backed reference | Original 10-trit machine, decoding, instructions, self-modification, I/O and specification/reference differences |
| [malbolge20-reference.md](upstream/malbolge20-reference.md) | ✅ source-backed reference | 20-trit machine, original-Malbolge incompatibility, reference runtime and toolchain layers |
| [toolchain-guide.md](upstream/toolchain-guide.md) | ✅ | Building and reproducing the external reference toolchain (platform pitfalls, determinism, verification conventions); no longer needed for compilation, kept for conformance cross-checking and archaeology |
| [lmao-internals.md](upstream/lmao-internals.md) | ✅ | Analysis of the LMAO assembler's internal algorithms (layout, bootstrap generation) |

## notes/ — engineering notes

| Document | Status | Contents |
|---|---|---|
| [release-1.2.0.md](notes/release-1.2.0.md) | Final 1.2.0 freeze; production acceptance pending | Frozen rc2 compiler/VM, exact test-version installation, notices and final release gates |
| [release-1.2.0rc2-testpypi.json](notes/release-1.2.0rc2-testpypi.json) | ✅ rc2 full matrix accepted | Commit 063a3c59: 35 native wheels plus pure/sdist, 13 remote install/input groups and seven quality-CI jobs; final artifacts remain separate |
| [release-1.2.0-testpypi.json](notes/release-1.2.0-testpypi.json) | ✅ dated rc1 acceptance | Commit a466170: three uploaded artifacts, nine remote install groups and seven quality-CI jobs; later candidate and full native matrix excluded |
| [release-1.2.0-validation.json](notes/release-1.2.0-validation.json) | 📌 earlier local candidate | Distribution-content review, local suite and installed-package checks before the recorded rc1 upload |
| [release-1.1.0.md](notes/release-1.1.0.md) | ✅ published 2026-10-27 | Changes since PyPI 1.0.0, 30 native wheels plus portable/source distributions and installed-package acceptance |
| [pypi-1.1.0-publication.json](notes/pypi-1.1.0-publication.json) | ✅ 32 public files verified | Source provenance, exact public artifacts/hashes, all 30 native downloads verified, initial no-cache compiler/IR/TUI smoke and mainline CI/Pages |
| [release-1.1.0-acceptance.json](notes/release-1.1.0-acceptance.json) | ✅ TestPyPI remote acceptance; platform scope explicit | Build/public-file hashes, nine remote installations, product CI and per-platform native/JIT evidence |
| [pypi-description.md](notes/pypi-description.md) | current build template | English index description embedded by pyproject.toml; production/TestPyPI install distinction and platform boundaries; edits require new artifacts |
| [ci-portability-validation.json](notes/ci-portability-validation.json) | ✅ local CI matrix acceptance | Clean-source Python 3.8/3.12/3.13 base suites, optional IR and semantic differential; pinned independent reference setup and AST/CLI/test portability repairs |
| [web-demo-deployment.json](notes/web-demo-deployment.json) | ✅ public Pages deployment verified | Actual public Hello execution, deployed revision/wheel identity, successful build/deploy and separate full-CI failures |
| [web-demo-validation.json](notes/web-demo-validation.json) | ✅ local Chromium acceptance | Portable browser-wheel build fix, freshness/vendor regression checks, Pyodide worker protocol and actual browser debugging controls; hosted evidence is recorded separately above |
| [native-jit-validation.json](notes/native-jit-validation.json) | ✅ local opt-in acceptance | JIT semantics/review/ABI/package checks, five-mode three-repeat same-image timings, emission/coverage/warmup costs and rejected first warmup |
| [native-engine-selection-validation.json](notes/native-engine-selection-validation.json) | ✅ current | Native-first batch defaults, explicit engine selection, Python fallback and CLI compatibility checks |
| [native-packaging-validation.json](notes/native-packaging-validation.json) | 📌 initial local acceptance | Native/pure/source installation, Python ABI wheels and CI configuration; later hosted acceptance and production publication are recorded in the release receipts above |
| [testpypi-ci-validation.json](notes/testpypi-ci-validation.json) | ✅ hosted test release accepted | CPython 3.12 manylinux native build, TestPyPI upload and exact-version remote installation/native smoke |
| [native-vm-validation.json](notes/native-vm-validation.json) | 📌 initial opt-in acceptance; default checks separate | Native VM correctness, review, ABI/package checks and five-repeat same-image Python/native/C execution measurements |
| [compiler-ir-validation.json](notes/compiler-ir-validation.json) | 📌 | First LAL/pass foundation acceptance and source fingerprints; later frontend/integration changes are covered by semantic-ir-validation.json |
| [semantic-ir-validation.json](notes/semantic-ir-validation.json) | 📌 | Semantic architecture acceptance before pass promotion; later changes are covered by semantic-pass-validation.json |
| [semantic-pass-validation.json](notes/semantic-pass-validation.json) | ✅ accepted pass profile | Pass acceptance; current unified compiler policy is covered by compiler-optimization-validation.json |
| [target-interface-validation.json](notes/target-interface-validation.json) | 📌 prototype snapshot | Target AST roles, regression and implementation fingerprints before integration; current acceptance is covered by compiler-optimization-validation.json |
| [compiler-optimization-validation.json](notes/compiler-optimization-validation.json) | ✅ default policy acceptance | O3 selection and explicit controls, cache failure regressions, full selected-image identity and independent execution-contract lineage |
| [structured-lowering-validation.json](notes/structured-lowering-validation.json) | ✅ local acceptance | Native lower-backend interface regression, library/CLI/IR integration and measurement scope |
| [latest-corpus-validation.json](notes/latest-corpus-validation.json) | ✅ dated working-cohort acceptance | Independent correctness 123/123; 36 cold compiles / 96 runtime attempts, 73 normal completions / 23 whole-child timeouts; local prototype and single-pass limits explicit |
| [common-vm-validation.json](notes/common-vm-validation.json) | ✅ dated uniform-VM acceptance | Same unmodified original C-O3 binary for 96 frozen corpus and 3 genuine original GCD inputs; 97 complete / 2 censored, exact sizes and final provenance/cleanup audit |
| [perf-baseline.md](notes/perf-baseline.md) | 📌 | Pre-QoS profiling baseline; its runtime representation/hotspot description is superseded by compact periodic memory and python-qos-validation.json |
| [fib-input-performance.json](notes/fib-input-performance.json) | 📌 | Pre-QoS 2026-10-08 shared measurement data: ordinary-Python Fibonacci, direct compilation, optimized C reference execution, CPython comparison, and a resource-bounded project Python CLI stop; bilingual interpretation is in the main README |
| [python-qos-audit.json](notes/python-qos-audit.json) | 📌 | Historical 11-group counterexamples; resolved by python-qos-validation.json, original evidence retained |
| [python-qos-validation.json](notes/python-qos-validation.json) | 📌 2026-10-08 acceptance | Local evidence and then-pending CI status at that snapshot; later hosted CI is recorded in release receipts |

Further research notes (the findings log, the `mb-dialect-plan` design, the
all-directions `roadmap`, the Nagoya array dissection, the ecosystem survey)
live in a private companion repository that is not part of this one; documents
here occasionally cite them by entry number.

Runtime library docs: [`runtime/mg/README.md`](../runtime/mg/README.md);
fixed Python benchmark programs and the CSV/JSON runner:
[`benchmarks/README.md`](../benchmarks/README.md);
test fixture provenance: `test/fixtures/hell/README.md` and
`test/fixtures/nagoya/README.md`.
