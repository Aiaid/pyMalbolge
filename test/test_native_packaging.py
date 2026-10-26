"""Native build policy and distributable artifact contracts.

Core tests need no compiler or packaging dependencies. Set
MALBOLGE_PACKAGING_TESTS=1 to additionally rebuild an extracted sdist, inspect
wheel metadata/RECORD, and install both native and pure wheels into fresh
targets. That acceptance test needs uv, the build-system dependencies in the
test interpreter, and a working host C compiler.
"""

import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import sysconfig
import tarfile
import types
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
CPYTHON_TAG = "cp{}{}".format(sys.version_info.major, sys.version_info.minor)
MACOS_WHEEL_TAG = CPYTHON_TAG + "-" + CPYTHON_TAG + "-macosx_11_0_arm64"


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def builder():
    return load_script("native_build")


@pytest.fixture
def hook_factory(monkeypatch, tmp_path, builder):
    """Exercise the hook itself without silently skipping for missing Hatchling."""
    class BuildHookInterface:
        def __init__(self, root, config, build_config, metadata, directory, target_name, app):
            self.root = root
            self.config = config
            self.build_config = build_config
            self.metadata = metadata
            self.directory = directory
            self.target_name = target_name
            self.app = app

    for name in ("hatchling", "hatchling.builders", "hatchling.builders.hooks",
                 "hatchling.builders.hooks.plugin", "hatchling.builders.hooks.plugin.interface"):
        module = types.ModuleType(name)
        module.__path__ = []
        monkeypatch.setitem(sys.modules, name, module)
    sys.modules["hatchling.builders.hooks.plugin.interface"].BuildHookInterface = BuildHookInterface
    monkeypatch.setitem(sys.modules, "native_build", builder)
    monkeypatch.setitem(sys.modules, "scripts.native_build", builder)
    hook_module = load_script("hatch_native")
    messages = []
    app = types.SimpleNamespace(display_warning=messages.append, display_info=messages.append,
                                display_error=messages.append, display=messages.append)
    source = tmp_path / "source"
    source.mkdir()
    (source / "malbolge").mkdir()
    for name in ("_native_vm.stale.so", "_native_vm.stale.pyd"):
        (source / "malbolge" / name).write_bytes(b"old binary")
    destination = tmp_path / "dist"
    destination.mkdir()

    def make(mode="auto", target="wheel"):
        monkeypatch.setenv("MALBOLGE_NATIVE_BUILD", mode)
        hook = hook_module.NativeBuildHook(str(source), {}, None, None,
                                           str(destination), target, app)
        data = {"force_include": {}, "artifacts": [], "pure_python": True, "infer_tag": False}
        return hook, data

    return make, builder, hook_module, source, messages


def mock_build(monkeypatch, factory, callback):
    _, builder, hook_module, _, _ = factory
    monkeypatch.setattr(builder, "build_native_extension", callback)
    # Accommodate a normal from-import without hiding any build result checks.
    if hasattr(hook_module, "build_native_extension"):
        monkeypatch.setattr(hook_module, "build_native_extension", callback)


@pytest.mark.parametrize("mode,target,version", [
    ("disabled", "wheel", "standard"), ("required", "sdist", "standard"),
    ("auto", "wheel", "editable"), ("disabled", "wheel", "editable"),
])
def test_non_native_modes_never_compile(monkeypatch, hook_factory, mode, target, version):
    def forbidden(*args, **kwargs):
        pytest.fail("compiler invoked for a source/pure/editable build")

    mock_build(monkeypatch, hook_factory, forbidden)
    hook, data = hook_factory[0](mode, target)
    hook.initialize(version, data)
    assert data["pure_python"] is True
    assert not data["force_include"]
    assert not data["infer_tag"]


@pytest.mark.parametrize("mode", ["auto", "required"])
def test_compiler_failure_policy_is_explicit(monkeypatch, hook_factory, capsys, mode):
    _, _, hook_module, _, messages = hook_factory

    def unavailable(*args, **kwargs):
        raise hook_module.NativeBuildError("test compiler unavailable")

    mock_build(monkeypatch, hook_factory, unavailable)
    hook, data = hook_factory[0](mode)
    if mode == "required":
        with pytest.raises(RuntimeError, match="test compiler unavailable"):
            hook.initialize("standard", data)
    else:
        hook.initialize("standard", data)
        captured = capsys.readouterr()
        assert "test compiler unavailable" in "\n".join(messages) + captured.err + captured.out
    assert data["pure_python"] is True
    assert not data["force_include"]


