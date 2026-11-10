# 1.2.0 release candidate

> **English** | [中文](release-1.2.0.zh.md)
>
> Preparation date: 2026-11-10. Next source candidate: **1.2.0rc2**.
> Earlier TestPyPI candidate **1.2.0rc1.dev42754363710001** passed the scoped remote checks below.
> Production PyPI remains at 1.1.0; no production release was made.

The next candidate is being prepared with additional input experiments and a
same-commit native-wheel matrix. Those checks are not yet accepted here. The
rc1 evidence below remains tied to `a466170` and its exact artifact hashes;
it is not evidence that rc2 or a final 1.2.0 package has passed.

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

## TestPyPI acceptance

[Run 42754363710](https://github.com/Aiaid/pyMalbolge/actions/runs/42754363710)
published three distributions from commit `a466170` on the separate
`codex/release-1-2-0-testpypi` branch. All nine remote install groups passed:
Linux Python 3.8/3.10 with IR/3.12 native/3.13, Linux ARM64 pure, macOS ARM64
and Intel pure, Windows pure, and a Linux sdist-to-native build. The seven
quality-CI jobs also passed. The three TestPyPI files were downloaded and
matched to the CI build hashes; notices and archive boundaries were rechecked.

See the [TestPyPI receipt](release-1.2.0-testpypi.json) and
[test project](https://test.pypi.org/project/malbolge/1.2.0rc1.dev42754363710001/).
These are test-site results, not production publication or Apple Silicon
native/JIT acceptance. The local validation receipt below records the earlier
pre-publication stage and has not been relabeled as hosted acceptance.

## Install the recorded TestPyPI candidate

Use a fresh directory outside a source checkout. The following pins the
already recorded rc1 snapshot, not the next candidate or production PyPI:

```sh
uv venv
uv pip install --index-url https://test.pypi.org/simple/ --no-deps 'malbolge==1.2.0rc1.dev42754363710001'
uv run --no-project python -c "import malbolge; print(malbolge.__version__)"
```

The reported version must be `1.2.0rc1.dev42754363710001`. Use a newly
recorded exact version when testing a later candidate. The base package has
no runtime dependencies. Optional dependencies come from production PyPI in
a separate step, without reinstalling the project or mixing package indexes:

```sh
uv pip install --index-url https://pypi.org/simple/ 'textual>=0.40.0'
# Optional IR only on Python 3.10+:
uv pip install --index-url https://pypi.org/simple/ 'xdsl==0.69.0'
```

A matching CPython 3.12 Linux x86-64 installation can select the native rc1
wheel; other platforms can select its portable wheel. This does not claim
native support on those platforms. For exact artifact auditing, use the
filenames and hashes in the receipt rather than only a version constraint.

`pyproject.toml` embeds `docs/notes/pypi-description.md` as the index description.
The Chinese file is its companion translation. Updating either GitHub README
does not change an existing TestPyPI/PyPI page: a new distribution must carry
the updated metadata. Description edits after rc1 are intended for the next
candidate, not retroactive changes to the recorded upload.

## Validation and remaining gates

See [candidate validation](release-1.2.0-validation.json) for final local
commands, artifact identities, installed checks and their scope. Test counts
from overlapping runs must not be added together.

This is not a completed cross-platform release. Before production publication:

1. Select the final production version and commit, then rebuild and accept
   those exact artifacts. TestPyPI acceptance covers only the recorded bytes.
2. Complete native OS/ABI coverage beyond the tested Linux CPython 3.12 wheel;
   the successful pure-wheel platform groups do not validate native builds.
3. Keep Apple Silicon wheels withheld until deployment target, wheel tag,
   Mach-O minimum OS and real minimum-OS execution agree.
4. Keep ARM64 JIT explicit and experimental. x86-64 unavailability tests are
   not ARM64 machine-code acceptance.
5. Run the final release-version checks and obtain publication authorization.

There is no new layout protocol, direct semantic-to-LAL backend, general Python
support or claimed speedup in this maintenance candidate.
