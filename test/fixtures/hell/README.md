# HeLL / Malbolge test fixtures

This directory contains six example programs taken from the
[LMAO](https://github.com/esoteric-programmer/LMAO) project (Low-level
Malbolge Assembler, Ooh!) by Matthias Lutter, used here purely as
input/output fixtures for pyMalbolge's tests.

## Provenance

- **Source**: https://github.com/esoteric-programmer/LMAO
- **Author**: Matthias Lutter <matthias@lutter.cc>
- **License**: GNU General Public License v3.0 (GPL-3.0). See the full
  license text in the upstream repository. The `*.hell` files below are
  reproduced verbatim from LMAO, including their original GPL-3.0 copyright
  headers.
- **LMAO version**: built from the LMAO source checked out at commit
  `3ea747e` ("LMAO v0.6"), one commit past the `v0.5.6b` tag; the resulting
  `lmao` binary self-reports as `LMAO v0.6.0`. The `*.mal` files were
  assembled with that binary, i.e. `lmao example_foo.hell -o example_foo.mal`.

## License note

pyMalbolge itself is MIT-licensed (see the repository root `LICENSE`). The
files in this directory are an exception: they are third-party GPL-3.0
fixtures used only as test inputs, not distributed as part of the pyMalbolge
library's own source code. They are kept here, tracked in git, to make the
test suite reproducible without needing a local checkout of LMAO.

## Files

Each example exists as a pair:

| `.hell` (HeLL source, from LMAO)     | `.mal` (assembled Malbolge, from LMAO's `lmao`) |
|---------------------------------------|--------------------------------------------------|
| `example_hello_world.hell`            | `example_hello_world.mal`                        |
| `example_simple_hello_world.hell`     | `example_simple_hello_world.mal`                 |
| `example_simple_cat.hell`             | `example_simple_cat.mal`                         |
| `example_cat_halt_on_eof.hell`        | `example_cat_halt_on_eof.mal`                    |
| `example_digital_root.hell`           | `example_digital_root.mal`                       |
| `example_adder.hell`                  | `example_adder.mal`                              |

The `.mal` files are run directly by pyMalbolge's tests (see
`test/test_hell_examples.py`); the `.hell` files are kept alongside them for
reference and are not currently consumed by any code (there is no HeLL
assembler in pyMalbolge yet).

## Intended future use

Per the pyMalbolge `CLAUDE.md` TODO list, a Python port of a HeLL
assembler/compiler is a pending feature. When that lands, these `.hell`
files can serve as a spec/conformance test suite: assemble each `.hell` file
with the Python assembler and check that the resulting Malbolge program
produces the same input/output behavior as the reference `.mal` files
checked in here (which were produced by the real LMAO tool).
