"""Cross-check the bounded C correctness gate against both independent VMs."""

import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from malbolge.compiler.mc2mb import assemble_mc_to_mb
from malbolge.malbolge20 import run
from scripts import verify_mb_reference as gate


FIXTURES = Path(__file__).parent / "fixtures" / "nagoya"


def instructions(*opcodes):
    return "".join(next(chr(value) for value in range(33, 127)
                        if (value + index) % 94 == opcode)
                   for index, opcode in enumerate(opcodes))


def test_fetch_provisions_a_clean_directory_and_reuses_verified_files(tmp_path, monkeypatch):
    source = tmp_path / "reference" / "malbolge20.c"
    payloads = {"malbolge20.c": b"test source", "LICENSE": b"test MIT notice"}
    monkeypatch.setattr(gate, "SOURCE_SHA256", hashlib.sha256(payloads["malbolge20.c"]).hexdigest())
    monkeypatch.setattr(gate, "LICENSE_SHA256", hashlib.sha256(payloads["LICENSE"]).hexdigest())
    requested = []

    def download(url, timeout):
        assert timeout == 30
        assert url.startswith(gate.SOURCE_REPOSITORY + "/-/raw/" + gate.SOURCE_COMMIT + "/")
        requested.append(url)
        return io.BytesIO(payloads[url.rsplit("/", 1)[1]])

    monkeypatch.setattr(gate.urllib.request, "urlopen", download)
    manifest = gate.fetch_reference(source)
    assert source.read_bytes() == payloads["malbolge20.c"]
    assert source.with_name("LICENSE").read_bytes() == payloads["LICENSE"]
    assert manifest["commit"] == gate.SOURCE_COMMIT
    assert manifest["license"] == "MIT"
    assert len(requested) == 2
    assert gate.fetch_reference(source) == manifest
    assert len(requested) == 2


@pytest.mark.parametrize("bad_file", ("malbolge20.c", "LICENSE"))
def test_fetch_rejects_changed_downloads_before_writing(tmp_path, monkeypatch, bad_file):
    source = tmp_path / "reference" / "malbolge20.c"
    payloads = {"malbolge20.c": b"test source", "LICENSE": b"test MIT notice"}
    monkeypatch.setattr(gate, "SOURCE_SHA256", hashlib.sha256(payloads["malbolge20.c"]).hexdigest())
    monkeypatch.setattr(gate, "LICENSE_SHA256", hashlib.sha256(payloads["LICENSE"]).hexdigest())
    payloads[bad_file] += b"changed"
    monkeypatch.setattr(gate.urllib.request, "urlopen", lambda url, timeout:
                        io.BytesIO(payloads[url.rsplit("/", 1)[1]]))
    with pytest.raises(gate.ReferenceGateError, match="fingerprint"):
        gate.fetch_reference(source)
    assert not source.parent.exists()


def test_fetch_preserves_unknown_local_source(tmp_path, monkeypatch):
    source = tmp_path / "malbolge20.c"
    source.write_bytes(b"local changes")

    def unexpected_download(*args, **kwargs):
        pytest.fail("an unrecognized local source must be refused before downloading")

    monkeypatch.setattr(gate.urllib.request, "urlopen", unexpected_download)
    with pytest.raises(gate.ReferenceGateError, match="fingerprint"):
        gate.fetch_reference(source)
    assert source.read_bytes() == b"local changes"


@pytest.fixture(scope="module")
def references(tmp_path_factory):
    if not shutil.which("clang", path=gate._SAFE_PATH):
        pytest.skip("clang is unavailable")
    folder = tmp_path_factory.mktemp("mb-reference-gate")
    source_before = gate.DEFAULT_SOURCE.read_bytes()
    binary, manifest = gate.build_reference_gate(gate.DEFAULT_SOURCE, folder)
    original_binary = folder / "malbolge20-original"
    subprocess.run([manifest["compiler"], *gate._COMPILER_FLAGS,
                    str(gate.DEFAULT_SOURCE), "-lm", "-o", str(original_binary)],
                   check=True, capture_output=True, timeout=60,
                   env=gate._environment(folder))
    assert gate.DEFAULT_SOURCE.read_bytes() == source_before
    return folder, binary, original_binary, manifest


