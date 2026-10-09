"""Verified pass boundaries for source semantics, before target lowering."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
from types import MappingProxyType
from typing import ClassVar

from . import require_ir_support

require_ir_support()

from xdsl.context import Context
from xdsl.dialects.builtin import ModuleOp
from xdsl.passes import ModulePass

from .passes import run_verified_pipeline, validate_pass_names
from .semantic import create_semantic_context, print_semantic, verify_semantic


@dataclass(frozen=True)
class VerifySemanticPass(ModulePass):
    name: ClassVar[str] = "verify-semantic"

    def apply(self, ctx: Context, op: ModuleOp) -> None:
        verify_semantic(op)


SEMANTIC_PASS_REGISTRY = MappingProxyType({VerifySemanticPass.name: VerifySemanticPass})
DEFAULT_SEMANTIC_PASSES = (VerifySemanticPass.name,)


@dataclass(frozen=True)
class SemanticSummary:
    ir_digest: str
    total_operations: int
    operation_counts: dict[str, int]
    ir_bytes: int


def summarize_semantic(module: ModuleOp) -> SemanticSummary:
    text = print_semantic(module).encode("utf8")
    counts = Counter(op.name for op in module.walk())
    return SemanticSummary(hashlib.sha256(text).hexdigest(), sum(counts.values()),
                           dict(sorted(counts.items())), len(text))


def validate_semantic_pass_names(passes=None, *, registry=None):
    selected = DEFAULT_SEMANTIC_PASSES if passes is None else passes
    return validate_pass_names(selected, registry=(SEMANTIC_PASS_REGISTRY
                                                   if registry is None else registry))


def run_semantic_pipeline(module, passes=None, *, clone=True, snapshots=False,
                          registry=None):
    registry = SEMANTIC_PASS_REGISTRY if registry is None else registry
    names = validate_semantic_pass_names(passes, registry=registry)
    return run_verified_pipeline(
        module, names, registry=registry, verifier=verify_semantic,
        context_factory=create_semantic_context, printer=print_semantic,
        summarizer=summarize_semantic, clone=clone, snapshots=snapshots)


def compile_python_semantic_result(source, passes=None, *, snapshots=False):
    """Validate selection before emitting any source IR, then run its passes."""
    names = validate_semantic_pass_names(passes)
    from .frontend import compile_python_to_semantic_ir
    return run_semantic_pipeline(compile_python_to_semantic_ir(source), names,
                                 snapshots=snapshots)
