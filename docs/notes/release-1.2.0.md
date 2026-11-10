# 1.2.0 production release

> **English** | [中文](release-1.2.0.zh.md)
>
> Publication checkpoint: 2026-11-10.

**[1.2.0 is published on PyPI](https://pypi.org/project/malbolge/1.2.0/).**
Source commit: `65c44bf7ee112f0df8c85b64b1c826787713492b`.
[Production run 42782746293](https://github.com/Aiaid/pyMalbolge/actions/runs/42782746293)
uploaded 35 native wheels, one portable wheel and one sdist through GitHub
OIDC Trusted Publishing. All 37 public artifact hashes, seven same-commit
quality-CI jobs and 13 pre-upload installation/input groups passed. All 13 post-upload remote installation/input groups passed. See the [publication receipt](pypi-1.2.0-publication.json)
for the final per-group results and artifact identities.

The released compiler/VM retains the rc2 baseline; uncommitted experimental
JIT changes were not released. The [rc2 receipt](release-1.2.0rc2-testpypi.json)
is separate historical evidence, not a substitute for final artifact checks.
macOS ARM64 has a 15.0 deployment/tag/Mach-O floor; exact macOS 15.0 runtime
compatibility remains untested. Both rc2 and all five final ARM64 ABI checks ran on macOS 15.8.2. Final
hosted Mac JIT was unavailable and explicitly rejected with guards retained;
Linux ARM64 NOP JIT execution is a separate claim. Local Mac/CM4 execution is device-specific,
not a general speed claim.

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

## Release changes

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

[Run 42757794922](https://github.com/Aiaid/pyMalbolge/actions/runs/42757794922)
succeeded at rc2 commit `063a3c59`, publishing **1.2.0rc2.dev42757794922001**.
All **37** public downloads match the accepted hashes: **35 native wheels**
(CPython 3.9–3.13, Linux glibc/musl x86-64/ARM64, macOS Intel/ARM64 and Windows
x86-64), one portable wheel and one sdist. All **13 remote installation/input
groups** and **seven same-commit quality-CI jobs** passed. Python 3.8 source-wheel
compatibility is checked separately from the 35-wheel matrix.

See the [rc2 receipt](release-1.2.0rc2-testpypi.json) and
[test project](https://test.pypi.org/project/malbolge/1.2.0rc2.dev42757794922001/).
The earlier [rc1 receipt](release-1.2.0-testpypi.json), at `a466170` with three
artifacts and nine installation groups, and [local candidate validation](release-1.2.0-validation.json)
remain unchanged historical evidence. Do not add overlapping test counts.

### Platform and JIT boundaries

- macOS ARM64 deployment target, wheel tag and Mach-O minimum OS agree at
  **15.0**. The historical rc2 hosted execution was on **15.8.2 only**; exact 15.0 runtime
  compatibility is untested. Metadata agreement is not minimum-OS execution proof.
- Hosted Mac JIT was unavailable and correctly rejected with write-protection
  guards retained. This is native VM acceptance, not hosted Mac JIT execution.
- All ten Linux ARM64 libc/ABI wheels executed real NOP JIT machine code.
  Existing local Mac/CM4 checks prove execution on those devices only.
  JIT remains explicit and experimental; none of this establishes a general speedup.

## Install production 1.2.0

In a fresh directory outside a source checkout, install the exact production version:

```sh
uv venv
uv pip install --index-url https://pypi.org/simple/ 'malbolge==1.2.0'
uv run --no-project python -c "import malbolge; print(malbolge.__version__)"
```

The version should be `1.2.0`. The TestPyPI commands below reproduce historical rc2 only.

## Install the recorded TestPyPI candidate

Use a fresh directory outside a source checkout. This installs the recorded
rc2 test snapshot, not final 1.2.0 or a production release:

```sh
uv venv
uv pip install --index-url https://test.pypi.org/simple/ --no-deps 'malbolge==1.2.0rc2.dev42757794922001'
uv run --no-project python -c "import malbolge; print(malbolge.__version__)"
```

The reported version must be `1.2.0rc2.dev42757794922001`. The base package has
no runtime dependencies. Install optional dependencies separately from
production PyPI without reinstalling the project or mixing indexes:

```sh
uv pip install --index-url https://pypi.org/simple/ 'textual>=0.40.0'
# Optional IR only on Python 3.10+:
uv pip install --index-url https://pypi.org/simple/ 'xdsl==0.69.0'
```

A matching platform/CPython ABI selects a native wheel; the portable wheel is
available otherwise. Audit exact filenames and hashes in the receipt.
`pyproject.toml` embeds `docs/notes/pypi-description.md` in distribution metadata;
README edits cannot change already uploaded package descriptions.

## Production publication and verification

The final source commit is `65c44bf7ee112f0df8c85b64b1c826787713492b`.
[Production run 42782746293](https://github.com/Aiaid/pyMalbolge/actions/runs/42782746293)
passed seven same-commit quality-CI jobs, built the complete **37-file** bundle
and passed **13 pre-upload installed-package/input groups**. PyPI upload
succeeded through GitHub OIDC Trusted Publishing using the `pypi` environment,
without a long-lived production API token. The environment was automatically
created; independent branch/environment protection has not been verified.

All **37 public artifact hashes** passed CI verification. All **13 post-upload remote installation/input groups** passed. See the [production publication receipt](pypi-1.2.0-publication.json)
for the final results, hashes and actual host evidence. Exact macOS 15.0 runtime
testing remains unperformed; rc2 execution on 15.8.2 and matching metadata do
not fulfill the earlier minimum-OS execution requirement.

Future production runs are intended to use manual dispatch only, so routine
pushes do not retry the immutable 1.2.0 upload. Check the current
[production workflow](https://github.com/Aiaid/pyMalbolge/actions/workflows/pypi.yml)
before dispatching. A new release needs a new version and its own acceptance.
There is no new layout protocol, direct semantic-to-LAL backend, general Python
support or general speedup claim in this maintenance release.
