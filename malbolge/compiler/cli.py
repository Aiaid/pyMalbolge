"""Python-subset compiler CLI with atomic outputs and opt-in stage caching."""

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time

from . import (
    compile_python_to_c, CompileError, compile_python_to_mg, Py2MgError,
    compile_c_to_mg, C2MgError, translate_mg_to_mc, translate_mg_to_lal, Mg2McError,
    iter_mc_to_mb, iter_lal_to_mb, Mc2MbError,
)
from .lal_model import LalModelError, emit_lal_to_mc
from .memory_image import MemoryImageError
from .ir import IRDependencyError, XDSL_VERSION, require_ir_support


def _die(msg):
    sys.stderr.write("error: {}\n".format(msg))
    raise SystemExit(1)


def _digest(path):
    value = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _atomic_write(path, chunks):
    """Preserve an existing artifact until its replacement is complete."""
    target = Path(path)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=str(target.parent),
                                         prefix="." + target.name + ".", delete=False) as f:
            temp = f.name
            for chunk in chunks:
                f.write(chunk)
            f.flush()
            os.fsync(f.fileno())
        if target.exists():
            os.chmod(temp, stat.S_IMODE(target.stat().st_mode))
        os.replace(temp, target)
        temp = None
    finally:
        if temp is not None:
            try:
                os.unlink(temp)
            except FileNotFoundError:
                pass


def _write(path, content, label):
    if path == "-":
        sys.stdout.write(content)
    else:
        _atomic_write(path, (content.encode("utf8"),))
        sys.stderr.write("wrote {} ({})\n".format(path, label))


def _same_path(left, right):
    if Path(left).resolve() == Path(right).resolve():
        return True
    try:
        return os.path.samefile(left, right)
    except OSError:
        return False


def _preflight(args):
    outputs = [value for value in (args.emit_c, args.emit_mg, args.emit_mc,
                                  args.emit_ir, args.emit_semantic_ir, args.output)
               if value is not None]
    for i, output in enumerate(outputs):
        if output != "-":
            if _same_path(args.source, output):
                _die("output must not overwrite the Python source: {}".format(output))
            target = Path(output)
            if not target.parent.is_dir():
                _die("output directory does not exist: {}".format(target.parent))
            if target.is_dir():
                _die("output is a directory: {}".format(output))
            if not os.access(str(target.parent), os.W_OK):
                _die("output directory is not writable: {}".format(target.parent))
        for earlier in outputs[:i]:
            if output == earlier or (output != "-" and earlier != "-"
                                     and _same_path(output, earlier)):
                _die("output paths must be distinct: {}".format(output))


class _Cache:
    def __init__(self, directory, source, args):
        compiler_dir = Path(__file__).parent
        toolchain = {str(path.relative_to(compiler_dir)): _digest(path)
                     for path in sorted(compiler_dir.rglob("*.py"))}
        payload = {"source": hashlib.sha256(source.encode("utf8")).hexdigest(),
                   "backend": args.backend, "op_style": args.op_style,
                   "jmp_style": args.jmp_style, "python": list(sys.version_info),
                   "target_pipeline": args.target_pipeline,
                   "toolchain": toolchain}
        if args.backend == "ir":
            payload["ir_passes"] = list(args.ir_passes)
            payload["xdsl_version"] = XDSL_VERSION
            payload["ir_frontend"] = args.ir_frontend
            payload["semantic_passes"] = list(args.semantic_pass_names)
        key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        self.root = Path(directory) / key
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest = self.root / "manifest.json"
        reserved = [self.manifest] + [self.path(stage) for stage in
                                     ("c", "semantic", "mg", "mc-source", "ir", "mc", "mb")]
        requested = [args.source] + [value for value in (
            args.emit_c, args.emit_mg, args.emit_mc, args.emit_ir,
            args.emit_semantic_ir, args.output)
            if value is not None and value != "-"]
        for target in reserved:
            if any(_same_path(target, value) for value in requested):
                _die("cache artifacts must not alias input/output paths: {}".format(target))
        try:
            self.entries = json.loads(self.manifest.read_text(encoding="utf8"))
            if not isinstance(self.entries, dict):
                self.entries = {}
        except (OSError, ValueError):
            self.entries = {}

    def path(self, stage):
        return self.root / ("program." + stage)

    def hit(self, stage):
        path = self.path(stage)
        entry = self.entries.get(stage)
        try:
            if (isinstance(entry, dict) and path.stat().st_size == entry.get("bytes")
                    and _digest(path) == entry.get("sha256")):
                return path
        except OSError:
            pass
        return None

    def record(self, stage):
        path = self.path(stage)
        self.entries[stage] = {"bytes": path.stat().st_size, "sha256": _digest(path)}
        _atomic_write(self.manifest, (json.dumps(self.entries, sort_keys=True).encode(),))


