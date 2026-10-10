"""Observable VM and sparse-memory parity for the opt-in native engine.

No compiler runs or generated images are needed. The extension is optional;
native tests skip when it has not been built in the current environment.
"""

from array import array
from pathlib import Path
import random
import signal

import pytest

from malbolge import run20
from malbolge import native
from malbolge.core import (
    ENCRYPT, MalbolgeConfig, SparseMemory, crazy, parse_source,
    rotate, run_memory,
)


CONFIG = MalbolgeConfig.malbolge20()
SIZE = CONFIG.memory_size
PAGE_SIZE = 4096
FIXTURES = Path(__file__).parent / "fixtures" / "nagoya"
requires_native = pytest.mark.skipif(
    not native.native_available(), reason="optional native VM is not built")


def instruction(opcode, address):
    """A printable instruction with the requested address-dependent opcode."""
    return 33 + (opcode - address - 33) % 94


def program(*opcodes):
    return bytes(instruction(opcode, i) for i, opcode in enumerate(opcodes))


def memory_pair(source, writes=()):
    python = SparseMemory(CONFIG)
    python.initialize_source(source)
    compiled = native.NativeMemory(source)
    for address, value in writes:
        python[address] = compiled[address] = value
    return python, compiled


def python_pages(memory):
    """Export logical cell values, regardless of their backing buffer type."""
    return {
        page: (array("I", list(block.values)).tobytes(), bytes(block.written))
        for page, block in memory._blocks.items()
    }


def assert_memory_equal(python, compiled):
    """Compare every materialized cell and its explicit-write provenance."""
    expected = python_pages(python)
    assert compiled.export_pages() == expected
    assert compiled.get_allocated_count() == python.get_allocated_count()
    assert len(compiled) == len(python) == SIZE


