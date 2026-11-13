# Current implementation and release boundaries

> **English** | [中文](current-status.zh.md)
>
> Documentation checkpoint: 2026-11-10. Implementation statements describe the
> source checkout, including shared-source-analysis extraction in `0321a26`.
> Release and benchmark claims keep their own dated provenance.
> This is not a new full-suite, platform or performance acceptance report.

## Implemented

- **Compiler:** a restricted Python subset to **Malbolge20**, through C,
  direct MG, or optional semantic IR. O3/auto compares applicable Direct and
  accepted semantic candidates by predicted final image size, then emits one
  bootstrap. O2/O3 use structured LAL/memory-image handoff by default.
- **Architecture:** semantic IR has SSA expression values, mutable source
  slots, verified named passes and an independent execution oracle. Its target
  path remains semantic IR → target AST → MG → LAL → memory image → MB.
  Shared AST analysis is integrated in the source checkout and included in the
  1.2.0 release source; the older 1.1.0 publication receipt does not cover it.
- **Language:** unsigned 20-trit integers, scalar/control/function forms,
  recursion and the documented decimal I/O, flat tuple assignment, keyword
  calls and basic print f-strings. This is not full Python. Semantic source
  validation is stricter than Direct in some dead-code and local-binding
  cases. See the [subset boundaries](specs/python-subset-spec.md#01-backend-boundaries)
  and [semantic compatibility](design/semantic-ir.md#4-compatibility-limits-and-validation).
- **Execution:** Python interpreters for Original Malbolge and Malbolge20.
  Malbolge20 `run20` and batch CLI default to native when loadable, with Python
  fallback. Original, debugger, legacy `eval20` and non-batch terminal streaming
  remain Python. Imports and execution do not invoke a compiler.
- **Browser:** the [static Pyodide debugger](https://aiaid.github.io/pyMalbolge/)
  is implemented for **Original Malbolge only**. Local browser and hosted
  deployment acceptance have separate [receipts](notes/web-demo-validation.json)
  and [deployment evidence](notes/web-demo-deployment.json). The broader TUI
  redesign is not complete merely because `malbolge/tui/` exists.

## Published versus experimental

**[1.2.0 is published on PyPI](https://pypi.org/project/malbolge/1.2.0/).**
Source commit: `65c44bf7ee112f0df8c85b64b1c826787713492b`.
[Production run 42782746293](https://github.com/Aiaid/pyMalbolge/actions/runs/42782746293)
uploaded 35 native wheels, one portable wheel and one sdist through GitHub
OIDC Trusted Publishing. All 37 public artifact hashes, seven same-commit
quality-CI jobs and 13 pre-upload installation/input groups passed. All 13 post-upload remote installation/input groups passed. See the [publication receipt](notes/pypi-1.2.0-publication.json)
for the final per-group results and artifact identities.

The released compiler/VM retains the rc2 baseline; uncommitted experimental
JIT changes were not released. The [rc2 receipt](notes/release-1.2.0rc2-testpypi.json)
is separate historical evidence, not a substitute for final artifact checks.
macOS ARM64 has a 15.0 deployment/tag/Mach-O floor; exact macOS 15.0 runtime
compatibility remains untested. Both rc2 and all five final ARM64 ABI checks ran on macOS 15.8.2. Final
hosted Mac JIT was unavailable and explicitly rejected with guards retained;
Linux ARM64 NOP JIT execution is a separate claim. Local Mac/CM4 execution is device-specific,
not a general speed claim.

[PyPI 1.1.0](https://pypi.org/project/malbolge/1.1.0/) was published on
2026-10-27 with **30 native wheels, one portable wheel and one sdist**. The
native wheels cover CPython 3.9–3.13 on Linux glibc/musl x86-64/ARM64,
Windows x86-64 and macOS Intel. Python 3.8 compatibility checks are separate
from that wheel matrix. See [release notes](notes/release-1.1.0.md) and the
[artifact hashes and installed acceptance](notes/pypi-1.1.0-publication.json).

Apple Silicon wheels are now published; exact minimum-OS runtime testing remains pending.
Local macOS ARM64 execution does not prove compatibility with every tagged
minimum OS. The guarded ARM64 NOP JIT is **explicit and experimental**, not
the default engine or a general LLVM backend; short real fixtures regressed
despite the synthetic NOP benefit. See [packaging](design/native-packaging.md)
and [JIT scope](design/native-jit.md).

## Still design or future work

Direct semantic→LAL lowering, full source-variable SSA/liveness, new
protocol/layout takeover, LLVM/MLIR adapters, a `.ll` frontend, general runtime
arrays/strings/objects, signed integers and Malbolge Unshackled are not current
product capabilities. Optional xDSL dialects and a small native JIT do not
establish those features. Preserve the separation between a design, a local
experiment, an accepted default and a published distribution.

## Reading comparisons correctly

The [upstream guide](upstream/toolchain-guide.md) separates the frozen legacy
Nagoya reference from the consolidated GitLab.com toolchain. Public issues
describe particular reproducers and revisions, not proof that the newest
upstream main remains unfixed. Two interpreters agreeing on a wrong image is
not source-program correctness: check expected output, input consumption,
errors and termination too.

Dated benchmark artifacts retain their original source/image/engine identities,
timeouts and platform limits. Do not relabel them as measurements of this
checkout or infer current speed from IR size, wheel availability or old
Python-only timings.

## Reliability and MG candidate

This candidate includes reliability fixes and `compile-mg`; the new JIT profiling,
MLIR exporter and overwritten-store pass remain on separate research branches.
[User guide](user-guide.md) · [Roadmap](roadmap.md).