def _structured_target(args, mg, stats, cache):
    """Build native LAL, verifying optional IR without MC/data text adapters."""
    started = time.perf_counter()
    model = translate_mg_to_lal(mg, op_style=args.op_style, jmp_style=args.jmp_style)
    stats["stages"].append({"stage": "mg2lal", "cache_hit": False,
                            "seconds": time.perf_counter() - started,
                            "representation": "structured",
                            "declarations": len(model.declarations)})
    if args.backend != "ir":
        return model

    from .ir.lal import lal_to_model, model_to_lal, parse_lal, print_lal, verify_lal
    from .ir.passes import run_pipeline, summarize_ir

    started = time.perf_counter()
    cached = cache.hit("ir") if cache else None
    if cached:
        ir_text = cached.read_text(encoding="utf8")
        module = parse_lal(ir_text)
        verify_lal(module)
        stats["ir"].update(cache_hit=True, cached_stage="ir")
    else:
        result = run_pipeline(model_to_lal(model), args.ir_passes)
        module = result.module
        stats["ir"] = result.to_dict()
        stats["ir"]["cache_hit"] = False
        ir_text = print_lal(module) if cache or args.emit_ir is not None else None
        if cache:
            _atomic_write(cache.path("ir"), (ir_text.encode("utf8"),))
            cache.record("ir")
    reports = stats["ir"]["reports"]
    stats["ir"]["summary"] = (reports[-1]["after"] if reports
                                else asdict(summarize_ir(module)))
    record = {"stage": "lal-passes", "cache_hit": bool(cached),
              "seconds": time.perf_counter() - started,
              "representation": "structured"}
    if ir_text is not None:
        record["bytes"] = len(ir_text.encode("utf8"))
    stats["stages"].append(record)
    if args.emit_ir is not None:
        _write(args.emit_ir, ir_text, "LAL IR")
    return lal_to_model(module)