@pytest.mark.parametrize("name,input_bytes,expected,consumed", (
    ("mg_b_hi", b"", b"Hi", 0),
    ("mg_c_echo", b"Qunread", b"Q", 1),
    ("mg_d_repeat", b"", b"AAAA", 0),
    ("mg_e_call", b"", b"X", 0),
))
def test_compiled_fixtures_match_python_and_uninstrumented_reference(
        references, name, input_bytes, expected, consumed):
    folder, binary, original, _ = references
    source = assemble_mc_to_mb((FIXTURES / (name + ".mc")).read_text())
    image = folder / (name + ".mb")
    image.write_text(source)
    result = gate.verify_image(binary, image, input_bytes, expected, consumed,
                               3_000_000, 1024, 15)
    assert result["gate_pass"], result
    python = run(source, input_bytes, max_steps=3_000_000, max_output=1024,
                 eof="sentinel")
    assert python.stop_reason == "terminated"
    assert result["steps"] == python.steps
    assert result["input_consumed"] == python.input_consumed == consumed
    assert result["stdout_hex"] == python.output.hex() == expected.hex()
    assert result["registers"] == {"a": python.a, "c": python.c, "d": python.d}
    upstream = subprocess.run([str(original), str(image)], input=input_bytes,
                              capture_output=True, timeout=15, env=gate._environment())
    assert upstream.returncode == 0
    assert upstream.stdout == expected


@pytest.mark.parametrize("source,input_bytes,max_steps,max_output", (
    (instructions(81, 68), b"", 0, 8),
    (instructions(81, 68), b"", 1, 8),
    (instructions(23, 5, 81), b"Q", 1, 8),
    (instructions(23, 5, 81), b"Q", 3, 8),
    (instructions(23, 5, 81), b"", 3, 8),
    (instructions(23, 5, 81), b"\xff", 3, 8),
    (instructions(23, 5, 23, 5, 81), b"\x00\xfftail", 5, 8),
    (instructions(23, 5, 5, 81), b"Q", 20, 1),
    (instructions(23, 5, 81), b"Q", 20, 0),
    ("D'", b"", 20, 8),
    ("D'", b"", 2, 8),
))
def test_instruction_boundaries_eof_and_budgets_match_python(
        references, tmp_path, source, input_bytes, max_steps, max_output):
    _, binary, original, _ = references
    image = tmp_path / "instruction-case.mb"
    image.write_text(source)
    python = run(source, input_bytes, max_steps=max_steps, max_output=max_output,
                 eof="sentinel")
    result = gate.verify_image(binary, image, input_bytes, python.output,
                               python.input_consumed, max_steps, max_output, 10)
    expected_status = "error" if python.stop_reason == "invalid_instruction" else python.stop_reason
    assert result["status"] == expected_status
    assert result["steps"] == python.steps
    assert result["input_consumed"] == python.input_consumed
    assert result["output_count"] == python.output_count
    assert result["stdout_hex"] == python.output.hex()
    assert result["registers"] == {"a": python.a, "c": python.c, "d": python.d}
    assert result["gate_pass"] is (python.stop_reason == "terminated")
    if python.stop_reason == "terminated":
        upstream = subprocess.run([str(original), str(image)], input=input_bytes,
                                  capture_output=True, timeout=10, env=gate._environment())
        assert upstream.returncode == 0
        assert upstream.stdout == python.output


def test_gate_checks_exact_output_and_consumed_bytes(references, tmp_path):
    _, binary, _, _ = references
    image = tmp_path / "echo.mb"
    image.write_text(instructions(23, 5, 81))
    wrong_output = gate.verify_image(binary, image, b"Qtail", b"X", 1, 20, 8, 10)
    assert not wrong_output["gate_pass"]
    assert wrong_output["reason"] == "output_mismatch"
    wrong_consumed = gate.verify_image(binary, image, b"Qtail", b"Q", 5, 20, 8, 10)
    assert not wrong_consumed["gate_pass"]
    assert wrong_consumed["reason"] == "input_consumption_mismatch"


@pytest.mark.parametrize("source", ("", "D", "!!", "\x00\x00"))
def test_source_rejection_is_startup_error_with_no_target_metrics(references, tmp_path, source):
    _, binary, _, _ = references
    image = tmp_path / "bad.mb"
    image.write_text(source)
    result = gate.verify_image(binary, image, b"", b"", 0, 20, 8, 10)
    assert result["status"] == "startup_error"
    assert result["validation_status"] == "unvalidated"
    assert result["steps"] is result["registers"] is result["input_consumed"] is None
    assert not result["gate_pass"]
    assert result["stdout_hex"] == ""


