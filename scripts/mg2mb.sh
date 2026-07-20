#!/usr/bin/env bash
#
# mg2mb.sh -- compile a Malbolge20 pseudo-instruction program (.mg) down to
# a runnable Malbolge20 program (.mb), by driving the Nagoya University
# toolchain that lives (gitignored, not part of this repo) under ref/:
#
#   .mg --[ref/nagoya-ternary/parser]--> .mc (Low-Level-Assembly)
#   .mc --[ref/nagoya-lowass/parse_mc2.pl]--> .data (memory image, stage 1)
#   .data --[ref/nagoya-lowass/init/init]--> .mb (Malbolge20 source, stage 2)
#
# All three tools are MIT-licensed and must be present and already built:
#   - ref/nagoya-ternary/parser        (build: cd ref/nagoya-ternary && make;
#     on macOS the system bison is too old, use e.g.
#     PATH="/opt/homebrew/opt/bison/bin:$PATH" make)
#   - ref/nagoya-lowass/parse_mc2.pl   (no build needed, just perl)
#   - ref/nagoya-lowass/init/init      (build: cd ref/nagoya-lowass/init && make)
#
# Usage:
#   scripts/mg2mb.sh [-s SEED] [-m|-d] [-c|-i] input.mg [output.mb]
#
#   -s SEED   Random seed passed to the ternary translator (default: 1).
#             Fix this for reproducible output -- without a seed option,
#             the translator randomizes code style on every run.
#   -m / -d   Control style for successive ROT/OPR module calls:
#             -m returns to the main control flow, -d jumps directly to
#             the next module. Default: -m.
#   -c / -i   Code style for OUTPUT/INPUT/SET/RESET: -c generates shared
#             modules, -i inlines the code. Default: -c.
#
# If output.mb is omitted, it defaults to input's basename with .mb.
#
# Reproducibility note: with -m/-d and -c/-i both given, the .mg -> .mc
# translation step is fully deterministic for a fixed seed, and the
# .mc -> .data assembly step is made deterministic by pinning
# PERL_HASH_SEED=0 (parse_mc2.pl otherwise depends on Perl's per-process
# randomized hash iteration order). However the final .data -> .mb step
# (ref/nagoya-lowass/init/init) is NOT byte-for-byte reproducible: its
# main() re-seeds srand(time(NULL)) on every unused/padding memory cell
# it fills (init.cpp, the "unset region" loop near the end of main), so
# the padding bytes of the output .mb vary from run to run depending on
# wall-clock time. This does not affect program behavior -- those cells
# sit outside the code path the compiled program actually executes -- but
# it means two runs of this script over the same input will differ in
# raw bytes (usually only in padding) even though they behave identically.
# If you need a byte-stable fixture, generate it once and check it in.
#
# Example:
#   scripts/mg2mb.sh examples/hello.mg examples/hello.mb
#   python3 -m malbolge --variant=malbolge20 examples/hello.mb

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

TERNARY="$REPO_ROOT/ref/nagoya-ternary/parser"
PARSE_MC2="$REPO_ROOT/ref/nagoya-lowass/parse_mc2.pl"
INIT="$REPO_ROOT/ref/nagoya-lowass/init/init"

SEED=1
STYLE_FLAG="-m"
IO_FLAG="-c"

usage() {
    grep '^#' "$0" | sed '1d;s/^# \{0,1\}//'
    exit 1
}

while getopts ":s:mdcih" opt; do
    case "$opt" in
        s) SEED="$OPTARG" ;;
        m) STYLE_FLAG="-m" ;;
        d) STYLE_FLAG="-d" ;;
        c) IO_FLAG="-c" ;;
        i) IO_FLAG="-i" ;;
        h) usage ;;
        *) usage ;;
    esac
done
shift $((OPTIND - 1))

if [ $# -lt 1 ]; then
    usage
fi

MG_INPUT="$1"
if [ ! -f "$MG_INPUT" ]; then
    echo "error: input file not found: $MG_INPUT" >&2
    exit 1
fi

if [ $# -ge 2 ]; then
    MB_OUTPUT="$2"
else
    MB_OUTPUT="$(basename "$MG_INPUT" .mg).mb"
fi

check_tool() {
    local path="$1" build_hint="$2"
    if [ ! -x "$path" ]; then
        echo "error: required tool not found or not executable: $path" >&2
        echo "  build it with: $build_hint" >&2
        exit 1
    fi
}

check_tool "$TERNARY" "cd '$REPO_ROOT/ref/nagoya-ternary' && PATH=\"/opt/homebrew/opt/bison/bin:\$PATH\" make  # macOS system bison (2.3) is too old; install a newer one via 'brew install bison'"
if [ ! -f "$PARSE_MC2" ]; then
    echo "error: required tool not found: $PARSE_MC2 (should be checked out with ref/nagoya-lowass, no build needed)" >&2
    exit 1
fi
check_tool "$INIT" "cd '$REPO_ROOT/ref/nagoya-lowass/init' && make"

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

BASE="$WORKDIR/prog"
MC_FILE="$BASE.mc"
DATA_FILE="$BASE.data"

echo "==> translating .mg -> .mc (seed=$SEED $STYLE_FLAG $IO_FLAG)" >&2
"$TERNARY" "$STYLE_FLAG" "$IO_FLAG" -s "$SEED" "$MG_INPUT" > "$MC_FILE"

echo "==> assembling .mc -> .data" >&2
# parse_mc2.pl iterates Perl hashes when assigning labels/addresses; Perl
# randomizes hash iteration order per-process by default (since 5.18),
# so without pinning PERL_HASH_SEED the resulting .data (and therefore
# .mb) byte layout is NOT reproducible across runs even though it is
# always functionally equivalent.
PERL_HASH_SEED=0 perl "$PARSE_MC2" "$MC_FILE" "$BASE" >&2

if [ ! -f "$DATA_FILE" ]; then
    echo "error: parse_mc2.pl did not produce $DATA_FILE" >&2
    exit 1
fi

echo "==> initializing .data -> .mb" >&2
"$INIT" "$DATA_FILE" > "$MB_OUTPUT"

echo "==> wrote $MB_OUTPUT ($(wc -c < "$MB_OUTPUT" | tr -d ' ') bytes)" >&2
