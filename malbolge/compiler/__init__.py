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

The semantic frontend emits structured source IR directly, with a
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
    layout_lal_to_image, image_to_mb, iter_image_to_mb, predict_image_mb_size, Mc2MbError,
)


from .optimization import (
    POLICY_VERSION, OptimizationPolicy, CompilationPlan,
    resolve_optimization_policy, build_compilation_plan,
)


def compile_python_to_mb(py_source: str, backend: str = "auto", *,
                         op_style: str = "cluster",
                         jmp_style: str = "main", passes=None,
                         ir_frontend=None, semantic_passes=None,
                         target_pipeline=None, opt_level=3) -> str:
    """Compile Python to Malbolge20 using the shared validated optimization policy.

    The default O3 ``auto`` backend compares direct and optional semantic
    candidates by final image bytes, choosing direct on ties. A missing optional
    IR environment or inapplicable semantic frontend leaves the direct candidate
    available; compiler and verification defects are never hidden by fallback.
    Candidate selection does not assemble either bootstrap until a winner exists.

    Explicit ``c``, ``direct`` and ``ir`` backends preserve frontend control.
    O0 disables direct arithmetic shortcuts and semantic target representation
    shortcuts; O1 enables validated arithmetic, O2 adds structured LAL/image
    transfer, and O3 adds frontend competition. An explicit ``target_pipeline``
    overrides the level's handoff. Explicit IR uses the semantic frontend at
    every level unless compatibility is requested explicitly. C retains its
    reference frontend intrinsics at every level. Explicit semantic passes are an exact profile override. Individual
    stage APIs retain their existing structural contracts.
    """
    policy = resolve_optimization_policy(
        backend, opt_level=opt_level, ir_frontend=ir_frontend,
        semantic_passes=semantic_passes, target_pipeline=target_pipeline,
        passes=passes)
    return build_compilation_plan(py_source, policy, op_style, jmp_style).to_mb()


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
    "image_to_mb", "iter_image_to_mb", "predict_image_mb_size",
    "compile_python_to_mb", "compile_python_to_ir", "compile_python_to_semantic_ir",
    "POLICY_VERSION", "OptimizationPolicy", "CompilationPlan",
    "resolve_optimization_policy", "build_compilation_plan",
]
