"""Fast synthetic subprocess tests; no compiler, Malbolge VM or corpus run."""

import copy
import json
from pathlib import Path
import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest

from scripts import benchmark_fixed_vm as fixed


@pytest.fixture
def setup_runner(tmp_path, monkeypatch):
    # The native shell executes tiny synthetic fixture images; production pins
    # remain fixed and tests never invoke the real VM or compile an artifact.
    binary = Path("/bin/sh").resolve()
    source = tmp_path / "synthetic-source.c"
    source.write_bytes(b"synthetic native fixture, not a Malbolge reference")
    monkeypatch.setattr(fixed, "SOURCE_SHA256", fixed.digest_file(source))
    monkeypatch.setattr(fixed, "BINARY_SHA256", fixed.digest_file(binary))
    manifest = {"source": str(source), "source_sha256": fixed.SOURCE_SHA256,
                "binary": str(binary), "binary_sha256": fixed.BINARY_SHA256,
                "instrumented": False, "compiler": "synthetic test fixture",
                "compiler_version": "synthetic 1", "compiler_flags": ["-O3"],
                "build_provenance": "synthetic fixture pins, no compiler invocation"}
    runner = fixed.FixedVMRunner(binary, manifest)

    def case(script, stdin=b"", stdout=b"", consumed=None):
        image = tmp_path / "program.mb"
        image.write_bytes(script.encode("ascii"))
        image_record = {"bytes": image.stat().st_size, "sha256": fixed.digest_file(image)}
        if consumed is None:
            consumed = len(stdin)
        reference = {"source_sha256": fixed.SOURCE_SHA256, "purpose": "correctness_only",
                     "performance_measurement": False, "binary": "/synthetic/gate",
                     "binary_sha256": "e" * 64}
        gate = {"gate_pass": True, "validation_status": "passed", "instrumented_reference": True,
                "performance_measurement": False, "normal_halt": True, "status": "terminated",
                "stop_reason": "halt", "returncode": 0, "output_matches": True,
                "input_consumption_matches": True, "image_sha256": image_record["sha256"],
                "reference_binary": reference["binary"], "stdin_hex": stdin.hex(),
                "expected_output_hex": stdout.hex(), "stdout_hex": stdout.hex(),
                "expected_consumed": consumed, "input_consumed": consumed,
                "output_count": len(stdout), "steps": 1}
        contract = {"provenance": {"oracle": "synthetic test fixture", "source_sha256": "d" * 64},
                    "stdin_hex": stdin.hex(), "expected_stdout_hex": stdout.hex(),
                    "expected_input_consumed": consumed}
        return image, fixed.accepted_receipt(image_record, gate, reference, contract)

    return runner, case


def assert_no_complete_metrics(result):
    assert result["complete"] is False
    for name in ("whole_child_wall_seconds", "whole_child_cpu_seconds",
                 "whole_child_cpu_user_seconds", "whole_child_cpu_system_seconds"):
        assert result[name] is None
    assert not any(key in result for key in ("steps", "input_consumed", "vm_wall_seconds",
                                            "vm_cpu_seconds", "steps_per_second"))


def test_success_preserves_exact_bytes_and_records_real_clock_scope(setup_runner, monkeypatch):
    runner, case = setup_runner
    stdin = b"\x00\xfftail\n"
    image, receipt = case("exec /bin/cat\n", stdin, stdin)
    monkeypatch.setenv("SECRET_TOKEN", "test-only")
    monkeypatch.setenv("DYLD_INSERT_LIBRARIES", "/bad/injection")
    result = runner.measure(image, stdin, stdin, receipt, 2)
    assert result["complete"] and result["status"] == "passed"
    assert result["stdout_hex"] == stdin.hex()
    assert result["stderr_hex"] == ""
    assert result["argv"] == [str(runner.binary), str(image)]
    assert result["environment"] == fixed.ENVIRONMENT
    assert result["cwd"] == str(runner.binary.parent)
    assert result["whole_child_wall_seconds"] >= 0
    assert result["whole_child_cpu_seconds"] == pytest.approx(
        result["whole_child_cpu_user_seconds"] + result["whole_child_cpu_system_seconds"])
    assert result["clock_scope"]["vm_only_time_available"] is False
    assert "wait4" in result["clock_scope"]["cpu"]
    assert result["partial_diagnostics"] is None
    assert result["accepted_receipt"] == receipt
    assert json.loads(json.dumps(result)) == result


