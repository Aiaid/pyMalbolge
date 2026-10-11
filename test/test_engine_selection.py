"""Default native selection, explicit engines and CLI execution boundaries."""

import io
import json
import subprocess
import sys

import pytest

from malbolge import native, run20
from malbolge import malbolge20
from malbolge import __main__ as cli


def program(*opcodes):
    return bytes(33 + (opcode - address - 33) % 94
                 for address, opcode in enumerate(opcodes))


def fail_if_called(*args, **kwargs):
    raise AssertionError("unexpected engine invocation")


@pytest.mark.parametrize("available,expected", [(False, "python"), (True, "native")])
def test_auto_resolves_native_availability_without_probing_jit(monkeypatch, available, expected):
    monkeypatch.setattr(native, "native_available", lambda: available)
    monkeypatch.setattr(native, "jit_available", fail_if_called)
    assert native.resolve_engine() == expected
    assert native.resolve_engine("auto") == expected


@pytest.mark.parametrize("engine", ["python", "native", "jit"])
def test_explicit_engine_does_not_probe_or_change_selection(monkeypatch, engine):
    monkeypatch.setattr(native, "native_available", fail_if_called)
    monkeypatch.setattr(native, "jit_available", fail_if_called)
    assert native.resolve_engine(engine) == engine


@pytest.mark.parametrize("engine", ["automatic", "", None])
def test_invalid_engine_rejected_before_execution(monkeypatch, engine):
    monkeypatch.setattr(native, "run20", fail_if_called)
    monkeypatch.setattr(malbolge20, "run_memory", fail_if_called)
    with pytest.raises(ValueError, match="engine"):
        native.resolve_engine(engine)
    with pytest.raises(ValueError, match="engine"):
        run20(program(81), engine=engine)


@pytest.mark.parametrize("requested,available,jit", [
    ("auto", True, False), ("native", False, False), ("jit", False, True),
])
def test_native_dispatch_forwards_source_input_and_every_budget(monkeypatch, requested, available, jit):
    monkeypatch.setattr(native, "native_available", lambda: available)
    monkeypatch.setattr(malbolge20, "run_memory", fail_if_called)
    calls = []
    expected = object()

    def capture(*args, **kwargs):
        calls.append((args, kwargs))
        return expected

    monkeypatch.setattr(native, "run20", capture)
    source, data = program(23, 5, 81), memoryview(b"\x00\xff")
    assert run20(source, data, engine=requested, max_steps=7,
                 max_output=2, eof="stop") is expected
    assert calls == [((source, data), {
        "max_steps": 7, "max_output": 2, "eof": "stop", "jit": jit,
    })]


def test_default_run_uses_native_without_enabling_jit(monkeypatch):
    monkeypatch.setattr(native, "native_available", lambda: True)
    monkeypatch.setattr(native, "jit_available", fail_if_called)
    monkeypatch.setattr(malbolge20, "run_memory", fail_if_called)
    calls = []
    monkeypatch.setattr(native, "run20", lambda *args, **kwargs: calls.append(kwargs))
    run20(program(81))
    assert len(calls) == 1
    assert calls[0]["jit"] is False


def test_missing_extension_auto_falls_back_and_explicit_native_jit_still_fail(monkeypatch):
    def missing(name):
        raise ImportError("test extension missing")

    source = program(23, 5, 23, 5, 81)
    expected = run20(source, b"X", engine="python", max_steps=4,
                     max_output=1, eof="stop")
    monkeypatch.setattr(native, "import_module", missing)
    assert run20(source, b"X", max_steps=4, max_output=1, eof="stop") == expected
    for engine in ("native", "jit"):
        with pytest.raises(RuntimeError, match="unavailable"):
            run20(source, b"X", engine=engine)


def test_explicit_python_does_not_load_native_extension(monkeypatch):
    monkeypatch.setattr(native, "import_module", fail_if_called)
    monkeypatch.setattr(native, "run20", fail_if_called)
    assert run20(program(23, 5, 81), b"\xff", engine="python").output == b"\xff"


@pytest.mark.parametrize("error", [RuntimeError("native runtime failed"),
                                      MemoryError("allocation failed"),
                                      ValueError("invalid source"),
                                      IndexError("invalid address")])
def test_auto_does_not_retry_python_after_native_execution_error(monkeypatch, error):
    monkeypatch.setattr(native, "native_available", lambda: True)
    monkeypatch.setattr(malbolge20, "run_memory", fail_if_called)
    calls = []

    def broken(*args, **kwargs):
        calls.append((args, kwargs))
        raise error

    monkeypatch.setattr(native, "run20", broken)
    with pytest.raises(type(error)) as caught:
        run20(program(81))
    assert caught.value is error
    assert len(calls) == 1


@pytest.mark.skipif(not native.native_available(), reason="optional native VM is not built")
@pytest.mark.parametrize("data,options", [
    (b"\x00\xff", {}), ("é", {}), (b"", {"eof": "stop"}),
    (b"X", {"max_steps": 1}), (b"X", {"max_output": 0}),
])
def test_current_native_default_matches_python_result(data, options):
    source = program(23, 5, 23, 5, 81)
    expected = run20(source, data, engine="python", **options)
    assert run20(source, data, **options) == expected
    assert run20(source, data, engine="native", **options) == expected


