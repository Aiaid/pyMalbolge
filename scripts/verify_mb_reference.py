"""Bounded correctness gate derived from the pinned Nagoya C interpreter.

The generated C copy adds counters and stop guards, never timing evidence.
Its VM, memory initialization and crazy-operation algorithms remain upstream.
Run ``uv run --no-sync python scripts/verify_mb_reference.py --help``.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "ref/nagoya-malbolge20-interpreter/malbolge20.c"
SOURCE_SHA256 = "0ea5d2cfd8e597256f91bae3ea505f2f8467e3704e5c362b24fc91b56b9782b0"
REPORT_PREFIX = "PYMALBOLGE_REFERENCE_GATE:"
_SAFE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
_MAX_COUNTER = 2 ** 64 - 1


class ReferenceGateError(RuntimeError):
    """The pinned reference could not be instrumented or compiled safely."""


_INSTRUMENTATION = r'''
/* pyMalbolge correctness-only instrumentation; not an upstream performance build. */
#include <errno.h>
#include <stdint.h>
#include <inttypes.h>

static uint64_t gate_steps = 0, gate_input = 0, gate_output = 0;
static uint64_t gate_max_steps = 0, gate_max_output = 0;
static unsigned int gate_a = 0, gate_c = 0, gate_d = 0;
static int gate_started = 0;
static const char *gate_status = "startup_error";
static const char *gate_reason = "startup_not_completed";

static void gate_report(void) {
  fprintf(stderr, "PYMALBOLGE_REFERENCE_GATE:{\"schema_version\":1,"
      "\"instrumented\":true,\"status\":\"%s\",\"stop_reason\":\"%s\","
      "\"execution_started\":%s,\"steps\":%" PRIu64 ","
      "\"input_consumed\":%" PRIu64 ",\"output_count\":%" PRIu64 ","
      "\"registers\":", gate_status, gate_reason,
      gate_started ? "true" : "false", gate_steps, gate_input, gate_output);
  if (gate_started)
    fprintf(stderr, "{\"a\":%u,\"c\":%u,\"d\":%u}", gate_a, gate_c, gate_d);
  else
    fputs("null", stderr);
  fputs("}\n", stderr);
  fflush(stderr);
}

/* Keep the diagnostic stream available for the atexit record. */
static void gate_close_errors(FILE *stream) {
  if (stream == stderr || stream == stdout) fflush(stream);
  else if (stream != NULL) fclose(stream);
}

static int gate_counter(const char *text, uint64_t *result) {
  const char *scan = text;
  char *end;
  unsigned long long value;
  if (*scan == '\0') return 0;
  while (*scan) { if (*scan < '0' || *scan > '9') return 0; ++scan; }
  errno = 0;
  value = strtoull(text, &end, 10);
  if (errno || *end) return 0;
  *result = (uint64_t)value;
  return 1;
}

static int gate_setup(int *argc, char ***argv) {
  if (atexit(gate_report) != 0) return 0;
  if (*argc != 4 || !gate_counter((*argv)[1], &gate_max_steps) ||
      !gate_counter((*argv)[2], &gate_max_output)) {
    gate_reason = "invalid_gate_arguments";
    return 0;
  }
  /* Retain the original main's [program, image] argument layout. */
  (*argv)[2] = (*argv)[0];
  *argv += 2;
  *argc -= 2;
  return 1;
}

'''


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _environment(output_dir=None):
    # Deliberately do not pass credentials, preload hooks, or user compiler flags.
    environment = {"PATH": _SAFE_PATH, "LANG": "C", "LC_ALL": "C"}
    if output_dir is not None:
        environment["TMPDIR"] = str(output_dir)
    return environment


def _instrument(source):
    original_hash = _digest(source)
    if original_hash != SOURCE_SHA256:
        raise ReferenceGateError("reference source fingerprint differs from the audited version")
    text = source.decode("utf-8")
    replacements = (
        ("includes", "#include <unistd.h>\n", "#include <unistd.h>\n" + _INSTRUMENTATION, 1),
        ("main", "int main( int argc, char **argv )\n{",
         "int main( int argc, char **argv )\n{\n  if (!gate_setup(&argc, &argv)) return 64;", 1),
        ("diagnostic_stream", "} else   fperror = stdout;", "} else   fperror = stderr;", 1),
        ("diagnostic_close", "fclose(fperror);", "gate_close_errors(fperror);", 10),
        ("execution_start", "  int c_id=0, d_id=0;\n  for (;;)",
         "  int c_id=0, d_id=0;\n  gate_started = 1;\n"
         "  gate_status = \"error\"; gate_reason = \"runtime_error\";\n  for (;;)", 1),
        ("instruction_boundary", "      if ( mem[c_id][c] < 33 || mem[c_id][c] > 126 ) {",
         "      gate_a = a; gate_c = c + c_id * 59049u; gate_d = d + d_id * 59049u;\n"
         "      if (gate_steps >= gate_max_steps) {\n"
         "        gate_status = \"step_limit\"; gate_reason = \"step_limit\"; return;\n"
         "      }\n"
         "      if ( mem[c_id][c] < 33 || mem[c_id][c] > 126 ) {\n"
         "        gate_status = \"error\"; gate_reason = \"invalid_instruction\";", 1),
        ("instruction_dispatch", "      switch ( xlat1[( mem[c_id][c] - 33 + (c+c_id*59049) ) % 94] )",
         "      if (xlat1[(mem[c_id][c] - 33 + (c+c_id*59049)) % 94] == '<' &&\n"
         "          gate_output >= gate_max_output) {\n"
         "        gate_status = \"output_limit\"; gate_reason = \"output_limit\"; return;\n"
         "      }\n"
         "      ++gate_steps;\n"
         "      switch ( xlat1[( mem[c_id][c] - 33 + (c+c_id*59049) ) % 94] )", 1),
        ("output_count", "\tcase '<'://OUTPUT", "\tcase '<'://OUTPUT\n          ++gate_output;", 1),
        ("input_count", "\t  x = getc( stdin );",
         "\t  x = getc( stdin );\n          if (x != EOF) ++gate_input;", 1),
        ("halt", "\tcase 'v':return;//HALT",
         "\tcase 'v': gate_status = \"terminated\"; gate_reason = \"halt\"; return;//HALT", 1),
    )
    counts = {}
    for name, anchor, replacement, expected in replacements:
        found = text.count(anchor)
        if found != expected:
            raise ReferenceGateError("instrumentation anchor %s: expected %d occurrences, found %d" %
                                     (name, expected, found))
        counts[name] = found
        text = text.replace(anchor, replacement)
    return text.encode("utf-8"), counts


def build_reference_gate(source=DEFAULT_SOURCE, output_dir=None):
    """Return ``(binary_path, manifest)`` for a pinned, instrumented C copy.

    The caller owns output_dir. The original vendor file is never edited.
    Existing evidence in that directory is replaced only under fixed gate names.
    """
    if output_dir is None:
        raise ValueError("output_dir is required")
    source = Path(source).resolve()
    output_dir = Path(output_dir).resolve()
    original = source.read_bytes()
    instrumented, counts = _instrument(original)
    output_dir.mkdir(parents=True, exist_ok=True)
    generated = output_dir / "malbolge20-reference-gate.c"
    binary = output_dir / "malbolge20-reference-gate"
    if source in (generated, binary):
        raise ReferenceGateError("output directory would overwrite the original source")
    compiler = shutil.which("clang", path=_SAFE_PATH)
    if compiler is None:
        raise ReferenceGateError("clang is unavailable")
    generated.write_bytes(instrumented)
    command = [compiler, "-O3", "-std=c99", str(generated), "-lm", "-o", str(binary)]
    try:
        compiled = subprocess.run(command, capture_output=True, timeout=60,
                                  env=_environment(output_dir), cwd=output_dir)
        if compiled.returncode:
            raise ReferenceGateError("reference gate build failed: " +
                                     compiled.stderr.decode("utf-8", errors="replace"))
        version = subprocess.run([compiler, "--version"], capture_output=True,
                                 timeout=10, env=_environment(output_dir))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReferenceGateError("reference gate build unavailable: %s" % exc) from exc
    manifest = {
        "schema_version": 1, "purpose": "correctness_only",
        "performance_measurement": False,
        "source": str(source), "source_sha256": _digest(original),
        "instrumented_source": str(generated),
        "instrumented_source_sha256": _digest(instrumented),
        "binary": str(binary), "binary_sha256": _digest(binary.read_bytes()),
        "compiler": compiler,
        "compiler_version": version.stdout.decode("utf-8", errors="replace").strip(),
        "compiler_flags": ["-O3", "-std=c99", "-lm"],
        "insertion_anchor_counts": counts,
        "eof_policy": "sentinel", "eof_sentinel": 59049,
        "step_contract": "HALT counts; invalid and budget-blocked instructions do not count",
        "diagnostics": compiled.stderr.decode("utf-8", errors="replace"),
    }
    (output_dir / "reference-gate-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n")
    return binary, manifest


def _budget(value, name):
    if type(value) is not int or not 0 <= value <= _MAX_COUNTER:
        raise ValueError("%s must be an unsigned 64-bit integer" % name)


def verify_image(binary, image, input_bytes, expected_output, expected_consumed,
                 max_steps, max_output, timeout):
    """Require exact output/consumption and normal HALT under explicit bounds.

    Output is a JSON-compatible correctness record. A subprocess timeout,
    startup failure or missing/malformed report leaves target counters null.
    No wall/CPU runtime field is collected from this instrumented execution.
    """
    for value, name in ((max_steps, "max_steps"), (max_output, "max_output"),
                        (expected_consumed, "expected_consumed")):
        _budget(value, name)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    if not isinstance(input_bytes, bytes) or not isinstance(expected_output, bytes):
        raise TypeError("input_bytes and expected_output must be bytes")
    if expected_consumed > len(input_bytes):
        raise ValueError("expected_consumed exceeds the provided input bytes")
    binary, image = Path(binary).resolve(), Path(image).resolve()
    result = {
        "schema_version": 1, "instrumented_reference": True,
        "performance_measurement": False, "gate_pass": False,
        "validation_status": "unvalidated", "status": "startup_error",
        "reason": "not_executed", "stop_reason": None,
        "steps": None, "input_consumed": None, "output_count": None,
        "registers": None, "stdout_hex": "", "expected_output_hex": expected_output.hex(),
        "expected_consumed": expected_consumed, "output_matches": False,
        "input_consumption_matches": None, "normal_halt": False,
        "max_steps": max_steps, "max_output": max_output,
        "timeout_seconds": timeout, "returncode": None,
        "image": str(image), "image_sha256": None, "reference_binary": str(binary),
    }
    try:
        result["image_sha256"] = _digest(image.read_bytes())
        completed = subprocess.run(
            [str(binary), str(max_steps), str(max_output), str(image)],
            input=input_bytes, capture_output=True, timeout=timeout,
            env=_environment(), cwd=binary.parent)
    except subprocess.TimeoutExpired as exc:
        result.update(status="timeout", reason="child_timeout",
                      stdout_hex=(exc.stdout or b"").hex(),
                      stderr=(exc.stderr or b"").decode("utf-8", errors="replace"))
        return result
    except OSError as exc:
        result.update(reason="reference_launch_error", stderr=str(exc))
        return result
    stderr = completed.stderr.decode("utf-8", errors="replace")
    result.update(returncode=completed.returncode, stderr=stderr,
                  stdout_hex=completed.stdout.hex(),
                  output_matches=completed.stdout == expected_output)
    reports = [line[len(REPORT_PREFIX):] for line in stderr.splitlines()
               if line.startswith(REPORT_PREFIX)]
    if len(reports) != 1:
        result.update(status="error", reason="missing_or_duplicate_reference_report")
        return result
    try:
        report = json.loads(reports[0])
        status = report["status"]
        if (report.get("schema_version") != 1 or report.get("instrumented") is not True or
                status not in ("terminated", "error", "step_limit", "output_limit", "startup_error")):
            raise ValueError("invalid reference report schema")
        if status == "startup_error":
            result.update(status=status, reason=report["stop_reason"],
                          stop_reason=report["stop_reason"])
            return result
        if report.get("execution_started") is not True:
            raise ValueError("target execution did not start")
        for key in ("steps", "input_consumed", "output_count"):
            _budget(report[key], key)
        registers = report["registers"]
        if (not isinstance(registers, dict) or set(registers) != {"a", "c", "d"} or
                any(type(value) is not int or not 0 <= value < 3 ** 20
                    for value in registers.values())):
            raise ValueError("invalid register report")
        if (report["steps"] > max_steps or report["input_consumed"] > len(input_bytes) or
                report["output_count"] != len(completed.stdout) or
                report["output_count"] > max_output):
            raise ValueError("reference counters violate execution bounds")
        if status == "terminated" and (completed.returncode != 0 or report["stop_reason"] != "halt"):
            raise ValueError("inconsistent HALT report")
    except (KeyError, TypeError, ValueError) as exc:
        result.update(status="error", reason="invalid_reference_report", report_error=str(exc))
        return result
    result.update(status=status, stop_reason=report["stop_reason"],
                  steps=report["steps"], input_consumed=report["input_consumed"],
                  output_count=report["output_count"], registers=registers,
                  validation_status="failed", normal_halt=status == "terminated",
                  input_consumption_matches=report["input_consumed"] == expected_consumed)
    if not result["normal_halt"]:
        result["reason"] = report["stop_reason"]
    elif not result["output_matches"]:
        result["reason"] = "output_mismatch"
    elif not result["input_consumption_matches"]:
        result["reason"] = "input_consumption_mismatch"
    else:
        result.update(gate_pass=True, validation_status="passed", reason="validated")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="build a pinned correctness-only C reference")
    build.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    build.add_argument("--output-dir", type=Path, required=True)
    verify = subparsers.add_parser("verify", help="verify one MB image before timing it")
    verify.add_argument("--binary", type=Path, required=True)
    verify.add_argument("--image", type=Path, required=True)
    verify.add_argument("--input-hex", default="")
    verify.add_argument("--expected-output-hex", required=True)
    verify.add_argument("--expected-consumed", type=int, required=True)
    verify.add_argument("--max-steps", type=int, required=True)
    verify.add_argument("--max-output", type=int, required=True)
    verify.add_argument("--timeout", type=float, required=True)
    args = parser.parse_args(argv)
    if args.command == "build":
        _, result = build_reference_gate(args.source, args.output_dir)
        code = 0
    else:
        result = verify_image(args.binary, args.image, bytes.fromhex(args.input_hex),
                              bytes.fromhex(args.expected_output_hex), args.expected_consumed,
                              args.max_steps, args.max_output, args.timeout)
        code = 0 if result["gate_pass"] else 1
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
