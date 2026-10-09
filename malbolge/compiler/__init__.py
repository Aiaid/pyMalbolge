"""
malbolge.compiler -- a pure-Python compiler from a Python subset to Malbolge20.

The full chain is self-contained (no external tools needed):

    Python subset --py2c--> Nagoya C subset --c2mg--> .mg pseudo-instructions
    --mg2mc--> .mc LAL assembly --mc2mb--> .mb Malbolge20 program

The C/direct paths need no external tools or mandatory dependencies. The
optional ``ir`` backend imports the direct path's MC into structured xDSL LAL,
runs explicit verified passes and emits MC for the same assembler. See
``docs/design/compiler-ir.md`` for this first migration boundary. Reference
C/C++/Perl tools under ref/ are used by the conformance test suite.

The opt-in semantic frontend emits structured source IR directly, with a
separate verified pipeline and an authoritative adapter to the existing target
backend; see ``docs/design/semantic-ir.md``.

    from malbolge.compiler import compile_python_to_mb
    mb_source = compile_python_to_mb("putchar(72)\\nputchar(105)\\n")

Individual stages are also exported for tooling and debugging.
"""

from .py2c import compile_python_to_c, CompileError
from .py2mg import compile_python_to_mg, Py2MgError
from .c2mg import compile_c_to_mg, C2MgError
from .mg2mc import translate_mg_to_mc, translate_mg_to_lal, Mg2McError
from .mc2mb import (
    assemble_mc_to_mb, iter_mc_to_mb, assemble_lal_to_mb, iter_lal_to_mb,
    layout_lal_to_image, image_to_mb, iter_image_to_mb, Mc2MbError,
)


def compile_python_to_mb(py_source: str, backend: str = "c", *,
                         op_style: str = "cluster",
                         jmp_style: str = "main", passes=None,
                         ir_frontend="compat", semantic_passes=None,
                         target_pipeline="text") -> str:
    """Compile a Python-subset program all the way to Malbolge20 source.

    ``backend`` selects the front half of the pipeline:

    * ``"c"`` (default) -- the two-step ``py2c`` + ``c2mg`` path (unchanged
      behaviour).
    * ``"direct"`` -- the ``py2mg`` direct Python -> ``.mg`` backend, which
      skips the C layer (smaller, non-recursive functions carry no frame
      protection; see ``docs/design/py2mg-backend.md``).
    * ``"ir"`` -- optional verified LAL IR pipeline, currently entered through
      the direct backend's MG/MC compatibility bridge. Requires the ``ir``
      extra and Python 3.10+. ``ir_frontend='semantic'`` uses the new semantic
      frontend and explicit target adapter; the default retains the old bridge.

    Both paths share the ``mg2mc`` and ``mc2mb`` back half.  ``op_style`` and
    ``jmp_style`` are the ``mg2mc`` code-generation styles (see
    :func:`~malbolge.compiler.mg2mc.translate_mg_to_mc`); the defaults keep the
    output byte-identical to the reference toolchain.

    ``target_pipeline='structured'`` selects the experimental native LAL/image
    handoff, avoiding mandatory MC/data serialization. It retains the existing
    protocol, layout and padding. The default ``'text'`` remains the reference
    path; neither selection changes the Python frontend or optimization profile.
    """
    if target_pipeline not in ("text", "structured"):
        raise ValueError("target_pipeline must be 'text' or 'structured'")
    if backend == "ir":
        if target_pipeline == "structured":
            from .ir.bridge import compile_python_ir_result
            from .ir.lal import lal_to_model
            result = compile_python_ir_result(
                py_source, op_style=op_style, jmp_style=jmp_style, passes=passes,
                frontend=ir_frontend, semantic_passes=semantic_passes,
                target_pipeline=target_pipeline)
            return assemble_lal_to_mb(lal_to_model(result.module))
        from .ir import compile_python_via_ir_to_mc
        mc_source = compile_python_via_ir_to_mc(
            py_source, op_style=op_style, jmp_style=jmp_style, passes=passes,
            frontend=ir_frontend, semantic_passes=semantic_passes)
        return assemble_mc_to_mb(mc_source)
    if passes is not None:
        raise ValueError("passes are only available with backend='ir'")
    if ir_frontend != "compat" or semantic_passes is not None:
        raise ValueError("IR frontend selection requires backend='ir'")
    if backend == "direct":
        mg_source = compile_python_to_mg(py_source)
    elif backend == "c":
        mg_source = compile_c_to_mg(compile_python_to_c(py_source))
    else:
        raise ValueError("unknown backend {!r} (use 'c', 'direct' or 'ir')".format(
            backend))
    if target_pipeline == "structured":
        model = translate_mg_to_lal(mg_source, op_style=op_style,
                                    jmp_style=jmp_style)
        return assemble_lal_to_mb(model)
    mc_source = translate_mg_to_mc(mg_source, op_style=op_style,
                                   jmp_style=jmp_style)
    return assemble_mc_to_mb(mc_source)


def compile_python_to_ir(py_source: str, *, op_style="cluster",
                         jmp_style="main", passes=None, frontend="compat",
                         semantic_passes=None, target_pipeline="text"):
    """Return verified low-level LAL IR through the optional compatibility bridge.

    Importing the compiler does not load xDSL. See
    ``docs/design/compiler-ir.md`` for the migration boundary and pass contract.
    """
    from .ir import compile_python_to_ir as compile_ir
    return compile_ir(py_source, op_style=op_style, jmp_style=jmp_style,
                      passes=passes, frontend=frontend, semantic_passes=semantic_passes,
                      target_pipeline=target_pipeline)


def compile_python_to_semantic_ir(py_source: str):
    """Emit verified structured source semantics without MG/MC generation."""
    from .ir import compile_python_to_semantic_ir as compile_semantic
    return compile_semantic(py_source)


__all__ = [
    "compile_python_to_c", "CompileError",
    "compile_python_to_mg", "Py2MgError",
    "compile_c_to_mg", "C2MgError",
    "translate_mg_to_mc", "translate_mg_to_lal", "Mg2McError",
    "assemble_mc_to_mb", "iter_mc_to_mb", "Mc2MbError",
    "assemble_lal_to_mb", "iter_lal_to_mb", "layout_lal_to_image",
    "image_to_mb", "iter_image_to_mb",
    "compile_python_to_mb", "compile_python_to_ir", "compile_python_to_semantic_ir",
]