@pytest.mark.parametrize("script,reason,returncode", (
    ("printf wrong\n", "output_mismatch", 0),
    ("printf partial; printf '\\000\\377' >&2; exit 7\n", "child_exit_failure", 7),
))
def test_wrong_output_and_exit_failures_have_diagnostics_only(setup_runner, script, reason, returncode):
    runner, case = setup_runner
    image, receipt = case(script, stdout=b"expected")
    result = runner.measure(image, b"", b"expected", receipt, 2)
    assert result["reason"] == reason
    assert result["returncode"] == returncode
    assert bytes.fromhex(result["stdout_hex"]) in (b"wrong", b"partial")
    if returncode:
        assert bytes.fromhex(result["stderr_hex"]) == b"\x00\xff"
    assert result["partial_diagnostics"]["observed_wall_seconds"] >= 0
    assert_no_complete_metrics(result)


def test_timeout_retains_partial_output_and_does_not_touch_other_processes(setup_runner):
    runner, case = setup_runner
    image, receipt = case("printf partial; exec /bin/sleep 5\n")
    unrelated = subprocess.Popen(["/bin/sleep", "5"], start_new_session=True)
    try:
        result = runner.measure(image, b"", b"", receipt, 0.1)
        assert result["status"] == "timeout"
        assert result["reason"] == "child_timeout"
        assert result["stdout_hex"] == b"partial".hex()
        assert result["returncode"] == -9
        assert result["partial_diagnostics"]["observed_wall_seconds"] < 2
        assert unrelated.poll() is None
        assert_no_complete_metrics(result)
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=2)


@pytest.mark.parametrize("script,expected_reason", (
    ("exec /usr/bin/yes x\n", "stdout_capture_limit"),
    ("exec /usr/bin/yes x >&2\n", "stderr_capture_limit"),
))
def test_capture_caps_bound_native_output(setup_runner, script, expected_reason):
    runner, case = setup_runner
    image, receipt = case(script)
    result = runner.measure(image, b"", b"", receipt, 2, output_cap=16, stderr_cap=32)
    assert result["reason"] == expected_reason
    assert len(bytes.fromhex(result["stdout_hex"])) <= 16
    assert len(bytes.fromhex(result["stderr_hex"])) <= 32
    assert_no_complete_metrics(result)


@pytest.mark.parametrize("change,message", (
    (lambda receipt: receipt["gate"].update(gate_pass=False), "accepted independent"),
    (lambda receipt: receipt["gate"].update(normal_halt=False), "accepted independent"),
    (lambda receipt: receipt["gate"].update(stdin_hex="78"), "input bytes"),
    (lambda receipt: receipt["gate"].update(input_consumed=1), "expected contract"),
    (lambda receipt: receipt["gate"].update(stdout_hex="78"), "expected contract"),
    (lambda receipt: receipt["contract"].pop("provenance"), "provenance"),
    (lambda receipt: receipt["reference"].update(source_sha256="0" * 64), "reference provenance"),
    (lambda receipt: receipt["image"].update(sha256="0" * 64), "gate and accepted"),
    (lambda receipt: receipt["image"].update(bytes=0), "full-image"),
))
def test_bad_acceptance_or_contract_is_rejected_before_child_start(setup_runner, monkeypatch, change, message):
    runner, case = setup_runner
    image, receipt = case("exit 0\n")
    change(receipt)
    monkeypatch.setattr(fixed.subprocess, "Popen", lambda *a, **k: pytest.fail("child started before acceptance"))
    with pytest.raises(fixed.FixedVMError, match=message):
        runner.measure(image, b"", b"", receipt, 2)


