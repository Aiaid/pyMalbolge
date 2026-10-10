# Structured lower-backend handoff

> **English** | [中文](structured-lowering.zh.md)
>
> Current-branch update, 2026-10-10: structured handoff is now the O2/O3
> default under the [compiler policy](compiler-optimization.md); text remains
> explicit and is the O0/O1 default. This interface originally shipped as an
> experiment preserving generation styles, protocol, layout and padding. Its
> original acceptance remains historical evidence; combined integration is
> tracked in [the new receipt](../notes/compiler-optimization-validation.json).

## Data flow

```
Python frontend → MG → dependency-free LAL records → MemoryImage → MB
                              ↕ optional verified xDSL LAL
```

`translate_mg_to_lal` uses the existing MG parser and lowering with a typed
generator sink. It does not emit a complete MC string and reparse it. Fixed
DJMP/IND_OPR templates become immutable records once during module loading.
`layout_lal_to_image` ingests the records directly and shares the existing
packing, address resolution, BASE and memory-placement logic. The bootstrap
generator consumes ordered image segments without serializing `.data`.

MC and `.data` remain export formats and reference adapters. Their legacy
readers retain their previous acceptance/error behavior. Canonical structured
MC export preserves semantics and declaration order, rather than whitespace
and comments.

## Contracts

- `lal_model.py` provides immutable targets, flags, units, routines, data words
  and explicit instructions. UNIT offset order, including repeated/decreasing
  offsets, and continuation gaps are significant. Verification checks types,
  scopes, declaration order, word bounds and legacy naming ambiguities.
- `memory_image.py` provides `MemoryImage(entry, segments)` and
  `MemorySegment(kind, index, offset, words)`. Segment order and unset `-1`
  cells are significant. Entry is the existing routine dispatch descriptor,
  not a promise that the VM executes that address as an instruction.
- The base C/direct paths remain compatible with Python 3.8 and do not import
  xDSL. The optional IR path adapts records to verified xDSL operations and
  converts the transformed module back to records. The transformed module is
  authoritative; assembly does not reuse pre-pass objects.
- IR reports/cache exports can serialize diagnostic IR/MC. These exports are
  not the native assembly handoff. No source semantic→LAL lowering or variable
  SSA promotion is introduced by this change.

Native assembly explicitly rejects legacy-unsupported ALIGN, cross-routine
ADDRESS, BRANCH subtraction and cross-routine JMP subtraction. It does not
silently route unsupported records through the old text parser.

## Selection and exports

```sh
uv run python -m malbolge compile examples/hello.py \
  --backend direct --target-pipeline structured -o hello.mb
uv run python -m malbolge compile examples/hello.py \
  --backend ir --target-pipeline structured --emit-ir hello.mlir \
  --emit-mc hello.mc -o hello.mb
```

Whole-program compilation now defaults to O3/structured. The explicit library
selector remains `compile_python_to_mb(..., target_pipeline="structured")`. The compiler also exports native MG→LAL,
LAL→image and LAL/image→MB functions, including streamed byte output. Existing
MC APIs and `target_pipeline="text"` remain available for comparison.

Cache identity includes the selected target pipeline. Native stage metrics
identify the structured representation; they do not fabricate a required MC
artifact. Full-image cache hits retain the existing atomic-copy behavior.

## Acceptance and optimization

For this interface change, equal MC/data meaning, final MB bytes and VM results
are regression evidence that transport changed without changing generation.
Future generation optimizations may change bytes, addresses and execution
steps. Their gate is observable semantics (output, input consumption, errors
and termination), necessary machine invariants and separately measured compile
time, final image size and execution cost. Byte identity is not an optimization
objective.

Tests cover all four styles, defined-output fixtures, indirect-access modules,
native paths with full text handoffs disabled, streamed output, optional IR
authority, CLI exports/cache isolation and base imports without xDSL.
Measurements and independent layer hotspot analysis are retained in the
private companion research record. Acceptance fingerprints are in
[`structured-lowering-validation.json`](../notes/structured-lowering-validation.json).
