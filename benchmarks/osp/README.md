# Fixed OSP experiment inputs

This is a public, bounded experiment entry point, not a claim that every
supported program or platform has been tested. No private research data is
required. The runner records new observations; existing historical benchmark
numbers are not silently carried into a new release.

## Inputs and contracts

- `manifest.json`: six programs / ten workloads. `smoke` selects literal
  output, folded arithmetic and two byte-echo inputs (three programs / four
  workloads). `standard` additionally tests a runtime loop and lazy boolean
  input consumption. `all` also includes inline double recursion.
- `regressions.json`: three public historical layout reproductions, evaluated
  against the **correct source-level output and normal termination**. Fixture
  comments describe old findings, not the outcome on the selected release.
  These larger tests require `--suite all`; they are not in the smoke suite.
- `../manifest.json`: the existing 12 ordinary-Python programs / 32 fixed
  workloads, including decimal I/O, GCD, factorial and recursion. The same
  runner accepts it. Decimal helpers can produce hundreds of MB of code, so
  this corpus is an explicit extended run, not a cheap install smoke test.

The new manifests lock normalized UTF-8/LF source SHA-256 values and specify
exact hexadecimal input/output, expected bytes consumed, instruction budgets
and whole-child deadlines. Raw source hashes are also retained, allowing CRLF
checkouts without claiming identical raw file bytes across systems.

The CPython oracle uses ordinary Python execution with two explicit byte
helpers: `putchar(n)` writes `n % 256`, and `getchar()` reads one byte (EOF is
`3**20 - 1`). These helper cases do not claim that unmodified CPython provides
Malbolge's byte builtins. The ordinary-Python corpus needs no such helpers.
All current oracle inputs avoid unsigned-arithmetic differences from CPython.
Run only trusted manifests: their Python sources are executed in subprocesses,
not a security sandbox.

## Quick input validation

From the repository or extracted source archive, with the development
environment prepared as described in the root README:

```sh
uv run --no-sync python scripts/osp_experiments.py --mode oracle --suite all \
  --output-dir /tmp/osp-input-check
uv run --no-sync python scripts/osp_experiments.py --mode oracle \
  --manifest benchmarks/osp/regressions.json --suite all \
  --output-dir /tmp/osp-regression-input-check
uv run --no-sync python scripts/osp_experiments.py --mode oracle \
  --manifest benchmarks/manifest.json --suite all \
  --output-dir /tmp/osp-corpus-input-check
```

Use a new output directory every time; an existing directory is never
overwritten. On Windows, replace `/tmp/...` with a new local directory.
Oracle-only success is **not** compiler or target-VM acceptance.

## Installed-artifact acceptance

Use the exact candidate wheel or sdist and preserve its external SHA-256
manifest. Install outside the checkout. `--python` selects the installed
environment; every child uses `-I` and imports that environment's package.
The controller and public inputs can remain in the source archive. They are
not imported into the installed package.

```sh
uv venv /tmp/osp-installed
uv pip install --python /tmp/osp-installed/bin/python /path/to/candidate.whl
uv run --no-sync python scripts/osp_experiments.py --mode run \
  --python /tmp/osp-installed/bin/python --expected-version 1.2.0rc1 \
  --forbid-source-root . --suite smoke --backends auto direct \
  --engines python --output-dir /tmp/osp-installed-smoke
```

The version above is a local candidate example, not a publication claim. Use
the exact installed version when evaluating a TestPyPI development build or
another release. Windows virtual environments use
`Scripts/python.exe`. An explicit `--forbid-source-root` rejects imports from
the checkout even if an editable install is accidentally present.

For a native-wheel job add `--engines python native`. Missing native support
is a failure of that requested job, never a silent Python fallback. For an
IR job install the selected release's `ir` extra and add `ir` to `--backends`.
The environment receipt records the exact xDSL version. Auto-selection and
explicit IR may select different images; compare their recorded identities.
JIT is deliberately outside this minimal experiment.