def _compile(args, source):
    started = time.perf_counter()
    stats = {"backend": args.backend, "target_pipeline": args.target_pipeline,
             "stages": []}
    if args.backend == "ir":
        stats["ir"] = {"xdsl_version": XDSL_VERSION,
                       "passes": list(args.ir_passes), "reports": [],
                       "cache_hit": False}
        stats["ir_frontend"] = args.ir_frontend
        if args.ir_frontend == "semantic":
            stats["semantic_ir"] = {"xdsl_version": XDSL_VERSION,
                                    "passes": list(args.semantic_pass_names),
                                    "reports": [], "cache_hit": False}
    cache = _Cache(args.cache_dir, source, args) if args.cache_dir else None

    def stage(name, extension, fn, value):
        t = time.perf_counter()
        cached = cache.hit(extension) if cache else None
        if cached:
            result = cached.read_text(encoding="utf8")
        else:
            result = fn(value)
            if cache:
                _atomic_write(cache.path(extension), (result.encode("utf8"),))
                cache.record(extension)
        stats["stages"].append({"stage": name, "cache_hit": bool(cached),
                                "seconds": time.perf_counter() - t,
                                "bytes": len(result.encode("utf8"))})
        return result

    def finish_stats():
        stats["seconds"] = time.perf_counter() - started
        if args.stats:
            sys.stderr.write(json.dumps(stats, sort_keys=True) + "\n")

    # A complete cached image can be copied without loading all intermediates.
    if (cache and args.output is not None and args.emit_c is None
            and args.emit_mg is None and args.emit_mc is None and args.emit_ir is None
            and args.emit_semantic_ir is None):
        cached = cache.hit("mb")
        if cached:
            if args.backend == "ir":
                stats["ir"].update(cache_hit=True, cached_stage="mb")
                if args.ir_frontend == "semantic":
                    stats["semantic_ir"].update(cache_hit=True, cached_stage="mb")
            _copy_image(cached, args.output)
            stats["stages"].append({"stage": "mc2mb", "cache_hit": True,
                                    "seconds": time.perf_counter() - started,
                                    "bytes": cached.stat().st_size})
            finish_stats()
            return

    if args.backend == "ir" and args.ir_frontend == "semantic":
        from .ir.semantic import parse_semantic, print_semantic, verify_semantic
        from .ir.semantic_passes import compile_python_semantic_result, summarize_semantic
        from .ir.lowering import lower_semantic_to_mg

        def to_semantic(value):
            result = compile_python_semantic_result(value, args.semantic_pass_names)
            stats["semantic_ir"] = result.to_dict()
            stats["semantic_ir"]["cache_hit"] = False
            return print_semantic(result.module)

        semantic_text = stage("python-to-semantic", "semantic", to_semantic, source)
        module = parse_semantic(semantic_text)
        verify_semantic(module)
        if stats["stages"][-1]["cache_hit"]:
            stats["semantic_ir"].update(cache_hit=True, cached_stage="semantic")
        reports = stats["semantic_ir"]["reports"]
        stats["semantic_ir"]["summary"] = (reports[-1]["after"] if reports
                                             else asdict(summarize_semantic(module)))
        if args.emit_semantic_ir is not None:
            _write(args.emit_semantic_ir, semantic_text, "semantic IR")
        if all(value is None for value in
               (args.emit_mg, args.emit_mc, args.emit_ir, args.output)):
            finish_stats()
            return
        mg = stage("semantic-to-mg", "mg", lower_semantic_to_mg, module)
    elif args.backend in ("direct", "ir"):
        mg = stage("py2mg", "mg", compile_python_to_mg, source)
    else:
        c = stage("py2c", "c", compile_python_to_c, source)
        if args.emit_c is not None:
            _write(args.emit_c, c, "C")
        if args.emit_mg is None and args.emit_mc is None and args.output is None:
            finish_stats()
            return
        mg = stage("c2mg", "mg", compile_c_to_mg, c)
    if args.emit_mg is not None:
        _write(args.emit_mg, mg, ".mg")
    if args.emit_mc is None and args.emit_ir is None and args.output is None:
        finish_stats()
        return
    if args.target_pipeline == "structured":
        model = _structured_target(args, mg, stats, cache)
        if args.emit_mc is not None:
            _write(args.emit_mc, emit_lal_to_mc(model), ".mc")
        image_chunks = lambda: iter_lal_to_mb(model)
    else:
        mc = stage("mg2mc", "mc-source" if args.backend == "ir" else "mc",
                   lambda value: translate_mg_to_mc(
            value, op_style=args.op_style, jmp_style=args.jmp_style), mg)
        if args.backend == "ir":
            from .ir.bridge import mc_to_ir_result
            from .ir.lal import emit_mc, parse_lal, print_lal, verify_lal
            from .ir.passes import summarize_ir

            def to_ir(value):
                result = mc_to_ir_result(value, passes=args.ir_passes)
                stats["ir"] = result.to_dict()
                stats["ir"]["cache_hit"] = False
                return print_lal(result.module)

            ir_text = stage("lal-passes", "ir", to_ir, mc)
            module = parse_lal(ir_text)
            verify_lal(module)
            if stats["stages"][-1]["cache_hit"]:
                stats["ir"].update(cache_hit=True, cached_stage="ir")
            reports = stats["ir"]["reports"]
            stats["ir"]["summary"] = (reports[-1]["after"] if reports
                                        else asdict(summarize_ir(module)))
            if args.emit_ir is not None:
                _write(args.emit_ir, ir_text, "LAL IR")
            if args.emit_mc is None and args.output is None:
                finish_stats()
                return
            mc = stage("lal-to-mc", "mc", emit_mc, module)
        if args.emit_mc is not None:
            _write(args.emit_mc, mc, ".mc")
        image_chunks = lambda: iter_mc_to_mb(mc)
    if args.output is not None:
        t = time.perf_counter()
        cached = cache.hit("mb") if cache else None
        if cached:
            _copy_image(cached, args.output)
            count = cached.stat().st_size
        elif cache:
            image = cache.path("mb")
            _atomic_write(image, image_chunks())
            cache.record("mb")
            _copy_image(image, args.output)
            count = image.stat().st_size
        elif args.output == "-":
            count = 0
            for chunk in image_chunks():
                sys.stdout.buffer.write(chunk)
                count += len(chunk)
        else:
            _atomic_write(args.output, image_chunks())
            count = Path(args.output).stat().st_size
            sys.stderr.write("wrote {} (Malbolge20)\n".format(args.output))
        stats["stages"].append({"stage": "mc2mb", "cache_hit": bool(cached),
                                "seconds": time.perf_counter() - t, "bytes": count})
    finish_stats()


def _copy_image(source, target):
    def chunks():
        with open(source, "rb") as stream:
            yield from iter(lambda: stream.read(1024 * 1024), b"")
    if target == "-":
        for chunk in chunks():
            sys.stdout.buffer.write(chunk)
    else:
        _atomic_write(target, chunks())
        sys.stderr.write("wrote {} (Malbolge20, cached)\n".format(target))


