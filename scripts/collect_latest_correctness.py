"""Consolidate exact target identities before permitting latest-corpus timing.

Every initial and supplementary attempt is retained. A later success is usable
only for the same source, full MB artifact, input/output contract and compiler
snapshot. This collector never runs or times a target program.
"""

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


BACKENDS = ("c", "direct", "ir")
REFERENCE_SOURCE_SHA256 = "0ea5d2cfd8e597256f91bae3ea505f2f8467e3704e5c362b24fc91b56b9782b0"


def digest_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_hashes(snapshot):
    return {str(path.relative_to(snapshot)): digest_file(path)
            for folder in ("malbolge", "scripts", "benchmarks")
            for path in sorted((snapshot / folder).rglob("*"))
            if path.is_file() and path.suffix in (".py", ".json")}


def _identity(kind, program, backend, workload):
    return kind, program, backend, workload


def _label(key):
    return "/".join(key)


def expected_targets(snapshot, canary_path):
    manifest_path = snapshot / "benchmarks/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    canaries = json.loads(canary_path.read_text())["canaries"]
    targets = {}
    for program in manifest["programs"]:
        source = (manifest_path.parent / program["path"]).read_bytes()
        source_sha = hashlib.sha256(source).hexdigest()
        for backend in BACKENDS:
            for work in program["workloads"]:
                key = _identity("corpus", program["id"], backend, work["id"])
                targets[key] = {
                    "source_sha256": source_sha,
                    "stdin_hex": work["stdin"].encode("ascii").hex(),
                    "expected_stdout_hex": work["stdout"].encode("ascii").hex(),
                    "expected_input_consumed": work.get("expected_input_consumed", len(work["stdin"].encode("ascii"))),
                    "original_max_steps": work["max_steps"],
                    "original_timeout_seconds": work["timeout_seconds"],
                }
    for canary in canaries:
        source_sha = hashlib.sha256(canary["source"].encode()).hexdigest()
        if source_sha != canary["source_sha256"]:
            raise ValueError("canary source fingerprint mismatch: " + canary["name"])
        for backend in BACKENDS:
            key = _identity("canary", canary["name"], backend, "fixed")
            targets[key] = {
                "source_sha256": source_sha,
                "stdin_hex": canary["stdin_hex"],
                "expected_stdout_hex": canary["expected_stdout_hex"],
                "expected_input_consumed": canary["expected_input_consumed"],
                "original_max_steps": 1000000000, "original_timeout_seconds": 300,
            }
    return targets


def source_oracle_provenance(run_dir, required, live_fingerprints):
    path = run_dir / "oracle-audit/source-semantic-report.json"
    audit = json.loads(path.read_text())
    issues = []
    for name, digest in audit["source_hashes"].items():
        if name == "benchmarks/manifest.json":
            continue  # Compare exact workload contracts below; metadata may differ.
        if name.startswith(("malbolge/", "benchmarks/")) and live_fingerprints.get(name) != digest:
            issues.append({"reason": "source_oracle_compiler_or_program_mismatch", "path": name})
    seen = set()
    for record in audit["manifest_records"]:
        key = _identity("corpus", record["program"], "c", record["workload"])
        expected = required.get(key)
        good = expected is not None and record.get("passed") is True
        if expected:
            good = good and all(record.get(left) == expected[right] for left, right in (
                ("input_hex", "stdin_hex"), ("expected_hex", "expected_stdout_hex"),
                ("expected_input_consumed", "expected_input_consumed")))
        if not good or key in seen:
            issues.append({"reason": "source_oracle_workload_contract_mismatch", "target": _label(key)})
        seen.add(key)
    for record in audit["canary_records"]:
        key = _identity("canary", record["name"], "c", "fixed")
        expected = required.get(key)
        good = expected is not None and record.get("passed") is True
        if expected:
            good = good and all(record.get(left) == expected[right] for left, right in (
                ("input_hex", "stdin_hex"), ("expected_hex", "expected_stdout_hex"),
                ("expected_input_consumed", "expected_input_consumed"),
                ("source_sha256", "source_sha256")))
        if not good or key in seen:
            issues.append({"reason": "source_oracle_canary_contract_mismatch", "target": _label(key)})
        seen.add(key)
    expected_keys = {key for key in required if key[2] == "c"}
    if seen != expected_keys:
        issues.append({"reason": "source_oracle_coverage_mismatch"})
    return {
        "path": str(path.relative_to(run_dir)), "sha256": digest_file(path),
        "manifest_records": len(audit["manifest_records"]), "canary_records": len(audit["canary_records"]),
        "oracle_manifest_sha256": audit["source_hashes"]["benchmarks/manifest.json"],
        "frozen_manifest_sha256": live_fingerprints["benchmarks/manifest.json"],
        "manifest_byte_identity": audit["source_hashes"]["benchmarks/manifest.json"] == live_fingerprints["benchmarks/manifest.json"],
        "exact_source_and_workload_contracts_match": not issues,
        "issues": issues,
    }


