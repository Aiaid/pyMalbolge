"""Shared default policy, explicit optouts and bounded automatic selection."""

import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest

from malbolge import compiler
from malbolge.compiler import optimization
from malbolge.compiler.ir import IRDependencyError, require_ir_support
from malbolge.malbolge20 import run


SOURCE = "putchar(65)\n"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ir_environment():
    try:
        require_ir_support()
    except IRDependencyError as exc:
        pytest.skip(str(exc))


@pytest.mark.parametrize("level,backend,pipeline,arithmetic,compete", (
    (0, "direct", "text", False, False),
    (1, "direct", "text", True, False),
    (2, "direct", "structured", True, False),
    (3, "auto", "structured", True, True),
))
def test_levels_select_only_accepted_facilities(level, backend, pipeline, arithmetic, compete):
    policy = compiler.resolve_optimization_policy(opt_level=level)
    assert (policy.backend, policy.target_pipeline, policy.arithmetic_optimizations,
            policy.compete) == (backend, pipeline, arithmetic, compete)


@pytest.mark.parametrize("backend", ("c", "direct", "ir"))
@pytest.mark.parametrize("pipeline", ("text", "structured"))
def test_explicit_backend_and_handoff_stay_authoritative(backend, pipeline):
    policy = compiler.resolve_optimization_policy(backend, target_pipeline=pipeline)
    assert policy.backend == backend
    assert policy.target_pipeline == pipeline
    assert not policy.compete


def test_explicit_ir_frontend_profiles_and_semantic_pass_override():
    assert compiler.resolve_optimization_policy("ir", opt_level=0).ir_frontend == "semantic"
    assert compiler.resolve_optimization_policy("ir").ir_frontend == "semantic"
    assert compiler.resolve_optimization_policy("ir", ir_frontend="compat").ir_frontend == "compat"
    policy = compiler.resolve_optimization_policy(semantic_passes=())
    assert policy.backend == "ir" and policy.ir_frontend == "semantic"
    assert policy.semantic_passes == () and not policy.compete
    assert compiler.resolve_optimization_policy(ir_frontend="semantic", opt_level=0).backend == "ir"


@pytest.mark.parametrize("options,error", (
    ({"opt_level": True}, "opt_level"),
    ({"opt_level": 4}, "opt_level"),
    ({"backend": "unknown"}, "unknown backend"),
    ({"target_pipeline": "unknown"}, "target_pipeline"),
    ({"backend": "direct", "ir_frontend": "semantic"}, "requires backend"),
    ({"passes": ("verify-lal",)}, "only available"),
    ({"backend": "ir", "ir_frontend": "compat", "semantic_passes": ()}, "require the semantic"),
    ({"semantic_passes": "verify-semantic"}, "sequence"),
))
def test_invalid_choices_fail_before_frontend(monkeypatch, options, error):
    frontend = Mock(side_effect=AssertionError("frontend ran"))
    monkeypatch.setattr(optimization, "_target_plan", frontend)
    with pytest.raises(ValueError, match=error):
        compiler.compile_python_to_mb("invalid input", **options)
    frontend.assert_not_called()


