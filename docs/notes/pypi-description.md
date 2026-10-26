# pyMalbolge

Compile a subset of Python to **Malbolge20**, run original Malbolge or
Malbolge20 programs, and inspect execution with CLI/TUI debuggers.

- Python compiler with C and direct backends, O0–O3 controls and automatic
  selection of applicable Direct/semantic IR candidates at O3.
- Optional semantic IR tools through the `ir` extra (Python 3.10+).
- Byte-oriented interpreters with execution/output budgets for batch runs.
- Optional native Malbolge20 batch execution with a Python fallback.
- Debugger breakpoints, watchpoints, step-back and memory inspection.

The compiler and Python interpreters have no mandatory Python runtime
dependencies. The optional TUI uses Textual. This is a Python subset compiler;
it does not compile arbitrary Python programs.

## Install

Requires Python 3.8 or newer:

```sh
uv venv
uv pip install malbolge
# Optional interfaces and IR tools:
uv pip install 'malbolge[tui]'
uv pip install 'malbolge[ir]'  # Python 3.10+
```

A pure Python wheel runs without a C compiler. When building from source,
the default build attempts the native extension and falls back to Python if
compilation is unavailable. `MALBOLGE_NATIVE_BUILD=disabled` disables native
compilation; `required` makes compilation failure fatal. Importing or running
the installed package never launches a compiler.
Editable installs skip native compilation; build the extension manually if
native execution is needed in a source checkout.

## Compile and run

Save this as `hello.py`:

```python
print("Hello, world!")
```

From the environment where the package is installed:

```sh
uv run python -m malbolge compile hello.py --no-cache -o hello.mb
uv run python -m malbolge --variant=malbolge20 hello.mb --engine=python --input '' --max-steps 5000000 --max-output 64
# Hello, world!
```

Compilation defaults to O3 automatic selection. Base installations can use
the direct path without xDSL; the optional `ir` extra enables applicable
semantic IR candidates. Explicit `--backend=c`, `--backend=direct` or
`--backend=ir` selects that path.

Malbolge20 uses 20-trit words and is **not backward compatible** with original
10-trit Malbolge. Python compiler output targets Malbolge20.

## Try the browser debugger

[Open the online debugger](https://aiaid.github.io/pyMalbolge/) to step through
**original Malbolge** without installing a package. The browser debugger does
not compile Python or execute Malbolge20 programs.

## Documentation and attribution

- [Source and detailed usage](https://github.com/Aiaid/pyMalbolge)
- [Python subset specification](https://github.com/Aiaid/pyMalbolge/blob/master/docs/specs/python-subset-spec.md)
- [Report an issue](https://github.com/Aiaid/pyMalbolge/issues)
- [Malbolge20 project](https://malbolge20.gitlab.io/index-en.html)
- [Upstream compiler toolchain](https://gitlab.com/malbolge20/malbolge20_creator)

pyMalbolge began as a fork of
[Avantgarde95/pyMalbolge](https://github.com/Avantgarde95/pyMalbolge).
Its compiler incorporates Python ports of the Nagoya University Malbolge20
toolchain components, alongside Python frontends and additional tooling.
Upstream attribution and applicable notices are retained in the source.
pyMalbolge is distributed under the MIT license.
