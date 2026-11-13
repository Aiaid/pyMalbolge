# Source checkout user guide

> **English** | [中文](user-guide.zh.md)
>
> Checked 2026-11-13. The MG command below is a candidate source
> change, not claims about the published PyPI 1.2.0 artifact.

## Setup and execution

Run from the repository root. The base package needs Python 3.8+; the optional
IR tools need Python 3.10+ and the pinned xDSL dependency.

```sh
uv sync --extra dev --extra ir
uv run --no-sync python -m malbolge compile --help
uv run --no-sync python -m malbolge compile-mg --help
```

Original Malbolge, debugger execution and legacy streaming remain Python.
Malbolge20 batches default to `auto`: use native when loadable, otherwise Python.
Select `--engine python` or `--engine native` when comparing results.

## Handwritten MG

This checkout includes a runnable fixture that outputs `Hi`:

```sh
uv run --no-sync python -m malbolge compile-mg test/fixtures/nagoya/mg_b_hi.mg --emit-mc demo.mc -o demo.mb --stats
uv run --no-sync python -m malbolge --variant=malbolge20 demo.mb --engine python --input '' --max-steps 3000000 --max-output 16
```

No C compiler, external Nagoya tools, Perl or xDSL is needed by `compile-mg`.
With no output option it emits MC to stdout. `--emit-mc -` and `-o -` select
stdout explicitly; only one output may use it. Defaults are
`--op-style cluster --jmp-style main --target-pipeline structured`.
Alternatives are `inline`, `direct` and `text`, respectively.

Input is UTF-8. Source/output aliases and duplicate output destinations are
rejected. Replacement is atomic **per file**, not a transaction across both
artifacts; stdout cannot be rolled back. Diagnostics and JSON stats use stderr.
Exit codes are 1 for compilation/I/O errors, 2 for invalid arguments and 130 for
interruption. Python frontend O-levels and compilation caching do not apply to
this command. See the [MG specification](specs/mg-spec.md).

## Native and JIT acceptance

```sh
uv run --no-sync --with setuptools --with wheel python scripts/build_native_vm.py
uv run --no-sync python -c "from malbolge import native; assert native.native_available(); print(native.jit_available())"
uv run --no-sync python -m pytest test/test_native_vm.py test/test_native_jit.py -q -rs
```

Native needs a host C compiler; Windows uses normal Visual Studio discovery.
JIT stays explicit and experimental, with a guarded NOP emitter for supported
little-endian Linux/macOS ARM64 hosts. Windows AMD64 native execution does not
imply JIT support; explicit JIT requests are rejected there. macOS capability
also depends on its runtime protection probe.

Candidate validation is recorded in [the scoped receipt](notes/reliability-mg-candidate-validation.json).
Full-suite and wheel results from the broader experimental integration are not
acceptance results for this candidate. Remote CI and browser layout remain unverified.
