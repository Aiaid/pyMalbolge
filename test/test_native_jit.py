"""Three-way semantic and memory parity for actual native machine-code JIT.

Programs are short handcrafted images; no compiler or benchmark jobs run here.
Supported hosts must execute generated code, rather than silently falling back.
"""

from array import array
from pathlib import Path
import signal

import pytest

from malbolge import native, run20
from malbolge.core import ENCRYPT, MalbolgeConfig, SparseMemory, parse_source, run_memory


CONFIG = MalbolgeConfig.malbolge20()
SIZE = CONFIG.memory_size
PAGE_SIZE = 4096
FIXTURES = Path(__file__).parent / "fixtures" / "nagoya"
requires_native = pytest.mark.skipif(
    not native.native_available(), reason="optional native VM is not built")
requires_jit = pytest.mark.skipif(
    not native.jit_available(), reason="native machine-code JIT is unavailable")
STAT_FIELDS = {
    "enabled", "available", "compiled_blocks", "compiled_bytes", "jit_blocks",
    "jit_steps", "guard_failures", "fallback_steps", "compile_cpu_seconds",
    "compile_wall_seconds", "cache_entries", "cache_code_bytes", "cache_mapped_bytes",
}


def instruction(opcode, address):
    return 33 + (opcode - address - 33) % 94


def program(*opcodes):
    return bytes(instruction(opcode, i) for i, opcode in enumerate(opcodes))


