"""Optional semantic and LAL IR; importing this package does not import xDSL.

Python can emit structured semantics directly, while target lowering uses an
explicit compatibility adapter. The original direct-to-LAL bridge is retained
as a separately selectable reference frontend.
"""

import importlib
from importlib import metadata
import sys


XDSL_VERSION = "0.69.0"


class IRDependencyError(RuntimeError):
    """The optional IR environment is missing or incompatible."""


def require_ir_support():
    """Check the supported environment before importing optional IR code."""
    if sys.version_info < (3, 10):
        raise IRDependencyError(
            "The IR backend requires Python 3.10 or newer; use a supported "
            "Python with uv and run `uv sync --extra ir --extra dev`."
        )
    try:
        version = metadata.version("xdsl")
    except metadata.PackageNotFoundError as exc:
        raise IRDependencyError(
            "The IR backend requires the optional xDSL dependency; run "
            "`uv sync --extra ir --extra dev` (Python 3.10 or newer)."
        ) from exc
    if version != XDSL_VERSION:
        raise IRDependencyError(
            "The IR backend requires xdsl=={}; found {}. Run "
            "`uv sync --extra ir --extra dev` to restore the supported version."
            .format(XDSL_VERSION, version)
        )


_LAZY_EXPORTS = {
    'InlinePureArithmeticPass': 'expression_passes',
    'FoldArithmeticPass': 'arithmetic_passes',
    'SimplifyArithmeticPass': 'arithmetic_passes',
    'LowerConstantMultiplyPass': 'arithmetic_passes',
    'SimplifyControlPass': 'arithmetic_passes',
    'ConstantPropagationPass': 'dataflow_passes',
    'EliminatePureComputationPass': 'dataflow_passes',
    'LowerDecimalOutputPass': 'decimal_passes',
    "compile_python_to_semantic_ir": "frontend",
    "compile_python_semantic_result": "semantic_passes",
    "run_semantic_pipeline": "semantic_passes",
    "validate_semantic_pass_names": "semantic_passes",
    "VerifySemanticPass": "semantic_passes",
    "summarize_semantic": "semantic_passes",
    "parse_semantic": "semantic",
    "print_semantic": "semantic",
    "verify_semantic": "semantic",
    "SemanticIRError": "semantic",
    "run_semantic": "interpreter",
    "lower_semantic_to_python_ast": "lowering",
    "lower_semantic_to_mg": "lowering",
    "compile_semantic_to_mc": "bridge",
    "compile_python_to_ir": "bridge",
    "compile_python_via_ir_to_mc": "bridge",
    "compile_python_ir_result": "bridge",
    "mc_to_ir_result": "bridge",
    "validate_pass_names": "passes",
    "available_passes": "passes",
    "run_pipeline": "passes",
    "PipelineResult": "passes",
    "PipelineError": "passes",
    "VerifyLalPass": "passes",
    "parse_mc": "lal",
    "emit_mc": "lal",
    "verify_lal": "lal",
    "parse_lal": "lal",
    "print_lal": "lal",
    "LalIRError": "lal",
    "create_lal_context": "lal",
}


def __getattr__(name):
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError("module {!r} has no attribute {!r}".format(__name__, name))
    require_ir_support()
    module = importlib.import_module(".{}".format(module_name), __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


__all__ = ["IRDependencyError", "XDSL_VERSION", "require_ir_support"] + list(_LAZY_EXPORTS)
