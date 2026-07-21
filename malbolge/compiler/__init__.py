"""
malbolge.compiler -- a pure-Python compiler from a Python subset to Malbolge20.

The full chain is self-contained (no external tools needed):

    Python subset --py2c--> Nagoya C subset --c2mg--> .mg pseudo-instructions
    --mg2mc--> .mc LAL assembly --mc2mb--> .mb Malbolge20 program

Each stage is a faithful pure-Python port of the corresponding Nagoya
reference tool, verified byte-identical against it (see docs/findings.md).
The reference C/C++/perl tools under ref/ are now only used by the
conformance test suite.

    from malbolge.compiler import compile_python_to_mb
    mb_source = compile_python_to_mb("putchar(72)\\nputchar(105)\\n")

Individual stages are also exported for tooling and debugging.
"""

from .py2c import compile_python_to_c, CompileError
from .c2mg import compile_c_to_mg, C2MgError
from .mg2mc import translate_mg_to_mc, Mg2McError
from .mc2mb import assemble_mc_to_mb, Mc2MbError


def compile_python_to_mb(py_source: str) -> str:
    """Compile a Python-subset program all the way to Malbolge20 source."""
    c_source = compile_python_to_c(py_source)
    mg_source = compile_c_to_mg(c_source)
    mc_source = translate_mg_to_mc(mg_source)
    return assemble_mc_to_mb(mc_source)


__all__ = [
    "compile_python_to_c", "CompileError",
    "compile_c_to_mg", "C2MgError",
    "translate_mg_to_mc", "Mg2McError",
    "assemble_mc_to_mb", "Mc2MbError",
    "compile_python_to_mb",
]