class Stream(io.StringIO):
    def __init__(self, data=b"", tty=False):
        super().__init__()
        self.buffer = io.BytesIO(data)
        self.tty = tty

    def isatty(self):
        return self.tty


def invoke_cli(monkeypatch, argv, data=b"", tty=False):
    stdin, stdout, stderr = Stream(data, tty), Stream(), io.StringIO()
    with monkeypatch.context() as patch:
        patch.setattr(sys, "argv", ["malbolge"] + argv)
        patch.setattr(sys, "stdin", stdin)
        patch.setattr(sys, "stdout", stdout)
        patch.setattr(sys, "stderr", stderr)
        try:
            cli.main()
        except SystemExit as error:
            code = error.code
        else:
            code = 0
    return code, stdout.buffer.getvalue(), stderr.getvalue()


@pytest.fixture
def source_file(tmp_path):
    path = tmp_path / "program.mb"
    path.write_bytes(program(23, 5, 81))
    return str(path)


@pytest.mark.parametrize("requested,available,selected", [
    (None, False, "python"), (None, True, "native"),
    ("auto", False, "python"), ("auto", True, "native"),
    ("python", True, "python"), ("native", True, "native"),
    ("jit", True, "jit"),
])
def test_cli_engine_selection_and_stats(monkeypatch, source_file, requested, available, selected):
    expected = run20(program(23, 5, 81), b"X", engine="python")
    calls = []

    def capture(*args, **kwargs):
        calls.append((args, kwargs))
        return expected

    monkeypatch.setattr(native, "native_available", lambda: available)
    monkeypatch.setattr(malbolge20, "run", capture)
    argv = ["--variant=malbolge20", source_file, "--input", "X", "--stats"]
    if requested is not None:
        argv += ["--engine", requested]
    code, output, error = invoke_cli(monkeypatch, argv, tty=True)
    assert (code, output) == (0, b"X")
    stats = json.loads(error)
    assert stats["engine"] == selected
    assert stats["requested_engine"] == (requested or "auto")
    assert "output_hex" not in stats
    assert len(calls) == 1
    assert calls[0][0] == (program(23, 5, 81), "X")
    assert calls[0][1]["engine"] == selected


@pytest.mark.parametrize("engine", ["native", "jit"])
def test_cli_unavailable_explicit_engine_has_concise_error(monkeypatch, source_file, engine):
    def missing(name):
        raise ImportError("test extension missing")

    monkeypatch.setattr(native, "import_module", missing)
    code, output, error = invoke_cli(monkeypatch, [
        "--variant=malbolge20", source_file, "--engine", engine, "--input", "X",
    ], tty=True)
    assert code == 1
    assert output == b""
    assert "unavailable" in error
    assert "Traceback" not in error


@pytest.mark.parametrize("engine", ["python", "auto", "native", "jit"])
def test_debug_rejects_explicit_engine(monkeypatch, source_file, engine):
    code, output, error = invoke_cli(monkeypatch, [
        "debug", source_file, "--engine", engine,
    ], tty=True)
    assert code == 2
    assert output == b""
    assert "engine" in error and "debug" in error


@pytest.mark.parametrize("engine", ["native", "jit"])
def test_original_variant_rejects_native_engines(monkeypatch, source_file, engine):
    code, output, error = invoke_cli(monkeypatch, [
        source_file, "--engine", engine, "--input", "X",
    ], tty=True)
    assert code == 2
    assert output == b""
    assert "malbolge20" in error


@pytest.mark.parametrize("engine", ["native", "jit"])
def test_tty_native_engines_require_explicit_batch_input(monkeypatch, source_file, engine):
    code, output, error = invoke_cli(monkeypatch, [
        "--variant=malbolge20", source_file, "--engine", engine,
    ], tty=True)
    assert code == 2
    assert output == b""
    assert "input" in error


@pytest.mark.parametrize("engine", [None, "auto", "python"])
def test_tty_without_batch_options_keeps_interactive_python(monkeypatch, source_file, engine):
    calls = []
    monkeypatch.setattr(malbolge20, "_interactive_main", lambda path: calls.append(path))
    monkeypatch.setattr(malbolge20, "run", fail_if_called)
    argv = ["--variant=malbolge20", source_file]
    if engine is not None:
        argv += ["--engine", engine]
    code, output, error = invoke_cli(monkeypatch, argv, tty=True)
    assert (code, output, error) == (0, b"", "")
    assert calls == [source_file]


@pytest.mark.parametrize("extension", ["mal", "mb"])
def test_redirected_plain_command_is_byte_batch_execution(tmp_path, extension):
    path = tmp_path / ("program." + extension)
    path.write_bytes(program(23, 5, 81))
    proc = subprocess.run([sys.executable, "-m", "malbolge", "--variant=malbolge20",
                           str(path)], input=b"\xff", capture_output=True, timeout=10)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, b"\xff", b"")


