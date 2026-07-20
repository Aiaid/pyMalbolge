"""
Command-line front-end for the Python -> Malbolge20 compiler.

Wired into ``python -m malbolge compile``:

    python -m malbolge compile foo.py --emit-c foo.c   # transpile to C only
    python -m malbolge compile foo.py --emit-c -       # C to stdout
    python -m malbolge compile foo.py -o foo.mb        # full pipeline to .mb
    python -m malbolge compile foo.py -o foo.mb --seed 7

The full-pipeline mode drives the (gitignored) Nagoya reference toolchain
under ``ref/`` via ``scripts/mg2mb.sh``; when a required tool is missing it
reports what to build instead of failing obscurely.
"""

import argparse
import os
import subprocess
import sys
import tempfile

from .py2c import compile_python_to_c, CompileError

# repo root: malbolge/compiler/cli.py -> parents[2]
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_HL_PARSER = os.path.join(_REPO_ROOT, "ref", "nagoya-highlevel", "parser")
_MG2MB = os.path.join(_REPO_ROOT, "scripts", "mg2mb.sh")


def _die(msg):
    sys.stderr.write("error: {}\n".format(msg))
    sys.exit(1)


def _run_highlevel(c_source, mg_path):
    """C -> .mg via the reference high-level parser.

    The parser always exits 0, reporting problems only on stderr, so we treat
    any stderr output as fatal (mirroring scripts/mg2mb.sh's handling of the
    downstream tools).
    """
    if not os.access(_HL_PARSER, os.X_OK):
        _die("required tool not found or not executable: {}\n"
             "  build it with: cd ref/nagoya-highlevel && make".format(
                 _HL_PARSER))
    with tempfile.NamedTemporaryFile(
            "w", suffix=".c", delete=False) as cf:
        cf.write(c_source)
        c_path = cf.name
    try:
        with open(mg_path, "w") as mg_out:
            proc = subprocess.run(
                [_HL_PARSER, c_path], stdout=mg_out,
                stderr=subprocess.PIPE, text=True)
        if proc.stderr.strip():
            _die("the high-level C parser rejected the generated C:\n"
                 + proc.stderr.rstrip())
        if os.path.getsize(mg_path) == 0:
            _die("the high-level C parser produced empty output")
    finally:
        os.unlink(c_path)


def _run_pipeline(mg_path, mb_path, seed):
    if not os.access(_MG2MB, os.X_OK):
        _die("pipeline script not found or not executable: {}".format(_MG2MB))
    proc = subprocess.run(
        ["bash", _MG2MB, "-s", str(seed), mg_path, mb_path],
        stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        _die("the .mg -> .mb pipeline failed:\n" + proc.stderr.rstrip())


def main(argv):
    parser = argparse.ArgumentParser(
        prog="malbolge compile",
        description="Compile a subset of Python to Nagoya C / Malbolge20.")
    parser.add_argument("source", help="Python source file (.py)")
    parser.add_argument(
        "--emit-c", metavar="PATH", default=None,
        help="write the generated C to PATH ('-' for stdout) and stop")
    parser.add_argument(
        "-o", "--output", metavar="MB", default=None,
        help="run the full pipeline and write a Malbolge20 program to MB")
    parser.add_argument(
        "--seed", type=int, default=1,
        help="random seed for the .mg -> .mb pipeline (default: 1)")
    args = parser.parse_args(argv)

    if args.emit_c is None and args.output is None:
        # Default: print the generated C to stdout.
        args.emit_c = "-"

    try:
        with open(args.source) as f:
            py_source = f.read()
    except OSError as e:
        _die("cannot read {}: {}".format(args.source, e))

    try:
        c_source = compile_python_to_c(py_source)
    except CompileError as e:
        sys.stderr.write("{}: {}\n".format(args.source, e))
        sys.exit(1)

    if args.emit_c is not None:
        if args.emit_c == "-":
            sys.stdout.write(c_source)
        else:
            with open(args.emit_c, "w") as f:
                f.write(c_source)
            sys.stderr.write("wrote {}\n".format(args.emit_c))
        if args.output is None:
            return

    if args.output is not None:
        with tempfile.NamedTemporaryFile(
                "w", suffix=".mg", delete=False) as mgf:
            mg_path = mgf.name
        try:
            _run_highlevel(c_source, mg_path)
            _run_pipeline(mg_path, args.output, args.seed)
        finally:
            if os.path.exists(mg_path):
                os.unlink(mg_path)
        sys.stderr.write("wrote {}\n".format(args.output))