def collect(run_dir):
    run_dir = Path(run_dir).resolve()
    snapshot = run_dir / "snapshots/working-latest"
    canary_path = run_dir / "oracle-audit/canaries.json"
    required = expected_targets(snapshot, canary_path)
    if len(required) != 123:
        raise ValueError("expected exactly 123 required targets, found %d" % len(required))
    original_path = run_dir / "target-gate/report.json"
    paths = [original_path] + sorted(path for path in run_dir.glob("target-gate*/report.json")
                                   if path != original_path)
    reports, anomalies, attempts = [], [], {key: [] for key in required}
    live_fingerprints = source_hashes(snapshot)
    oracle = source_oracle_provenance(run_dir, required, live_fingerprints)
    anomalies.extend(oracle["issues"])
    canonical_image = {}
    for path in paths:
        raw = path.read_bytes()
        report = json.loads(raw)
        reference = report.get("reference_gate", {})
        completed = report.get("state") in ("passed", "needs_diagnosis")
        source_start = report.get("source_hashes_start")
        lineage_valid = (report.get("phase") == "correctness_only" and
                         report.get("cohort") == "working-latest" and
                         Path(report["snapshot"]).resolve() == snapshot and
                         source_start == live_fingerprints and
                         reference.get("source_sha256") == REFERENCE_SOURCE_SHA256 and
                         report.get("selection", {}).get("target_pipeline") == "structured" and
                         report.get("selection", {}).get("style") == "cluster/main" and
                         report.get("selection", {}).get("ir_frontend") == "semantic")
        if completed:
            lineage_valid = (lineage_valid and report.get("source_unchanged") is True and
                             report.get("source_hashes_end") == source_start)
        if not lineage_valid:
            anomalies.append({"report": str(path), "reason": "source_or_selection_lineage_mismatch"})
        report_id = str(path.relative_to(run_dir))
        reports.append({"path": report_id, "sha256": hashlib.sha256(raw).hexdigest(),
                        "state": report.get("state"), "active": report.get("active"),
                        "completed": completed, "lineage_valid": lineage_valid,
                        "attempted": report.get("attempted_targets"), "passed": report.get("passed_targets"),
                        "source_unchanged": report.get("source_unchanged"),
                        "reference_binary_sha256": reference.get("binary_sha256"),
                        "reference_instrumented_source_sha256": reference.get("instrumented_source_sha256")})
        seen = set()
        for sample in report["samples"]:
            image = sample.get("image")
            compilation_ok = sample.get("compilation", {}).get("accepted") is True
            for work in sample["workloads"]:
                key = _identity(sample["kind"], sample["program"], sample["backend"], work["workload"])
                if key not in required or key in seen:
                    anomalies.append({"report": report_id, "target": _label(key), "reason": "unexpected_or_duplicate_identity"})
                    continue
                seen.add(key)
                expected = required[key]
                contract_valid = sample["source_sha256"] == expected["source_sha256"]
                for name in ("stdin_hex", "expected_stdout_hex", "expected_input_consumed"):
                    contract_valid = contract_valid and work.get(name) == expected[name]
                if not contract_valid:
                    anomalies.append({"report": report_id, "target": _label(key), "reason": "source_or_contract_mismatch"})
                if work.get("reason") in ("output_mismatch", "input_consumption_mismatch", "invalid_instruction"):
                    anomalies.append({"report": report_id, "target": _label(key),
                                      "reason": "actual_correctness_failure_requires_diagnosis",
                                      "detail": work["reason"]})
                image_valid = False
                if compilation_ok and isinstance(image, dict):
                    image_valid = (type(image.get("bytes")) is int and image["bytes"] > 0 and
                                   isinstance(image.get("sha256"), str) and len(image["sha256"]) == 64 and
                                   work.get("image_sha256") == image["sha256"])
                    if key not in canonical_image:
                        canonical_image[key] = copy.deepcopy(image)
                    elif canonical_image[key] != image:
                        image_valid = False
                        anomalies.append({"report": report_id, "target": _label(key), "reason": "full_mb_identity_mismatch",
                                          "original": canonical_image[key], "observed": image})
                if compilation_ok and not image_valid:
                    anomalies.append({"report": report_id, "target": _label(key), "reason": "missing_or_invalid_image_fingerprint"})
                registers = work.get("registers")
                registers_valid = (isinstance(registers, dict) and set(registers) == {"a", "c", "d"} and
                                   all(type(value) is int and 0 <= value < 3 ** 20 for value in registers.values()))
                semantic_pass = (
                    work.get("gate_pass") is True and work.get("validation_status") == "passed" and
                    work.get("status") == "terminated" and work.get("stop_reason") == "halt" and
                    work.get("normal_halt") is True and work.get("returncode") == 0 and
                    work.get("stdout_hex") == expected["expected_stdout_hex"] and
                    work.get("input_consumed") == expected["expected_input_consumed"] and
                    work.get("output_count") == len(bytes.fromhex(expected["expected_stdout_hex"])) and
                    registers_valid and type(work.get("steps")) is int and work["steps"] > 0 and
                    type(work.get("max_steps")) is int and work["steps"] <= work["max_steps"])
                accepted = bool(lineage_valid and contract_valid and image_valid and semantic_pass)
                attempts[key].append({
                    "report": report_id, "report_completed": completed, "source_sha256": sample["source_sha256"],
                    "image": copy.deepcopy(image), "accepted": accepted,
                    "compilation": copy.deepcopy(sample.get("compilation")),
                    "result": copy.deepcopy(work),
                })
    rows = []
    for key, expected in required.items():
        successful = [attempt for attempt in attempts[key] if attempt["accepted"]]
        if successful:
            step_counts = {attempt["result"]["steps"] for attempt in successful}
            if len(step_counts) != 1:
                anomalies.append({"target": _label(key), "reason": "same_image_step_count_mismatch", "counts": sorted(step_counts)})
            final_states = {json.dumps(attempt["result"].get("registers"), sort_keys=True) for attempt in successful}
            if len(final_states) != 1:
                anomalies.append({"target": _label(key), "reason": "same_image_register_state_mismatch"})
            completed_successful = [attempt for attempt in successful if attempt["report_completed"]]
            selected = (completed_successful or successful)[0]
        else:
            selected = None
        row = {"identity": dict(zip(("kind", "program", "backend", "workload"), key)),
               "target_id": _label(key), "contract": expected, "image": canonical_image.get(key),
               "passed": bool(selected), "accepted_report": selected["report"] if selected else None,
               "accepted_steps": selected["result"]["steps"] if selected else None,
               "attempts": attempts[key]}
        rows.append(row)
    workers_complete = all(report["completed"] and report["active"] is None for report in reports)
    all_passed = all(row["passed"] for row in rows) and not anomalies
    return {
        "schema_version": 1, "cohort": "working-latest", "phase": "combined_correctness",
        "snapshot": str(snapshot), "performance_measurement": False,
        "required_targets": len(rows), "required_corpus_targets": sum(key[0] == "corpus" for key in required),
        "required_canary_targets": sum(key[0] == "canary" for key in required),
        "unique_passed_targets": sum(row["passed"] for row in rows),
        "total_attempts_preserved": sum(len(row["attempts"]) for row in rows),
        "original_unsuccessful_attempts_preserved": sum(not attempt["accepted"] for row in rows
            for attempt in row["attempts"] if attempt["report"] == "target-gate/report.json"),
        "all_required_targets_passed": all_passed,
        "all_correctness_workers_complete": workers_complete,
        "performance_gate_open": bool(all_passed and workers_complete),
        "source_hashes_current": live_fingerprints,
        "manifest_sha256": digest_file(snapshot / "benchmarks/manifest.json"),
        "canaries_sha256": digest_file(canary_path),
        "collector_sha256": digest_file(Path(__file__)),
        "source_oracle_provenance": oracle,
        "reports": reports, "anomalies": anomalies, "targets": rows,
    }


