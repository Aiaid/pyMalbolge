# 1.2.0 final release freeze

> **English** | [中文](release-1.2.0.zh.md)
>
> Freeze checkpoint: 2026-11-10. Final version: **1.2.0**.
> Final source commit/artifact acceptance and production publication are pending.
> The recorded production release remains 1.1.0.

The final release freezes the compiler/VM implementation at rc2 commit
`063a3c59efaa1de4545e59bd0a26ee68dfddf860`. Uncommitted experimental JIT
changes from the development checkout are excluded. Final version metadata,
release gates and documentation require a new commit and freshly built bytes;
the rc2 receipt must not be relabeled as final acceptance.

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
  **15.0**. Hosted execution was on **15.8.2 only**; exact 15.0 runtime
  compatibility is untested. Metadata agreement is not minimum-OS execution proof.
- Hosted Mac JIT was unavailable and correctly rejected with write-protection
  guards retained. This is native VM acceptance, not hosted Mac JIT execution.
- All ten Linux ARM64 libc/ABI wheels executed real NOP JIT machine code.
  Existing local Mac/CM4 checks prove execution on those devices only.
  JIT remains explicit and experimental; none of this establishes a general speedup.

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

## Final production gates

The production workflow `.github/workflows/pypi.yml` requires the final source
commit's quality checks, a complete **37-file** build and **13 pre-upload
installed-package/input groups** before upload. Publication requires a valid
production credential. After upload, every public artifact hash and **13 remote
installation/input groups** must pass. A configured or queued gate is not a pass;
missing credentials or failed gates must not be reported as publication success.

Final source SHA, final artifact hashes and production execution acceptance
are not yet recorded here. Consult [production Actions](https://github.com/Aiaid/pyMalbolge/actions/workflows/pypi.yml)
and the [production project](https://pypi.org/project/malbolge/) for subsequent
status. Rebuild and accept the exact final artifacts rather than reusing rc2
hashes. Exact macOS 15.0 runtime testing remains a separately disclosed gap;
the previous minimum-OS execution requirement is not claimed as fulfilled by
15.8.2 hosting or by matching metadata.

There is no new layout protocol, direct semantic-to-LAL backend, general Python
support or claimed speedup in this maintenance release freeze.
