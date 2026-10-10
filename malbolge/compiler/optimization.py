"""Shared, dependency-free optimization policy and prepared compilation plans.

Levels select validated facilities: O0 keeps the direct reference lowering, O1
adds its arithmetic shortcuts, O2 uses the native target handoff, and O3 also
compares the accepted semantic frontend with direct code. Optional xDSL is only
loaded while executing a plan that can use it; policy resolution never loads it.
"""

from dataclasses import dataclass, field
from typing import Any, Optional, Tuple


POLICY_VERSION = "1"


@dataclass(frozen=True)
class OptimizationPolicy:
    """Normalized options, preserving explicit choices for diagnostics/cache keys."""

    requested_backend: str
    opt_level: int
    requested_ir_frontend: Optional[str]
    requested_target_pipeline: Optional[str]
    backend: str
    ir_frontend: Optional[str]
    target_pipeline: str
    arithmetic_optimizations: bool
    semantic_passes: Optional[Tuple[str, ...]]
    passes: Optional[Tuple[str, ...]]
    compete: bool
    policy_version: str = POLICY_VERSION

    def metadata(self):
        """Return JSON-compatible requested and resolved policy choices."""
        semantic_frontend = self.backend == "ir" and self.ir_frontend == "semantic"
        return {
            "policy_version": self.policy_version,
            "opt_level": self.opt_level,
            "requested_backend": self.requested_backend,
            "resolved_backend": self.backend,
            "requested_ir_frontend": self.requested_ir_frontend,
            "ir_frontend": self.ir_frontend,
            "requested_target_pipeline": self.requested_target_pipeline,
            "target_pipeline": self.target_pipeline,
            "arithmetic_optimizations": (False if semantic_frontend
                                         else self.arithmetic_optimizations),
            "arithmetic_optimization_scope": (
                "semantic_named_passes" if semantic_frontend else
                "c_reference_intrinsics" if self.backend == "c" else
                "direct_frontend_shortcuts"),
            "direct_frontend_arithmetic_optimizations": (
                None if self.backend == "c" else
                False if semantic_frontend else self.arithmetic_optimizations),
            "c_reference_intrinsics": self.backend == "c",
            "semantic_target_options": (_semantic_target_options(self.opt_level)
                                        if self.ir_frontend == "semantic" else None),
            "semantic_passes": (None if self.semantic_passes is None
                                else list(self.semantic_passes)),
            "passes": None if self.passes is None else list(self.passes),
            "candidate_competition": self.compete,
        }


def _pass_sequence(value, role):
    if value is None:
        return None
    if isinstance(value, str):
        raise ValueError("{} must be a sequence of names, not a string".format(role))
    result = tuple(value)
    if any(not isinstance(name, str) or not name for name in result):
        raise ValueError("{} names must be nonempty strings".format(role))
    return result


def resolve_optimization_policy(backend="auto", *, opt_level=3,
                                ir_frontend=None, semantic_passes=None,
                                target_pipeline=None, passes=None):
    """Validate and resolve levels without importing optional compiler modules.

    Explicit backends and target pipelines stay authoritative. An explicit IR
    frontend or semantic pass sequence with ``auto`` selects IR rather than participating
    in optional candidate competition. Explicit semantic passes override the
    level's pass profile; O0 still disables the target representation shortcuts.
    Low-level LAL pass selection requires an explicitly selected IR backend.
    """
    if backend not in ("auto", "c", "direct", "ir"):
        raise ValueError("unknown backend {!r} (use 'auto', 'c', 'direct' or 'ir')".format(backend))
    if type(opt_level) is not int or opt_level not in (0, 1, 2, 3):
        raise ValueError("opt_level must be an integer in 0..3")
    if ir_frontend not in (None, "compat", "semantic"):
        raise ValueError("IR frontend must be 'compat' or 'semantic'")
    if target_pipeline not in (None, "text", "structured"):
        raise ValueError("target_pipeline must be 'text' or 'structured'")
    if passes is not None and backend != "ir":
        raise ValueError("passes are only available with backend='ir'")
    if (ir_frontend is not None or semantic_passes is not None) and backend in ("c", "direct"):
        raise ValueError("IR frontend selection requires backend='ir'")
    semantic_names = _pass_sequence(semantic_passes, "semantic passes")
    lal_names = _pass_sequence(passes, "passes")
    explicit_ir = ir_frontend is not None or semantic_names is not None or lal_names is not None
    resolved_backend = ("ir" if explicit_ir else ("auto" if opt_level == 3 else "direct")) if backend == "auto" else backend
    frontend = None
    if resolved_backend == "ir":
        frontend = ir_frontend or "semantic"
        if frontend == "compat" and semantic_names is not None:
            raise ValueError("semantic passes require the semantic frontend")
    return OptimizationPolicy(
        backend, opt_level, ir_frontend, target_pipeline, resolved_backend,
        frontend, target_pipeline or ("structured" if opt_level >= 2 else "text"),
        opt_level > 0 or resolved_backend == "c", semantic_names, lal_names,
        resolved_backend == "auto")


