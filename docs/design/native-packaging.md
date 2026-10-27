# Native extension packaging

> **English** | [中文](native-packaging.zh.md)
>
> Status: source-build hook implemented; release acceptance workflows updated
> 2026-10-27. The local installation checks and single hosted Linux TestPyPI
> trial below are dated 2026-10-10. The expanded 1.1.0 TestPyPI upload and all
> nine remote installation cases passed on 2026-10-27. Thirty hosted native
> wheels and five supplementary local macOS ARM64 wheels passed; hosted macOS
> ARM64 retry ended without acquiring a runner because of hosted capacity.
> Production PyPI 1.1.0 was published as a portable wheel and source archive;
> see the [publication receipt](../notes/pypi-1.1.0-publication.json).

## Installation behavior

The project keeps Hatchling. Source installs call `scripts/hatch_native.py`
during a PEP 517 wheel build; `scripts/native_build.py` uses standard Setuptools
`Extension`/`build_ext` compiler discovery. Build dependencies are Hatchling,
Setuptools and wheel, with compatible releases selected by the installer.
Runtime imports and execution never invoke a compiler. Native VM/JIT currently
support Malbolge20; Original Malbolge retains its Python execution paths.

| Installation input | Behavior |
|---|---|
| Matching native wheel | Install the packaged extension; no local compiler |
| Pure Python wheel | Install Python fallback; no native compilation |
| sdist or ordinary source directory | Build a wheel and attempt native compilation |
| Editable source directory | Do not compile automatically; build locally when needed |

