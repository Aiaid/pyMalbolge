"""Target adapters for semantic IR and the original direct-to-LAL bridge.

Semantic frontend selection is explicit. The current target adapter reconstructs
ordered operations as Python AST for the existing MG backend; it never reuses
stored source instead of the authoritative semantic module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from . import require_ir_support

if TYPE_CHECKING:
    from xdsl.dialects.builtin import ModuleOp
    from .passes import PipelineResult


def mc_to_ir_result(
    mc_source: str,
    passes: Sequence[str] | None = None,
    *,
    snapshots: bool = False,
) -> PipelineResult:
    """Parse MC and run a fully validated explicit pass selection."""
    require_ir_support()
    from .lal import parse_mc
    from .passes import run_pipeline, validate_pass_names

    names = validate_pass_names(passes)
    return run_pipeline(parse_mc(mc_source), names, snapshots=snapshots)


def compile_python_ir_result(
    source: str,
    op_style: str = "cluster",
    jmp_style: str = "main",
    passes: Sequence[str] | None = None,
    *,
    snapshots: bool = False,
    frontend: str = "compat",
    semantic_passes: Sequence[str] | None = None,
) -> PipelineResult:
    """Select a frontend explicitly and return verified low-level LAL reports."""
    require_ir_support()
    from .passes import validate_pass_names

    names = validate_pass_names(passes)
    from ..mg2mc import translate_mg_to_mc
    if frontend == "semantic":
        from .semantic_passes import compile_python_semantic_result
        from .lowering import lower_semantic_to_mg
        semantic = compile_python_semantic_result(source, semantic_passes,
                                                  snapshots=snapshots)
        mg_source = lower_semantic_to_mg(semantic.module)
    elif frontend == "compat":
        if semantic_passes is not None:
            raise ValueError("semantic passes require the semantic frontend")
        from ..py2mg import compile_python_to_mg
        mg_source = compile_python_to_mg(source)
    else:
        raise ValueError("IR frontend must be 'compat' or 'semantic'")
    mc_source = translate_mg_to_mc(mg_source, op_style=op_style, jmp_style=jmp_style)
    return mc_to_ir_result(mc_source, names, snapshots=snapshots)


def compile_python_to_ir(
    source: str,
    op_style: str = "cluster",
    jmp_style: str = "main",
    passes: Sequence[str] | None = None,
    *, frontend: str = "compat", semantic_passes: Sequence[str] | None = None,
) -> ModuleOp:
    """Return a verified xDSL LAL module from the existing direct frontend."""
    return compile_python_ir_result(source, op_style, jmp_style, passes,
                                    frontend=frontend, semantic_passes=semantic_passes).module


def compile_python_via_ir_to_mc(
    source: str,
    op_style: str = "cluster",
    jmp_style: str = "main",
    passes: Sequence[str] | None = None,
    *, frontend: str = "compat", semantic_passes: Sequence[str] | None = None,
) -> str:
    """Return canonical MC emitted from the verified compatibility IR."""
    module = compile_python_to_ir(source, op_style, jmp_style, passes,
                                  frontend=frontend, semantic_passes=semantic_passes)
    from .lal import emit_mc

    return emit_mc(module)


def compile_semantic_to_mc(module, *, op_style="cluster", jmp_style="main",
                           passes=None):
    """Compile the supplied semantic module through the explicit target adapter."""
    require_ir_support()
    from .passes import validate_pass_names
    names = validate_pass_names(passes)
    from .lowering import lower_semantic_to_mg
    from ..mg2mc import translate_mg_to_mc
    from .lal import emit_mc
    mc = translate_mg_to_mc(lower_semantic_to_mg(module), op_style=op_style,
                            jmp_style=jmp_style)
    return emit_mc(mc_to_ir_result(mc, names).module)