Useful next layers, using the same installed Python/version flags:

```sh
# Loops, side effects and recursion; larger than the smoke tier.
uv run --no-sync python scripts/osp_experiments.py --mode run --suite all \
  --backends auto direct --engines native --output-dir /tmp/osp-extended
# Decimal input/output, all three existing fixed inputs. Native recommended.
uv run --no-sync python scripts/osp_experiments.py --mode run \
  --manifest benchmarks/manifest.json --cases decimal_echo \
  --backends direct --engines native --output-dir /tmp/osp-decimal
# Historical source cases, not the old tests that assert failure.
uv run --no-sync python scripts/osp_experiments.py --mode run \
  --manifest benchmarks/osp/regressions.json --suite all \
  --backends auto direct --engines native --output-dir /tmp/osp-layout
```

These shortened examples use the current interpreter. Add `--python`,
`--expected-version` and `--forbid-source-root` from the installation example
for release acceptance; omitting them does not establish installed-artifact
acceptance. To compare O0 or the text target handoff, select `--opt-level 0`
or `--target-pipeline text` in a separate output directory. C retains its
reference arithmetic intrinsics, so it is not a universal unoptimized baseline.

## Results, timing and independent checks

Each directory contains `report.json`, an environment receipt, CPython
contracts, one compile receipt per program/backend/repetition, and separate
runtime receipts per input/engine. They include package-file fingerprints,
source/input contracts, image size/SHA-256, selected backend, output bytes,
consumption, stop reason, executed steps and CPU/wall times. The package and
inputs are rechecked at the end. Raw image files are deleted by default;
`--keep-images` retains them for a separate independent-reference gate.

Compilation uses the public compilation-plan API with no persistent cache;
its timer excludes import, file write and hashing. Runtime uses `run20` in
a fresh child; its timer includes source validation, memory initialization
and execution but excludes image reading, hashing and imports. Whole-child
wall time is recorded separately as a diagnostic. CPU/wall costs, MB size
and guest steps are different quantities and must not be combined into a
single score. Budgets and deadlines are limits, not performance thresholds.

Default `--repeats 1` is acceptance only. `--repeats 3` or more rotates
backend and engine order between repetitions, retains every raw sample and
checks repeated image identity. Same-host controlled measurements are still
needed for a speed claim; this script does not control thermal state, CPU
frequency, load or filesystem caching. Do not treat CI runner differences
as compiler improvements.

Timeout, compile error, unavailable requested engine, wrong output, wrong
consumption, non-HALT stop, input/package change and repeated-image mismatch
make the run unsuccessful. A timeout is preserved without a successful API
runtime; never replace missing measurements with its deadline or hide them
from a table. Ctrl-C or a killed controller leaves `status: running`, not a
false pass. Reports may contain diagnostic stderr; inspect before publishing.

CPython-versus-project-VM agreement is not an independent target-VM proof.
For selected images use the existing hash-pinned reference workflow:

```sh
uv run --no-sync python scripts/verify_mb_reference.py fetch
uv run --no-sync python scripts/verify_mb_reference.py build \
  --output-dir /tmp/osp-reference
uv run --no-sync python scripts/verify_mb_reference.py verify --help
```

Use the binary path returned by `build`, the retained full image, the exact
manifest input/output/consumption and explicit budgets with `verify`.
Reference instrumentation is correctness evidence, not performance data.

## Platform evidence

Run the same manifest and runner on each claimed OS/architecture using its
installed artifact. Preserve each host's receipts separately. Linux glibc,
Linux musl, macOS Intel, macOS ARM64 and Windows are distinct targets; an
uploaded wheel, source compilation or skipped test is not execution evidence.
Minimum-OS claims need execution on that OS. Python fallback, native and
optional IR are separate rows. This directory defines inputs and commands;
it does not predeclare any unexecuted platform as passed.