def test_import_and_policy_resolution_do_not_import_xdsl():
    script = """
import sys
class RejectXDSL:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'xdsl' or fullname.startswith('xdsl.'):
            raise AssertionError('optional framework loaded during policy resolution')
sys.meta_path.insert(0, RejectXDSL())
from malbolge.compiler import resolve_optimization_policy
for backend in ('auto', 'c', 'direct', 'ir'):
    for level in range(4):
        resolve_optimization_policy(backend, opt_level=level)
assert not any(m == 'xdsl' or m.startswith('xdsl.') for m in sys.modules)
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT,
                            capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr.decode()


def test_auto_unavailable_ir_preserves_direct_and_never_installs(monkeypatch):
    from malbolge.compiler import ir
    def unavailable():
        raise IRDependencyError("missing optional IR environment")
    monkeypatch.setattr(ir, "require_ir_support", unavailable)
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=AssertionError("external installer ran")))
    plan = compiler.build_compilation_plan(SOURCE, compiler.resolve_optimization_policy())
    assert plan.selected_backend == "direct"
    assert plan.selection["skipped_semantic"] == {
        "reason": "unavailable", "detail": "missing optional IR environment"}
    assert plan.selection["xdsl_version"] is None
    assert plan.selection["candidate_semantic_passes"] is None
    with pytest.raises(IRDependencyError):
        compiler.build_compilation_plan(SOURCE, compiler.resolve_optimization_policy("ir"))
    with pytest.raises(IRDependencyError):
        compiler.build_compilation_plan(SOURCE, compiler.resolve_optimization_policy(ir_frontend="semantic"))


def test_semantic_frontend_applicability_is_the_only_source_fallback(monkeypatch, ir_environment):
    from malbolge.compiler.ir.frontend import SemanticFrontendError
    from malbolge.compiler.ir import semantic_passes
    monkeypatch.setattr(semantic_passes, "compile_python_semantic_result",
                        Mock(side_effect=SemanticFrontendError("inapplicable candidate")))
    plan = compiler.build_compilation_plan(SOURCE, compiler.resolve_optimization_policy())
    assert plan.selected_backend == "direct"
    assert plan.selection["skipped_semantic"]["reason"] == "inapplicable"
    from malbolge.compiler.ir.semantic_passes import DEFAULT_SEMANTIC_PASSES
    assert plan.metadata()["candidate_semantic_passes"] == list(DEFAULT_SEMANTIC_PASSES)
    with pytest.raises(SemanticFrontendError):
        compiler.build_compilation_plan(SOURCE, compiler.resolve_optimization_policy("ir"))


@pytest.mark.parametrize("error_kind", ("lowering", "pipeline", "layout"))
def test_optional_candidate_defects_are_not_hidden(monkeypatch, ir_environment, error_kind):
    from malbolge.compiler.ir import lowering, semantic_passes
    from malbolge.compiler.ir.passes import PipelineError
    from malbolge.compiler.mc2mb import Mc2MbError
    if error_kind == "lowering":
        error = lowering.SemanticLoweringError("lowering defect")
        monkeypatch.setattr(lowering, "lower_semantic_to_mg", Mock(side_effect=error))
    elif error_kind == "pipeline":
        error = PipelineError("verification defect")
        monkeypatch.setattr(semantic_passes, "compile_python_semantic_result", Mock(side_effect=error))
    else:
        error = Mc2MbError("layout defect")
        original = optimization._target_plan
        def target(*args, **kwargs):
            if kwargs.get("semantic_result") is not None:
                raise error
            return original(*args, **kwargs)
        monkeypatch.setattr(optimization, "_target_plan", target)
    with pytest.raises(type(error), match="defect"):
        compiler.build_compilation_plan(SOURCE, compiler.resolve_optimization_policy())


@pytest.mark.parametrize("sizes,backend,reason", (
    ((10, 10), "direct", "direct_tie"),
    ((10, 11), "direct", "direct_smaller"),
    ((10, 9), "ir", "semantic_smaller"),
))
def test_competition_preserves_winner_and_builds_only_its_bootstrap(
        monkeypatch, ir_environment, sizes, backend, reason):
    from malbolge.compiler import mc2mb
    predictor = Mock(side_effect=sizes)
    assembler = Mock(return_value="winning image")
    monkeypatch.setattr(mc2mb, "predict_image_mb_size", predictor)
    monkeypatch.setattr(mc2mb, "image_to_mb", assembler)
    plan = compiler.build_compilation_plan(SOURCE, compiler.resolve_optimization_policy())
    assert plan.selected_backend == backend
    assert plan.selection["selection_reason"] == reason
    assert plan.selection["candidate_sizes"] == {"direct": sizes[0], "semantic": sizes[1]}
    assert (plan.semantic_result is not None) == (backend == "ir")
    assert plan.mg and plan.lal is not None and plan.image is not None
    assembler.assert_not_called()
    assert plan.to_mb() == "winning image"
    assembler.assert_called_once_with(plan.image)
    report = json.loads(json.dumps(plan.metadata()))
    assert report["policy_version"] == compiler.POLICY_VERSION
    assert report["requested_backend"] == "auto"
    assert report["selected_backend"] == backend
    assert report["selected_frontend"] == ("semantic" if backend == "ir" else "direct")
    assert report["xdsl_version"] == "0.69.0"
    # Auto describes the direct candidate's enabled shortcuts even when the
    # semantic candidate wins. Its named profile is recorded independently.
    assert report["arithmetic_optimizations"] is True
    assert report["direct_frontend_arithmetic_optimizations"] is True
    from malbolge.compiler.ir.semantic_passes import DEFAULT_SEMANTIC_PASSES
    assert report["candidate_semantic_passes"] == list(DEFAULT_SEMANTIC_PASSES)
    assert report["candidate_semantic_target_options"] == {
        "skip_generated_initialization": True, "structured_while": True,
        "native_conditions": True}


def test_o0_semantic_disables_all_target_shortcuts(monkeypatch, ir_environment):
    from malbolge.compiler.ir import lowering
    adapter = Mock(wraps=lowering.lower_semantic_to_mg)
    monkeypatch.setattr(lowering, "lower_semantic_to_mg", adapter)
    plan = compiler.build_compilation_plan(
        SOURCE, compiler.resolve_optimization_policy("ir", opt_level=0, ir_frontend="semantic"))
    assert [report.name for report in plan.semantic_result.reports] == ["verify-semantic"]
    assert adapter.call_args.kwargs == {
        "arithmetic_optimizations": False, "skip_generated_initialization": False,
        "structured_while": False, "native_conditions": False}


def test_accepted_profile_excludes_decimal_and_explicit_empty_profile_is_exact(ir_environment):
    from malbolge.compiler.ir.semantic_passes import DEFAULT_SEMANTIC_PASSES
    optimized = compiler.build_compilation_plan(SOURCE, compiler.resolve_optimization_policy("ir"))
    assert [r.name for r in optimized.semantic_result.reports] == list(DEFAULT_SEMANTIC_PASSES)
    assert "lower-decimal-output" not in DEFAULT_SEMANTIC_PASSES
    explicit = compiler.build_compilation_plan(
        SOURCE, compiler.resolve_optimization_policy("ir", semantic_passes=()))
    assert explicit.semantic_result.reports == ()


def test_default_api_runs_and_text_override_preserves_image(monkeypatch):
    from malbolge.compiler import ir
    def unavailable():
        raise IRDependencyError("optional test environment disabled")
    monkeypatch.setattr(ir, "require_ir_support", unavailable)
    structured = compiler.compile_python_to_mb(SOURCE)
    text = compiler.compile_python_to_mb(SOURCE, target_pipeline="text")
    assert structured == text
    result = run(structured, engine="python", max_steps=1_000_000, max_output=4)
    assert (result.stop_reason, result.output) == ("terminated", b"A")


def test_o0_direct_disables_arithmetic_in_actual_frontend(monkeypatch):
    from malbolge.compiler import py2mg
    frontend = Mock(wraps=py2mg.compile_python_to_mg)
    monkeypatch.setattr(py2mg, "compile_python_to_mg", frontend)
    source = "n = getchar()\nputchar(n * 2)\n"
    reference = compiler.build_compilation_plan(source, compiler.resolve_optimization_policy(opt_level=0))
    optimized = compiler.build_compilation_plan(source, compiler.resolve_optimization_policy(opt_level=1))
    assert [call.kwargs["arithmetic_optimizations"] for call in frontend.call_args_list] == [False, True]
    assert reference.mg != optimized.mg


@pytest.mark.parametrize("level", range(4))
def test_explicit_ir_default_frontend_matches_cli_at_every_level(tmp_path, ir_environment, level):
    import contextlib
    import io
    from malbolge.compiler import cli
    source = tmp_path / "source.py"
    target = tmp_path / "source.mg"
    source.write_text(SOURCE)
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        cli.main([str(source), "--backend=ir", "-O", str(level), "--no-cache",
                  "--emit-mg", str(target), "--stats"])
    report = json.loads(stderr.getvalue().splitlines()[-1])
    plan = compiler.build_compilation_plan(SOURCE, compiler.resolve_optimization_policy("ir", opt_level=level))
    assert plan.frontend == report["ir_frontend"] == "semantic"
    assert target.read_text() == plan.mg
    assert plan.metadata()["resolved_semantic_passes"] == report["semantic_ir"]["passes"]
    assert plan.metadata()["semantic_target_options"] == {
        "skip_generated_initialization": level > 0,
        "structured_while": level > 0, "native_conditions": level > 0}


def test_o0_explicit_compat_remains_a_distinct_frontend(ir_environment):
    plan = compiler.build_compilation_plan(
        SOURCE, compiler.resolve_optimization_policy("ir", opt_level=0, ir_frontend="compat"))
    assert plan.frontend == "compat" and plan.semantic_result is None
    assert plan.mg == compiler.compile_python_to_mg(SOURCE, arithmetic_optimizations=False)
    assert plan.metadata()["semantic_target_options"] is None


def test_o0_explicit_ir_library_and_cli_preserve_frontend_error_callbacks(
        monkeypatch, tmp_path, ir_environment):
    import contextlib
    import io
    from malbolge.compiler import cli
    from malbolge.compiler.ir import frontend
    source, output = tmp_path / "source.py", tmp_path / "last-good.mg"
    source.write_text(SOURCE)
    output.write_text("last good artifact")
    failure = frontend.SemanticFrontendError("same semantic source rejection")
    monkeypatch.setattr(frontend, "compile_python_to_semantic_ir", Mock(side_effect=failure))
    with pytest.raises(frontend.SemanticFrontendError, match="same semantic source rejection"):
        compiler.compile_python_to_mb(SOURCE, "ir", opt_level=0)
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr), pytest.raises(SystemExit) as error:
        cli.main([str(source), "--backend=ir", "-O0", "--no-cache", "--emit-mg", str(output)])
    assert error.value.code == 1
    assert "same semantic source rejection" in stderr.getvalue()
    assert "Traceback" not in stderr.getvalue()
    assert output.read_text() == "last good artifact"


def test_c_o0_metadata_reports_reference_intrinsics_and_exact_legacy_transform(tmp_path):
    source = "n = getchar()\nputchar(n // 1)\nputchar(n % 1)\nputchar(n * 2)\n"
    reference_c = compiler.compile_python_to_c(source)
    assert "putchar(n);" in reference_c and "putchar(0);" in reference_c
    assert "n + n" in reference_c
    assert not any(helper in reference_c for helper in ("zzdiv", "zzmod", "zzmul"))
    expected_mg = compiler.compile_c_to_mg(reference_c)
    raw = compiler.build_compilation_plan(source, compiler.resolve_optimization_policy("c", opt_level=0))
    optimized = compiler.build_compilation_plan(source, compiler.resolve_optimization_policy("c", opt_level=3))
    assert raw.mg == optimized.mg == expected_mg
    metadata = raw.metadata()
    assert metadata["opt_level"] == 0
    assert metadata["arithmetic_optimizations"] is True
    assert metadata["arithmetic_optimization_scope"] == "c_reference_intrinsics"
    assert metadata["c_reference_intrinsics"] is True

    import contextlib
    import io
    from malbolge.compiler import cli
    source_path, output = tmp_path / "source.py", tmp_path / "source.c"
    source_path.write_text(source)
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        cli.main([str(source_path), "--backend=c", "-O0", "--no-cache",
                  "--emit-c", str(output), "--stats"])
    report = json.loads(stderr.getvalue().splitlines()[-1])["optimization"]
    assert output.read_text() == reference_c
    assert report["arithmetic_optimizations"] is True
    assert report["arithmetic_optimization_scope"] == "c_reference_intrinsics"


@pytest.mark.parametrize("level", (0, 3))
def test_explicit_semantic_provenance_matches_disabled_direct_lowering(
        monkeypatch, ir_environment, level):
    from malbolge.compiler.ir import lowering
    from malbolge.compiler.ir.semantic_passes import DEFAULT_SEMANTIC_PASSES
    adapter = Mock(wraps=lowering.lower_semantic_to_mg)
    monkeypatch.setattr(lowering, "lower_semantic_to_mg", adapter)
    plan = compiler.build_compilation_plan(
        SOURCE, compiler.resolve_optimization_policy("ir", opt_level=level))
    report = plan.metadata()
    assert adapter.call_args.kwargs["arithmetic_optimizations"] is False
    assert report["arithmetic_optimizations"] is False
    assert report["direct_frontend_arithmetic_optimizations"] is False
    assert report["arithmetic_optimization_scope"] == "semantic_named_passes"
    expected = ["verify-semantic"] if level == 0 else list(DEFAULT_SEMANTIC_PASSES)
    assert report["resolved_semantic_passes"] == expected
