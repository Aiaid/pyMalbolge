"""
Entry point for running malbolge as a module: python -m malbolge

Supports multiple Malbolge variants:
  python -m malbolge program.mal                    # Original Malbolge
  python -m malbolge --variant=malbolge20 program.mal  # Malbolge20
  python -m malbolge debug program.mal              # Debug mode
"""

import argparse
import json
from pathlib import Path
import sys
import time


def _nonnegative(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be nonnegative")
    return number


def _bounded_run(args, parser, *, legacy_source=False):
    from .malbolge import run as run_original
    from .malbolge20 import run as run_twenty
    try:
        if legacy_source:
            # Plain commands historically read UTF-8 source even with redirected
            # stdin. Preserve that contract when selecting a batch engine.
            try:
                source = Path(args.file).read_text(encoding="utf8")
            except (OSError, UnicodeError) as error:
                parser.exit(1, "error: cannot read {}: {}\n".format(args.file, error))
        else:
            source = Path(args.file).read_bytes()
        if args.input_file is not None:
            data = Path(args.input_file).read_bytes()
        elif args.input is not None:
            data = args.input
        else:
            data = b"" if sys.stdin.isatty() else sys.stdin.buffer.read()
        started = time.perf_counter()
        runner = run_twenty if args.variant == "malbolge20" else run_original
        requested_engine = args.engine or "auto"
        options = {}
        if args.variant == "malbolge20":
            from .native import resolve_engine
            engine = resolve_engine(requested_engine)
            options["engine"] = engine
        else:
            engine = "python"
        result = runner(source, data, max_steps=args.max_steps,
                        max_output=args.max_output, eof=args.eof or "sentinel",
                        **options)
        sys.stdout.buffer.write(result.output)
        sys.stdout.buffer.flush()
        if args.stats:
            metrics = result.to_dict()
            metrics.pop("output_hex", None)
            metrics.update(variant=args.variant, engine=engine,
                           requested_engine=requested_engine,
                           seconds=time.perf_counter() - started)
            sys.stderr.write(json.dumps(metrics, sort_keys=True) + "\n")
        if result.stop_reason in ("step_limit", "output_limit"):
            raise SystemExit(3)
        if result.stop_reason == "invalid_instruction":
            raise SystemExit(2)
    except (OSError, UnicodeError, ValueError, TypeError, RuntimeError) as error:
        parser.exit(1, "error: {}\n".format(error))
    except KeyboardInterrupt:
        parser.exit(130, "interrupted\n")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    # `compile` is a self-contained subcommand with its own option grammar;
    # dispatch it before the interpreter's positional argument parsing.
    if argv and argv[0] == 'compile':
        from .compiler.cli import main as compile_main
        compile_main(argv[1:])
        return

    parser = argparse.ArgumentParser(
        description='Malbolge interpreter - supports multiple variants',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python -m malbolge examples/hello.mal
  python -m malbolge --variant=malbolge20 program.mal
  python -m malbolge debug examples/hello.mal
  python -m malbolge debug --tui examples/hello.mal
  python -m malbolge compile prog.py --emit-c prog.c
  python -m malbolge compile prog.py -o prog.mb
'''
    )

    parser.add_argument(
        'command',
        nargs='?',
        default='run',
        help='Command: run (default), debug, compile'
    )

    parser.add_argument(
        'file',
        nargs='?',
        help='Malbolge source file'
    )

    parser.add_argument(
        '--variant', '-v',
        choices=['malbolge', 'malbolge20'],
        default='malbolge',
        help='Malbolge variant (default: malbolge)'
    )

    parser.add_argument(
        '--tui',
        action='store_true',
        help='Use TUI debugger (requires textual)'
    )
    parser.add_argument('--max-steps', type=_nonnegative,
                        help='stop after this many VM instructions (exit 3)')
    parser.add_argument('--max-output', type=_nonnegative,
                        help='cap output bytes (exit 3 when exceeded)')
    parser.add_argument('--eof', choices=('sentinel', 'stop'), default=None)
    parser.add_argument('--stats', action='store_true',
                        help='batch execution with JSON metrics on stderr')
    parser.add_argument('--engine', choices=('auto', 'python', 'native', 'jit'),
                        default=None,
                        help='batch Malbolge20 engine (default: auto prefers native; '
                             'JIT requires explicit selection)')
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument('-i', '--input', help='program text input (UTF-8 in batch mode)')
    inputs.add_argument('--input-file', help='read program input bytes from a file')

    args, remaining = parser.parse_known_args(argv)
    if args.command != 'debug' and remaining:
        parser.error('unrecognized arguments: ' + ' '.join(remaining))

    # Handle case where command is actually the file
    if args.command not in ('run', 'debug'):
        if args.file is not None:
            parser.error('unexpected extra source filename')
        args.file = args.command
        args.command = 'run'
    elif args.command == 'debug' and not args.file and remaining:
        args.file = remaining[0]
        remaining = remaining[1:]

    if args.command == 'run':
        if not args.file:
            parser.error('File argument is required for run command')

        if remaining:
            parser.error('unrecognized arguments: ' + ' '.join(remaining))
        if args.variant != 'malbolge20' and args.engine in ('native', 'jit'):
            parser.error('--engine=native/jit require --variant=malbolge20')
        batch_requested = (args.max_steps is not None or args.max_output is not None
                           or args.stats or args.eof is not None
                           or args.input is not None or args.input_file is not None)
        redirected_batch = args.variant == 'malbolge20' and not sys.stdin.isatty()
        if (args.variant == 'malbolge20' and sys.stdin.isatty()
                and args.input is None and args.input_file is None
                and args.engine in ('native', 'jit')):
            parser.error('native/JIT batch execution requires --input, --input-file, '
                         'or redirected stdin when running from a terminal')
        if batch_requested or redirected_batch:
            _bounded_run(args, parser, legacy_source=not batch_requested)
            return

        if args.variant == 'malbolge20':
            from .malbolge20 import _interactive_main
            _interactive_main(args.file)
        else:
            from .malbolge import main as malbolge_main
            sys.argv = ['malbolge', args.file] + remaining
            malbolge_main()

    elif args.command == 'debug':
        if not args.file:
            parser.error('File argument is required for debug command')
        if args.engine is not None:
            parser.error('--engine applies to run, not debug')
        if (args.max_steps is not None or args.max_output is not None
                or args.stats or args.eof is not None):
            parser.error('execution limits and --stats apply to run, not debug')
        if args.input_file is not None:
            try:
                args.input = Path(args.input_file).read_bytes().decode('latin1')
            except OSError as error:
                parser.exit(1, 'error: {}\n'.format(error))
        if args.input is not None:
            remaining += ['--input', args.input]

        if args.tui:
            from .debug_tui import main as tui_main
            sys.argv = ['debug_tui', args.file] + remaining
            if args.variant == 'malbolge20':
                sys.argv.insert(1, '--variant=malbolge20')
            tui_main()
        else:
            from .debug_cli import main as cli_main
            sys.argv = ['debug_cli', args.file] + remaining
            if args.variant == 'malbolge20':
                sys.argv.insert(1, '--variant=malbolge20')
            cli_main()


if __name__ == '__main__':
    main()