@pytest.mark.parametrize("mode,message", (("missing", "unavailable"), ("size", "byte count"),
                                          ("hash", "fingerprint")))
def test_missing_or_changed_full_image_rejected_before_child_start(setup_runner, monkeypatch, mode, message):
    runner, case = setup_runner
    image, receipt = case("exit 0\n")
    if mode == "missing":
        image.unlink()
    elif mode == "size":
        image.write_bytes(b"longer image")
    else:
        image.write_bytes(b"exit 1\n")
    monkeypatch.setattr(fixed.subprocess, "Popen", lambda *a, **k: pytest.fail("child started with changed image"))
    with pytest.raises(fixed.FixedVMError, match=message):
        runner.measure(image, b"", b"", receipt, 2)


def test_native_identity_rechecked_for_each_measurement(setup_runner, monkeypatch):
    runner, case = setup_runner
    image, receipt = case("exit 0\n")
    monkeypatch.setattr(fixed, "BINARY_SHA256", "0" * 64)
    monkeypatch.setattr(fixed.subprocess, "Popen", lambda *a, **k: pytest.fail("changed binary launched"))
    with pytest.raises(fixed.FixedVMError, match="pins"):
        runner.measure(image, b"", b"", receipt, 2)


def test_source_and_actual_binary_hashes_rechecked_before_launch(setup_runner, monkeypatch):
    runner, case = setup_runner
    image, receipt = case("exit 0\n")
    actual_digest = fixed.digest_file
    monkeypatch.setattr(fixed.subprocess, "Popen", lambda *a, **k: pytest.fail("changed binary launched"))
    monkeypatch.setattr(fixed, "digest_file", lambda path:
                        "0" * 64 if Path(path) == runner.binary else actual_digest(path))
    with pytest.raises(fixed.FixedVMError, match="binary fingerprint"):
        runner.measure(image, b"", b"", receipt, 2)
    monkeypatch.setattr(fixed, "digest_file", actual_digest)
    Path(runner.manifest["source"]).write_bytes(b"changed source")
    with pytest.raises(fixed.FixedVMError, match="source fingerprint"):
        runner.measure(image, b"", b"", receipt, 2)


def test_missing_native_binary_rejected(setup_runner, tmp_path):
    runner, _ = setup_runner
    manifest = copy.deepcopy(runner.manifest)
    manifest["binary"] = str(tmp_path / "missing")
    with pytest.raises(fixed.FixedVMError, match="missing"):
        fixed.FixedVMRunner(manifest["binary"], manifest)


@pytest.mark.parametrize("input_bytes,expected", ((b"different", b""), (b"", b"different")))
def test_timed_contract_must_equal_gate_contract(setup_runner, monkeypatch, input_bytes, expected):
    runner, case = setup_runner
    image, receipt = case("exit 0\n")
    monkeypatch.setattr(fixed.subprocess, "Popen", lambda *a, **k: pytest.fail("changed contract launched"))
    with pytest.raises(fixed.FixedVMError, match="timed input/output"):
        runner.measure(image, input_bytes, expected, receipt, 2)


def test_launch_error_has_no_complete_metrics(setup_runner, monkeypatch):
    runner, case = setup_runner
    image, receipt = case("exit 0\n")

    def fail(*args, **kwargs):
        raise OSError("synthetic launch failure")

    monkeypatch.setattr(fixed.subprocess, "Popen", fail)
    result = runner.measure(image, b"", b"", receipt, 2)
    assert result["reason"] == "child_launch_or_capture_error"
    assert result["returncode"] is None
    assert b"synthetic launch failure" in bytes.fromhex(result["stderr_hex"])
    assert result["partial_diagnostics"]["observed_cpu_user_seconds"] is None
    assert_no_complete_metrics(result)


