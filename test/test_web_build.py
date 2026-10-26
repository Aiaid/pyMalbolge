"""Exercise the browser build's wheel selection without packaging or a compiler."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
PORTABLE = "malbolge-1.0.1-py3-none-any.whl"
STALE = "malbolge-0.0.0-py3-none-any.whl"


@pytest.fixture
def browser_build(tmp_path):
    if os.name == "nt":
        pytest.skip("fake uv executable uses a POSIX shebang and executable permissions")
    node = shutil.which("node")
    if node is None:
        pytest.skip("browser build regression tests require Node.js")
    root = tmp_path / "repo"
    (root / "web").mkdir(parents=True)
    shutil.copy2(ROOT / "web/build.mjs", root / "web/build.mjs")
    sources = {
        "malbolge/__init__.py": "",
        "scripts/hatch_native.py": "# fixture build hook\n",
        "pyproject.toml": '[project]\nname = "malbolge"\nversion = "1.0.1"\n',
        "README.md": "Fixture package\n",
        "README.zh.md": "Fixture package\n",
        "LICENSE": "Fixture license\n",
    }
    old = time.time() - 100
    for relative, contents in sources.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf8")
        os.utime(path, (old, old))
    (root / "examples").mkdir()
    (root / "examples/hello.mal").write_text("hello fixture", encoding="utf8")
    (root / "examples/manifest.json").write_text(json.dumps({
        "variant": "original", "programs": [{"file": "hello.mal"}],
    }), encoding="utf8")
    (root / "dist").mkdir()
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    fake_uv = binary_dir / "uv"
    fake_uv.write_text("#!/usr/bin/env node\n" + r'''
const fs = require("node:fs");
fs.writeFileSync("uv-call.json", JSON.stringify({
  args: process.argv.slice(2), mode: process.env.MALBOLGE_NATIVE_BUILD,
}));
if (process.env.FAKE_UV_RESULT !== "unchanged") {
  const portable = process.env.FAKE_UV_RESULT !== "native"
    && process.env.MALBOLGE_NATIVE_BUILD === "disabled";
  const name = portable ? "malbolge-1.0.1-py3-none-any.whl"
    : "malbolge-1.0.1-cp313-cp313-macosx_11_0_arm64.whl";
  fs.writeFileSync("dist/" + name, "fresh fixture wheel");
}
''', encoding="utf8")
    fake_uv.chmod(0o755)

    def invoke(*args, result="portable"):
        env = dict(os.environ, PATH=str(binary_dir) + os.pathsep + os.environ.get("PATH", ""),
                   MALBOLGE_NATIVE_BUILD="required", FAKE_UV_RESULT=result)
        return subprocess.run([node, str(root / "web/build.mjs"), *args], cwd=str(root),
                              env=env, capture_output=True, text=True, timeout=20)

    return root, old, invoke


def stale_wheel(root, timestamp):
    path = root / "dist" / STALE
    path.write_text("stale fixture wheel", encoding="utf8")
    os.utime(path, (timestamp, timestamp))


def test_browser_build_overrides_native_policy_and_copies_fresh_portable(browser_build):
    root, old, invoke = browser_build
    stale_wheel(root, old - 10)
    completed = invoke()
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads((root / "uv-call.json").read_text()) == {
        "args": ["build", "--wheel"], "mode": "disabled",
    }
    info = json.loads((root / "web/vendor/build.json").read_text())
    assert info["wheel"] == PORTABLE
    assert info["version"] == "1.0.1"
    assert (root / "web/vendor" / PORTABLE).read_text() == "fresh fixture wheel"
    assert not (root / "web/vendor" / STALE).exists()
    assert (root / "web/vendor/examples/hello.mal").read_text() == "hello fixture"


@pytest.mark.parametrize("result,existing_stale", [("native", False), ("unchanged", True)])
def test_successful_uv_without_fresh_portable_preserves_vendor(browser_build, result, existing_stale):
    root, old, invoke = browser_build
    if existing_stale:
        stale_wheel(root, old - 10)
    vendor = root / "web/vendor"
    vendor.mkdir()
    sentinel = vendor / "build.json"
    sentinel.write_text("previous build metadata", encoding="utf8")
    completed = invoke("--clean", result=result)
    assert completed.returncode != 0
    assert "up-to-date py3-none-any wheel" in completed.stderr
    assert sentinel.read_text() == "previous build metadata"
    assert sorted(path.name for path in vendor.iterdir()) == ["build.json"]


@pytest.mark.parametrize("changed", [
    "scripts/hatch_native.py", "pyproject.toml", "README.md", "README.zh.md", "LICENSE",
])
def test_package_metadata_and_build_script_changes_trigger_rebuild(browser_build, changed):
    root, old, invoke = browser_build
    stale_wheel(root, old + 10)
    os.utime(root / changed, (old + 20, old + 20))
    completed = invoke()
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert (root / "uv-call.json").is_file(), "newer package input must invoke uv"
    info = json.loads((root / "web/vendor/build.json").read_text())
    assert info["wheel"] == PORTABLE


@pytest.mark.parametrize("args,offset", [((), 10), (("--no-build",), -10)])
def test_reuses_existing_portable_without_invoking_uv(browser_build, args, offset):
    root, old, invoke = browser_build
    stale_wheel(root, old + offset)
    completed = invoke(*args)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert not (root / "uv-call.json").exists()
    info = json.loads((root / "web/vendor/build.json").read_text())
    assert info["wheel"] == STALE
    assert (root / "web/vendor" / STALE).read_text() == "stale fixture wheel"
    if args:
        assert "--no-build was given" in completed.stdout