pip delegates source builds to the backend in an isolated environment. Python
build dependencies do not supply an OS compiler or SDK. See the
[pip build interface](https://pip.pypa.io/en/stable/reference/build-system/).

## Build policy

`MALBOLGE_NATIVE_BUILD` affects builds, not installation of an existing wheel.

| Value | Rule |
|---|---|
| `auto` (default) | Try native; compilation failure emits a diagnostic and creates a pure wheel |
| `required` | Compilation failure aborts the wheel build |
| `disabled` | Build a pure wheel without invoking the compiler |

A source archive does not compile, even in required mode. Editable auto/disabled
builds do not generate native code; required editable builds report an error.
An editable checkout may still load a previously built local extension.

```sh
uv pip install .
MALBOLGE_NATIVE_BUILD=required uv build --wheel
MALBOLGE_NATIVE_BUILD=disabled uv build --wheel
uv run --with setuptools --with wheel python scripts/build_native_vm.py
```

Use `--output-dir` and Unix `--cc` with the developer builder when needed.
Windows uses standard Visual Studio compiler discovery; custom Windows CC,
true cross-compilation and fat/universal2 extension outputs are not accepted.
Unsupported native builds can fall back in auto mode. JIT stays explicit.

## Fresh artifacts and compatible tags

The hook compiles in fresh temporary staging and includes only that new binary
via Hatch `force_include`. Checkout `.so`/`.pyd` files remain excluded from
sdists and wheel selection. The sdist includes both hook/helper files, the C
source and JIT header. The helper checks source stability, records compiler
commands/version and fingerprints, and loads the fresh extension in its build
worker before accepting it. The developer command saves its build receipt.

Native wheels have non-pure metadata and a CPython/platform ABI tag, verified
against the build host. The current extension is not abi3. Pure fallback wheels
use `py3-none-any`. Packaging or invalid-tag errors do not silently fall back.
See [Hatch hooks](https://hatch.pypa.io/latest/plugins/build-hook/custom/),
[build data](https://hatch.pypa.io/latest/plugins/build-hook/reference/#build-data)
and [Setuptools extensions](https://setuptools.pypa.io/en/latest/userguide/ext_modules.html).

On macOS, default compilation selects the running host slice only in the worker
when ARCHFLAGS is absent. Explicit caller settings are preserved. A universal2
Python interpreter is supported for host-slice extension builds: the actual
thin Mach-O architecture determines the wheel architecture, while standard
wheel tools inspect deployment targets. Fat extensions, non-host slices and
unsupported target overrides are rejected rather than mislabeled.

## GitHub Actions prebuilds

`.github/workflows/native-wheels.yml` uses cibuildwheel 4.3.0 on five native
runners: Linux x86-64/ARM64, macOS Intel/ARM64 and Windows x86-64. No emulator
is used. The default macOS ARM64 job uses `macos-15`. Current labels and resource
availability are documented in the
[GitHub runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).

| Trigger/job | Configured coverage |
|---|---|
| Relevant pull request | CPython 3.12, seven wheels including both Linux libc families |
| Version tag or full manual dispatch | CPython 3.9–3.13, 35 wheels on the same five runners |
| Separate compatibility job | CPython 3.8 native/pure source-wheel installation and policy checks on Ubuntu |

Manual dispatch accepts `macos_arm64_only=true` to retry the five macOS ARM64
wheels without rebuilding the completed groups or the Python 3.8 job.
`macos_arm64_runner` selects `macos-15` (default) or `macos-26` for this group.

The 3.8 Linux artifact is a compatibility check, not a manylinux release wheel.
Native builds are required. cibuildwheel repairs Linux wheels for manylinux or
musllinux, tests installed wheels from a temporary directory, and stores wheel
artifacts for 14 days. The workflow does not publish to PyPI. See
[cibuildwheel options](https://cibuildwheel.pypa.io/en/v4.3.0/options/).

`scripts/verify_native_install.py` rejects checkout imports and missing required
native code, checks wheel metadata/default selection, Original Python I/O/EOF,
native byte I/O/EOF/budgets, COW/pages and self-modification. Linux ARM64
requires actual JIT machine-code steps. On macOS ARM64, an independent ctypes
call to `pthread_jit_write_protect_supported_np()` must agree with the native
JIT capability result: available JIT must execute machine code and pass
self-modification parity; unavailable JIT must reject explicit `engine="jit"`.
The native write-protection guard remains enabled. The x86-64 jobs require
explicit unsupported-JIT rejection. See the [JIT capability contract](native-jit.md).
Each installed wheel also runs `scripts/verify_release_install.py`: distribution
metadata and `malbolge.__version__` must match the candidate version read from
the checkout's `pyproject.toml`. The stdlib-only helper compiles a small Hello
program through default O3 and explicit Direct, executes both with bounded
Python VM execution, checks automatic VM selection, and checks Original
Malbolge byte I/O and CLI budget exits. It rejects checkout imports and records
installed module and generated-image hashes. The separate Python 3.8 native
and pure installations run both helpers as well.

Release reports use the cibuildwheel build identifier, including interpreter,
platform and Linux libc family, with a separate filename prefix from the VM
reports. Linux smoke reports use an explicit host mount so container failures
do not lose their JSON. CI preserves commit/interpreter/module hashes, wheel
tags and artifact hashes. Compiler command/version receipts are currently saved by the
developer builder; successful hook builds do not archive that receipt in CI
JSON. Build failures include backend diagnostics.

## TestPyPI trial pipeline

`.github/workflows/testpypi.yml` runs manually or on the
`codex/testpypi-native-ci` branch. It stamps matching distribution and module
versions with a unique `1.1.0.dev<run-id-and-attempt>` version in the disposable
CI checkout. It builds and tests one required-native CPython 3.12 manylinux
x86-64 wheel, then builds a `py3-none-any` wheel and an sdist with native
compilation disabled. All three distributions pass metadata checks, have their
SHA-256 hashes recorded, and are uploaded to TestPyPI. The stable repository
version stays unchanged.

Nine remote installation jobs cover the following configurations:

| Native runner | Python | TestPyPI distribution / extra |
|---|---|---|
| Linux x86-64 | 3.8 | Pure wheel |
| Linux x86-64 | 3.10 | Pure wheel plus pinned optional IR dependencies |
| Linux x86-64 | 3.12 | Native wheel |
| Linux x86-64 | 3.13 | Pure wheel |
| Linux ARM64 | 3.12 | Pure wheel |
| macOS ARM64 | 3.12 | Pure wheel |
| macOS Intel | 3.12 | Pure wheel |
| Windows x86-64 | 3.12 | Pure wheel |
| Linux x86-64 | 3.12 | sdist, required native source build |

Each job creates a fresh environment without a source checkout, verifies the
copied helpers against the build's commit/run/version identity and recorded
hashes, and installs the exact version from TestPyPI with required artifact
hashes and caching disabled. Wheel jobs require binary distributions; the
source job selects the sdist and requires compilation. Source-build and IR
dependencies come from production PyPI in separate installation steps; the
project distribution comes only from TestPyPI. The source job preinstalls its
build dependencies and disables build isolation for the explicit sdist build.

Both installed-package helpers run in every remote job. Release checks cover
O3/Direct compilation and bounded execution, version identity, byte I/O and
budgets; the IR job also compiles and executes through the explicit IR backend.
The VM helper checks the required native or pure installation contract. Remote
ARM jobs here install pure wheels; native ARM/JIT acceptance belongs to the
35-wheel workflow above. Build and per-job installation provenance are retained
as Actions artifacts for 14 days.

Only the isolated publishing job receives `TEST_PYPI_API_TOKEN`, stored as a
GitHub Actions encrypted repository secret. It has no source checkout and
explicitly targets `https://test.pypi.org/legacy/`. Missing credentials fail
before upload. This workflow configures no production PyPI upload. See
[the historical hosted trial evidence](../notes/testpypi-ci-validation.json).

## Acceptance and remaining limits

The 2026-10-10 local checks showed that installation from a default-mode sdist
built native code automatically.
CPython 3.8.19, 3.12.9 and 3.13.14 native wheels passed installed-environment
native/JIT checks; a pure wheel passed Python fallback checks. Policy, RECORD,
source completeness, stale-binary exclusion and source rebuild tests passed.
The matrix identifiers and workflow syntax were checked locally. This is not
hosted multi-platform acceptance or a new performance benchmark.

[Packaging validation](../notes/native-packaging-validation.json) and the
TestPyPI trial record those dated checks, including the hosted Linux x86-64
CPython 3.12 native build and installed-wheel smoke.

The expanded [TestPyPI acceptance run](https://github.com/Aiaid/pyMalbolge/actions/runs/40355946022)
at commit `f781b45` passed on 2026-10-27. It uploaded the three distributions as
`1.1.0.dev40355946022001`; all nine remote installation cases passed, and all
nine downloaded `release.json` reports record success. This covers source,
pure, native and optional IR installation in the configurations listed above.

The [product QoS run](https://github.com/Aiaid/pyMalbolge/actions/runs/40355389398)
at `5ba394b` passed all seven jobs. Changes from that commit through `b7b36ed`
are limited to CI configuration, the verification helper and documentation.

The earlier [native matrix run](https://github.com/Aiaid/pyMalbolge/actions/runs/40355942641)
failed the macOS ARM64 JIT requirement because its OS reported no thread-local
JIT write protection. The current helper checks that OS capability explicitly
while preserving the native guard.

The [native coverage run](https://github.com/Aiaid/pyMalbolge/actions/runs/40356927572)
at `e97edc2` completed 30 wheel files across Linux x86-64/ARM64, macOS Intel and
Windows x86-64. All 30 artifact hashes, 30 VM reports and 30 release reports were
checked; the Python 3.8 native/pure compatibility checks also passed. The ten
Linux ARM64 cases each executed at least 4,096 actual JIT steps. The remaining
macOS ARM64 group stayed queued for over ten minutes. A
[targeted macOS ARM64 retry](https://github.com/Aiaid/pyMalbolge/actions/runs/40358838205)
at `b7b36ed` selected `macos-26`. Rechecked on 2026-10-27, GitHub cancelled
that job without assigning a runner: "The job was not acquired by Runner of
type hosted even after multiple attempts", with an ARM64 capacity notice.
No code tests ran for that group. Full 35-wheel hosted native acceptance
remains incomplete; 30 hosted wheels passed.

Supplementary local macOS 27.0.1 ARM64 checks passed for all five CPython
versions, 3.9–3.13. Each wheel was built from a pinned 1.1.0 sdist, installed into
a fresh environment, and passed both helpers with 4,096 actual JIT steps and
the native write-protection guard enabled. All 58 `malbolge/` source files
matched the pinned sdist. The CPython 3.12 extension has a Mach-O minimum OS of
11.0; the other four have 26.0. Execution on macOS 27.0.1 establishes local
acceptance there; older OS and minimum-OS runtime acceptance remain unverified.

The [1.1.0 acceptance receipt](../notes/release-1.1.0-acceptance.json) records
the nine TestPyPI cases, 30 hosted wheels, five local wheels and pending hosted
macOS ARM64 scope. Original native support, general JIT emitters and
prebuilt native-wheel distribution to PyPI remain separate roadmap items.

pip can cache a pure fallback wheel and reuse it after a compiler becomes
available. Installing a selected wheel never runs a build hook, so changing
build mode does not rebuild it. Rebuild explicitly from source when native is
required; a same-version published pure wheel can also satisfy an uncovered
platform without trying its sdist. See the
[pip optional-extension cache caveat](https://pip.pypa.io/en/stable/topics/caching/#avoiding-caching).