def nops(count, start=0):
    period = bytes(instruction(68, start + i) for i in range(94))
    return (period * ((count + 93) // 94))[:count]


def memories(source, writes=()):
    python = SparseMemory(CONFIG)
    python.initialize_source(source)
    scalar, jitted = native.NativeMemory(source), native.NativeMemory(source)
    for address, value in writes:
        python[address] = scalar[address] = jitted[address] = value
    return python, scalar, jitted


def assert_pages(python, *native_memories):
    expected = {
        page: (array("I", list(block.values)).tobytes(), bytes(block.written))
        for page, block in python._blocks.items()
    }
    for memory in native_memories:
        assert memory.export_pages() == expected
        assert memory.get_allocated_count() == python.get_allocated_count()


def assert_stats(memory, result, enabled):
    stats = memory.jit_stats()
    assert STAT_FIELDS <= stats.keys()
    assert stats["enabled"] is enabled
    assert stats["available"] is True
    assert stats["jit_steps"] + stats["fallback_steps"] == result.steps
    for name in STAT_FIELDS - {"enabled", "available"}:
        assert stats[name] >= 0
    assert stats["cache_mapped_bytes"] >= stats["cache_code_bytes"]
    if not enabled:
        assert stats["jit_steps"] == stats["jit_blocks"] == 0
        assert stats["fallback_steps"] == result.steps
    return stats


def differential(source, input_data=b"", writes=(), **limits):
    python, scalar, jitted = memories(source, writes)
    expected = run_memory(python, CONFIG, input_data, **limits)
    assert native.run_memory(scalar, input_data, jit=False, **limits) == expected
    assert native.run_memory(jitted, input_data, jit=True, **limits) == expected
    assert_pages(python, scalar, jitted)
    assert_stats(scalar, expected, False)
    stats = assert_stats(jitted, expected, True)
    return expected, python, scalar, jitted, stats


def warm_cache():
    memory = native.NativeMemory(nops(4096))
    result = native.run_memory(memory, max_steps=4096, jit=True)
    stats = assert_stats(memory, result, True)
    assert stats["jit_steps"] > 0
    assert stats["jit_blocks"] > 0
    assert stats["cache_entries"] > 0
    assert stats["cache_code_bytes"] > 0
    return stats


@requires_jit
@pytest.mark.parametrize("count", [128, 4097, 1000000])
def test_long_nop_runs_execute_real_machine_code(count):
    result, _, _, memory, stats = differential(nops(count), max_steps=count)
    assert (result.stop_reason, result.steps, result.c, result.d) == (
        "step_limit", count, count, count)
    assert stats["jit_steps"] > 0
    assert stats["jit_blocks"] > 0
    assert stats["cache_entries"] > 0
    assert stats["cache_code_bytes"] > 0
    assert memory[count - 1] == ENCRYPT[nops(1, count - 1)[0] - 33]


@requires_jit
@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.mb")), ids=lambda p: p.stem)
def test_existing_nagoya_images_keep_complete_machine_state(path):
    differential(parse_source(path.read_bytes(), CONFIG), b"Q",
                 max_steps=50000, max_output=16)


@requires_jit
@pytest.mark.parametrize("budget", [0, 1, 2, 63, 64, 65, 127, 128, 129,
                                    4095, 4096, 4097, 16383, 16384, 16385])
def test_exact_step_boundaries_do_not_encrypt_pending_code(budget):
    source = nops(16450)
    result, _, _, memory, stats = differential(source, max_steps=budget)
    assert result.steps == result.c == result.d == budget
    assert result.stop_reason == "step_limit"
    assert memory[budget] == source[budget]
    if budget == 0:
        assert memory.export_pages() == {}
        assert stats["jit_steps"] == stats["fallback_steps"] == 0


@requires_jit
@pytest.mark.parametrize("source,max_steps,reason,steps", [
    (b"", 0, "step_limit", 0),
    (b"", 5, "invalid_instruction", 0),
    (program(81), 0, "step_limit", 0),
    (program(81), 1, "terminated", 1),
])
def test_empty_and_halt_have_no_execution_writes(source, max_steps, reason, steps):
    result, _, _, memory, _ = differential(source, max_steps=max_steps)
    assert (result.stop_reason, result.steps) == (reason, steps)
    assert memory.export_pages() == {}


@requires_jit
def test_fresh_memory_reuses_immutable_process_cache():
    source = nops(4096)
    first = native.NativeMemory(source)
    assert first.jit_stats()["enabled"] is False
    before = first.jit_stats()
    first_result = native.run_memory(first, max_steps=len(source), jit=True)
    first_stats = assert_stats(first, first_result, True)
    fresh = native.NativeMemory(source)
    assert fresh.export_pages() == {}
    second_result = native.run_memory(fresh, max_steps=len(source), jit=True)
    second_stats = assert_stats(fresh, second_result, True)
    assert second_result == first_result
    assert fresh.export_pages() == first.export_pages()
    assert second_stats["jit_steps"] > 0
    assert second_stats["compiled_blocks"] == second_stats["compiled_bytes"] == 0
    assert second_stats["cache_entries"] >= first_stats["cache_entries"] >= before["cache_entries"]
    assert second_stats["cache_code_bytes"] >= first_stats["cache_code_bytes"] > 0


@requires_jit
@pytest.mark.parametrize("opcode,limits", [
    (5, {"max_output": 0}), (39, {}), (62, {}), (40, {}), (81, {}), (0, {}),
])
def test_warm_guards_exit_at_changed_future_instruction(opcode, limits):
    warm_cache()
    source = bytearray(nops(128))
    source[8] = instruction(opcode, 8)
    result, _, _, _, stats = differential(bytes(source), max_steps=128, **limits)
    assert stats["guard_failures"] > 0
    assert stats["jit_steps"] >= 8
    if opcode == 5:
        assert (result.stop_reason, result.steps, result.c) == ("output_limit", 8, 8)
    elif opcode == 81:
        assert (result.stop_reason, result.steps, result.c) == ("terminated", 9, 8)
        assert stats["fallback_steps"] >= 1  # HALT itself is a scalar step.
    else:
        assert stats["fallback_steps"] >= 1


@requires_jit
@pytest.mark.parametrize("opcode", [39, 62])
def test_alias_write_to_future_code_is_observed(opcode):
    warm_cache()
    source = bytearray(nops(128))
    for address, operation in enumerate((40, 40, opcode)):
        source[address] = instruction(operation, address)
    target = 80
    # MOVD at 1 reads cell 41; ROT/CRZ at 2 then mutates future code at 80.
    result, _, _, memory, stats = differential(
        bytes(source), writes=[(41, target - 1)], max_steps=128)
    assert result.stop_reason == "invalid_instruction"
    assert result.c == target
    assert memory[target] > 126
    assert stats["jit_steps"] > 0


@requires_jit
def test_jit_writes_only_executed_non_source_initialization_cells():
    source = program(40, 4)
    python = SparseMemory(CONFIG)
    python.initialize_source(source)
    first_default_nop = next(
        address for address in range(512, 4096)
        if python[address] == instruction(68, address))
    start = first_default_nop - 8
    writes = [(41, start - 1), (start - 1, 0)]
    unchanged_defaults = []
    for address in range(start, start + 512):
        value = instruction(68, address)
        if python[address] == value:
            unchanged_defaults.append(address)
        else:
            writes.append((address, value))
    executed_defaults = [address for address in unchanged_defaults if address < start + 64]
    pending_defaults = [address for address in unchanged_defaults if address >= start + 64]
    assert executed_defaults and pending_defaults
    expected_count = len(source) + len(writes) + len(executed_defaults)
    result, _, _, memory, stats = differential(source, writes=writes, max_steps=66)
    assert result.c == start + 64
    assert memory.get_allocated_count() == expected_count
    assert stats["jit_steps"] > 0
    pages = memory.export_pages()
    for address in executed_defaults:
        assert pages[address // PAGE_SIZE][1][address % PAGE_SIZE] == 1
    for address in pending_defaults:
        assert pages[address // PAGE_SIZE][1][address % PAGE_SIZE] == 0


@requires_jit
def test_jit_execution_detaches_preexisting_copy_on_write_pages():
    source = nops(PAGE_SIZE + 128)
    python, scalar, jitted = memories(source, [(17, source[17]), (4097, source[4097])])
    python_copy, scalar_copy, jit_copy = python.copy(), scalar.copy(), jitted.copy()
    expected = run_memory(python, CONFIG, max_steps=len(source))
    assert native.run_memory(scalar, max_steps=len(source), jit=False) == expected
    assert native.run_memory(jitted, max_steps=len(source), jit=True) == expected
    assert_pages(python, scalar, jitted)
    assert_pages(python_copy, scalar_copy, jit_copy)
    assert jit_copy[17] == source[17]
    assert jit_copy[4097] == source[4097]
    assert assert_stats(jitted, expected, True)["jit_steps"] > 0


@requires_jit
def test_code_and_data_register_wrap_boundaries():
    start = SIZE - 96
    writes = [(41, start - 1), (start - 1, 0)]
    writes.extend((address, instruction(68, address)) for address in range(start, SIZE))
    result, _, _, _, stats = differential(program(40, 4), writes=writes, max_steps=98)
    assert (result.c, result.d, result.steps) == (0, 138, 98)
    assert stats["jit_steps"] > 0
    # Jump over the wide pointer cell so it is never fetched as code.
    source = bytearray(nops(192))
    source[0], source[99] = instruction(4, 0), instruction(40, 99)
    result, _, _, _, _ = differential(bytes(source), writes=[(1, SIZE - 65)], max_steps=66)
    assert (result.c, result.d) == (164, 0)


@requires_jit
def test_high_data_pointer_nops_preserve_scalar_error_behavior():
    source = bytearray(nops(192))
    source[0], source[99] = instruction(4, 0), instruction(40, 99)
    source[168] = instruction(39, 168)
    python, scalar, jitted = memories(bytes(source), [(1, SIZE + 7)])
    with pytest.raises(IndexError):
        run_memory(python, CONFIG, max_steps=100)
    with pytest.raises(IndexError):
        native.run_memory(scalar, max_steps=100, jit=False)
    with pytest.raises(IndexError):
        native.run_memory(jitted, max_steps=100, jit=True)
    assert_pages(python, scalar, jitted)


@requires_jit
@pytest.mark.parametrize("input_data,eof,max_output", [
    (b"\x00\xff", "sentinel", None), ("é", "stop", None),
    (b"", "stop", None), (b"", "sentinel", 0),
    (b"X", "sentinel", 1), (b"X", "stop", 2),
])
def test_scalar_io_and_eof_boundaries_after_jit(input_data, eof, max_output):
    source = nops(128) + bytes(instruction(opcode, 128 + i)
                              for i, opcode in enumerate((23, 5, 23, 5, 81)))
    _, _, _, _, stats = differential(source, input_data, eof=eof,
                                     max_output=max_output, max_steps=140)
    assert stats["jit_steps"] > 0


@requires_jit
@pytest.mark.parametrize("budget", [2**64 - 1, 2**64, 2**128])
def test_large_python_budgets_preserve_termination(budget):
    source = nops(128) + bytes([instruction(81, 128)])
    result, _, _, _, stats = differential(source, max_steps=budget, max_output=budget)
    assert (result.stop_reason, result.steps) == ("terminated", 129)
    assert stats["fallback_steps"] >= 1


@requires_jit
def test_each_run_resets_registers_stats_and_observes_encrypted_memory():
    source = nops(256)
    python, scalar, jitted = memories(source)
    for budget in (128, 1, 0):
        expected = run_memory(python, CONFIG, max_steps=budget)
        assert native.run_memory(scalar, max_steps=budget, jit=False) == expected
        assert native.run_memory(jitted, max_steps=budget, jit=True) == expected
        assert_pages(python, scalar, jitted)
        assert_stats(jitted, expected, True)


@requires_jit
def test_disabling_jit_for_next_run_resets_per_run_accounting():
    memory = native.NativeMemory(nops(256))
    first = native.run_memory(memory, max_steps=128, jit=True)
    assert assert_stats(memory, first, True)["jit_steps"] > 0
    second = native.run_memory(memory, max_steps=0, jit=False)
    stats = assert_stats(memory, second, False)
    assert stats["compiled_blocks"] == stats["compiled_bytes"] == 0


@requires_jit
def test_run20_jit_engine_is_explicit():
    source = nops(128) + bytes([instruction(81, 128)])
    assert run20(source, engine="jit", max_steps=200) == run20(
        source, engine="python", max_steps=200)


@requires_jit
@pytest.mark.skipif(
    not all(hasattr(signal, name) for name in
            ("SIGALRM", "ITIMER_REAL", "getitimer", "setitimer")),
    reason="requires POSIX interval signals")
def test_signal_reinitialization_guard_is_preserved_during_jit():
    steps = 300000
    python, scalar, memory = memories(nops(steps))
    rejected = []

    def reinitialize(signum, frame):
        if memory[0] == instruction(68, 0):
            signal.setitimer(signal.ITIMER_REAL, 0.0001)
            return
        try:
            memory.__init__(program(81))
        except RuntimeError as error:
            rejected.append(str(error))
        else:
            rejected.append(None)

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, 0)
    try:
        signal.signal(signal.SIGALRM, reinitialize)
        signal.setitimer(signal.ITIMER_REAL, 0.0001)
        actual = native.run_memory(memory, max_steps=steps, jit=True)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
    assert rejected
    assert all(message is not None and "running" in message for message in rejected)
    expected = run_memory(python, CONFIG, max_steps=steps)
    assert actual == native.run_memory(scalar, max_steps=steps, jit=False) == expected
    assert_pages(python, scalar, memory)
    assert assert_stats(memory, actual, True)["jit_steps"] > 0


def test_missing_extension_rejects_jit_without_changing_python_default(monkeypatch):
    def unavailable(name):
        raise ImportError("extension intentionally missing")

    monkeypatch.setattr(native, "import_module", unavailable)
    assert native.jit_available() is False
    assert run20(program(81)).stop_reason == "terminated"
    with pytest.raises(RuntimeError):
        run20(program(81), engine="jit")


@requires_native
def test_unsupported_host_rejects_jit_instead_of_silent_fallback():
    if native.jit_available():
        pytest.skip("host supports actual JIT; unavailable path tested elsewhere")
    with pytest.raises(RuntimeError, match="JIT|jit"):
        run20(program(81), engine="jit")