def test_wait4_targets_only_the_owned_child(setup_runner, monkeypatch):
    runner, case = setup_runner
    image, receipt = case("exit 0\n")
    actual_wait4 = fixed.os.wait4
    targets = []

    def tracked(pid, options):
        targets.append(pid)
        assert pid > 0
        return actual_wait4(pid, options)

    monkeypatch.setattr(fixed.os, "wait4", tracked)
    assert runner.measure(image, b"", b"", receipt, 2)["complete"]
    assert targets and len(set(targets)) == 1


def test_shared_runner_serializes_fresh_native_children(setup_runner, monkeypatch):
    runner, case = setup_runner
    image, receipt = case("exec /bin/sleep 0.03\n")
    events = []
    actual_popen, actual_wait4 = fixed.subprocess.Popen, fixed.os.wait4

    def start(*args, **kwargs):
        assert kwargs["start_new_session"] is True
        child = actual_popen(*args, **kwargs)
        events.append(("start", child.pid))
        return child

    def wait(pid, options):
        result = actual_wait4(pid, options)
        if result[0]:
            events.append(("reaped", pid))
        return result

    monkeypatch.setattr(fixed.subprocess, "Popen", start)
    monkeypatch.setattr(fixed.os, "wait4", wait)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(runner.measure, image, b"", b"", receipt, 2) for _ in range(2)]
        results = [future.result() for future in futures]
    assert all(result["complete"] for result in results)
    assert [kind for kind, pid in events] == ["start", "reaped", "start", "reaped"]
    assert events[0][1] != events[2][1]
    assert results[0]["argv"] == results[1]["argv"]


def test_fingerprints_and_stdin_spooling_precede_timer(setup_runner, monkeypatch):
    runner, case = setup_runner
    stdin = b"\x00\xff"
    image, receipt = case("exec /bin/cat\n", stdin, stdin)
    actual_digest, actual_clock, actual_popen = fixed.digest_file, fixed.time.perf_counter, fixed.subprocess.Popen
    events = []

    def digest(path):
        events.append("digest")
        return actual_digest(path)

    def clock():
        events.append("clock")
        return actual_clock()

    def launch(*args, **kwargs):
        assert kwargs["stdin"].read() == stdin
        kwargs["stdin"].seek(0)
        return actual_popen(*args, **kwargs)

    monkeypatch.setattr(fixed, "digest_file", digest)
    monkeypatch.setattr(fixed.time, "perf_counter", clock)
    monkeypatch.setattr(fixed.subprocess, "Popen", launch)
    assert runner.measure(image, stdin, stdin, receipt, 2)["complete"]
    assert events[:3] == ["digest", "digest", "digest"]
    assert "digest" not in events[events.index("clock"):]


def test_manifest_mutation_cannot_switch_runner_binary(setup_runner):
    runner, _ = setup_runner
    manifest = copy.deepcopy(runner.manifest)
    second = fixed.FixedVMRunner(runner.binary, manifest)
    manifest["binary_sha256"] = "0" * 64
    assert second.manifest["binary_sha256"] == fixed.BINARY_SHA256


def test_cli_emits_exact_result_json(setup_runner, tmp_path, capsys):
    runner, case = setup_runner
    image, receipt = case("printf '\\000\\377'\n", stdout=b"\x00\xff")
    manifest_file, receipt_file = tmp_path / "native.json", tmp_path / "receipt.json"
    manifest_file.write_text(json.dumps(runner.manifest))
    receipt_file.write_text(json.dumps(receipt))
    code = fixed.main(["--binary", str(runner.binary), "--native-manifest", str(manifest_file),
                       "--image", str(image), "--receipt", str(receipt_file), "--input-hex", "",
                       "--expected-output-hex", "00ff", "--timeout", "2"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["stdout_hex"] == "00ff"
