# 1.2.0 release candidate

> **English** | [中文](release-1.2.0.zh.md)
>
> Preparation date: 2026-11-10. Checkout version: **1.2.0rc1**.
> Local candidate only. Nothing has been uploaded to PyPI or TestPyPI, and
> this preparation does not replace the published 1.1.0 artifacts.

## Why a separate version

The published 1.1.0 portable wheel, Linux CPython 3.12 native wheel and source
archive were downloaded and checked against their recorded SHA-256 values.
Both wheels carry the project's LICENSE but omit the full Nagoya copyright
and permission notices for the ported compiler stages. The source archive
also includes optional HeLL test fixtures whose provenance README declares
GPL-3.0. These are distribution-content findings, not a claim that all program
behavior is broken or a blanket legal conclusion about the project.

The 1.2 candidate includes the missing notices and narrows the source archive.
The original 1.1.0 files remain unchanged; its publication receipt describes
only those original files.

## Candidate changes

- Include `THIRD_PARTY_NOTICES.md` and four verbatim upstream MIT license
  texts in wheel and source distributions, with `License-File` metadata.
- Exclude optional HeLL/LMAO fixtures and their dependent test from the source
  distribution. They remain in the repository for explicitly scoped research.
- Extract shared AST source analysis from the Direct compiler into a
  dependency-free module used by both Direct and semantic frontends. The
  source checks and generated-code behavior are intended to remain unchanged.
- Keep shared-analysis tests in the optional-IR CI job; test exact license
  bytes, distribution exclusions, wheel RECORD and installed execution.
- Preserve a caller's compiler override during packaging acceptance.
- Allow the disposable TestPyPI stamping helper to preserve canonical alpha,
  beta and release-candidate identities, including retries. For example,
  `1.2.0rc1` becomes `1.2.0rc1.dev<run-and-attempt>` in the disposable checkout.
- Refresh implementation/release boundaries without relabeling historical
  benchmarks as measurements of this candidate.

## Validation and remaining gates

See [candidate validation](release-1.2.0-validation.json) for final local
commands, artifact identities, installed checks and their scope. Test counts
from overlapping runs must not be added together.

This is not a completed cross-platform release. Before production publication:

1. Review and commit the candidate source, then build artifacts from that exact
   reviewed commit and rerun acceptance for those exact bytes.
2. Run the declared Python/OS/ABI CI matrix and installed-artifact checks;
   local Linux x86-64 CPython 3.12 results do not establish other platforms.
3. Keep Apple Silicon wheels withheld until deployment target, wheel tag,
   Mach-O minimum OS and real minimum-OS execution agree.
4. Keep ARM64 JIT explicit and experimental. x86-64 unavailability tests are
   not ARM64 machine-code acceptance.
5. Run the final release-version checks and obtain publication authorization.

There is no new layout protocol, direct semantic-to-LAL backend, general Python
support or claimed speedup in this maintenance candidate.
