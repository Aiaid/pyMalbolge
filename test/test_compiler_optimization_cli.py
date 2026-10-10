"""User-visible optimization selection, output inference and cache integrity."""

import contextlib
import io
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from malbolge.compiler import cli, compile_python_to_c, compile_python_to_mg
from malbolge.compiler.ir import IRDependencyError, require_ir_support


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.py"
    path.write_text("putchar(65)\n")
    return path


def invoke(source, *arguments):
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        cli.main([str(source)] + list(map(str, arguments)))
    lines = stderr.getvalue().splitlines()
    report = json.loads(lines[-1]) if "--stats" in arguments else None
    return stdout.getvalue(), report


def error(source, *arguments):
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr), pytest.raises(SystemExit) as exc:
        cli.main([str(source)] + list(map(str, arguments)))
    assert exc.value.code == 1
    assert "Traceback" not in stderr.getvalue()
    return stderr.getvalue()


def test_default_o3_and_explicit_o3_have_identical_image_and_policy(source, tmp_path):
    default, explicit = tmp_path / "default.mb", tmp_path / "explicit.mb"
    _, first = invoke(source, "--no-cache", "--stats", "-o", default)
    _, second = invoke(source, "-O3", "--no-cache", "--stats", "-o", explicit)
    assert default.read_bytes() == explicit.read_bytes()
    assert first["optimization"] == second["optimization"]
    decision = first["optimization"]
    assert decision["requested_backend"] == "auto"
    assert decision["opt_level"] == 3
    assert decision["target_pipeline"] == "structured"
    assert decision["candidate_competition"] is True
    assert decision["backend_inferred"] is True
    assert decision["selected_backend"] == first["backend"]
    chosen = "semantic" if decision["selected_frontend"] == "semantic" else "direct"
    assert decision["candidate_sizes"][chosen] == len(default.read_bytes())
    assert first["stages"][0]["bootstrap_generated"] is False
    assert first["stages"][-1]["predicted_final_bytes"] == len(default.read_bytes())


def test_plain_default_compilation_emits_selected_mg(source):
    text, report = invoke(source, "--no-cache", "--stats")
    assert text and "DEF MAIN" in text and "OUTPUT" in text
    assert report["optimization"]["candidate_competition"] is True
    assert all(stage["stage"] != "mc2mb" for stage in report["stages"])


def test_global_o0_needs_no_ir_and_uses_reference_direct_frontend(source, monkeypatch):
    from malbolge.compiler import ir
    monkeypatch.setattr(ir, "require_ir_support", Mock(side_effect=AssertionError("IR was attempted")))
    text, report = invoke(source, "-O0", "--stats")
    assert text == compile_python_to_mg(source.read_text(), arithmetic_optimizations=False)
    assert report["backend"] == "direct"
    assert report["target_pipeline"] == "text"
    assert report["optimization"]["candidate_competition"] is False
    assert report["optimization"]["arithmetic_optimizations"] is False
    assert report["cache"]["mode"] == "disabled"
    assert not (source.parent / ".cache").exists()


@pytest.mark.parametrize("backend", ("c", "direct"))
def test_explicit_backend_and_text_handoff_lock_selection(source, tmp_path, backend):
    output = tmp_path / (backend + ".mb")
    _, report = invoke(source, "--backend", backend, "--target-pipeline=text",
                       "--no-cache", "--stats", "-o", output)
    assert report["backend"] == backend
    assert report["target_pipeline"] == "text"
    assert report["optimization"]["requested_backend"] == backend
    assert report["optimization"]["candidate_competition"] is False
    assert report["optimization"]["backend_inferred"] is False
    assert "optimization-selection" not in [stage["stage"] for stage in report["stages"]]


def test_emit_c_infers_c_and_explicit_auto_conflict_preserves_output(source, tmp_path):
    output = tmp_path / "source.c"
    _, report = invoke(source, "--emit-c", output, "--no-cache", "--stats")
    expected = compile_python_to_c(source.read_text())
    assert output.read_text() == expected
    assert report["backend"] == "c" and report["optimization"]["backend_inferred"] is True
    assert "requires --backend=c" in error(source, "--backend=auto", "--emit-c", output)
    assert output.read_text() == expected


def test_semantic_output_infers_ir_and_o0_inspection_stays_semantic(source, tmp_path):
    try:
        require_ir_support()
    except IRDependencyError as exc:
        pytest.skip(str(exc))
    output = tmp_path / "source.mlir"
    _, report = invoke(source, "--emit-semantic-ir", output, "-O0", "--stats")
    assert "pysem." in output.read_text()
    assert report["backend"] == "ir" and report["ir_frontend"] == "semantic"
    assert report["semantic_ir"]["passes"] == ["verify-semantic"]
    assert report["optimization"]["backend_inferred"] is True


