"""Explicit, verified LAL passes; no upstream optimization is enabled.

Operation counts and serialized sizes describe structure, not execution speed.
The registry is intentionally small: passes must be explicitly registered and
selected, and source modules are cloned before any pass runs by default.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
from types import MappingProxyType
from typing import Callable, ClassVar, Mapping, Protocol, Sequence

from . import XDSL_VERSION, require_ir_support

require_ir_support()

from xdsl.context import Context
from xdsl.dialects.builtin import ModuleOp
from xdsl.passes import ModulePass

from .lal import create_lal_context, emit_mc, print_lal, verify_lal


class PipelineError(ValueError):
    """Pass selection, execution, or a verification boundary failed."""


@dataclass(frozen=True)
class VerifyLalPass(ModulePass):
    """Validate the LAL contract without changing the module."""

    name: ClassVar[str] = "verify-lal"

    def apply(self, ctx: Context, op: ModuleOp) -> None:
        verify_lal(op)


PassFactory = Callable[[], ModulePass]
PASS_REGISTRY: Mapping[str, PassFactory] = MappingProxyType({
    VerifyLalPass.name: VerifyLalPass,
})
DEFAULT_PASSES = (VerifyLalPass.name,)


def available_passes(registry: Mapping[str, PassFactory] | None = None) -> tuple[str, ...]:
    """Return registered names in a stable order."""
    return tuple(sorted(PASS_REGISTRY if registry is None else registry))


def validate_pass_names(
    passes: Sequence[str] | None = None,
    *,
    registry: Mapping[str, PassFactory] | None = None,
) -> tuple[str, ...]:
    """Validate the entire requested sequence before running any codegen/pass.

    ``None`` selects the verification pass; an empty sequence explicitly selects
    no passes (the pipeline still verifies its input and output).
    """
    registry = PASS_REGISTRY if registry is None else registry
    if isinstance(passes, str):
        raise PipelineError("Passes must be a sequence of names, not a string.")
    names = DEFAULT_PASSES if passes is None else tuple(passes)
    if any(not isinstance(name, str) or not name for name in names):
        raise PipelineError("Pass names must be nonempty strings.")
    unknown = sorted(set(names).difference(registry))
    if unknown:
        raise PipelineError(
            "Unknown IR pass(es): {}. Available: {}.".format(
                ", ".join(unknown), ", ".join(available_passes(registry)) or "(none)"
            )
        )
    return names


@dataclass(frozen=True)
class IRSummary:
    ir_digest: str
    mc_digest: str
    total_operations: int
    operation_counts: dict[str, int]
    mc_bytes: int


class StructuralSummary(Protocol):
    """Common inspection fields; dialect summaries remain distinct."""

    ir_digest: str
    total_operations: int
    operation_counts: dict[str, int]


@dataclass(frozen=True)
class PassReport:
    name: str
    before: StructuralSummary
    after: StructuralSummary


@dataclass(frozen=True)
class IRSnapshot:
    stage: str
    text: str


@dataclass(frozen=True)
class PipelineResult:
    module: ModuleOp
    reports: tuple[PassReport, ...]
    snapshots: tuple[IRSnapshot, ...] = ()

    def to_dict(self) -> dict:
        """JSON-compatible report, excluding the live xDSL module object."""
        result = {
            "xdsl_version": XDSL_VERSION,
            "passes": [report.name for report in self.reports],
            "reports": [asdict(report) for report in self.reports],
        }
        if self.snapshots:
            result["snapshots"] = [asdict(snapshot) for snapshot in self.snapshots]
        return result


def summarize_ir(module: ModuleOp) -> IRSummary:
    """Describe a verified module with deterministic textual SHA-256 digests."""
    ir_text = print_lal(module).encode("utf-8")
    mc_text = emit_mc(module).encode("utf-8")
    counts = Counter(op.name for op in module.walk())
    return IRSummary(
        ir_digest=hashlib.sha256(ir_text).hexdigest(),
        mc_digest=hashlib.sha256(mc_text).hexdigest(),
        total_operations=sum(counts.values()),
        operation_counts=dict(sorted(counts.items())),
        mc_bytes=len(mc_text),
    )


def _verify(module: ModuleOp, stage: str, verifier) -> None:
    try:
        verifier(module)
    except Exception as exc:
        raise PipelineError("IR verification failed {}: {}".format(stage, exc)) from exc


def run_pipeline(
    module: ModuleOp,
    passes: Sequence[str] | None = None,
    *,
    clone: bool = True,
    snapshots: bool = False,
    registry: Mapping[str, PassFactory] | None = None,
) -> PipelineResult:
    """Run named ModulePass instances, verifying before and after each pass.

    A failed pass cannot mutate the supplied module under the default ``clone``
    policy. Custom registries support project pass development without silently
    enabling the xDSL upstream optimization catalog.
    """
    registry = PASS_REGISTRY if registry is None else registry
    names = validate_pass_names(passes, registry=registry)
    return run_verified_pipeline(
        module, names, registry=registry, verifier=verify_lal,
        context_factory=create_lal_context, printer=print_lal,
        summarizer=summarize_ir, clone=clone, snapshots=snapshots)


def run_verified_pipeline(
    module: ModuleOp,
    passes: Sequence[str],
    *,
    registry: Mapping[str, PassFactory],
    verifier: Callable[[ModuleOp], None],
    context_factory: Callable[[], Context],
    printer: Callable[[ModuleOp], str],
    summarizer: Callable[[ModuleOp], StructuralSummary],
    clone: bool = True,
    snapshots: bool = False,
) -> PipelineResult:
    """Shared execution boundaries with explicit dialect-specific contracts.

    A semantic IR has no MC yet, so its summary must not manufacture target
    sizes or digests. Each dialect provides its own verifier and serializer.
    """
    names = validate_pass_names(passes, registry=registry)
    pipeline = []
    for name in names:
        instance = registry[name]()
        if not isinstance(instance, ModulePass) or instance.name != name:
            raise PipelineError("Registry entry {!r} must construct a matching ModulePass.".format(name))
        pipeline.append(instance)
    current = module.clone() if clone else module
    context = context_factory()
    _verify(current, "at pipeline input", verifier)
    captured = [IRSnapshot("input", printer(current))] if snapshots else []
    reports = []
    for index, instance in enumerate(pipeline):
        _verify(current, "before pass {!r}".format(instance.name), verifier)
        before = summarizer(current)
        try:
            instance.apply(context, current)
        except Exception as exc:
            raise PipelineError("IR pass {!r} failed: {}".format(instance.name, exc)) from exc
        _verify(current, "after pass {!r}".format(instance.name), verifier)
        reports.append(PassReport(instance.name, before, summarizer(current)))
        if snapshots:
            captured.append(IRSnapshot("{}:{}".format(index + 1, instance.name), printer(current)))
    _verify(current, "at pipeline output", verifier)
    return PipelineResult(current, tuple(reports), tuple(captured))