def test_python_page_normalization_preserves_byte_valued_cells():
    values = [65, 66, 67, 68] * (PAGE_SIZE // 4)
    byte_memory, wide_memory = SparseMemory(CONFIG), SparseMemory(CONFIG)
    byte_memory.initialize_source(bytes(values))
    wide_memory.initialize_source(array("I", values))
    byte_memory[0] = wide_memory[0] = 65
    assert isinstance(byte_memory._blocks[0].values, bytearray)
    assert isinstance(wide_memory._blocks[0].values, array)
    expected = {0: (array("I", values).tobytes(), bytes(PAGE_SIZE))}
    assert python_pages(byte_memory) == python_pages(wide_memory) == expected


def differential(source, input_data=b"", writes=(), **limits):
    python, compiled = memory_pair(source, writes)
    expected = run_memory(python, CONFIG, input_data, **limits)
    actual = native.run_memory(compiled, input_data, **limits)
    assert actual == expected
    assert actual.to_dict() == expected.to_dict()
    assert_memory_equal(python, compiled)
    return actual, python, compiled


@requires_native
@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.mb")), ids=lambda p: p.stem)
@pytest.mark.parametrize("max_steps", [17, 50000])
def test_checked_in_nagoya_images(path, max_steps):
    cells = parse_source(path.read_bytes(), CONFIG)
    differential(cells, b"Q", max_steps=max_steps, max_output=16)


@requires_native
@pytest.mark.parametrize("input_data", [b"\x00\xff", bytearray(b"AZ"),
                                        memoryview(b"XY"), "é"])
def test_byte_input_and_utf8_text(input_data):
    result, _, _ = differential(program(23, 5, 23, 5, 81), input_data)
    expected = input_data.encode("utf8") if isinstance(input_data, str) else bytes(input_data)
    assert result.output == expected
    assert result.input_consumed == len(expected)
    assert result.stop_reason == "terminated"


@requires_native
@pytest.mark.parametrize("eof,reason,steps,a,output", [
    ("stop", "input_exhausted", 0, 0, b""),
    ("sentinel", "terminated", 3, 59049, bytes([59049 % 256])),
])
def test_eof_policy_stops_before_input_or_uses_nagoya_sentinel(eof, reason, steps, a, output):
    result, _, _ = differential(program(23, 5, 81), eof=eof)
    assert (result.stop_reason, result.steps, result.a, result.output) == (reason, steps, a, output)


@requires_native
@pytest.mark.parametrize("limits,reason,steps,c,output", [
    ({"max_steps": 0}, "step_limit", 0, 0, b""),
    ({"max_steps": 1}, "step_limit", 1, 1, b""),
    ({"max_steps": 2}, "step_limit", 2, 2, b"X"),
    ({"max_steps": 3}, "step_limit", 3, 3, b"XX"),
    ({"max_steps": 4}, "terminated", 4, 3, b"XX"),
    ({"max_output": 0}, "output_limit", 1, 1, b""),
    ({"max_output": 1}, "output_limit", 2, 2, b"X"),
    ({"max_output": 2}, "terminated", 4, 3, b"XX"),
    ({"max_steps": 2, "max_output": 1}, "step_limit", 2, 2, b"X"),
])
def test_budget_stops_preserve_pending_instruction(limits, reason, steps, c, output):
    source = program(23, 5, 5, 81)
    result, _, memory = differential(source, b"X", **limits)
    assert (result.stop_reason, result.steps, result.c, result.output) == (reason, steps, c, output)
    # Neither HALT nor a stopped pending instruction is encrypted.
    assert memory[c] == source[c]


@requires_native
@pytest.mark.parametrize("raw", [0, 32, 127, 255, SIZE - 1, 0xffffffff])
def test_nonprintable_instruction_stops_without_mutation(raw):
    result, _, memory = differential(array("I", [raw, 81]), max_steps=1)
    assert result.stop_reason == "invalid_instruction"
    assert result.steps == result.c == result.d == result.a == 0
    assert memory.export_pages() == {}


@requires_native
@pytest.mark.parametrize("opcode", [39, 62])
def test_rotate_and_crazy_when_data_and_code_addresses_alias(opcode):
    source = program(opcode, 81)
    result, _, memory = differential(source, max_steps=1)
    value = rotate(source[0], CONFIG) if opcode == 39 else crazy(0, source[0], 20)
    assert result.a == value
    assert memory[0] == (ENCRYPT[value - 33] if 33 <= value <= 126 else value)
    assert (result.c, result.d) == (1, 1)


@requires_native
@pytest.mark.parametrize("target_value", [33, 126, 0, 127, SIZE - 1])
def test_jump_encrypts_new_code_address_only_when_printable(target_value):
    source = program(4, 81)
    target = source[0]
    result, _, memory = differential(source, writes=[(target, target_value)], max_steps=1)
    assert (result.c, result.d) == (target + 1, 1)
    assert memory[0] == source[0]
    assert memory[target] == (ENCRYPT[target_value - 33]
                              if 33 <= target_value <= 126 else target_value)


@requires_native
def test_registers_wrap_at_last_memory_cell():
    # MOVD selects cell 41; JMP uses that cell to reach the final address.
    result, _, memory = differential(
        program(40, 4), writes=[(41, SIZE - 1), (SIZE - 1, 68)], max_steps=2)
    assert (result.c, result.d) == (0, 42)
    assert memory[SIZE - 1] == ENCRYPT[68 - 33]
    result, _, _ = differential(program(40, 40, 81), writes=[(41, SIZE - 1)], max_steps=2)
    assert (result.c, result.d) == (2, 0)


@requires_native
def test_repeated_execution_resets_registers_and_uses_mutated_memory():
    python, compiled = memory_pair(program(23, 5, 81))
    for data in (b"A", b"B", b""):
        assert native.run_memory(compiled, data, max_steps=3) == run_memory(
            python, CONFIG, data, max_steps=3)
        assert_memory_equal(python, compiled)


@requires_native
def test_bounded_random_programs_and_sparse_data_states():
    rng = random.Random(0x20C0FFEE)
    # Sequential programs include aliasing self-modification and printable
    # unrecognized opcodes, which the VM executes as NOPs.
    for _ in range(24):
        opcodes = [rng.choice((5, 23, 39, 62, 68, 0, 93)) for _ in range(24)]
        source = program(*(opcodes + [81]))
        data = bytes(rng.randrange(256) for _ in range(12))
        differential(source, data, max_steps=rng.randrange(1, 32),
                     max_output=rng.randrange(5), eof=rng.choice(("stop", "sentinel")))
    # Keep data pointers valid while varying full-width rotate/crazy operands,
    # including data on either side of a page boundary and the final page.
    for address in (42, 4095, 4096, 4097, SIZE - 3):
        for _ in range(3):
            writes = [(41, address - 1),
                      (address, rng.randrange(SIZE)),
                      (address + 1, rng.randrange(SIZE))]
            differential(program(40, 40, 39, 62, 5, 81), writes=writes,
                         max_steps=6, max_output=1)


@requires_native
@pytest.mark.parametrize("source", [b"", b"D", b"D'", bytes(range(256)) * 17,
                                     array("I", [256, 59049, SIZE - 1, 0xffffffff])])
def test_frozen_fill_and_out_of_order_reads(source):
    python, compiled = memory_pair(source)
    probes = [SIZE - 1, 59050, 4096, 4095, len(source) + 13, 2, 0, 1]
    expected = {address: python[address] for address in probes}
    for address in probes:
        assert compiled[address] == expected[address]
    assert compiled.export_pages() == {}
    # Writes to the source tail cannot change later unread initialization.
    if len(source) >= 2:
        python[len(source) - 2] = compiled[len(source) - 2] = 7
        python[len(source) - 1] = compiled[len(source) - 1] = 11
    for address in reversed(probes):
        assert compiled[address] == python[address]
    for address in (100001, SIZE - 2, 2 * PAGE_SIZE + 37):
        assert compiled[address] == python[address]
    assert_memory_equal(python, compiled)


@requires_native
def test_slices_and_mutable_source_detachment():
    for source in (bytearray(b"D'"), array("I", [68, 59049, SIZE - 1]),
                   memoryview(array("I", [68, 39, 59049]))):
        python, compiled = memory_pair(source)
        source[0] = 1
        source[-1] = 2
        for selection in (slice(0, 12), slice(4093, 4100), slice(-7, None),
                          slice(12, 0, -2), slice(9, 9)):
            assert compiled[selection] == python[selection]
        assert_memory_equal(python, compiled)


@requires_native
def test_copies_detach_pages_and_count_unique_non_source_writes():
    python, compiled = memory_pair(bytes([68]) * (PAGE_SIZE + 1))
    for address, value in ((0, 255), (4095, SIZE - 1), (4096, 0),
                           (4097, 123), (SIZE - 1, 0xffffffff)):
        python[address] = compiled[address] = value
    assert compiled.get_allocated_count() == PAGE_SIZE + 3
    python_copy, native_copy = python.copy(), compiled.copy()
    for address, value in ((0, 256), (4097, 59049), (SIZE - 1, 17)):
        python[address] = compiled[address] = value
    for address, value in ((4095, 33), (4097, 44), (SIZE - 2, 55)):
        python_copy[address] = native_copy[address] = value
    assert native_copy[0] == 255
    assert compiled[4095] == SIZE - 1
    assert_memory_equal(python, compiled)
    assert_memory_equal(python_copy, native_copy)
    assert compiled.get_allocated_count() == PAGE_SIZE + 3
    assert native_copy.get_allocated_count() == PAGE_SIZE + 4


@requires_native
def test_snapshot_and_exports_survive_owner_mutation_and_deletion():
    python, memory = memory_pair(array("I", [68, 59049]), writes=[(4097, 123)])
    snapshot = memory.copy()
    reference = python.copy()
    exported = memory.export_pages()
    memory[4097] = 456
    assert exported == snapshot.export_pages()
    del memory
    assert snapshot[4097] == 123
    assert_memory_equal(reference, snapshot)
    snapshot[4097] = reference[4097] = 789
    assert exported != snapshot.export_pages()
    assert_memory_equal(reference, snapshot)


@requires_native
def test_successful_reinitialization_keeps_existing_copies_intact():
    python, memory = memory_pair(b"D'", writes=[(4097, 123), (SIZE - 1, 456)])
    python_copy, native_copy = python.copy(), memory.copy()
    source = array("I", [81, 59049, SIZE - 1])
    memory.__init__(source)
    python.initialize_source(source)
    assert_memory_equal(python, memory)
    assert memory.export_pages() == {}
    assert memory.get_allocated_count() == len(source)
    assert native_copy[4097] == 123
    assert native_copy[SIZE - 1] == 456
    assert_memory_equal(python_copy, native_copy)
    native_copy[4097] = python_copy[4097] = 789
    assert_memory_equal(python, memory)
    assert_memory_equal(python_copy, native_copy)


@requires_native
@pytest.mark.parametrize("source", [[-1, 68], [0x100000000, 68], [1.5, 68]])
def test_invalid_reinitialization_preserves_original_memory(source):
    python, memory = memory_pair(b"D'", writes=[(4097, 123), (SIZE - 1, 456)])
    before = memory.export_pages()
    with pytest.raises((ValueError, OverflowError, TypeError)):
        memory.__init__(source)
    assert memory.export_pages() == before
    assert_memory_equal(python, memory)
    for address in (0, 1, 2, 4096, 4097, SIZE - 1):
        assert memory[address] == python[address]


@requires_native
@pytest.mark.skipif(
    not all(hasattr(signal, name) for name in
            ("SIGALRM", "ITIMER_REAL", "getitimer", "setitimer")),
    reason="requires POSIX interval signals")
def test_signal_callback_cannot_replace_running_wrapper_memory():
    steps = 300000
    source = bytes(instruction(68, address) for address in range(steps))
    python, memory = memory_pair(source)
    rejected = []
    replacement = program(81)

    def reinitialize_during_run(signum, frame):
        # A timer may fire before the call enters C on a heavily loaded host.
        # Wait until an execution write is visible before attempting reinit.
        if memory[0] == source[0]:
            signal.setitimer(signal.ITIMER_REAL, 0.0001)
            return
        try:
            memory.__init__(replacement)
        except RuntimeError as error:
            rejected.append(str(error))
        else:
            rejected.append(None)

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, 0)
    try:
        signal.signal(signal.SIGALRM, reinitialize_during_run)
        signal.setitimer(signal.ITIMER_REAL, 0.0001)
        actual = native.run_memory(memory, max_steps=steps)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
    assert rejected, "signal callback did not run during the bounded native loop"
    assert all(message is not None and "running" in message for message in rejected)
    expected = run_memory(python, CONFIG, max_steps=steps)
    assert actual == expected
    assert (actual.stop_reason, actual.steps) == ("step_limit", steps)
    assert_memory_equal(python, memory)


