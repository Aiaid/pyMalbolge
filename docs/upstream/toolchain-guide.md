# Toolchain Build & Reproduction Guide

> [中文](toolchain-guide.zh.md) | **English**

> **Note (post-P4)**: Compiling Python/C/.mg programs no longer requires
> any of the external tools described in this document — the pure-Python
> port in `malbolge/compiler/` covers the whole chain
> (`python3 -m malbolge compile prog.py -o prog.mb`). This document is kept
> for **conformance byte-exact differential comparison** (checking against
> the reference implementations) and upstream-archaeology scenarios.
>
> Acquisition, build, and usage of the external reference tools, including
> every platform pitfall we've hit (verified on macOS/Darwin). The tools
> themselves live under the gitignored `ref/` and are not checked in.

## 1. Acquisition

```bash
# The five Nagoya repos (MIT; the site's cert chain is incomplete, so verification must be skipped)
for r in highlevel highlevel-examples ternary lowass malbolge20-interpreter; do
  GIT_SSL_NO_VERIFY=1 git clone --depth 1 \
    "https://git.trs.css.i.nagoya-u.ac.jp/malbolge/$r" "ref/nagoya-$r"
done

# LMAO (GPL-3, HeLL -> original Malbolge)
git clone https://github.com/esoteric-programmer/LMAO ref/LMAO
```

Web resources follow the same pattern: `curl -sk https://www.trs.css.i.nagoya-u.ac.jp/projects/Malbolge/`.

## 2. Build (verified on macOS)

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

## 3. Pipeline Usage

```bash
# .mg -> .mb (recommended entry point; fixed seed and style, error-checking below)
scripts/mg2mb.sh -s 1 prog.mg prog.mb

# C subset -> .mg (highlevel; note it exits 0 even on error — must check stderr)
ref/nagoya-highlevel/parser prog.c > prog.mg 2>err.txt; [ -s err.txt ] && echo FAILED

# Python subset -> .mb (this project's front-end; handles the above error-checking internally)
python3 -m malbolge compile prog.py -o prog.mb

# Run and cross-validate
python3 -m malbolge --variant=malbolge20 prog.mb
ref/nagoya-malbolge20-interpreter/malbolge20 prog.mb   # C reference, 15-100x faster

# HeLL -> original Malbolge (LMAO)
ref/LMAO/lmao program.hell -o program.mal
python3 -m malbolge program.mal
```

**Scope note**: `python3 -m malbolge compile` only accepts `.py` source as
input. For the hand-written-`.mg`-to-`.mb` scenario — you already have
hand-authored `.mg` intermediate code, not something compiled from `.py` —
`scripts/mg2mb.sh` (wrapping the external ref/ toolchain) is still the only
CLI path today. To do that scenario in pure Python, call
`translate_mg_to_mc()` (`malbolge/compiler/mg2mc.py`) and
`assemble_mc_to_mb()` (`malbolge/compiler/mc2mb.py`) directly instead of
going through the CLI.

## 4. Determinism and Reproducibility

- `ternary`: without `-s`, it randomizes code style; pin `-m -c -s 1` (the mg2mb.sh default).
- `parse_mc2.pl`: Perl hash-order randomization -> `PERL_HASH_SEED=0` (already handled by mg2mb.sh); it drops an `info` byproduct in the cwd (mg2mb.sh already isolates this to a temp directory).
- `lowass init`: calls `srand(time(NULL))` per padding cell, so the .mb is **not byte-reproducible** (behavior is unaffected). Byte-stable fixtures = generate once and check them in.
- Both the `ternary` and `highlevel` parsers **exit 0 even on error** — the only way to detect failure is checking stderr.

## 5. Verification Conventions

- Byte-exact differential comparison between the two interpreters (pyMalbolge vs. the reference C interpreter) is the admission bar for every fixture.
- Bulk verification uses the C reference (fast); pyMalbolge cross-checks a sample.
- Runtime library self-test: `uv run --no-sync python runtime/mg/tests/run.py` (19 checks; `--py` also runs pyMalbolge).
- Full test suite: `uv run --no-sync python -m unittest discover test/` (doesn't depend on the ref/ tools — fixtures are checked in; e2e tests auto-skip when tools are missing).
