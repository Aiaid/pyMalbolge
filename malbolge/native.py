"""Opt-in native Malbolge20 execution with the bounded Python VM contract.

Build the extension with ``uv run python scripts/build_native_vm.py``.
Importing this module never compiles code or changes the default interpreter.
"""
from array import array
from importlib import import_module
from operator import index

from .core import MalbolgeConfig, RunResult, parse_source


_CONFIG = MalbolgeConfig.malbolge20()


def _extension():
    try:
        return import_module("malbolge._native_vm")
    except ImportError as error:
        raise RuntimeError(
            "Native VM is unavailable for this Python interpreter; build it with "
            "'uv run python scripts/build_native_vm.py'."
        ) from error


def native_available():
    """Whether an extension built for this Python interpreter can be loaded."""
    try:
        import_module("malbolge._native_vm")
    except ImportError:
        return False
    return True


def jit_available():
    """Whether this extension offers the experimental machine-code backend."""
    try:
        extension = import_module("malbolge._native_vm")
    except ImportError:
        return False
    query = getattr(extension, "jit_available", None)
    return bool(query()) if query is not None else False


class NativeMemory:
    """Immutable source and native uint32 mutable pages for Malbolge20.

    Reads do not allocate or change initialization defaults. Copies share
    pages until a write. Inspection exports use native-endian uint32 bytes;
    written masks contain one byte per cell, matching SparseMemory accounting.
    External writes accept uint32 integers; arbitrary Python integers remain
    supported by the Python SparseMemory implementation.
    """
    __slots__ = ("_state",)
    _PAGE_SIZE = 4096
    size = _CONFIG.memory_size
    config = _CONFIG

    def __init__(self, source_cells=b""):
        if len(source_cells) > self.size:
            raise ValueError("Source file is too long")
        if isinstance(source_cells, array) or (
                isinstance(source_cells, memoryview) and source_cells.itemsize > 1):
            words = array("I", source_cells)
            if words.itemsize != 4:
                raise RuntimeError("Native VM requires four-byte unsigned int words")
            data, word_size = words.tobytes(), 4
        else:
            try:
                data, word_size = bytes(source_cells), 1
            except (ValueError, OverflowError):
                words = array("I", source_cells)
                if words.itemsize != 4:
                    raise RuntimeError("Native VM requires four-byte unsigned int words")
                data, word_size = words.tobytes(), 4
        try:
            state = self._state
        except AttributeError:
            self._state = _extension()._Memory(data, word_size=word_size)
        else:
            # Preserve the raw state's busy guard during signal callbacks,
            # rather than replacing the wrapper's currently running state.
            state.__init__(data, word_size=word_size)

    def __len__(self):
        return self.size

    def __getitem__(self, address):
        if isinstance(address, slice):
            return [self._state[i] for i in range(*address.indices(self.size))]
        return self._state[index(address)]

    def __setitem__(self, address, value):
        self._state[index(address)] = index(value)

    def copy(self):
        result = object.__new__(type(self))
        result._state = self._state.copy()
        return result

    def get_allocated_count(self):
        return self._state.get_allocated_count()

    def export_pages(self):
        """Return detached page values and write masks for parity checks."""
        return self._state.export_pages()


    def jit_stats(self):
        """Last-run translation/coverage metrics and process cache sizes."""
        return self._state.jit_stats()


def run_memory(memory, input_data=b"", *, max_steps=None,
               max_output=None, eof="sentinel", jit=False):
    """Execute prepared NativeMemory and return the ordinary RunResult.

    Registers start at zero on each call, as with core.run_memory. The memory
    keeps execution writes. No implicit transfer from a Python memory object
    occurs, making preparation and execution independently measurable.
    """
    if not isinstance(memory, NativeMemory):
        raise TypeError("memory must be NativeMemory")
    if isinstance(input_data, str):
        data = input_data.encode("utf8")
    elif isinstance(input_data, (bytes, bytearray, memoryview)):
        data = bytes(input_data)
    else:
        raise TypeError("input_data must be text or bytes-like")
    for name, value in (("max_steps", max_steps), ("max_output", max_output)):
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError("{} must be a nonnegative integer or None".format(name))
    if eof not in ("sentinel", "stop"):
        raise ValueError("eof must be 'stop' or 'sentinel'")
    if type(jit) is not bool:
        raise ValueError("jit must be a boolean")
    options = {"max_steps": max_steps, "max_output": max_output,
               "eof_stop": eof == "stop"}
    if jit:
        if not jit_available():
            raise RuntimeError("Experimental JIT is unavailable; rebuild the native "
                               "extension for a supported ARM64 interpreter")
        options["jit"] = True
    return RunResult(*memory._state.run(data, **options))


def run20(code, input_data=b"", *, max_steps=None, max_output=None,
          eof="sentinel", jit=False):
    """Validate ordinary source, prepare native memory and execute it."""
    memory = NativeMemory(parse_source(code, _CONFIG))
    return run_memory(memory, input_data, max_steps=max_steps,
                      max_output=max_output, eof=eof, jit=jit)