@requires_native
@pytest.mark.parametrize("address", [-1, SIZE, SIZE + 1])
def test_invalid_memory_addresses(address):
    memory = native.NativeMemory(b"D'")
    with pytest.raises(IndexError):
        memory[address]
    with pytest.raises(IndexError):
        memory[address] = 1
    assert memory.export_pages() == {}


@requires_native
@pytest.mark.parametrize("value", [-1, 0x100000000, 1.5, "1"])
def test_external_writes_reject_non_uint32_without_mutation(value):
    memory = native.NativeMemory(b"D'")
    with pytest.raises((ValueError, OverflowError, TypeError)):
        memory[4096] = value
    assert memory.export_pages() == {}
    assert memory.get_allocated_count() == 2


@requires_native
@pytest.mark.parametrize("source", [[-1, 68], [0x100000000, 68], [1.5, 68]])
def test_source_rejects_values_outside_uint32(source):
    with pytest.raises((ValueError, OverflowError, TypeError)):
        native.NativeMemory(source)


@requires_native
@pytest.mark.parametrize("keyword", ["max_steps", "max_output"])
@pytest.mark.parametrize("value", [-1, True, 1.5, "1"])
def test_invalid_budget_arguments_do_not_mutate_memory(keyword, value):
    python, compiled = memory_pair(program(81))
    with pytest.raises(ValueError):
        native.run_memory(compiled, **{keyword: value})
    assert_memory_equal(python, compiled)


