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
from .py2mg import compile_python_to_mg, Py2MgError
from .c2mg import compile_c_to_mg, C2MgError
from .mg2mc import translate_mg_to_mc, Mg2McError
from .mc2mb import assemble_mc_to_mb, Mc2MbError


def compile_python_to_mb(py_source: str, backend: str = "c", *,
                         op_style: str = "cluster",
                         jmp_style: str = "main") -> str:
    """Compile a Python-subset program all the way to Malbolge20 source.

    ``backend`` selects the front half of the pipeline:

    * ``"c"`` (default) -- the two-step ``py2c`` + ``c2mg`` path (unchanged
      behaviour).
    * ``"direct"`` -- the ``py2mg`` direct Python -> ``.mg`` backend, which
      skips the C layer (smaller, non-recursive functions carry no frame
      protection; see ``docs/py2mg-backend.md``).

    Both paths share the ``mg2mc`` and ``mc2mb`` back half.  ``op_style`` and
    ``jmp_style`` are the ``mg2mc`` code-generation styles (see
    :func:`~malbolge.compiler.mg2mc.translate_mg_to_mc`); the defaults keep the
    output byte-identical to the reference toolchain.
    """
    if backend == "direct":
        mg_source = compile_python_to_mg(py_source)
    elif backend == "c":
        mg_source = compile_c_to_mg(compile_python_to_c(py_source))
    else:
        raise ValueError("unknown backend {!r} (use 'c' or 'direct')".format(
            backend))
    mc_source = translate_mg_to_mc(mg_source, op_style=op_style,
                                   jmp_style=jmp_style)
    return assemble_mc_to_mb(mc_source)


__all__ = [
    "compile_python_to_c", "CompileError",
    "compile_python_to_mg", "Py2MgError",
    "compile_c_to_mg", "C2MgError",
    "translate_mg_to_mc", "Mg2McError",
    "assemble_mc_to_mb", "Mc2MbError",
    "compile_python_to_mb",
]
