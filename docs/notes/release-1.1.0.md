# 1.1.0 release

> **English** | [中文](release-1.1.0.zh.md)
>
> Status: published to production PyPI on 2026-10-27 as a portable wheel and
> source archive. The source commit is `0176888` on the default `master` branch.
> [Publication and fresh-install receipt](pypi-1.1.0-publication.json).

This release packages the development since 1.0.0 together with updated
distribution metadata. Its version is declared in `pyproject.toml` and
`malbolge.__version__`; the PyPI description is the concise
[package introduction](pypi-description.md), rather than the longer source
README with historical benchmarks.

## Changes since the published 1.0.0 wheel

- Compiler O0–O3 policy, automatic applicable candidate selection, structured
  LAL/memory-image handoff and bounded CLI caching.
- Optional verified semantic IR tools through the `ir` extra (Python 3.10+).
- Expanded Python subset, including unsigned decimal input/output and the
  documented tuple, keyword-call and f-string cases.
- Compact sparse memory, bounded byte-oriented batch execution, optional
  native Malbolge20 VM, explicit experimental ARM64 JIT and Python fallback.
- Debugger ViewModel support and an independently hosted browser debugger
  for original Malbolge only.
- Python-version portability fixes and fixed-source C reference preparation
  in CI.
- Corrected current-upstream activity, attribution, seed controls and
  historical comparison wording in both source READMEs.

The normative [Python subset specification](../specs/python-subset-spec.md)
defines supported inputs and divergences. Default compiler/engine choices
have changed since 1.0.0; pin explicit backends, optimization levels and
engines when comparing results. Optimizations need not preserve old image
bytes. Malbolge20 is not backward compatible with original Malbolge.

## Candidate artifacts and acceptance

The initial portable distribution consists of a `py3-none-any` wheel and a
source archive. Native compilation from source retains the existing
auto/required/disabled policy. A local macOS ARM64 native wheel can validate
that source path; it does not establish acceptance of every platform in the
configured native-wheel matrix.

Before upload, verify the actual archives' version, README metadata, source
completeness, RECORD hashes and exclusion of private research, environments
and stale native binaries. Install from the artifacts outside the checkout
and exercise the documented compiler/runtime commands, Python fallback,
optional IR and native execution. Keep an external artifact manifest with
hashes and installation receipts; archive hashes cannot be embedded into
their own source archive.

The separately configured TestPyPI workflow is a test-site path. Neither its
past success nor preparation of these local artifacts publishes this release.
Production upload, Git tags and the Wiki edits are separate actions.

## Production publication, 2026-10-27

[PyPI 1.1.0](https://pypi.org/project/malbolge/1.1.0/) contains the portable
`py3-none-any` wheel and source archive built from the merged mainline commit.
Both public file hashes and the description match the inspected local artifacts.
A fresh no-cache installation from production PyPI passed O3, Direct and IR
compilation/execution, byte I/O and execution-budget checks. The TUI extra
passed headless startup, step and step-back checks with Textual 8.2.8.
The mainline quality workflow passed all seven jobs and Pages build/deploy passed.
The [publication receipt](pypi-1.1.0-publication.json) records exact artifacts
and source identity. Native acceleration is available through source builds;
the incomplete hosted native-wheel matrix is recorded separately.

## Test-site execution, 2026-10-27

[TestPyPI run 40355946022](https://github.com/Aiaid/pyMalbolge/actions/runs/40355946022)
published `1.1.0.dev40355946022001` as a source archive, portable wheel and
CPython 3.12 manylinux wheel. All nine remote installation jobs passed,
including Python 3.8, optional IR, a required-native source rebuild, Windows,
Linux x86-64/ARM64 and macOS Intel/ARM64. The downloaded reports and public
TestPyPI file hashes agree with the build provenance.

The [acceptance receipt](release-1.1.0-acceptance.json) separates these completed
remote checks from the native-wheel platform matrix and its exact JIT scope.
The product-quality workflow passed all seven jobs; later CI/helper-only
changes do not change the packaged interpreter/compiler modules.