@dataclass
class CompilationPlan:
    """Prepared winning target; candidate selection never generates a bootstrap."""

    policy: OptimizationPolicy
    selected_backend: str
    frontend: str
    mg: str
    lal: Any
    image: Any
    selection: dict = field(default_factory=dict)
    semantic_result: Any = None
    ir_result: Any = None

    def metadata(self):
        result = self.policy.metadata()
        result.update(self.selection)
        result.update(selected_backend=self.selected_backend,
                      selected_frontend=self.frontend)
        return result

    def to_mc(self):
        """Export the winning ordered target for debugging or the text handoff."""
        from .lal_model import emit_lal_to_mc
        return emit_lal_to_mc(self.lal)

    def to_mb(self):
        """Generate the bootstrap once, using the requested target interface."""
        from .mc2mb import assemble_mc_to_mb, image_to_mb
        if self.policy.target_pipeline == "text":
            return assemble_mc_to_mb(self.to_mc())
        return image_to_mb(self.image)


def _target_plan(mg, policy, selected_backend, frontend, op_style, jmp_style,
                 semantic_result=None, ir_result=None):
    from .mg2mc import translate_mg_to_lal
    from .mc2mb import layout_lal_to_image
    model = translate_mg_to_lal(mg, op_style=op_style, jmp_style=jmp_style)
    return CompilationPlan(policy, selected_backend, frontend, mg, model,
                           layout_lal_to_image(model),
                           semantic_result=semantic_result, ir_result=ir_result)


def _semantic_target_options(opt_level):
    """The three accepted representation controls, with one shared O0 optout."""
    enabled = opt_level > 0
    return {"skip_generated_initialization": enabled,
            "structured_while": enabled, "native_conditions": enabled}


def _semantic_pass_names(policy):
    """Resolve exact ordered names only after the optional framework is available."""
    from .ir.semantic_passes import validate_semantic_pass_names, VERIFY_SEMANTIC_PASSES
    names = policy.semantic_passes
    if names is None and policy.opt_level == 0:
        names = VERIFY_SEMANTIC_PASSES
    return validate_semantic_pass_names(names)


def _semantic_plan(source, policy, op_style, jmp_style):
    from .ir.semantic_passes import compile_python_semantic_result
    from .ir.lowering import lower_semantic_to_mg
    semantic = compile_python_semantic_result(source, _semantic_pass_names(policy))
    mg = lower_semantic_to_mg(semantic.module, arithmetic_optimizations=False,
                              **_semantic_target_options(policy.opt_level))
    plan = _target_plan(mg, policy, "ir", "semantic", op_style, jmp_style,
                        semantic_result=semantic)
    plan.selection["resolved_semantic_passes"] = [report.name for report in semantic.reports]
    plan.selection["semantic_target_options"] = _semantic_target_options(policy.opt_level)
    return plan


