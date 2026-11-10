# 1.1.0 release

> **English** | [中文](release-1.1.0.zh.md)
>
> Status: production PyPI 1.1.0 contains 30 native wheels, one portable wheel
> and one source archive (32 files), published on 2026-10-27. The initial
> portable/source commit is `0176888` on the default `master` branch; the
> accepted native wheels were built at `e97edc2`. Apple Silicon remains TODO.
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

[PyPI 1.1.0](https://pypi.org/project/malbolge/1.1.0/) initially received the portable
`py3-none-any` wheel and source archive built from the merged mainline commit.
Both public file hashes and the description match the inspected local artifacts.
A fresh no-cache installation from production PyPI passed O3, Direct and IR
compilation/execution, byte I/O and execution-budget checks. The TUI extra
passed headless startup, step and step-back checks with Textual 8.2.8.
The mainline quality workflow passed all seven jobs and Pages build/deploy passed.
The [publication receipt](pypi-1.1.0-publication.json) records exact artifacts
and source identity.

Thirty accepted native wheels were subsequently added to the same release:
CPython 3.9–3.13 across Linux x86-64/ARM64 with glibc and musl (20 files),
Windows x86-64 (5) and macOS Intel (5). The release now contains 32 files;
the original portable wheel and source archive are preserved. All 30 public
downloads match their accepted size and SHA-256. Their 56 Python payload files
match the portable wheel after newline normalization; only the five Windows
wheels use different line endings. The native artifacts came from `e97edc2`
and [hosted acceptance run 40356927572](https://github.com/Aiaid/pyMalbolge/actions/runs/40356927572).
Each exact wheel passed VM/release installed-package checks before upload;
the production download checks do not constitute a new 30-platform execution
run. The publication receipt records every artifact. Apple Silicon native
wheels remain excluded as described below.

### Apple Silicon native-wheel TODO

Apple Silicon wheels remain unpublished. The five local CPython 3.9–3.13
wheels passed installed VM/JIT checks on macOS 27.0.1 only, with W^X and JIT
write-protection guards enabled. Four extensions record Mach-O minimum OS
26.0; CPython 3.12 records 11.0. Reconcile deployment target, wheel tag and
Mach-O minimum OS, then test the claimed minimum OS before publication.
The five-ABI hosted group remains untested because GitHub could not assign a
macOS ARM64 runner; local acceptance does not complete the 35-wheel matrix.
See the [acceptance receipt](release-1.1.0-acceptance.json).

## Esolangs Wiki publication, 2026-10-27

After the user confirmed CC0/public-domain-equivalent contribution terms,
`Anend` saved and verified the
[self-introduction (revision 200571)](https://esolangs.org/w/index.php?title=Esolang:Introduce_yourself&oldid=200571),
[Malbolge20 entry (revision 200572)](https://esolangs.org/w/index.php?title=Malbolge20&oldid=200572)
and [Malbolge resource entry (revision 200573)](https://esolangs.org/w/index.php?title=Malbolge&oldid=200573).
These small resource edits are separate from the larger article drafts.

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