def test_unavailable_optional_ir_is_declared_in_auto_stats(source, tmp_path, monkeypatch):
    from malbolge.compiler import ir
    monkeypatch.setattr(ir, "require_ir_support", Mock(side_effect=IRDependencyError("test IR unavailable")))
    _, report = invoke(source, "--stats", "--no-cache", "-o", tmp_path / "output.mb")
    decision = report["optimization"]
    assert decision["selected_backend"] == "direct"
    assert decision["skipped_semantic"] == {"reason": "unavailable", "detail": "test IR unavailable"}
    assert decision["xdsl_version"] is None
    assert set(decision["candidate_sizes"]) == {"direct"}


def test_mg_only_output_never_generates_bootstrap(source, tmp_path, monkeypatch):
    from malbolge.compiler import mc2mb
    forbidden = Mock(side_effect=AssertionError("bootstrap generated for MG inspection"))
    monkeypatch.setattr(mc2mb, "iter_image_to_mb", forbidden)
    monkeypatch.setattr(cli, "iter_mc_to_mb", forbidden)
    monkeypatch.setattr(cli, "iter_lal_to_mb", forbidden)
    output = tmp_path / "source.mg"
    _, report = invoke(source, "--emit-mg", output, "--stats", "--no-cache")
    assert output.read_text() and "OUTPUT" in output.read_text()
    assert report["stages"][0]["bootstrap_generated"] is False
    forbidden.assert_not_called()


