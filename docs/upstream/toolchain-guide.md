# Toolchain Build & Reproduction Guide

> [中文](toolchain-guide.zh.md) | **English**

> **Note (post-P4)**: Compiling Python/C/.mg programs no longer requires
> any of the external tools described in this document — the pure-Python
> port in `malbolge/compiler/` covers the whole chain
> (`python3 -m malbolge compile prog.py -o prog.mb`). This document is kept
> for controlled reference-port comparison, independent execution checks and
> upstream archaeology. Byte-identical intermediate artifacts, deterministic
> padding and source-program correctness are separate claims.
>
> Acquisition, build, and usage of the external reference tools, including
> every platform pitfall we've hit (verified on macOS/Darwin). The tools
> themselves live under the gitignored `ref/` and are not checked in.

## 0. Current upstream versus the frozen reference

The [official project page](https://malbolge20.gitlab.io/index-en.html) links
to the consolidated [GitLab.com creator repository](https://gitlab.com/malbolge20/malbolge20_creator).
The last source revision reproduced here is
[`2b42f4817afecca6b4c4f7374e21a399b6488e31`](https://gitlab.com/malbolge20/malbolge20_creator/-/tree/2b42f4817afecca6b4c4f7374e21a399b6488e31)
(commit 2026-10-06, checked 2026-10-26), **not a claim about today's main**.
It provides an `mbcc` driver, Python `parse_mc2.py`, seed controls and
address-search caching; it is not the old five-repository Perl-only setup.
Use that revision's README/build instructions for a current-upstream comparison.

```bash
git clone https://gitlab.com/malbolge20/malbolge20_creator ref/malbolge20_creator
git -C ref/malbolge20_creator checkout 2b42f4817afecca6b4c4f7374e21a399b6488e31
```

At that reproduced revision:

- `mbcc --seed N` controls ternary and initializer seeds; the initializer also
  accepts `-s`. Unseeded variation remains intentional. Fixed seeds are not
  proof of cross-platform byte identity.
- The old highlevel parser-exit defect has a correction. Do not apply the
  legacy statement "both parsers always exit 0 on error" to this revision.
- [Issue #1](https://gitlab.com/malbolge20/malbolge20_creator/-/work_items/1)
  records an inline-recursive Fibonacci miscompilation; the split-call result
  only validates that particular workaround. [Issue #2](https://gitlab.com/malbolge20/malbolge20_creator/-/work_items/2)
  separately records ternary returning success after syntax/lexical errors.
  These are revision-scoped reports, not a diagnosis of every source program
  or proof of the newest main's status.

**Issue status checked 2026-11-10:** both #1 and #2 are Open, with no public
replies visible. Their pages were read; the newest main revision was not
revalidated. An open issue does not establish that no later fix exists.

The legacy instructions below are retained for old fixtures and port
conformance. Their source identities are highlevel `5c4fb169`, ternary
`bf6b493b` and lowass `34b743f5`; the independent interpreter is pinned
separately below. Do not replace these fixtures silently with new upstream
output, or reuse their timings as a comparison with the consolidated toolchain.

## 1. Acquisition

For the full test suite's independent C correctness gate, use this explicit
setup command rather than cloning the whole toolchain:

```bash
uv run --no-sync python scripts/verify_mb_reference.py fetch
```

It retrieves only `malbolge20.c` and its MIT notice from pinned upstream
revision `21ebda787362ab009276e216be34c169e4d049f4`, checks both hashes and
keeps TLS certificate verification enabled. Existing different local files
are rejected, not overwritten. CI also requires clang on its protected
compiler PATH before executing the independent gate tests.
Both the instrumented gate and untouched reference compile as C99 with
`_POSIX_C_SOURCE=200809L`, making `getopt`/`optind` visible on glibc without
editing the pinned source.

The broader **legacy** acquisition below is historical, for optional compiler
comparison and research. It is not the recommended current-upstream entry.
Licenses vary; the legacy `highlevel-examples` has no license file. A shallow
clone follows the server tip, so inspect/record its commit and obtain the
recorded revision above before using it for a frozen comparison.

```bash
# Historical split repositories; retain normal TLS verification
for r in highlevel highlevel-examples ternary lowass malbolge20-interpreter; do
  git clone --depth 1 \
    "https://git.trs.css.i.nagoya-u.ac.jp/malbolge/$r" "ref/nagoya-$r"
done

# LMAO (GPL-3, HeLL -> original Malbolge)
git clone https://github.com/esoteric-programmer/LMAO ref/LMAO
```

Historical upstream certificate-chain failures need diagnosis when encountered;
the current correctness-gate setup uses verified HTTPS and pinned content hashes.

## 2. Legacy build (historically verified on macOS)

| Tool | Command | Pitfall |
|---|---|---|
| LMAO | `cd ref/LMAO && PATH="/opt/homebrew/opt/bison/bin:$PATH" make` | System bison 2.3 is too old (doesn't support `%define parse.lac`); needs `brew install bison` (3.8, keg-only, not on PATH by default) |
| nagoya-ternary | Same as above — `make` with the PATH prefix | Same bison issue; the many POSIX Yacc warnings can be ignored |
| nagoya-highlevel | Same as above — `make` with the PATH prefix | Same as above |
| nagoya-lowass | `cd ref/nagoya-lowass/init && make` | None; the perl stage needs no build |
| nagoya-malbolge20-interpreter | `make -C ref/nagoya-malbolge20-interpreter` | The `-L/usr/local/opt/llvm/lib` path in the Makefile doesn't exist — just a warning |
| ref/mbi.c (original-Malbolge reference interpreter, bundled in the repo) | `gcc -O2 ref/mbi.c -o ref/mbi` | Needed removing the glibc-specific `#include <malloc.h>` (already fixed and committed) |

General platform pitfalls:
- macOS has no `timeout` command — scripts wrap calls with Python's `subprocess.run(..., timeout=)` instead.
- The official LMAO README says `parse_mc.pl`, but the actual file in lowass is `parse_mc2.pl`.

## 3. Legacy pipeline and current Python entry points

```bash
# .mg -> .mb through the legacy ref/ wrapper (style/seed and checks below)
scripts/mg2mb.sh -s 1 prog.mg prog.mb

# Legacy C subset -> .mg (old highlevel can exit 0 on error; inspect stderr)
ref/nagoya-highlevel/parser prog.c > prog.mg 2>err.txt; [ -s err.txt ] && echo FAILED

# Python subset -> .mb (pure-Python compiler, no external parser invocation)
uv run python -m malbolge compile prog.py -o prog.mb

# Run and cross-validate
uv run python -m malbolge --variant=malbolge20 prog.mb --engine python
ref/nagoya-malbolge20-interpreter/malbolge20 prog.mb   # independent C reference

# HeLL -> original Malbolge (LMAO)
ref/LMAO/lmao program.hell -o program.mal
uv run python -m malbolge program.mal
```

**Scope note**: `uv run python -m malbolge compile` accepts Python source.
For handwritten MG, use `uv run python -m malbolge compile-mg prog.mg -o prog.mb`.
This pure-Python CLI needs no external reference toolchain. Omit `-o` to emit
MC on stdout, or use `--emit-mc prog.mc` alongside the MB output. The
`scripts/mg2mb.sh` wrapper remains available for frozen external-reference
comparisons. See the [MG specification](../specs/mg-spec.md) for options and
the output-safety contract.

## 4. Legacy determinism and error handling

These observations apply to the frozen split repositories, not the seedable
consolidated toolchain in §0:

- `ternary`: without `-s`, it randomizes code style; pin `-m -c -s 1` (the mg2mb.sh default).
- `parse_mc2.pl`: Perl hash-order randomization -> `PERL_HASH_SEED=0` (already handled by mg2mb.sh); it drops an `info` byproduct in the cwd (mg2mb.sh already isolates this to a temp directory).
- `lowass init`: calls `srand(time(NULL))` per padding cell, so the .mb is **not byte-reproducible** (behavior is unaffected). Byte-stable fixtures = generate once and check them in.
- Both the `ternary` and `highlevel` parsers **exit 0 even on error** — the only way to detect failure is checking stderr.

`scripts/mg2mb.sh` already rejects nonempty ternary stderr and empty output;
the wrapper is not an unguarded pass-through. Its `-s` fixes the legacy
ternary style choice, not the old initializer's randomized padding.

## 5. Verification Conventions

- Compare exact program output between the project and independent C
  interpreters, and also compare with the source program's expected result.
  Agreement between two VMs on an incorrectly compiled image is insufficient.
  Where relevant, assert consumed input, errors and termination, not just output.
- Intermediate byte identity is a controlled reference-port regression check;
  optimized lowering can change image bytes and steps while preserving behavior.
- Bulk verification uses the C reference (fast); pyMalbolge cross-checks a sample.
- Runtime library self-test: `uv run --no-sync python runtime/mg/tests/run.py` (19 checks; `--py` also runs pyMalbolge).
- Full test suite: `uv run --no-sync pytest test/`. Run the pinned reference
  fetch above and provide clang first: the independent gate requires them.
  Some optional external-tool tests may skip, but that does not make the full
  suite independent of reference setup. See `AGENTS.md` for slow/IR scopes.