def main(argv):
    parser = argparse.ArgumentParser(prog="malbolge compile",
        description="Compile a subset of Python to Malbolge20 (pure Python).")
    parser.add_argument("source", help="Python source file (.py)")
    parser.add_argument("--emit-c", metavar="PATH", help="write C ('-' for stdout)")
    parser.add_argument("--emit-mg", metavar="PATH", help="write .mg ('-' for stdout)")
    parser.add_argument("--emit-mc", metavar="PATH", help="write .mc ('-' for stdout)")
    parser.add_argument("--emit-ir", metavar="PATH",
                        help="write verified LAL IR with --backend=ir ('-' for stdout)")
    parser.add_argument("--emit-semantic-ir", metavar="PATH",
                        help="write source-semantic IR before target lowering ('-' for stdout)")
    parser.add_argument("-o", "--output", metavar="MB", help="write Malbolge20 source")
    parser.add_argument("--backend", choices=("c", "direct", "ir"), default="c")
    parser.add_argument("--target-pipeline", choices=("text", "structured"),
                        default="text", help="target handoff (structured is experimental)")
    parser.add_argument("--passes", metavar="NAMES",
                        help="comma-separated IR passes (default: verify-lal; IR backend only)")
    parser.add_argument("--ir-frontend", choices=("compat", "semantic"),
                        help="IR source path (default: compat; semantic for --emit-semantic-ir)")
    parser.add_argument("--semantic-passes", metavar="NAMES",
                        help="explicit semantic pass sequence (default: accepted optimization profile)")
    parser.add_argument("--opt-level", choices=("0", "1"),
                        help="semantic optimization profile: 0 verifies only, 1 enables arithmetic/dataflow passes")
    parser.add_argument("--op-style", choices=("cluster", "inline"), default="cluster")
    parser.add_argument("--jmp-style", choices=("main", "direct"), default="main")
    parser.add_argument("--cache-dir", metavar="PATH", help="opt-in content-addressed stage cache")
    parser.add_argument("--stats", action="store_true", help="write JSON compilation metrics to stderr")
    args = parser.parse_args(argv)
    if args.backend != "ir" and any(value is not None for value in
                                     (args.ir_frontend, args.emit_semantic_ir, args.semantic_passes, args.opt_level)):
        _die("semantic IR and frontend options require --backend=ir")
    if args.opt_level is not None and args.semantic_passes is not None:
        _die("--opt-level and --semantic-passes are alternative selections")
    args.ir_frontend = args.ir_frontend or (
        "semantic" if (args.emit_semantic_ir is not None or args.semantic_passes is not None
                       or args.opt_level is not None)
        else "compat")
    if args.ir_frontend != "semantic" and (
            args.emit_semantic_ir is not None or args.semantic_passes is not None or args.opt_level is not None):
        _die("--emit-semantic-ir, --semantic-passes and --opt-level require --ir-frontend=semantic")
    if args.output is None and all(value is None for value in
                                  (args.emit_c, args.emit_mg, args.emit_mc, args.emit_ir,
                                   args.emit_semantic_ir)):
        if args.backend == "ir" and args.ir_frontend == "semantic":
            args.emit_semantic_ir = "-"
        elif args.backend == "ir":
            args.emit_ir = "-"
        elif args.backend == "direct":
            args.emit_mg = "-"
        else:
            args.emit_c = "-"
    if args.backend in ("direct", "ir") and args.emit_c is not None:
        _die("--emit-c is not available with --backend={}".format(args.backend))
    if args.backend != "ir" and (args.emit_ir is not None or args.passes is not None):
        _die("--emit-ir and --passes require --backend=ir")
    ir_errors = ()
    try:
        if args.backend == "ir":
            require_ir_support()
            from .ir.lal import LalIRError
            from .ir.passes import PipelineError, validate_pass_names
            ir_errors = (LalIRError, PipelineError)
            names = None if args.passes is None else tuple(
                name.strip() for name in args.passes.split(","))
            args.ir_passes = validate_pass_names(names)
            args.semantic_pass_names = ()
            if args.ir_frontend == "semantic":
                from .ir.semantic import SemanticIRError
                from .ir.semantic_passes import validate_semantic_pass_names, CANDIDATE_OPTIMIZATION_PASSES
                ir_errors += (SemanticIRError,)
                semantic_names = (None if args.semantic_passes is None else tuple(
                    name.strip() for name in args.semantic_passes.split(",")))
                if args.opt_level == "0":
                    semantic_names = ("verify-semantic",)
                elif args.opt_level == "1":
                    semantic_names = CANDIDATE_OPTIMIZATION_PASSES
                args.semantic_pass_names = validate_semantic_pass_names(semantic_names)
        _preflight(args)
        with open(args.source, encoding="utf8") as stream:
            source = stream.read()
        _compile(args, source)
    except (CompileError, Py2MgError) as error:
        _die("{}: {}".format(args.source, error))
    except (C2MgError, Mg2McError, Mc2MbError, LalModelError, MemoryImageError) as error:
        _die("compiler stage failed: {}".format(error))
    except IRDependencyError as error:
        _die(str(error))
    except ir_errors as error:
        _die("IR stage failed: {}".format(error))
    except (OSError, UnicodeError) as error:
        _die("file I/O failed: {}".format(error))
    except KeyboardInterrupt:
        sys.stderr.write("interrupted\n")
        raise SystemExit(130)


if __name__ == "__main__":
    main(sys.argv[1:])