def test_automatic_cache_reuses_image_and_preserves_policy_provenance(source, tmp_path, monkeypatch):
    from malbolge.compiler import mc2mb
    output = tmp_path / "output.mb"
    _, first = invoke(source, "--stats", "-o", output)
    original = output.read_bytes()
    cache = source.parent / ".cache" / "malbolge"
    assert first["cache"]["mode"] == "automatic"
    assert Path(first["cache"]["directory"]) == cache
    manifests = list(cache.glob("*/manifest.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text())
    assert manifest["optimization"] == first["optimization"]
    assert manifest["mb"]["bytes"] == len(original)
    monkeypatch.setattr(mc2mb, "iter_image_to_mb", Mock(side_effect=AssertionError("cached image regenerated")))
    _, second = invoke(source, "--stats", "-o", output)
    assert output.read_bytes() == original
    assert second["stages"][-1]["cache_hit"] is True
    assert second["optimization"] == first["optimization"]


def test_no_cache_disables_default_project_persistence(source, tmp_path):
    output = tmp_path / "output.mb"
    for _ in range(2):
        _, report = invoke(source, "--stats", "--no-cache", "-o", output)
        assert report["cache"]["mode"] == "disabled"
        assert report["stages"][-1]["cache_hit"] is False
    assert not (source.parent / ".cache").exists()


def test_explicit_cache_keys_source_and_declared_handoff(source, tmp_path):
    cache, output = tmp_path / "chosen-cache", tmp_path / "output.mb"
    _, first = invoke(source, "--stats", "--cache-dir", cache, "-o", output)
    initial = output.read_bytes()
    assert first["cache"]["mode"] == "explicit"
    _, text = invoke(source, "--stats", "--cache-dir", cache, "--target-pipeline=text", "-o", output)
    assert output.read_bytes() == initial
    assert text["stages"][-1]["cache_hit"] is False
    assert len(list(cache.glob("*/manifest.json"))) == 2
    source.write_text("putchar(66)\n")
    _, changed = invoke(source, "--stats", "--cache-dir", cache, "-o", output)
    assert changed["stages"][-1]["cache_hit"] is False
    assert output.read_bytes() != initial
    assert len(list(cache.glob("*/manifest.json"))) == 3
    assert not (source.parent / ".cache").exists()


@pytest.mark.parametrize("corruption", ("image", "provenance"))
def test_cache_corruption_is_rebuilt_without_trusting_stale_provenance(source, tmp_path, corruption):
    output = tmp_path / "output.mb"
    _, first = invoke(source, "--stats", "-o", output)
    original = output.read_bytes()
    manifest_path = next((source.parent / ".cache" / "malbolge").glob("*/manifest.json"))
    if corruption == "image":
        manifest_path.with_name("program.mb").write_bytes(b"corrupt")
    else:
        manifest = json.loads(manifest_path.read_text())
        manifest["optimization"]["selection_reason"] = "forged decision"
        manifest_path.write_text(json.dumps(manifest))
    _, rebuilt = invoke(source, "--stats", "-o", output)
    assert rebuilt["stages"][-1]["cache_hit"] is False
    assert rebuilt["optimization"] == first["optimization"]
    assert output.read_bytes() == original
    assert json.loads(manifest_path.read_text())["optimization"] == first["optimization"]


def test_automatic_cache_artifact_limit_keeps_compilation_available(source, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "AUTO_CACHE_ARTIFACT_LIMIT", 10)
    output = tmp_path / "output.mb"
    _, report = invoke(source, "--stats", "-o", output)
    assert output.stat().st_size > 10
    assert report["cache"]["max_artifact_bytes"] == 10
    assert not list((source.parent / ".cache" / "malbolge").glob("*/program.mb"))


@pytest.mark.parametrize("failure", ("directory", "image", "manifest"))
@pytest.mark.parametrize("mode", ("automatic", "explicit"))
def test_cache_only_io_failures_preserve_output_contract_and_never_repeat_bootstrap(
        source, tmp_path, monkeypatch, failure, mode):
    from malbolge.compiler import mc2mb
    output = tmp_path / "output.mb"
    previous = b"previous usable output"
    output.write_bytes(previous)
    reference = tmp_path / "reference.mb"
    if mode == "automatic":
        invoke(source, "--no-cache", "-o", reference)
    cache_dir = (source.parent / ".cache" / "malbolge" if mode == "automatic"
                 else tmp_path / "explicit-cache")
    mkdir = Path.mkdir
    atomic_write = cli._atomic_write
    failures = []

    def is_cache_path(path):
        try:
            Path(path).relative_to(cache_dir)
        except ValueError:
            return False
        return True

    def fail_cache_directory(path, *args, **kwargs):
        if failure == "directory" and is_cache_path(path):
            failures.append("directory")
            raise PermissionError("simulated cache directory failure")
        return mkdir(path, *args, **kwargs)

    def fail_cache_write(path, chunks):
        path = Path(path)
        if is_cache_path(path):
            if failure == "image" and path.name == "program.mb":
                failures.append("image")
                raise OSError("simulated cache image failure")
            if failure == "manifest" and path.name == "manifest.json":
                chunks = tuple(chunks)
                payload = json.loads(b"".join(chunks))
                # Allow earlier MG provenance to be written normally. Fail only
                # the final image's manifest update, after real MB generation.
                if "mb" in payload:
                    failures.append("manifest")
                    raise OSError("simulated cache manifest failure")
        return atomic_write(path, chunks)

    monkeypatch.setattr(Path, "mkdir", fail_cache_directory)
    monkeypatch.setattr(cli, "_atomic_write", fail_cache_write)
    bootstrap = Mock(wraps=mc2mb.iter_image_to_mb)
    monkeypatch.setattr(mc2mb, "iter_image_to_mb", bootstrap)
    arguments = ("--stats", "-o", output)
    if mode == "explicit":
        arguments += ("--cache-dir", cache_dir)
        message = error(source, *arguments)
        assert "file I/O failed" in message and "simulated cache" in message
        assert output.read_bytes() == previous
        assert bootstrap.call_count == (0 if failure == "directory" else 1)
    else:
        _, report = invoke(source, *arguments)
        assert output.read_bytes() == reference.read_bytes()
        assert bootstrap.call_count == 1
        assert report["stages"][-1]["bytes"] == output.stat().st_size
        assert report["stages"][-1]["cache_hit"] is False
        if failure == "directory":
            assert report["cache"]["mode"] == "unavailable"
            assert "simulated cache directory failure" in report["cache"]["reason"]
        else:
            assert report["cache"]["mode"] == "automatic"
    assert failures == [failure]
    if failure != "directory":
        manifest = next(cache_dir.glob("*/manifest.json"))
        assert "mb" not in json.loads(manifest.read_text())


@pytest.mark.parametrize("backend", ("auto", "direct"))
def test_automatic_cache_copy_read_failure_preserves_completed_mb_without_regeneration(
        source, tmp_path, monkeypatch, backend):
    import builtins
    from malbolge.compiler import mc2mb
    output, reference = tmp_path / "output.mb", tmp_path / "reference.mb"
    arguments = () if backend == "auto" else ("--backend=direct",)
    invoke(source, *arguments, "--no-cache", "-o", reference)
    output.write_bytes(b"previous output")
    open_file = builtins.open
    initialize = mc2mb._Assembler.memory_init_image
    failed_reads, bootstraps = [], []

    def cache_copy_open(path, mode="r", *args, **kwargs):
        if Path(path) == output and mode == "rb":
            failed_reads.append("open")
            raise PermissionError("simulated automatic cache-copy read failure")
        return open_file(path, mode, *args, **kwargs)

    def initialize_once(assembler, image):
        bootstraps.append(image)
        return initialize(assembler, image)

    with monkeypatch.context() as context:
        context.setattr(builtins, "open", cache_copy_open)
        context.setattr(mc2mb._Assembler, "memory_init_image", initialize_once)
        _, report = invoke(source, *arguments, "--stats", "-o", output)
    assert output.read_bytes() == reference.read_bytes()
    assert failed_reads == ["open"]
    assert len(bootstraps) == 1
    assert report["cache"]["mode"] == "automatic"
    assert report["stages"][-1]["cache_hit"] is False
    assert report["stages"][-1]["bytes"] == output.stat().st_size
    manifest = next((source.parent / ".cache" / "malbolge").glob("*/manifest.json"))
    assert "mb" not in json.loads(manifest.read_text())
