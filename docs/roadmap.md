# Public candidate roadmap

> [English](roadmap.md) | [中文](roadmap.zh.md)

2026-11-13. This candidate contains reliability/documentation and the handwritten
MG CLI only; source changes are not a published release.

| State | Scope | Next gate |
|---|---|---|
| Candidate | Pure-Python `compile-mg`, UTF-8, alias checks and atomic per-file outputs | [Guide](user-guide.md); scoped regression receipt |
| Candidate | Web build/staging tests, Windows paths/bytes/permissions, native CI | Run hosted CI and real-browser checks; local tests do not establish these |
| Separate research branches | New JIT profiling, MLIR arithmetic exporter, overwritten-store pass | Continue independent correctness and performance review; absent from this candidate |
| Existing baseline | Native VM and guarded experimental ARM64 NOP JIT | Windows native availability does not imply Windows JIT support |
| Pending | Direct semantic-to-LAL, full variable SSA, runtime arrays/strings, Unshackled | Define bounded semantics and independent execution acceptance first |

Existing release claims remain scoped to the [1.2.0 receipt](notes/pypi-1.2.0-publication.json).
This public summary does not disclose private research documents.