def test_redirected_plain_command_uses_default_native_selection(monkeypatch, source_file):
    expected = run20(program(23, 5, 81), b"\xff", engine="python")
    calls = []

    def capture(*args, **kwargs):
        calls.append((args, kwargs))
        return expected

    monkeypatch.setattr(native, "native_available", lambda: True)
    monkeypatch.setattr(native, "run20", capture)
    monkeypatch.setattr(malbolge20, "_interactive_main", fail_if_called)
    monkeypatch.setattr(malbolge20, "run_memory", fail_if_called)
    code, output, error = invoke_cli(monkeypatch, [
        "--variant=malbolge20", source_file,
    ], data=b"\xff")
    assert (code, output, error) == (0, b"\xff", "")
    assert calls == [((program(23, 5, 81).decode("ascii"), b"\xff"), {
        "max_steps": None, "max_output": None, "eof": "sentinel", "jit": False,
    })]


def test_cli_native_runtime_error_is_concise_and_does_not_retry(monkeypatch, source_file):
    monkeypatch.setattr(native, "native_available", lambda: True)
    monkeypatch.setattr(malbolge20, "run_memory", fail_if_called)
    calls = []

    def broken(*args, **kwargs):
        calls.append((args, kwargs))
        raise RuntimeError("native test runtime failure")

    monkeypatch.setattr(native, "run20", broken)
    code, output, error = invoke_cli(monkeypatch, [
        "--variant=malbolge20", source_file, "--input", "X", "--stats",
    ], tty=True)
    assert code == 1
    assert output == b""
    assert "native test runtime failure" in error
    assert "Traceback" not in error
    assert len(calls) == 1


@pytest.mark.skipif(not native.native_available(), reason="optional native VM is not built")
def test_direct_module_entry_uses_default_native_and_reports_selection(source_file):
    proc = subprocess.run([sys.executable, "-m", "malbolge.malbolge20", source_file,
                           "--input", "X", "--stats"],
                          capture_output=True, timeout=10)
    assert (proc.returncode, proc.stdout) == (0, b"X")
    # Package imports can produce a runpy warning before the final JSON line.
    stats = json.loads(proc.stderr.splitlines()[-1])
    assert (stats["engine"], stats["requested_engine"]) == ("native", "auto")
    assert stats["stop_reason"] == "terminated"


@pytest.mark.parametrize("module,args", [
    ("malbolge", ["--variant=malbolge20"]), ("malbolge.malbolge20", []),
])
def test_plain_redirected_invalid_utf8_preserves_legacy_read_error(tmp_path, module, args):
    path = tmp_path / "invalid.mal"
    path.write_bytes(b"\xff")
    proc = subprocess.run([sys.executable, "-m", module] + args + [str(path)],
                          input=b"", capture_output=True, timeout=10)
    assert (proc.returncode, proc.stdout) == (1, b"")
    assert b"cannot read" in proc.stderr
    assert b"Traceback" not in proc.stderr


@pytest.mark.parametrize("module,args", [
    ("malbolge", ["--variant=malbolge20"]), ("malbolge.malbolge20", []),
])
def test_plain_redirected_unicode_source_preserves_legacy_text_contract(tmp_path, module, args):
    path = tmp_path / "wide-halt.mal"
    path.write_text(chr(81 + 94 * 100), encoding="utf8")
    command = [sys.executable, "-m", module] + args + [str(path)]
    plain = subprocess.run(command, input=b"", capture_output=True, timeout=10)
    # The text loader accepts the wide cell; execution rejects it as an
    # instruction because it exceeds printable ASCII (the batch exit is 2).
    assert (plain.returncode, plain.stdout) == (2, b"")
    assert b"Invalid character" not in plain.stderr
    # Explicit batch options preserve the byte-source API: UTF-8 bytes do not
    # represent the single wide character accepted by the legacy text loader.
    bounded = subprocess.run(command + ["--max-steps", "1"], input=b"",
                             capture_output=True, timeout=10)
    assert (bounded.returncode, bounded.stdout) == (1, b"")
    assert b"Invalid character" in bounded.stderr
    assert b"Traceback" not in bounded.stderr


@pytest.mark.parametrize("limit,value,reason", [
    ("--max-steps", "1", "step_limit"),
    ("--max-output", "0", "output_limit"),
])
@pytest.mark.parametrize("engine", ["python", "auto", "native", "jit"])
def test_cli_explicit_engines_preserve_budget_exit_and_stats(monkeypatch, source_file, engine,
                                                           limit, value, reason):
    if engine == "native" and not native.native_available():
        pytest.skip("optional native VM is not built")
    if engine == "jit" and not native.jit_available():
        pytest.skip("native machine-code JIT is unavailable")
    code, output, error = invoke_cli(monkeypatch, [
        "--variant=malbolge20", source_file, "--engine", engine,
        "--input", "X", limit, value, "--stats",
    ], tty=True)
    assert (code, output) == (3, b"")
    stats = json.loads(error)
    assert stats["stop_reason"] == reason
    assert stats["requested_engine"] == engine
    assert stats["engine"] == native.resolve_engine(engine)