def test_auto_does_not_swallow_unrelated_packaging_errors(monkeypatch, hook_factory):
    def broken_package(*args, **kwargs):
        raise ValueError("broken package mapping")

    mock_build(monkeypatch, hook_factory, broken_package)
    hook, data = hook_factory[0]("auto")
    with pytest.raises(ValueError, match="broken package mapping"):
        hook.initialize("standard", data)


def test_required_editable_is_rejected(monkeypatch, hook_factory):
    mock_build(monkeypatch, hook_factory, lambda *args, **kwargs: pytest.fail("unexpected build"))
    hook, data = hook_factory[0]("required")
    with pytest.raises(RuntimeError, match="(?i)editable"):
        hook.initialize("editable", data)


def test_invalid_policy_is_rejected(hook_factory):
    hook, data = hook_factory[0]("requiredd")
    with pytest.raises(ValueError, match="(?i)(MALBOLGE_NATIVE_BUILD|mode|policy)"):
        hook.initialize("standard", data)


def test_success_includes_only_fresh_staged_binary(monkeypatch, hook_factory):
    _, _, hook_module, source, _ = hook_factory
    compiled = []
    newer_host_tag = MACOS_WHEEL_TAG.replace("macosx_11_0", "macosx_14_0")
    supported = hook_module.parse_tag(newer_host_tag) | hook_module.parse_tag(MACOS_WHEEL_TAG)
    monkeypatch.setattr(hook_module, "sys_tags", lambda: iter(supported))

    def successful(root, output_dir, compiler=None):
        assert Path(root) == source
        binary = Path(output_dir) / ("_native_vm" + sysconfig.get_config_var("EXT_SUFFIX"))
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_bytes(b"newly compiled binary")
        compiled.append(binary)
        return {"binary": str(binary), "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                "extension_suffix": sysconfig.get_config_var("EXT_SUFFIX"), "wheel_tag": MACOS_WHEEL_TAG}

    mock_build(monkeypatch, hook_factory, successful)
    hook, data = hook_factory[0]("required")
    hook.initialize("standard", data)
    assert len(compiled) == 1
    binary = compiled[0]
    assert binary.parent != source / "malbolge"
    assert data["force_include"] == {str(binary): "malbolge/" + binary.name}
    assert data["pure_python"] is False
    assert data["infer_tag"] is True
    # Preserve the compiler's deployment floor rather than inferring the host OS version.
    assert data["tag"] == MACOS_WHEEL_TAG
    hook.finalize("standard", data, "unused-wheel-path.whl")
    assert not binary.exists()
    assert (source / "malbolge/_native_vm.stale.so").read_bytes() == b"old binary"


@pytest.mark.parametrize("tag", [None, "py3-none-any", CPYTHON_TAG + "-abi3-macosx_11_0_arm64",
                                 CPYTHON_TAG + "-" + CPYTHON_TAG + "-any", "malformed-tag",
                                 "cp999-cp999-macosx_11_0_arm64",
                                 CPYTHON_TAG + "-" + CPYTHON_TAG + "-unverified_target"])
def test_invalid_compiler_wheel_tag_cannot_create_native_wheel(monkeypatch, hook_factory, tag):
    binaries = []

    def bad_receipt(root, output_dir, compiler=None):
        binary = Path(output_dir) / ("_native_vm" + sysconfig.get_config_var("EXT_SUFFIX"))
        binary.write_bytes(b"newly compiled binary")
        binaries.append(binary)
        receipt = {"binary": str(binary)}
        if tag is not None:
            receipt["wheel_tag"] = tag
        return receipt

    mock_build(monkeypatch, hook_factory, bad_receipt)
    hook, data = hook_factory[0]("auto")
    with pytest.raises((ValueError, RuntimeError, KeyError), match="(?i)(wheel.?tag|native.*tag)"):
        hook.initialize("standard", data)
    assert data["pure_python"] is True
    assert not data["force_include"]
    assert not any(binary.exists() for binary in binaries)


@pytest.fixture
def native_source(tmp_path, monkeypatch, builder):
    source = tmp_path / "source"
    (source / "malbolge").mkdir(parents=True)
    (source / "malbolge/_native_vm.c").write_bytes(b"native C source")
    (source / "malbolge/_native_jit.h").write_bytes(b"JIT header dependency")
    headers = tmp_path / "headers"
    headers.mkdir()
    (headers / "Python.h").write_bytes(b"controlled Python headers")
    monkeypatch.setattr(builder.sysconfig, "get_path", lambda name: str(headers))
    monkeypatch.setattr(builder.sysconfig, "get_config_var", lambda name: ".test.so")
    return source


def worker_result(argv, *, env, cwd, payload=b"fresh binary", mutate=None, missing=False, **kwargs):
    temporary = Path(argv[3])
    assert Path(cwd) == temporary
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert temporary.name.startswith(".native-build-")
    binary = temporary / "lib/malbolge/_native_vm.test.so"
    binary.parent.mkdir(parents=True)
    if not missing:
        binary.write_bytes(payload)
    record = {"binary": str(binary), "compiler": "test-cc", "compiler_version": "test version",
              "compiler_flags": ["-O3", "-std=c99"], "compiler_argv": [["test-cc", "-O3"]],
              "wheel_tag": MACOS_WHEEL_TAG}
    Path(argv[4]).write_text(json.dumps(record), encoding="utf8")
    if mutate:
        mutate()
    return subprocess.CompletedProcess(argv, 0, b"compiler stdout", b"compiler stderr")


def test_builder_receipt_hashes_the_new_binary_and_all_sources(monkeypatch, builder, native_source, tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    target = output / "_native_vm.test.so"
    target.write_bytes(b"stale destination")

    def compile_worker(argv, **kwargs):
        assert kwargs["env"]["CC"] == "test compiler override"
        return worker_result(argv, **kwargs)

    monkeypatch.setattr(builder.subprocess, "run", compile_worker)
    receipt = builder.build_native_extension(native_source, output, compiler="test compiler override")
    assert target.read_bytes() == b"fresh binary"
    assert receipt["binary"] == str(target)
    assert receipt["binary_sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
    assert receipt["source_hashes"] == {
        "malbolge/" + name: hashlib.sha256((native_source / "malbolge" / name).read_bytes()).hexdigest()
        for name in ("_native_vm.c", "_native_jit.h")
    }
    assert receipt["source_sha256"] == receipt["source_hashes"]["malbolge/_native_vm.c"]
    assert receipt["python"] == sys.version
    assert receipt["compiler_flags"] == ["-O3", "-std=c99"]
    assert receipt["wheel_tag"] == MACOS_WHEEL_TAG
    assert receipt["build_wall_seconds"] >= 0
    assert list(output.iterdir()) == [target]
    assert not (native_source / "build").exists()


@pytest.mark.parametrize("platform_name,explicit_archflags,expected_archflags", [
    ("darwin", None, "-arch arm64"),
    ("darwin", "-arch x86_64", "-arch x86_64"),
    ("linux", None, None),
])
def test_native_archflags_default_is_child_only_and_preserves_user_environment(
        monkeypatch, builder, native_source, tmp_path,
        platform_name, explicit_archflags, expected_archflags):
    monkeypatch.setattr(builder, "sys", types.SimpleNamespace(
        implementation=sys.implementation, platform=platform_name,
        executable=sys.executable, version=sys.version))
    monkeypatch.setattr(builder.platform, "machine", lambda: "arm64")
    if explicit_archflags is None:
        monkeypatch.delenv("ARCHFLAGS", raising=False)
    else:
        monkeypatch.setenv("ARCHFLAGS", explicit_archflags)
    monkeypatch.setenv("CFLAGS", "-O0 -g")
    monkeypatch.setenv("SDKROOT", "controlled-user-sdk")
    original_environment = dict(os.environ)

    def compile_worker(argv, **kwargs):
        child_environment = kwargs["env"]
        assert child_environment.get("ARCHFLAGS") == expected_archflags
        assert child_environment["CFLAGS"] == original_environment["CFLAGS"]
        assert child_environment["SDKROOT"] == original_environment["SDKROOT"]
        assert child_environment is not os.environ
        return worker_result(argv, **kwargs)

    monkeypatch.setattr(builder.subprocess, "run", compile_worker)
    builder.build_native_extension(native_source, tmp_path / "output")
    assert dict(os.environ) == original_environment


@pytest.mark.parametrize("failure", ["compiler", "timeout", "missing_binary", "source_changed"])
def test_failed_builder_preserves_previous_binary_and_cleans_stage(
        monkeypatch, builder, native_source, tmp_path, failure):
    output = tmp_path / "output"
    output.mkdir()
    target = output / "_native_vm.test.so"
    target.write_bytes(b"previous known binary")

    def broken_worker(argv, **kwargs):
        if failure == "compiler":
            return subprocess.CompletedProcess(argv, 1, b"", b"compiler intentionally failed")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 120)
        mutate = None
        if failure == "source_changed":
            mutate = lambda: (native_source / "malbolge/_native_jit.h").write_bytes(b"edited header")
        return worker_result(argv, mutate=mutate, missing=failure == "missing_binary", **kwargs)

    monkeypatch.setattr(builder.subprocess, "run", broken_worker)
    with pytest.raises(builder.NativeBuildError):
        builder.build_native_extension(native_source, output)
    assert target.read_bytes() == b"previous known binary"
    assert list(output.iterdir()) == [target]


def test_missing_source_dependency_never_uses_checkout_binary(monkeypatch, builder, native_source, tmp_path):
    (native_source / "malbolge/_native_vm.test.so").write_bytes(b"stale checkout extension")
    (native_source / "malbolge/_native_jit.h").unlink()
    monkeypatch.setattr(builder.subprocess, "run", lambda *args, **kwargs: pytest.fail("unexpected worker"))
    with pytest.raises(builder.NativeBuildError, match="_native_jit.h"):
        builder.build_native_extension(native_source, tmp_path / "output")


@pytest.fixture
def host_target_environment(monkeypatch, builder):
    for name in ("ARCHFLAGS", "CFLAGS", "CPPFLAGS", "LDFLAGS", "CC", "LDSHARED",
                 "_PYTHON_HOST_PLATFORM", "_PYTHON_SYSCONFIGDATA_NAME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(builder, "os", types.SimpleNamespace(environ=os.environ, name="posix"))
    monkeypatch.setattr(builder.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(builder.sysconfig, "get_platform", lambda: "macosx-11.0-arm64")
    monkeypatch.setattr(builder.struct, "calcsize", lambda format: 8)
    return builder


@pytest.mark.parametrize("variable,value", [
    ("ARCHFLAGS", "-arch x86_64"), ("CFLAGS", "--target=x86_64-linux-gnu"),
    ("CC", "cc -target aarch64"), ("LDFLAGS", "-m32"),
    ("_PYTHON_HOST_PLATFORM", "win-arm64"),
    ("_PYTHON_SYSCONFIGDATA_NAME", "target-custom-sysconfig"),
])
def test_cross_target_requests_are_rejected_before_compilation(
        monkeypatch, host_target_environment, variable, value):
    monkeypatch.setenv(variable, value)
    builder = host_target_environment
    with pytest.raises(builder.NativeBuildError, match="(?i)(cross-target|target triples|target Python)"):
        builder._validate_host_target()
    assert os.environ[variable] == value


def test_host_architecture_and_platform_overrides_remain_valid(monkeypatch, host_target_environment):
    monkeypatch.setenv("ARCHFLAGS", "-arch arm64")
    monkeypatch.setenv("_PYTHON_HOST_PLATFORM", "macosx-11.0-arm64")
    host_target_environment._validate_host_target()
    assert os.environ["_PYTHON_HOST_PLATFORM"] == "macosx-11.0-arm64"


def test_msvc_custom_cc_is_explicitly_rejected(monkeypatch, host_target_environment):
    builder = host_target_environment
    monkeypatch.setattr(builder, "os", types.SimpleNamespace(environ=os.environ, name="nt"))
    monkeypatch.setenv("CC", "clang-cl")
    with pytest.raises(builder.NativeBuildError, match="(?i)(CC|MSVC)"):
        builder._validate_host_target()


def test_universal2_python_allows_the_host_slice_override(monkeypatch, host_target_environment):
    builder = host_target_environment
    monkeypatch.setattr(builder, "sys", types.SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(builder.sysconfig, "get_platform", lambda: "macosx-10.9-universal2")
    monkeypatch.setenv("_PYTHON_HOST_PLATFORM", "macosx-11.0-arm64")
    monkeypatch.setenv("ARCHFLAGS", "-arch arm64")
    builder._validate_host_target()
    assert os.environ["_PYTHON_HOST_PLATFORM"] == "macosx-11.0-arm64"


def macho_header(cpu_type=0x0100000c, cpu_subtype=0, byte_order="<"):
    # mach_header_64: MH_MAGIC_64, cpu type/subtype, MH_BUNDLE, commands, flags, reserved.
    return struct.pack(byte_order + "8I", 0xfeedfacf, cpu_type, cpu_subtype, 8, 0, 0, 0, 0)


@pytest.mark.parametrize("architecture,cpu_type,cpu_subtype", [
    ("arm64", 0x0100000c, 0), ("x86_64", 0x01000007, 3),
])
@pytest.mark.parametrize("byte_order", ["<", ">"])
def test_thin_macho_tag_uses_binary_architecture_and_keeps_deployment_floor(
        monkeypatch, builder, tmp_path, architecture, cpu_type, cpu_subtype, byte_order):
    monkeypatch.setattr(builder.platform, "machine", lambda: architecture)
    binary = tmp_path / "thin-extension.so"
    binary.write_bytes(macho_header(cpu_type, cpu_subtype, byte_order))
    universal = CPYTHON_TAG + "-" + CPYTHON_TAG + "-macosx_11_0_universal2"
    assert builder._macos_native_tag(binary, universal) == universal.replace("universal2", architecture)


@pytest.mark.parametrize("header", [
    b"\xca\xfe\xba\xbe" + bytes(28),  # Fat Mach-O with multiple slices.
    b"\xca\xfe\xba\xbf" + bytes(28),  # 64-bit fat container.
    b"BAD!" + bytes(28),
    macho_header()[:24],
    macho_header(0x01000007, 3),  # x86_64 binary on an ARM64 host.
    macho_header(0x0100000c, 2),  # ARM64e cannot be advertised as ordinary arm64.
    macho_header(0x01000012, 0),  # Unknown/unsupported CPU type.
], ids=["fat", "fat64", "unknown-magic", "truncated", "nonhost", "arm64e", "unknown-cpu"])
def test_unsupported_macho_images_do_not_get_host_wheel_tags(monkeypatch, builder, tmp_path, header):
    monkeypatch.setattr(builder.platform, "machine", lambda: "arm64")
    binary = tmp_path / "invalid-extension.so"
    binary.write_bytes(header)
    with pytest.raises(builder.NativeBuildError, match="(?i)(Mach-O|architecture)"):
        builder._macos_native_tag(binary, MACOS_WHEEL_TAG)


def packaging_source(destination):
    """Copy public build inputs, then plant controlled excluded products."""
    destination.mkdir()
    shutil.copytree(ROOT / "malbolge", destination / "malbolge",
                    ignore=shutil.ignore_patterns("__pycache__", "*.so", "*.pyd"))
    (destination / "scripts").mkdir()
    for name in ("native_build.py", "hatch_native.py"):
        shutil.copy2(ROOT / "scripts" / name, destination / "scripts" / name)
    for name in ("pyproject.toml", "README.md", "README.zh.md", "LICENSE",
                 "docs/notes/pypi-description.md"):
        (destination / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, destination / name)
    for name in ("_native_vm.stale.so", "_native_vm.stale.pyd"):
        (destination / "malbolge" / name).write_bytes(b"stale checkout binary")
    for name in ("docs/research/private-sentinel.txt", ".claude/private-sentinel.txt",
                 "build/native-vm/build.json"):
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("excluded sentinel", encoding="utf8")
    return destination


def command(argv, *, cwd, env):
    completed = subprocess.run(argv, cwd=str(cwd), env=env, capture_output=True,
                               text=True, timeout=180)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return completed


def assert_wheel_integrity(path, *, native):
    """Validate metadata and RECORD against actual archive members."""
    import csv
    import io

    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        binary_names = [name for name in names if name.endswith((".so", ".pyd"))]
        assert len(binary_names) == (1 if native else 0)
        assert not any("stale" in name or "private-sentinel" in name for name in names)
        wheel_name = next(name for name in names if name.endswith(".dist-info/WHEEL"))
        wheel_metadata = archive.read(wheel_name).decode("utf8")
        assert "Root-Is-Purelib: " + ("false" if native else "true") in wheel_metadata
        tags = [line[5:] for line in wheel_metadata.splitlines() if line.startswith("Tag: ")]
        assert tags
        if native:
            assert all(not tag.endswith("-none-any") for tag in tags)
            assert any(tag.split("-")[1] not in ("none", "abi3") for tag in tags)
            assert binary_names == ["malbolge/_native_vm" + sysconfig.get_config_var("EXT_SUFFIX")]
        else:
            assert tags == ["py3-none-any"]
        record_name = next(name for name in names if name.endswith(".dist-info/RECORD"))
        records = list(csv.reader(io.StringIO(archive.read(record_name).decode("utf8"))))
        assert {row[0] for row in records} == set(names)
        for name, digest, size in records:
            if name == record_name:
                assert digest == size == ""
                continue
            data = archive.read(name)
            algorithm, encoded = digest.split("=", 1)
            assert algorithm == "sha256"
            expected = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
            assert encoded.encode("ascii") == expected
            assert int(size) == len(data)


@pytest.mark.skipif(os.environ.get("MALBOLGE_PACKAGING_TESTS") != "1",
                    reason="set MALBOLGE_PACKAGING_TESTS=1 for build/install acceptance")
def test_sdist_rebuild_and_installed_wheel_contract(tmp_path):
    uv = shutil.which("uv")
    assert uv, "packaging acceptance requires uv"
    source = packaging_source(tmp_path / "source")
    env = dict(os.environ, MALBOLGE_NATIVE_BUILD="required",
               CC="malbolge-test-compiler-does-not-exist")
    env.pop("PYTHONPATH", None)
    sdist_dir = tmp_path / "sdist"
    # Even required mode must not run a compiler while producing source archives.
    command([uv, "build", "--sdist", "--no-build-isolation", "--python", sys.executable,
             "--out-dir", str(sdist_dir),
             str(source)], cwd=tmp_path, env=env)
    sdist = next(sdist_dir.glob("*.tar.gz"))
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    with tarfile.open(sdist) as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        assert not any(name.endswith((".so", ".pyd")) or "private-sentinel" in name
                       or name.endswith("build.json") for name in names)
        for required in ("scripts/native_build.py", "scripts/hatch_native.py",
                         "malbolge/_native_vm.c", "malbolge/_native_jit.h"):
            assert any(name.endswith("/" + required) for name in names)
        # Source archives are generated here, but reject traversal before extraction.
        assert all(not Path(name).is_absolute() and ".." not in Path(name).parts for name in names)
        assert all(member.isfile() or member.isdir() for member in members)
        if sys.version_info >= (3, 12):
            archive.extractall(str(extracted), filter="data")
        else:
            archive.extractall(str(extracted))
    extracted_source = next(extracted.iterdir())
    for mode in ("disabled", "required"):
        env["MALBOLGE_NATIVE_BUILD"] = mode
        if mode == "required":
            env.pop("CC", None)
        wheel_dir = tmp_path / (mode + "-wheel")
        command([uv, "build", "--wheel", "--no-build-isolation", "--python", sys.executable,
                 "--out-dir", str(wheel_dir),
                 str(extracted_source)], cwd=tmp_path, env=env)
        wheel = next(wheel_dir.glob("*.whl"))
        assert_wheel_integrity(wheel, native=mode == "required")
        installed = tmp_path / (mode + "-installed")
        command([uv, "pip", "install", "--python", sys.executable, "--target", str(installed),
                 "--no-deps", "--no-compile", str(wheel)], cwd=tmp_path, env=env)
        probe = """
import os, pathlib, sys
sys.path.insert(0, sys.argv[1])
from malbolge import native, run20
assert os.path.commonpath([str(pathlib.Path(native.__file__).resolve()),
                          str(pathlib.Path(sys.argv[1]).resolve())]) == str(pathlib.Path(sys.argv[1]).resolve())
assert native.native_available() == (sys.argv[2] == 'required')
# Any implicit runtime compiler invocation is a contract violation.
import subprocess
def unexpected_build(*args, **kwargs):
    raise AssertionError('runtime attempted to run an external command')
subprocess.run = subprocess.Popen = unexpected_build
cells = bytes(33 + (opcode - address - 33) % 94
              for address, opcode in enumerate((23, 5, 81)))
result = run20(cells, b'Q', engine='auto', max_steps=10, max_output=2)
assert result.output == b'Q' and result.stop_reason == 'terminated'
if sys.argv[2] == 'required':
    assert run20(cells, b'Q', engine='native', max_steps=10).output == b'Q'
"""
        # -I removes cwd/PYTHONPATH influence, so checkout extensions cannot help.
        command([uv, "run", "--no-project", "--no-sync", "--python", sys.executable,
                 "python", "-I", "-c", probe, str(installed), mode], cwd=tmp_path, env=env)
