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


def _bounded_run(args, parser):
    from .malbolge import run as run_original
    from .malbolge20 import run as run_twenty
    try:
        source = Path(args.file).read_bytes()
        if args.input_file is not None:
            data = Path(args.input_file).read_bytes()
        elif args.input is not None:
            data = args.input
        else:
            data = b"" if sys.stdin.isatty() else sys.stdin.buffer.read()
        started = time.perf_counter()
        runner = run_twenty if args.variant == "malbolge20" else run_original
        result = runner(source, data, max_steps=args.max_steps,
                        max_output=args.max_output, eof=args.eof or "sentinel")
        sys.stdout.buffer.write(result.output)
        sys.stdout.buffer.flush()
        if args.stats:
            metrics = result.to_dict()
            metrics.pop("output_hex", None)
            metrics.update(variant=args.variant, seconds=time.perf_counter() - started)
            sys.stderr.write(json.dumps(metrics, sort_keys=True) + "\n")
        if result.stop_reason in ("step_limit", "output_limit"):
            raise SystemExit(3)
        if result.stop_reason == "invalid_instruction":
            raise SystemExit(2)
    except (OSError, UnicodeError, ValueError, TypeError) as error:
        parser.exit(1, "error: {}\n".format(error))
    except KeyboardInterrupt:
        parser.exit(130, "interrupted\n")


def main():
    # `compile` is a self-contained subcommand with its own option grammar;
    # dispatch it before the interpreter's positional argument parsing.
    if len(sys.argv) >= 2 and sys.argv[1] == 'compile':
        from .compiler.cli import main as compile_main
        compile_main(sys.argv[2:])
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
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument('-i', '--input', help='program text input (UTF-8 in batch mode)')
    inputs.add_argument('--input-file', help='read program input bytes from a file')

    args, remaining = parser.parse_known_args()
    if args.command != 'debug' and remaining:
        parser.error('unrecognized arguments: ' + ' '.join(remaining))

    # Handle case where command is actually the file
    if args.command and args.command.endswith('.mal'):
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
        if (args.max_steps is not None or args.max_output is not None or args.stats
                or args.eof is not None or args.input is not None
                or args.input_file is not None):
            _bounded_run(args, parser)
            return

        if args.variant == 'malbolge20':
            from .malbolge20 import main as malbolge20_main
            sys.argv = ['malbolge20', args.file] + remaining
            malbolge20_main()
        else:
            from .malbolge import main as malbolge_main
            sys.argv = ['malbolge', args.file] + remaining
            malbolge_main()

    elif args.command == 'debug':
        if not args.file:
            parser.error('File argument is required for debug command')
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

    else:
        # Assume command is actually a filename
        if args.file is not None:
            parser.error('unexpected extra source filename')
        args.file = args.command
        if remaining:
            parser.error('unrecognized arguments: ' + ' '.join(remaining))
        if (args.max_steps is not None or args.max_output is not None or args.stats
                or args.eof is not None or args.input is not None
                or args.input_file is not None):
            _bounded_run(args, parser)
            return
        if args.variant == 'malbolge20':
            from .malbolge20 import main as malbolge20_main
            sys.argv = ['malbolge20', args.file] + remaining
            malbolge20_main()
        else:
            from .malbolge import main as malbolge_main
            sys.argv = ['malbolge', args.file] + remaining
            malbolge_main()


if __name__ == '__main__':
    main()
