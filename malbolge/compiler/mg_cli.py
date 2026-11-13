"""Compile handwritten MG to Malbolge20 without external tools."""

import argparse
import json
from pathlib import Path
import sys
import time

from . import translate_mg_to_mc, translate_mg_to_lal, iter_mc_to_mb, iter_lal_to_mb
from . import Mg2McError, Mc2MbError
from .cli import _atomic_write, _die, _preflight_outputs, _write
from .lal_model import LalModelError, emit_lal_to_mc
from .memory_image import MemoryImageError


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="malbolge compile-mg",
        description="Compile handwritten MG to Malbolge20 (pure Python).")
    parser.add_argument("source", help="UTF-8 MG source file (.mg)")
    parser.add_argument("--emit-mc", metavar="PATH", help="write MC ('-' for stdout; default when no output is selected)")
    parser.add_argument("-o", "--output", metavar="MB", help="write Malbolge20 source ('-' for stdout)")
    parser.add_argument("--op-style", choices=("cluster", "inline"), default="cluster")
    parser.add_argument("--jmp-style", choices=("main", "direct"), default="main")
    parser.add_argument("--target-pipeline", choices=("text", "structured"), default="structured")
    parser.add_argument("--stats", action="store_true", help="write JSON compilation metrics to stderr")
    args = parser.parse_args(argv)
    if args.emit_mc is None and args.output is None:
        args.emit_mc = "-"
    try:
        _preflight_outputs(args.source, [p for p in (args.emit_mc, args.output)
                                         if p is not None], "MG")
        source = Path(args.source).read_text(encoding="utf8")
        started = time.perf_counter()
        options = dict(op_style=args.op_style, jmp_style=args.jmp_style)
        if args.target_pipeline == "structured":
            model = translate_mg_to_lal(source, **options)
            chunks = lambda: iter_lal_to_mb(model)
            mc = emit_lal_to_mc(model) if args.emit_mc is not None else None
            stage = "mg2lal"
        else:
            mc = translate_mg_to_mc(source, **options)
            chunks = lambda: iter_mc_to_mb(mc)
            stage = "mg2mc"
        stats = {"source_language": "mg", "target_pipeline": args.target_pipeline,
                 "stages": [{"stage": stage, "seconds": time.perf_counter() - started}]}
        if args.emit_mc is not None:
            _write(args.emit_mc, mc, ".mc")
        if args.output is not None:
            assembled = time.perf_counter()
            if args.output == "-":
                count = 0
                for chunk in chunks():
                    sys.stdout.buffer.write(chunk)
                    count += len(chunk)
            else:
                _atomic_write(args.output, chunks())
                count = Path(args.output).stat().st_size
                sys.stderr.write("wrote {} (Malbolge20)\n".format(args.output))
            stats["stages"].append({"stage": "mc2mb", "bytes": count,
                                    "seconds": time.perf_counter() - assembled})
        stats["seconds"] = time.perf_counter() - started
        if args.stats:
            sys.stderr.write(json.dumps(stats, sort_keys=True) + "\n")
    except (Mg2McError, Mc2MbError, LalModelError, MemoryImageError) as error:
        _die("compiler stage failed: {}".format(error))
    except (OSError, UnicodeError) as error:
        _die("file I/O failed: {}".format(error))
    except KeyboardInterrupt:
        sys.stderr.write("interrupted\n")
        raise SystemExit(130)


if __name__ == "__main__":
    main()