def write_derived_manifest(collected, destination):
    if not collected["performance_gate_open"]:
        raise ValueError("performance manifest cannot be authorized before all exact targets pass and workers finish")
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError("refusing to overwrite an existing performance manifest")
    original_path = Path(collected["snapshot"]) / "benchmarks/manifest.json"
    manifest = json.loads(original_path.read_text())
    targets = {row["target_id"]: row for row in collected["targets"]}
    budget_records = []
    for program in manifest["programs"]:
        program["path"] = str((original_path.parent / program["path"]).resolve())
        for work in program["workloads"]:
            backend_steps = {backend: targets[_label(("corpus", program["id"], backend, work["id"]))]["accepted_steps"]
                             for backend in BACKENDS}
            old_budget = work["max_steps"]
            new_budget = max(old_budget, (max(backend_steps.values()) * 11 + 9) // 10 + 10000)
            work["max_steps"] = new_budget
            budget_records.append({"program": program["id"], "workload": work["id"],
                                   "verified_backend_steps": backend_steps,
                                   "original_max_steps": old_budget, "performance_max_steps": new_budget,
                                   "timeout_seconds_unchanged": work["timeout_seconds"]})
    manifest["correctness_budget_provenance"] = {
        "original_manifest_sha256": collected["manifest_sha256"],
        "reason": "Avoid known-insufficient target step budgets after independent normal-HALT verification.",
        "formula": "max(original, ceil(max verified steps across all backends * 1.10) + 10000)",
        "timeouts": "Original per-workload timeouts preserved; wall-clock timeouts remain censored.",
        "required_targets_passed": collected["required_targets"], "budgets": budget_records,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(manifest, indent=2) + "\n")


def postcheck_performance(accepted, report_path):
    """Compare fresh artifacts and completed Python-VM states with C evidence."""
    report_path = Path(report_path)
    report = json.loads(report_path.read_text())
    targets = {row["target_id"]: row for row in accepted["targets"]}
    issues, rows, images = [], [], []
    if not accepted["performance_gate_open"]:
        issues.append({"reason": "performance_started_before_correctness_acceptance"})
    for name in ("source_hashes_at_start", "source_hashes_at_end"):
        observed = report.get(name)
        if observed is not None and any(accepted["source_hashes_current"].get(path) != digest
                                        for path, digest in observed.items()):
            issues.append({"reason": "benchmark_source_fingerprint_mismatch", "field": name})
    if report.get("profiled"):
        issues.append({"reason": "profiled_execution_cannot_supply_normal_timings"})
    seen = set()
    for sample in report["samples"]:
        identity = (sample["program"], sample["backend"], sample["style"], sample["repeat"])
        compilation = sample.get("compile", {})
        compiled = "stages" in compilation
        image = compilation.get("image")
        accepted_group = [row for row in accepted["targets"]
                          if row["identity"]["kind"] == "corpus" and
                          row["identity"]["program"] == sample["program"] and
                          row["identity"]["backend"] == sample["backend"]]
        if not accepted_group:
            issues.append({"reason": "unexpected_benchmark_program", "sample": identity})
            continue
        image_matches = (compiled and image == accepted_group[0]["image"] and
                         sample.get("source_sha256") == accepted_group[0]["contract"]["source_sha256"])
        if compiled:
            images.append({"sample": identity, "image": image, "matches_accepted_gate": image_matches})
            if not image_matches:
                issues.append({"reason": "benchmark_image_identity_mismatch", "sample": identity,
                               "accepted": accepted_group[0]["image"], "observed": image})
        for work in sample["workloads"]:
            key = _label(("corpus", sample["program"], sample["backend"], work["id"]))
            unique = (key, sample["style"], sample["repeat"])
            if key not in targets or unique in seen:
                issues.append({"reason": "unexpected_or_duplicate_benchmark_workload", "target": key})
                continue
            seen.add(unique)
            target = targets[key]
            accepted_attempt = next(attempt for attempt in target["attempts"]
                                    if attempt["accepted"] and attempt["report"] == target["accepted_report"])
            reference = accepted_attempt["result"]
            runtime = work.get("runtime")
            measured = (runtime or {}).get("result", {})
            complete = measured.get("stop_reason") == "terminated"
            status = "pending"
            comparisons = None
            if runtime is not None:
                if runtime.get("error") == "timeout":
                    status = "child_timeout"
                elif complete:
                    comparisons = {
                        "output": measured.get("output_hex") == reference["stdout_hex"],
                        "input_consumed": measured.get("input_consumed") == reference["input_consumed"],
                        "steps": measured.get("steps") == reference["steps"],
                        "registers": measured.get("registers") == reference["registers"],
                        "image": image_matches,
                    }
                    status = "passed" if all(comparisons.values()) and runtime.get("passed") else "correctness_mismatch"
                    if status == "correctness_mismatch":
                        issues.append({"reason": status, "target": key, "comparisons": comparisons})
                elif measured.get("stop_reason") in ("step_limit", "output_limit", "input_exhausted"):
                    status = measured["stop_reason"]
                else:
                    status = "runtime_error"
                    issues.append({"reason": status, "target": key,
                                   "detail": runtime.get("error") or measured.get("stop_reason")})
            elif "compile" in sample and not compiled:
                status = "compile_error"
            if status in ("child_timeout", "step_limit", "output_limit", "input_exhausted"):
                leaked = [field for field in ("wall_seconds", "cpu_seconds", "execute_seconds",
                                              "execute_cpu_seconds", "process_peak_rss_bytes")
                          if field in runtime]
                if leaked:
                    issues.append({"reason": "censored_runtime_exposes_completed_metrics", "target": key, "fields": leaked})
            rows.append({"target_id": key, "style": sample["style"], "repeat": sample["repeat"],
                         "status": status, "reference_steps": reference["steps"],
                         "vm_steps": measured.get("steps") if complete else None,
                         "state_comparison": comparisons})
    counts = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {
        "schema_version": 1, "phase": "performance_postcheck", "report": str(report_path),
        "run_state": report.get("run_state"), "expected_compiles": 36, "expected_target_runs": 96,
        "observed_compiles": len(images), "observed_workloads": len(rows), "classifications": counts,
        "all_images_match": all(image["matches_accepted_gate"] for image in images),
        "all_requested_attempted": len(rows) == 96 and all(row["status"] != "pending" for row in rows),
        "complete_runtime_samples_match_reference": not issues,
        "issues": issues, "images": images, "workloads": rows,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--performance-manifest", type=Path)
    parser.add_argument("--performance-report", type=Path)
    args = parser.parse_args(argv)
    result = collect(args.run_dir)
    output = args.output or args.run_dir / "correctness-acceptance.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, indent=2) + "\n")
    temporary.replace(output)
    if args.performance_manifest:
        write_derived_manifest(result, args.performance_manifest)
    if args.performance_report:
        checked = postcheck_performance(result, args.performance_report)
        (args.performance_report.parent / "reference-postcheck.json").write_text(json.dumps(checked, indent=2) + "\n")
    progress = {
        "schema_version": 1, "updated_utc": datetime.now(timezone.utc).isoformat(),
        "phase": "correctness", "run_state": "ready_for_performance" if result["performance_gate_open"] else "waiting_for_correctness",
        "accepted_targets": result["unique_passed_targets"], "required_targets": result["required_targets"],
        "performance_gate_open": result["performance_gate_open"],
        "correctness_anomalies": result["anomalies"],
        "pending_targets": [row["target_id"] for row in result["targets"] if not row["passed"]],
        "active_correctness_workers": [{"report": item["path"], "active": item["active"]}
                                        for item in result["reports"] if not item["completed"]],
    }
    if args.performance_report:
        performance = json.loads(args.performance_report.read_text())
        progress.update(phase="performance", run_state=performance.get("run_state"),
                        active=performance.get("active"),
                        attempted_target_runs=performance.get("attempted_target_runs"),
                        completed_target_runs=performance.get("completed_target_runs"),
                        passed_target_runs=performance.get("passed_target_runs"),
                        completed_program_compiles=performance.get("completed_program_compiles"),
                        classifications=checked["classifications"], postcheck_issues=checked["issues"])
    progress_path = args.run_dir / "progress.json"
    temporary_progress = progress_path.with_suffix(".json.tmp")
    temporary_progress.write_text(json.dumps(progress, indent=2) + "\n")
    temporary_progress.replace(progress_path)
    print(json.dumps({key: result[key] for key in (
        "required_targets", "unique_passed_targets", "total_attempts_preserved",
        "original_unsuccessful_attempts_preserved", "all_correctness_workers_complete",
        "performance_gate_open", "anomalies")}))
    for row in result["targets"]:
        if not row["passed"]:
            print(json.dumps({"pending": row["target_id"], "attempts": len(row["attempts"])}))
    return 0 if result["performance_gate_open"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