def _verify_ir_plan(plan, policy):
    """Keep the transformed verified LAL module authoritative for image layout."""
    from .ir.passes import run_pipeline, validate_pass_names
    from .ir.lal import model_to_lal, lal_to_model, parse_mc
    from .mc2mb import layout_lal_to_image
    names = validate_pass_names(policy.passes)
    module = (model_to_lal(plan.lal) if policy.target_pipeline == "structured"
              else parse_mc(plan.to_mc()))
    plan.ir_result = run_pipeline(module, names)
    plan.lal = lal_to_model(plan.ir_result.module)
    plan.image = layout_lal_to_image(plan.lal)
    return plan


def build_compilation_plan(source, policy, op_style="cluster", jmp_style="main"):
    """Prepare targets and select O3's smaller final image without bootstrapping.

    Only a missing/incompatible optional IR environment or a semantic frontend
    applicability diagnostic can skip the semantic auto candidate. Verification,
    optimization, layout and lowering failures remain visible. Ties select direct.
    """
    if not isinstance(policy, OptimizationPolicy):
        raise TypeError("policy must be an OptimizationPolicy")
    from .py2mg import compile_python_to_mg
    if policy.backend == "c":
        from .py2c import compile_python_to_c
        from .c2mg import compile_c_to_mg
        mg = compile_c_to_mg(compile_python_to_c(source))
        plan = _target_plan(mg, policy, "c", "c", op_style, jmp_style)
    elif policy.backend == "ir":
        from .ir import require_ir_support, XDSL_VERSION
        require_ir_support()
        # Validate both explicit pipelines before invoking a frontend.
        from .ir.passes import validate_pass_names
        validate_pass_names(policy.passes)
        if policy.ir_frontend == "semantic":
            plan = _semantic_plan(source, policy, op_style, jmp_style)
        else:
            mg = compile_python_to_mg(source, arithmetic_optimizations=policy.arithmetic_optimizations)
            plan = _target_plan(mg, policy, "ir", "compat", op_style, jmp_style)
        _verify_ir_plan(plan, policy)
        plan.selection["xdsl_version"] = XDSL_VERSION
    else:
        mg = compile_python_to_mg(source, arithmetic_optimizations=policy.arithmetic_optimizations)
        plan = _target_plan(mg, policy, "direct", "direct", op_style, jmp_style)
        if policy.compete:
            from .mc2mb import predict_image_mb_size
            sizes = {"direct": predict_image_mb_size(plan.image)}
            selection = {"candidate_sizes": sizes, "selection_reason": "direct_only",
                         "skipped_semantic": None, "xdsl_version": None,
                         "candidate_semantic_passes": None,
                         "candidate_semantic_target_options": _semantic_target_options(policy.opt_level)}
            from .ir import require_ir_support, IRDependencyError, XDSL_VERSION
            try:
                require_ir_support()
            except IRDependencyError as exc:
                selection["skipped_semantic"] = {"reason": "unavailable", "detail": str(exc)}
            else:
                selection["xdsl_version"] = XDSL_VERSION
                selection["candidate_semantic_passes"] = list(_semantic_pass_names(policy))
                from .ir.frontend import SemanticFrontendError
                try:
                    semantic = _semantic_plan(source, policy, op_style, jmp_style)
                except SemanticFrontendError as exc:
                    selection["skipped_semantic"] = {"reason": "inapplicable", "detail": str(exc)}
                else:
                    selection["candidate_semantic_passes"] = semantic.selection["resolved_semantic_passes"]
                    sizes["semantic"] = predict_image_mb_size(semantic.image)
                    if sizes["semantic"] < sizes["direct"]:
                        plan = semantic
                        selection["selection_reason"] = "semantic_smaller"
                    elif sizes["semantic"] == sizes["direct"]:
                        selection["selection_reason"] = "direct_tie"
                    else:
                        selection["selection_reason"] = "direct_smaller"
            plan.selection.update(selection)
    plan.selection.setdefault("candidate_sizes", {})
    plan.selection.setdefault("selection_reason", "explicit_backend" if policy.requested_backend != "auto" else "level_direct")
    plan.selection.setdefault("skipped_semantic", None)
    plan.selection.setdefault("xdsl_version", None)
    return plan


__all__ = ["POLICY_VERSION", "OptimizationPolicy", "CompilationPlan",
           "resolve_optimization_policy", "build_compilation_plan"]
