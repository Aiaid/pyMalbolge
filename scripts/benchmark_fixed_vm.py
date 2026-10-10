"""Measure accepted MB images serially with one pinned, unmodified C VM.

Wall time covers launch, read/validate/initialize/execute, and output capture.
Per-child CPU comes from wait4, never a cumulative RUSAGE_CHILDREN delta.
No internal VM clocks, instruction counts, or input-consumption claims are made.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import tempfile
import threading
import time


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "ref/nagoya-malbolge20-interpreter/malbolge20.c"
SOURCE_SHA256 = "0ea5d2cfd8e597256f91bae3ea505f2f8467e3704e5c362b24fc91b56b9782b0"
BINARY_SHA256 = "6dcd2b2913794c122252cce85c634fe0a583d5f4819be1c0f33112ee42ffc2a1"
ENVIRONMENT = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "C", "LC_ALL": "C"}
CLOCK_SCOPE = {
    "wall": "time.perf_counter; whole child including launch/read/validation/initialization/execution/output capture",
    "cpu": "os.wait4 rusage for this child: ru_utime + ru_stime; includes the entire child lifetime",
    "excluded": "source/binary/image hashing, correctness gate, receipt validation and parent report serialization",
    "vm_only_time_available": False,
    "runtime_instruction_count_available": False,
    "runtime_input_consumption_available": False,
}


class FixedVMError(ValueError):
    """A measurement prerequisite or accepted receipt is inconsistent."""


def digest_file(path):
    """Hash complete files without loading large MB artifacts into memory."""
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _require(condition, message):
    if not condition:
        raise FixedVMError(message)


def accepted_receipt(image_record, gate_record, reference_manifest, contract):
    """Package existing correctness evidence; this does not run or accept a VM.

    image_record is the accepted full-image {bytes, sha256}, not a fresh timing
    fingerprint. gate_record is verify_mb_reference.verify_image's passed record.
    contract requires stdin_hex, expected_stdout_hex, expected_input_consumed,
    and nonempty provenance (e.g. an oracle/manifest source hash).
    """
    receipt = {"schema_version": 1, "image": dict(image_record),
               "gate": dict(gate_record), "reference": dict(reference_manifest),
               "contract": dict(contract)}
    _validate_receipt(receipt)
    return receipt


def _validate_receipt(receipt):
    _require(isinstance(receipt, dict) and receipt.get("schema_version") == 1,
             "accepted receipt schema_version 1 is required")
    image, gate = receipt.get("image", {}), receipt.get("gate", {})
    reference, contract = receipt.get("reference", {}), receipt.get("contract", {})
    _require(all(isinstance(item, dict) for item in (image, gate, reference, contract)),
             "receipt image/gate/reference/contract must be objects")
    _require(type(image.get("bytes")) is int and image["bytes"] > 0 and
             isinstance(image.get("sha256"), str) and len(image["sha256"]) == 64,
             "accepted full-image byte count and hash are required")
    _require(gate.get("gate_pass") is True and gate.get("validation_status") == "passed" and
             gate.get("instrumented_reference") is True and
             gate.get("performance_measurement") is False and
             gate.get("normal_halt") is True and gate.get("status") == "terminated" and
             gate.get("stop_reason") == "halt" and gate.get("returncode") == 0 and
             gate.get("output_matches") is True and gate.get("input_consumption_matches") is True,
             "receipt requires accepted independent normal-HALT/output/input evidence")
    _require(gate.get("image_sha256") == image["sha256"],
             "gate and accepted full-image hash differ")
    _require(reference.get("source_sha256") == SOURCE_SHA256 and
             reference.get("purpose") == "correctness_only" and
             reference.get("performance_measurement") is False and
             isinstance(reference.get("binary_sha256"), str) and
             len(reference["binary_sha256"]) == 64 and
             gate.get("reference_binary") == reference.get("binary"),
             "independent reference provenance is absent or inconsistent")
    provenance = contract.get("provenance")
    _require(isinstance(provenance, (str, dict)) and bool(provenance),
             "expected contract provenance is required")
    try:
        stdin = bytes.fromhex(contract["stdin_hex"])
        stdout = bytes.fromhex(contract["expected_stdout_hex"])
    except (KeyError, TypeError, ValueError) as exc:
        raise FixedVMError("contract requires exact input/output hex bytes") from exc
    consumed = contract.get("expected_input_consumed")
    _require(type(consumed) is int and 0 <= consumed <= len(stdin),
             "contract requires expected input consumption")
    _require(gate.get("expected_output_hex") == stdout.hex() and
             gate.get("stdout_hex") == stdout.hex() and gate.get("output_count") == len(stdout) and
             gate.get("expected_consumed") == consumed and gate.get("input_consumed") == consumed,
             "accepted gate does not match the expected contract")
    # verify_image does not store its input, so callers must preserve the original
    # gate input alongside its result rather than infer it from a later workload.
    _require(gate.get("stdin_hex") == stdin.hex(), "accepted gate input bytes are not preserved")
    return stdin, stdout


def _returncode(status):
    return os.WEXITSTATUS(status) if os.WIFEXITED(status) else -os.WTERMSIG(status)


def _kill_group(pid):
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _execute(argv, cwd, input_file, timeout, stdout_cap, stderr_cap):
    """Own only this newly created session, including its pipes and wait4 receipt."""
    output, errors = bytearray(), bytearray()
    proc, usage, returncode = None, None, None
    failure = None
    start = time.perf_counter()
    deadline = start + timeout
    try:
        proc = subprocess.Popen(argv, stdin=input_file, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, cwd=cwd, env=dict(ENVIRONMENT),
                                start_new_session=True)
        with selectors.DefaultSelector() as selector:
            for stream, name in ((proc.stdout, "stdout"), (proc.stderr, "stderr")):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            while returncode is None or selector.get_map():
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    failure = "child_timeout"
                    break
                for key, _ in selector.select(min(remaining, 0.01)):
                    try:
                        block = os.read(key.fileobj.fileno(), 65536)
                    except BlockingIOError:
                        continue
                    if not block:
                        selector.unregister(key.fileobj)
                        continue
                    target = output if key.data == "stdout" else errors
                    cap = stdout_cap if key.data == "stdout" else stderr_cap
                    room = cap - len(target)
                    target.extend(block[:room])
                    if len(block) > room:
                        failure = key.data + "_capture_limit"
                        break
                if failure:
                    break
                if returncode is None:
                    child, status, child_usage = os.wait4(proc.pid, os.WNOHANG)
                    if child:
                        usage, returncode = child_usage, _returncode(status)
                        proc.returncode = returncode
        if failure:
            _kill_group(proc.pid)
        if returncode is None:
            _, status, usage = os.wait4(proc.pid, 0)
            returncode = _returncode(status)
            proc.returncode = returncode
    except OSError as exc:
        failure = "child_launch_or_capture_error"
        errors.extend(str(exc).encode("utf-8", errors="replace")[:max(0, stderr_cap - len(errors))])
    finally:
        if proc is not None:
            if proc.returncode is None:
                _kill_group(proc.pid)
                _, status, usage = os.wait4(proc.pid, 0)
                returncode = _returncode(status)
                proc.returncode = returncode
            for stream in (proc.stdout, proc.stderr):
                if stream is not None:
                    stream.close()
    elapsed = time.perf_counter() - start
    cpu_user = usage.ru_utime if usage is not None else None
    cpu_system = usage.ru_stime if usage is not None else None
    return {"failure": failure, "returncode": returncode, "stdout": bytes(output),
            "stderr": bytes(errors), "observed_wall_seconds": elapsed,
            "observed_cpu_user_seconds": cpu_user, "observed_cpu_system_seconds": cpu_system}


class FixedVMRunner:
    """One binary and environment for every serial, fresh-process measurement.

    manifest must audit the actual unmodified source, binary and -O3 build:
    {source, source_sha256, binary, binary_sha256, instrumented: False,
     compiler, compiler_flags: ['-O3'], build_provenance: <audited build receipt>}.
    Record only flags/version actually established by that receipt.
    Default pins are intentionally not CLI-overridable.
    """

    def __init__(self, binary, manifest):
        _require(hasattr(os, "wait4") and os.name == "posix", "POSIX wait4 is required")
        self.binary = Path(binary).resolve()
        self.manifest = json.loads(json.dumps(manifest))
        self._lock = threading.Lock()
        self._verify_binary()

    def _verify_binary(self):
        manifest = self.manifest
        _require(isinstance(manifest, dict), "native build manifest is required")
        _require(manifest.get("instrumented") is False and
                 manifest.get("source_sha256") == SOURCE_SHA256 and
                 manifest.get("binary_sha256") == BINARY_SHA256 and
                 manifest.get("binary") == str(self.binary),
                 "native source/binary pins or unmodified build provenance differ")
        flags = manifest.get("compiler_flags")
        _require(isinstance(flags, list) and all(isinstance(flag, str) for flag in flags) and
                 "-O3" in flags and bool(manifest.get("compiler")) and
                 bool(manifest.get("build_provenance")),
                 "audited original C -O3 build provenance is required")
        source = Path(manifest.get("source", str(DEFAULT_SOURCE))).resolve()
        try:
            _require(digest_file(source) == SOURCE_SHA256, "native source fingerprint differs")
            _require(self.binary.is_file() and os.access(self.binary, os.X_OK),
                     "native binary is missing or not executable")
            _require(digest_file(self.binary) == BINARY_SHA256, "native binary fingerprint differs")
        except OSError as exc:
            raise FixedVMError("native source/binary is unavailable: %s" % exc) from exc

    def measure(self, image, input_bytes, expected_output, receipt, timeout,
                output_cap=4096, stderr_cap=65536):
        """Return JSON-compatible timing/diagnostics, or reject before child start.

        Failed or censored runs have all complete timing fields null. Observed
        resource usage lives only in partial_diagnostics and is not VM runtime.
        The lock serializes calls sharing this runner; callers must also avoid
        scheduling competing benchmark processes outside this instance.
        """
        _require(isinstance(input_bytes, bytes) and isinstance(expected_output, bytes),
                 "input and expected output must be explicit bytes")
        _require(type(timeout) in (int, float) and math.isfinite(timeout) and timeout > 0,
                 "external timeout must be finite and positive")
        _require(type(output_cap) is int and output_cap >= len(expected_output) and
                 type(stderr_cap) is int and stderr_cap >= 0, "invalid capture byte caps")
        with self._lock:
            self._verify_binary()
            receipt = json.loads(json.dumps(receipt))
            accepted_input, accepted_output = _validate_receipt(receipt)
            _require(input_bytes == accepted_input and expected_output == accepted_output,
                     "timed input/output differs from accepted contract")
            image = Path(image).resolve()
            try:
                _require(image.stat().st_size == receipt["image"]["bytes"],
                         "full-image byte count differs from accepted receipt")
                _require(digest_file(image) == receipt["image"]["sha256"],
                         "full-image fingerprint differs from accepted receipt")
            except OSError as exc:
                raise FixedVMError("accepted image is unavailable: %s" % exc) from exc
            argv = [str(self.binary), str(image)]
            result = {
                "schema_version": 1, "status": "not_started", "reason": None,
                "complete": False, "performance_measurement": True,
                "instrumented": False, "argv": argv, "cwd": str(self.binary.parent),
                "environment": dict(ENVIRONMENT), "clock_scope": dict(CLOCK_SCOPE),
                "native_vm": json.loads(json.dumps(self.manifest)), "accepted_receipt": receipt,
                "image": dict(receipt["image"]), "stdin_hex": input_bytes.hex(),
                "expected_stdout_hex": expected_output.hex(), "stdout_hex": "",
                "stderr_hex": "", "output_matches": False, "returncode": None,
                "timeout_seconds": timeout, "stdout_capture_cap_bytes": output_cap,
                "stderr_capture_cap_bytes": stderr_cap,
                "whole_child_wall_seconds": None, "whole_child_cpu_seconds": None,
                "whole_child_cpu_user_seconds": None, "whole_child_cpu_system_seconds": None,
                "partial_diagnostics": None,
            }
            # Spool the exact stdin before the timer; a pipe write must not block
            # deadline enforcement or alter the stream when the VM reads slowly.
            with tempfile.TemporaryFile() as stdin:
                stdin.write(input_bytes)
                stdin.seek(0)
                observed = _execute(argv, self.binary.parent, stdin, timeout, output_cap, stderr_cap)
            result.update(stdout_hex=observed["stdout"].hex(), stderr_hex=observed["stderr"].hex(),
                          returncode=observed["returncode"],
                          output_matches=observed["stdout"] == expected_output)
            reason = observed["failure"]
            if reason is None and observed["returncode"] != 0:
                reason = "child_exit_failure"
            if reason is None and not result["output_matches"]:
                reason = "output_mismatch"
            if reason is not None:
                result.update(status="timeout" if reason == "child_timeout" else "failed", reason=reason,
                              partial_diagnostics={key: value for key, value in observed.items()
                                                   if key.startswith("observed_")})
            else:
                user, system = observed["observed_cpu_user_seconds"], observed["observed_cpu_system_seconds"]
                result.update(status="passed", reason="completed_exact_output", complete=True,
                              whole_child_wall_seconds=observed["observed_wall_seconds"],
                              whole_child_cpu_seconds=user + system,
                              whole_child_cpu_user_seconds=user, whole_child_cpu_system_seconds=system)
            return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--native-manifest", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--input-hex", required=True)
    parser.add_argument("--expected-output-hex", required=True)
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("--output-cap", type=int, default=4096)
    args = parser.parse_args(argv)
    try:
        runner = FixedVMRunner(args.binary, json.loads(args.native_manifest.read_text()))
        result = runner.measure(args.image, bytes.fromhex(args.input_hex),
                                bytes.fromhex(args.expected_output_hex),
                                json.loads(args.receipt.read_text()), args.timeout, args.output_cap)
    except (FixedVMError, OSError, ValueError) as exc:
        print(json.dumps({"schema_version": 1, "status": "rejected_before_start", "reason": str(exc),
                          "complete": False, "performance_measurement": False}))
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