def test_timeout_and_launch_failure_never_claim_target_counters(tmp_path, monkeypatch):
    image = tmp_path / "pending.mb"
    image.write_text(instructions(81, 68))

    def time_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"], output=b"partial", stderr=b"")

    with monkeypatch.context() as patch:
        patch.setattr(gate.subprocess, "run", time_out)
        result = gate.verify_image(tmp_path / "binary", image, b"", b"", 0, 20, 8, 0.01)
    assert result["status"] == "timeout"
    assert result["reason"] == "child_timeout"
    assert result["validation_status"] == "unvalidated"
    assert result["steps"] is result["registers"] is result["input_consumed"] is None
    result = gate.verify_image(tmp_path / "missing", image, b"", b"", 0, 20, 8, 1)
    assert result["status"] == "startup_error"
    assert result["reason"] == "reference_launch_error"
    assert result["steps"] is None


def test_manifest_fingerprints_source_instrumentation_binary_and_anchor_counts(references):
    _, binary, _, manifest = references
    assert manifest["source_sha256"] == gate.SOURCE_SHA256
    assert manifest["binary_sha256"] == hashlib.sha256(binary.read_bytes()).hexdigest()
    generated = Path(manifest["instrumented_source"]).read_bytes()
    assert manifest["instrumented_source_sha256"] == hashlib.sha256(generated).hexdigest()
    assert manifest["purpose"] == "correctness_only"
    assert manifest["performance_measurement"] is False
    assert "-D_POSIX_C_SOURCE=200809L" in manifest["compiler_flags"]
    assert manifest["insertion_anchor_counts"]["diagnostic_close"] == 10
    assert manifest["insertion_anchor_counts"]["halt"] == 1


def test_source_hash_and_anchor_changes_are_refused(tmp_path, monkeypatch):
    changed = gate.DEFAULT_SOURCE.read_bytes() + b"\n"
    source = tmp_path / "changed.c"
    source.write_bytes(changed)
    with pytest.raises(gate.ReferenceGateError, match="fingerprint"):
        gate.build_reference_gate(source, tmp_path / "build")
    changed = gate.DEFAULT_SOURCE.read_bytes().replace(b"case 'v':return;//HALT", b"case 'v':return;")
    monkeypatch.setattr(gate, "SOURCE_SHA256", hashlib.sha256(changed).hexdigest())
    with pytest.raises(gate.ReferenceGateError, match="anchor halt"):
        gate._instrument(changed)


@pytest.mark.parametrize("stderr", (
    "", gate.REPORT_PREFIX + "{}\n", gate.REPORT_PREFIX + "not-json\n",
    gate.REPORT_PREFIX + "{}\n" + gate.REPORT_PREFIX + "{}\n",
))
def test_missing_or_malformed_records_leave_target_unvalidated(tmp_path, monkeypatch, stderr):
    image = tmp_path / "image.mb"
    image.write_text(instructions(81, 68))
    monkeypatch.setattr(gate.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 0, b"", stderr.encode()))
    result = gate.verify_image(tmp_path / "binary", image, b"", b"", 0, 10, 8, 1)
    assert result["status"] == "error"
    assert result["validation_status"] == "unvalidated"
    assert not result["gate_pass"]
    assert result["steps"] is None


def test_subprocess_environment_omits_credentials_and_injection_hooks(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_TOKEN", "test-only-sensitive")
    monkeypatch.setenv("DYLD_INSERT_LIBRARIES", "/does/not/exist")
    assert gate._environment(tmp_path) == {
        "PATH": gate._SAFE_PATH, "LC_ALL": "C", "LANG": "C", "TMPDIR": str(tmp_path)}


def test_cli_verify_emits_json(references, tmp_path, capsys):
    _, binary, _, _ = references
    image = tmp_path / "halt.mb"
    image.write_text(instructions(81, 68))
    status = gate.main(["verify", "--binary", str(binary), "--image", str(image),
                        "--expected-output-hex", "", "--expected-consumed", "0",
                        "--max-steps", "1", "--max-output", "0", "--timeout", "10"])
    assert status == 0
    assert json.loads(capsys.readouterr().out)["gate_pass"] is True
