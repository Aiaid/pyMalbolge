"""Python-subset compiler CLI with atomic outputs and opt-in stage caching."""

import argparse
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
    compile_c_to_mg, C2MgError, translate_mg_to_mc, Mg2McError,
    iter_mc_to_mb, Mc2MbError,
)


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
    outputs = [value for value in (args.emit_c, args.emit_mg, args.emit_mc, args.output)
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
        toolchain = {path.name: _digest(path) for path in sorted(compiler_dir.glob("*.py"))}
        payload = {"source": hashlib.sha256(source.encode("utf8")).hexdigest(),
                   "backend": args.backend, "op_style": args.op_style,
                   "jmp_style": args.jmp_style, "python": list(sys.version_info),
                   "toolchain": toolchain}
        key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        self.root = Path(directory) / key
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest = self.root / "manifest.json"
        reserved = [self.manifest] + [self.path(stage) for stage in ("c", "mg", "mc", "mb")]
        requested = [args.source] + [value for value in (
            args.emit_c, args.emit_mg, args.emit_mc, args.output)
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


def _compile(args, source):
    started = time.perf_counter()
    stats = {"backend": args.backend, "stages": []}
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
            and args.emit_mg is None and args.emit_mc is None):
        cached = cache.hit("mb")
        if cached:
            _copy_image(cached, args.output)
            stats["stages"].append({"stage": "mc2mb", "cache_hit": True,
                                    "seconds": time.perf_counter() - started,
                                    "bytes": cached.stat().st_size})
            finish_stats()
            return

    if args.backend == "direct":
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
    if args.emit_mc is None and args.output is None:
        finish_stats()
        return
    mc = stage("mg2mc", "mc", lambda value: translate_mg_to_mc(
        value, op_style=args.op_style, jmp_style=args.jmp_style), mg)
    if args.emit_mc is not None:
        _write(args.emit_mc, mc, ".mc")
    if args.output is not None:
        t = time.perf_counter()
        cached = cache.hit("mb") if cache else None
        if cached:
            _copy_image(cached, args.output)
            count = cached.stat().st_size
        elif cache:
            image = cache.path("mb")
            _atomic_write(image, iter_mc_to_mb(mc))
            cache.record("mb")
            _copy_image(image, args.output)
            count = image.stat().st_size
        elif args.output == "-":
            count = 0
            for chunk in iter_mc_to_mb(mc):
                sys.stdout.buffer.write(chunk)
                count += len(chunk)
        else:
            _atomic_write(args.output, iter_mc_to_mb(mc))
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
    parser.add_argument("-o", "--output", metavar="MB", help="write Malbolge20 source")
    parser.add_argument("--backend", choices=("c", "direct"), default="c")
    parser.add_argument("--op-style", choices=("cluster", "inline"), default="cluster")
    parser.add_argument("--jmp-style", choices=("main", "direct"), default="main")
    parser.add_argument("--cache-dir", metavar="PATH", help="opt-in content-addressed stage cache")
    parser.add_argument("--stats", action="store_true", help="write JSON compilation metrics to stderr")
    args = parser.parse_args(argv)
    if args.output is None and all(value is None for value in
                                  (args.emit_c, args.emit_mg, args.emit_mc)):
        if args.backend == "direct":
            args.emit_mg = "-"
        else:
            args.emit_c = "-"
    if args.backend == "direct" and args.emit_c is not None:
        _die("--emit-c is not available with --backend=direct")
    try:
        _preflight(args)
        with open(args.source, encoding="utf8") as stream:
            source = stream.read()
        _compile(args, source)
    except (CompileError, Py2MgError) as error:
        _die("{}: {}".format(args.source, error))
    except (C2MgError, Mg2McError, Mc2MbError) as error:
        _die("compiler stage failed: {}".format(error))
    except (OSError, UnicodeError) as error:
        _die("file I/O failed: {}".format(error))
    except KeyboardInterrupt:
        sys.stderr.write("interrupted\n")
        raise SystemExit(130)


if __name__ == "__main__":
    main(sys.argv[1:])
