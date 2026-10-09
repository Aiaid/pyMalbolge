"""Check benchmark contracts without turning routine tests into a speed test."""

import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

from malbolge.compiler import (
    compile_c_to_mg,
    compile_python_to_c,
    compile_python_to_mg,
    compile_python_to_mb,
    translate_mg_to_mc,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "benchmarks/manifest.json"
CORPUS = json.loads(MANIFEST.read_text(encoding="utf8"))
PROGRAMS = CORPUS["programs"]
BACKENDS = ("c", "direct")


def source(program):
    return (MANIFEST.parent / program["path"]).read_text(encoding="utf8")


def lower_mg(text, backend):
    if backend == "c":
        return compile_c_to_mg(compile_python_to_c(text))
    return compile_python_to_mg(text)


def test_manifest_contract_and_source_inventory():
    assert set(CORPUS) == {"schema_version", "description", "programs"}
    assert CORPUS["schema_version"] == 1
    assert isinstance(CORPUS["description"], str) and CORPUS["description"]
    assert PROGRAMS
    assert len({program["id"] for program in PROGRAMS}) == len(PROGRAMS)
    declared = set()
    for program in PROGRAMS:
        assert set(program) == {"id", "path", "description", "tags", "tier", "workloads"}
        assert re.fullmatch(r"[a-z][a-z0-9_]*", program["id"])
        assert program["tier"] in {"smoke", "standard", "stress"}
        assert isinstance(program["description"], str) and program["description"]
        assert program["tags"] and all(isinstance(tag, str) for tag in program["tags"])
        path = (MANIFEST.parent / program["path"]).resolve()
        assert path.parent == (MANIFEST.parent / "programs").resolve()
        assert path.suffix == ".py" and path.is_file()
        assert path not in declared
        declared.add(path)
        assert program["workloads"]
        ids = [workload["id"] for workload in program["workloads"]]
        assert len(ids) == len(set(ids))
        for workload in program["workloads"]:
            assert set(workload) == {"id", "stdin", "stdout", "max_steps", "timeout_seconds"}
            assert re.fullmatch(r"[a-z][a-z0-9_]*", workload["id"])
            assert isinstance(workload["stdin"], str) and workload["stdin"].isascii()
            assert isinstance(workload["stdout"], str) and workload["stdout"].isascii()
            assert type(workload["max_steps"]) is int and workload["max_steps"] >= 0
            assert type(workload["timeout_seconds"]) is int and workload["timeout_seconds"] > 0
    assert declared == set((MANIFEST.parent / "programs").glob("*.py"))
    assert sum(program["tier"] == "smoke" for program in PROGRAMS) >= 2


@pytest.mark.parametrize("program", PROGRAMS, ids=lambda program: program["id"])
def test_cpython_oracles(program):
    for workload in program["workloads"]:
        result = subprocess.run(
            [sys.executable, str(MANIFEST.parent / program["path"])],
            input=workload["stdin"].encode("ascii"),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
        )
        assert result.returncode == 0, result.stderr.decode("utf8", errors="replace")
        assert result.stderr == b""
        assert result.stdout == workload["stdout"].encode("ascii"), workload["id"]


def test_matched_fibonacci_and_multiplication_workloads():
    by_id = {program["id"]: program for program in PROGRAMS}
    iterative = by_id["fibonacci_iterative"]["workloads"]
    recursive = by_id["fibonacci_recursive"]["workloads"]
    assert [(w["id"], w["stdin"], w["stdout"]) for w in iterative] == [
        (w["id"], w["stdin"], w["stdout"]) for w in recursive]
    literal = by_id["multiply_literal"]["workloads"]
    dynamic = by_id["multiply_dynamic"]["workloads"]
    assert [(w["id"], w["stdin"] + "17\n", w["stdout"]) for w in literal] == [
        (w["id"], w["stdin"], w["stdout"]) for w in dynamic]


@pytest.mark.parametrize("program", PROGRAMS, ids=lambda program: program["id"])
@pytest.mark.parametrize("backend", BACKENDS)
def test_frontend_accepts_every_program(program, backend):
    assert lower_mg(source(program), backend).strip()


@pytest.mark.parametrize("program", PROGRAMS, ids=lambda program: program["id"])
@pytest.mark.parametrize("backend", BACKENDS)
def test_mc_lowering(program, backend):
    assert translate_mg_to_mc(lower_mg(source(program), backend)).strip()


@pytest.mark.parametrize("program", [p for p in PROGRAMS if p["tier"] == "smoke"],
                         ids=lambda program: program["id"])
@pytest.mark.parametrize("backend", BACKENDS)
def test_tiny_smoke_vm(program, backend):
    from malbolge.core import MalbolgeConfig, SparseMemory, parse_source, run_memory

    image = compile_python_to_mb(source(program), backend=backend)
    config = MalbolgeConfig.malbolge20()
    for workload in program["workloads"]:
        memory = SparseMemory(config)
        memory.initialize_source(parse_source(image, config))
        result = run_memory(memory, config, workload["stdin"].encode("ascii"),
                            max_steps=workload["max_steps"], max_output=1024)
        assert result.stop_reason == "terminated"
        assert result.output == workload["stdout"].encode("ascii")
