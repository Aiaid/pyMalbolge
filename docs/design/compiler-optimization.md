# Compiler optimization policy

> **English** | [中文](compiler-optimization.zh.md)
>
> Status, 2026-10-10: O3 policy and the target-interface implementation are
> integrated and locally accepted. [The integration receipt](../notes/compiler-optimization-validation.json)
> records full regression, final focused checks and all 12 selected full-image
> fingerprints. Earlier performance receipts retain their frozen-cohort scope.

## Default compilation

The CLI and `compile_python_to_mb()` default to `backend="auto"`, optimization
level 3, `target_pipeline="structured"`, and the existing `cluster/main` styles.
Applicable accepted transformations are enabled automatically. Explicit backend,
frontend, target-pipeline and pass selections retain control of their own scope.

```sh
uv run python -m malbolge compile program.py -o program.mb --stats
uv run python -m malbolge compile program.py -O0 --no-cache -o reference.mb
uv run python -m malbolge compile program.py --backend=direct -o direct.mb
uv run python -m malbolge compile program.py --target-pipeline=text -o text.mb
```

O3 auto always prepares the direct candidate. On Python 3.10+ with the pinned
optional `ir` extra available, it also prepares the semantic candidate with the
accepted ordered pass profile and target-interface controls. Each candidate
stops at its verified LAL records and laid-out `MemoryImage`. The smaller
predicted final MB wins; equal sizes select direct. Only the winner generates
bootstrap code, including when the requested final handoff is `text`.

This is deterministic size selection for a fixed source, toolchain, options and
optional-dependency environment. Installing the IR extra can introduce another
candidate and change the selected artifact. It does not promise the fastest
program or the cheapest total compilation on every workload. Candidate
preparation has a cost even when direct wins; a smaller image is not a general
runtime cost model.

## Levels and explicit choices

The table assumes no explicit backend, frontend, pass list or target handoff.

| Level | Frontend selection | Direct arithmetic shortcuts | Target handoff | CLI automatic cache |
|---|---|---|---|---|
| O0 | direct | Disabled | text | Off |
| O1 | direct | Enabled | text | Off |
| O2 | direct | Enabled | structured | Off |
| O3, default | direct versus applicable accepted semantic | Enabled | structured | On |

`-O0` through `-O3` and `--opt-level=0` through `--opt-level=3` are equivalent
CLI spellings. The library accepts the integer `opt_level` keyword.

- `--backend=c`, `direct` or `ir` locks that backend and disables competition.
  Explicit IR defaults to `semantic` at every level; `--ir-frontend=compat`
  restores the original direct-to-LAL IR bridge.
- Semantic O0 runs verification only and disables generated-local initialization
  omission, structured loop-condition preludes and native condition predicates.
  Semantic O1–O3 use the same accepted pass profile and enable those three
  representation controls; a higher level does not invent another pass profile.
- C is the reference frontend: its intrinsic constant folding and arithmetic
  identities remain active even at O0. Metadata marks this as
  `c_reference_intrinsics`; C0 is not a completely unoptimized arithmetic baseline.
- `--target-pipeline=text` or `structured` overrides the level's handoff.
  `--op-style` and `--jmp-style` remain explicit; O3 does not search all four styles.
- `--semantic-passes` supplies an exact ordered semantic sequence; `--passes`
  controls LAL passes. CLI `--semantic-passes` and an explicitly supplied
  optimization level are mutually exclusive. In the library an explicit
  `semantic_passes` sequence overrides the level's semantic profile, while O0
  still disables target representation shortcuts.
- An omitted backend is inferred from requested CLI inspection output:
  `--emit-c` selects C and IR inspection selects IR. An explicit incompatible
  backend/output combination is rejected. With no output option, default auto
  prints the winning MG; use `--emit-c -` for the former C inspection behavior.

O0 preserves syntax validation, error checks, required normalization and the
selected backend's calling convention. Individual stage APIs retain their
existing contracts; for example `compile_python_to_ir()` retains its explicit
compatibility-bridge defaults rather than inheriting the whole-program selector.

## Optional IR and failure boundaries

The base compiler remains dependency-free on Python 3.8+. Importing it does not
load xDSL. O3 auto skips the semantic candidate when its Python/xDSL environment
is unavailable or incompatible, or when that frontend reports an applicability
diagnostic for source already accepted by direct. The decision and reason are
reported. It does not install dependencies automatically.

Explicit IR requests require the supported environment and report errors rather
than changing backend. Verification, optimization, target lowering and layout
failures are not treated as optional-candidate failures. The semantic module
remains authoritative: no original-source replay or arbitrary fallback is used.

```sh
uv sync --extra dev --extra ir
uv run --no-sync python -m malbolge compile program.py --backend=ir \
  --ir-frontend=semantic -o semantic.mb --stats
```

## Exact size before bootstrap generation

`mc2mb.predict_image_mb_size(image)` checks the standard ordered segment layout,
direct offsets and bootstrap reservation, and legal direct source instructions.
Successful assembly requires the bootstrap to end at or before the final direct
segment's offset. Direct source cells therefore establish the output high-water
mark; adding the shared final alignment and two-byte tail gives the exact MB
byte count, without generating bootstrap instructions.

The prediction is conditional on successful assembly. It is not a certificate
of program correctness or sufficient reserved bootstrap space. Unsupported raw
images fail explicitly. The assembler still performs its own overlap and other
checks. LAL operation counts, IR sizes and address-space spans are not substitutes
for this final-file metric.

## Cache and provenance

At O3 the CLI automatically uses `.cache/malbolge` next to the source file.
Automatic persistence admits each artifact only up to **64 MiB**; this is a
per-artifact threshold, not a total-directory quota. Larger outputs still compile.
`--no-cache` disables persistence, and `--cache-dir PATH` explicitly selects a
cache without the automatic threshold, including at lower levels. Library
compilation does not create a persistent cache.

Outputs are atomic, aliases against input/output/cache artifacts are rejected,
and cached artifacts require matching size and SHA256. Invalid manifests or
corrupt artifacts are misses. An unavailable automatic cache must not prevent
writing an otherwise valid output; explicit cache I/O errors remain visible.
Auto still prepares candidates to determine the decision before a complete-MB
cache hit; it does not claim to skip frontend work or replay cached pass reports.

`--stats` and cache provenance retain the requested/resolved policy, selected
candidate, exact candidate sizes and reason, optional-IR status, ordered semantic
passes and target controls. Cache keys also include source/toolchain fingerprints,
Python, xDSL where applicable, styles and target handoff. Cold performance
measurements must pass `--no-cache`; warm-cache reuse is a separate result.

## Accepted scope and evidence

The accepted profile excludes the regressing experimental decimal-output pass.
The rejected bulk-NOP emitter remains excluded. Runtime engine selection and
JIT are separate from compiler O3: JIT stays explicit and is not enabled by this
policy. Native packaging and VM defaults have their own acceptance records.

The [semantic-pass receipt](../notes/semantic-pass-validation.json),
[structured-interface receipt](../notes/structured-lowering-validation.json),
[target-interface receipt](../notes/target-interface-validation.json) and
[common-VM comparison](../notes/common-vm-validation.json) retain their original
measurement scopes. Target-interface sources are integrated; prior prototype
measurements alone do not certify this policy change. The integration receipt
above records the final combined checks. Compile time, exact image size
and same-VM execution remain separate acceptance measurements.
