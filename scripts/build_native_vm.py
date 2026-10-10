"""Build the optional VM extension for the Python selected by uv.

Usage: uv run python scripts/build_native_vm.py
This explicit developer command writes into the checkout by default. Source
installs use the same compiler adapter through a separate Hatch wheel hook.
Build dependencies can be supplied with:
uv run --with setuptools --with wheel python scripts/build_native_vm.py.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sysconfig

if __package__:
    from .native_build import build_native_extension
else:
    from native_build import build_native_extension


ROOT = Path(__file__).resolve().parents[1]


def build(output_dir=None, compiler=None):
    record = build_native_extension(ROOT, output_dir or ROOT / "malbolge", compiler)
    receipt_dir = ROOT / "build/native-vm" / (sysconfig.get_config_var("SOABI") or "unknown")
    receipt_dir.mkdir(parents=True, exist_ok=True)
    (receipt_dir / "build.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf8")
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, help="default: repository malbolge directory")
    parser.add_argument("--cc", help="Unix compiler command override; MSVC uses standard discovery")
    args = parser.parse_args(argv)
    try:
        record = build(args.output_dir, args.cc)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        parser.exit(1, str(error) + "\n")
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
