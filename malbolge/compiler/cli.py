"""
Command-line front-end for the Python -> Malbolge20 compiler.

Wired into ``python -m malbolge compile``:

    python -m malbolge compile foo.py                  # generated C to stdout
    python -m malbolge compile foo.py --emit-c foo.c   # transpile to C only
    python -m malbolge compile foo.py --emit-mg foo.mg # stop after .mg
    python -m malbolge compile foo.py -o foo.mb        # full pipeline to .mb

The entire pipeline is pure Python (see malbolge.compiler) and fully
deterministic -- the same input always produces the same .mb bytes. The
Nagoya reference tools under ref/ are no longer needed to compile; they
are only exercised by the conformance test suite.

--op-style/--jmp-style select the mg2mc code-generation style; they take
effect from the .mc stage onwards, so --emit-c and --emit-mg output is
the same whatever they are set to. The defaults keep the .mc byte-identical
to `parser -m -c`.
"""

import argparse
import sys

from . import (
    compile_python_to_c, CompileError,
    compile_python_to_mg, Py2MgError,
    compile_c_to_mg, C2MgError,
    translate_mg_to_mc, Mg2McError,
    assemble_mc_to_mb, Mc2MbError,
)


def _die(msg):
    sys.stderr.write("error: {}\n".format(msg))
    sys.exit(1)


def _write(path, content, label):
    if path == "-":
        sys.stdout.write(content)
    else:
        with open(path, "w") as f:
            f.write(content)
        sys.stderr.write("wrote {} ({})\n".format(path, label))


def main(argv):
    parser = argparse.ArgumentParser(
        prog="malbolge compile",
        description="Compile a subset of Python to Malbolge20 (pure Python).")
    parser.add_argument("source", help="Python source file (.py)")
    parser.add_argument(
        "--emit-c", metavar="PATH", default=None,
        help="write the generated C to PATH ('-' for stdout)")
    parser.add_argument(
        "--emit-mg", metavar="PATH", default=None,
        help="write the generated .mg pseudo-instructions to PATH")
    parser.add_argument(
        "--emit-mc", metavar="PATH", default=None,
        help="write the generated .mc LAL assembly to PATH")
    parser.add_argument(
        "-o", "--output", metavar="MB", default=None,
        help="write the final Malbolge20 program to MB")
    parser.add_argument(
        "--backend", choices=("c", "direct"), default="c",
        help="front-end path to .mg: 'c' (default, via py2c+c2mg) or 'direct' "
             "(py2mg, skips the C layer)")
    parser.add_argument(
        "--op-style", choices=("cluster", "inline"), default="cluster",
        help="mg2mc code generation for OUTPUT/INPUT/SET/RESET: 'cluster' "
             "(default, upstream -c) shares one cluster module per operation; "
             "'inline' (upstream -i) expands each occurrence in place, which "
             "drops the cluster branch flags and shrinks the .mb -- little to "
             "gain on ROT/OPR-heavy programs. Affects .mc and .mb only")
    parser.add_argument(
        "--jmp-style", choices=("main", "direct"), default="main",
        help="mg2mc code generation for continuous ROT/OPR calls: 'main' "
             "(default, upstream -m) returns to the main control flow between "
             "modules; 'direct' (upstream -d) jumps straight to the next "
             "module. Affects .mc and .mb only")
    args = parser.parse_args(argv)

    wants_intermediate = (args.emit_c is not None or args.emit_mg is not None
                          or args.emit_mc is not None)
    if not wants_intermediate and args.output is None:
        # Default: print the first intermediate the backend produces.
        if args.backend == "direct":
            args.emit_mg = "-"
        else:
            args.emit_c = "-"

    if args.backend == "direct" and args.emit_c is not None:
        _die("--emit-c is not available with --backend=direct "
             "(the direct backend does not generate C)")

    try:
        with open(args.source) as f:
            py_source = f.read()
    except OSError as e:
        _die("cannot read {}: {}".format(args.source, e))

    if args.backend == "direct":
        try:
            mg_source = compile_python_to_mg(py_source)
        except Py2MgError as e:
            sys.stderr.write("{}: {}\n".format(args.source, e))
            sys.exit(1)
    else:
        try:
            c_source = compile_python_to_c(py_source)
        except CompileError as e:
            sys.stderr.write("{}: {}\n".format(args.source, e))
            sys.exit(1)
        if args.emit_c is not None:
            _write(args.emit_c, c_source, "C")
        if args.emit_mg is None and args.emit_mc is None \
                and args.output is None:
            return
        try:
            mg_source = compile_c_to_mg(c_source)
        except C2MgError as e:
            _die("internal: generated C rejected by c2mg: {}".format(e))

    if args.emit_mg is not None:
        _write(args.emit_mg, mg_source, ".mg")

    if args.emit_mc is None and args.output is None:
        return

    try:
        mc_source = translate_mg_to_mc(mg_source, op_style=args.op_style,
                                       jmp_style=args.jmp_style)
    except Mg2McError as e:
        _die("internal: generated .mg rejected by mg2mc: {}".format(e))
    if args.emit_mc is not None:
        _write(args.emit_mc, mc_source, ".mc")

    if args.output is None:
        return

    try:
        mb_source = assemble_mc_to_mb(mc_source)
    except Mc2MbError as e:
        _die("internal: generated .mc rejected by mc2mb: {}".format(e))
    _write(args.output, mb_source, "Malbolge20")
