"""
Entry point for running malbolge as a module: python -m malbolge

Supports multiple Malbolge variants:
  python -m malbolge program.mal                    # Original Malbolge
  python -m malbolge --variant=malbolge20 program.mal  # Malbolge20
  python -m malbolge debug program.mal              # Debug mode
"""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(
        description='Malbolge interpreter - supports multiple variants',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python -m malbolge examples/hello.mal
  python -m malbolge --variant=malbolge20 program.mal
  python -m malbolge debug examples/hello.mal
  python -m malbolge debug --tui examples/hello.mal
'''
    )

    parser.add_argument(
        'command',
        nargs='?',
        default='run',
        help='Command: run (default), debug'
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

    args, remaining = parser.parse_known_args()

    # Handle case where command is actually the file
    if args.command and args.command.endswith('.mal'):
        args.file = args.command
        args.command = 'run'
    elif args.command == 'debug' and not args.file and remaining:
        args.file = remaining[0]
        remaining = remaining[1:]

    if args.command == 'run':
        if not args.file:
            parser.error('File argument is required for run command')

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
        args.file = args.command
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
