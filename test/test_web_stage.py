"""Verify the public browser artifact allowlist without packaging or a network."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
WHEEL = "malbolge-1.0.0-py3-none-any.whl"
RUNTIME = {
    "index.html", "bridge.js", "worker.js", "theme.js",
    "screens/launch.js", "screens/debugger.js", "vendor/build.json",
    "vendor/manifest.json", "vendor/" + WHEEL, "vendor/examples/hello.mal",
}


@pytest.fixture
def browser_stage(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("browser staging tests require Node.js")
    root = tmp_path / "repo"
    web = root / "web"
    web.mkdir(parents=True)
    shutil.copy2(ROOT / "web/stage.mjs", web / "stage.mjs")
    for name in RUNTIME | {
        "README.md", "smoke.mjs", "node_modules/private.txt",
        "screens/debugger.dev.html", "screens/debugger.dev.fixtures.py",
        "vendor/old.whl", "vendor/examples/unlisted.mal", "vendor/private.txt",
    }:
        path = web / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture: " + name, encoding="utf8")
    (web / "vendor/build.json").write_text(json.dumps({"wheel": WHEEL}), encoding="utf8")
    (web / "vendor/manifest.json").write_text(json.dumps({
        "programs": [{"file": "hello.mal"}],
    }), encoding="utf8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    def invoke(*args):
        return subprocess.run([node, str(web / "stage.mjs"), *map(str, args)],
                              cwd=str(elsewhere), capture_output=True, text=True, timeout=20)

    return root, web, elsewhere, invoke


@pytest.mark.parametrize("explicit", [False, True])
def test_stages_only_runtime_files_from_any_working_directory(browser_stage, explicit):
    root, web, elsewhere, invoke = browser_stage
    output = elsewhere / "public" if explicit else root / "_site"
    completed = invoke("public") if explicit else invoke()
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert {path.relative_to(output).as_posix() for path in output.rglob("*")
            if path.is_file()} == RUNTIME
    for name in RUNTIME:
        assert (output / name).read_bytes() == (web / name).read_bytes()


@pytest.mark.parametrize("wheel", ["../private.whl", "/tmp/private.whl",
                                   "C:\\private.whl", "malbolge-1.0-cp313-linux.whl", None])
def test_rejects_unsafe_or_nonportable_wheel_names(browser_stage, wheel):
    root, web, _, invoke = browser_stage
    (web / "vendor/build.json").write_text(json.dumps({"wheel": wheel}), encoding="utf8")
    completed = invoke()
    assert completed.returncode != 0
    assert "portable malbolge wheel" in completed.stderr
    assert not (root / "_site").exists()


@pytest.mark.parametrize("example", ["../private.mal", "/tmp/private.mal", "C:\\private.mal",
                                     "hello.py", "nested/hello.mal", None])
def test_rejects_unsafe_example_names(browser_stage, example):
    root, web, _, invoke = browser_stage
    (web / "vendor/manifest.json").write_text(json.dumps({
        "programs": [{"file": example}],
    }), encoding="utf8")
    completed = invoke()
    assert completed.returncode != 0
    assert ".mal files without paths" in completed.stderr
    assert not (root / "_site").exists()


@pytest.mark.parametrize("name,contents", [
    ("build.json", "{"), ("manifest.json", "{"),
    ("manifest.json", '{"programs": {}}'),
])
def test_rejects_malformed_metadata_before_output_creation(browser_stage, name, contents):
    root, web, _, invoke = browser_stage
    (web / "vendor" / name).write_text(contents, encoding="utf8")
    completed = invoke()
    assert completed.returncode != 0
    assert not (root / "_site").exists()


@pytest.mark.parametrize("name", ["worker.js", "vendor/" + WHEEL,
                                  "vendor/examples/hello.mal"])
def test_missing_input_fails_before_output_creation(browser_stage, name):
    root, web, _, invoke = browser_stage
    (web / name).unlink()
    completed = invoke()
    assert completed.returncode != 0
    assert not (root / "_site").exists()


def test_refuses_existing_nonempty_output_without_modifying_it(browser_stage):
    root, _, _, invoke = browser_stage
    output = root / "_site"
    output.mkdir()
    (output / "keep.txt").write_text("user contents", encoding="utf8")
    completed = invoke()
    assert completed.returncode != 0
    assert "existing contents were preserved" in completed.stderr
    assert sorted(path.name for path in output.iterdir()) == ["keep.txt"]
    assert (output / "keep.txt").read_text() == "user contents"


@pytest.mark.parametrize("name", ["worker.js", "vendor/examples"])
def test_rejects_symlink_input_files_and_directories(browser_stage, name):
    root, web, elsewhere, invoke = browser_stage
    target = elsewhere / "external"
    path = web / name
    if path.is_dir():
        shutil.move(str(path), str(target))
        path.symlink_to(target, target_is_directory=True)
    else:
        path.rename(target)
        path.symlink_to(target)
    completed = invoke()
    assert completed.returncode != 0
    assert "symlink input" in completed.stderr
    assert not (root / "_site").exists()


def test_accepts_existing_empty_output(browser_stage):
    root, _, _, invoke = browser_stage
    (root / "_site").mkdir()
    completed = invoke()
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_refuses_output_symlink_without_writing_through_it(browser_stage):
    root, _, elsewhere, invoke = browser_stage
    target = elsewhere / "external"
    target.mkdir()
    (root / "_site").symlink_to(target, target_is_directory=True)
    completed = invoke()
    assert completed.returncode != 0
    assert list(target.iterdir()) == []
    assert (root / "_site").is_symlink()