@requires_native
@pytest.mark.parametrize("arguments,exception", [
    ({"input_data": 7}, TypeError),
    ({"input_data": [65]}, TypeError),
    ({"eof": "unknown"}, ValueError),
])
def test_invalid_io_arguments_do_not_mutate_memory(arguments, exception):
    python, compiled = memory_pair(program(81))
    with pytest.raises(exception):
        native.run_memory(compiled, **arguments)
    assert_memory_equal(python, compiled)


@requires_native
def test_run20_native_matches_explicit_python_engine():
    source = program(23, 5, 81)
    assert run20(source, "é", engine="native") == run20(source, "é", engine="python")
    wide_halt = chr(81 + 94 * 100)
    assert run20(wide_halt, engine="native") == run20(wide_halt, engine="python")


@requires_native
@pytest.mark.parametrize("max_steps,reason,steps", [(None, "terminated", 1),
                                                   (0, "step_limit", 0)])
def test_halt_counts_as_step_without_encryption(max_steps, reason, steps):
    result, _, memory = differential(program(81), max_steps=max_steps)
    assert (result.stop_reason, result.steps, result.c, result.d) == (reason, steps, 0, 0)
    assert memory.export_pages() == {}


@requires_native
def test_invalid_jump_address_is_a_checked_exception():
    python, compiled = memory_pair(program(40, 4), writes=[(41, SIZE)])
    with pytest.raises(IndexError):
        run_memory(python, CONFIG, max_steps=2)
    with pytest.raises(IndexError):
        native.run_memory(compiled, max_steps=2)


def test_unavailable_extension_has_explicit_error_and_default_still_works(monkeypatch):
    def missing_module(name):
        raise ImportError("extension deliberately unavailable for test")

    monkeypatch.setattr(native, "import_module", missing_module)
    assert native.native_available() is False
    assert run20(program(81)).stop_reason == "terminated"
    with pytest.raises(RuntimeError, match="scripts/build_native_vm.py"):
        run20(program(81), engine="native")


def test_unknown_engine_is_rejected():
    with pytest.raises(ValueError, match="engine"):
        run20(program(81), engine="automatic")


@requires_native
def test_run_requires_native_memory():
    python = SparseMemory(CONFIG)
    with pytest.raises(TypeError, match="NativeMemory"):
        native.run_memory(python)
