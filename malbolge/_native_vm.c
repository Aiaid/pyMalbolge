/* Optional Malbolge20 execution core; semantics are defined by core.py.
 *
 * This is deliberately independent of any reference interpreter. Immutable
 * source bytes and the frozen crazy-fill cycle are shared by snapshots. A
 * two-level page table allocates only on writes, and mutable pages use native
 * reference counts for copy-on-write. All ownership changes happen with the
 * GIL held. The execution loop also retains the GIL, checking signals every
 * 16384 instructions. The busy flag protects against signal-handler callbacks
 * that try to mutate, copy, reinitialize, or recursively run the same memory.
 */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdint.h>
#include <string.h>
#include <limits.h>

#define MEMORY_SIZE UINT64_C(3486784401)
#define ROTATE_MULTIPLIER UINT64_C(1162261467)
#define PAGE_BITS 12
#define PAGE_SIZE (1U << PAGE_BITS)
#define TABLE_BITS 10
#define TABLE_SIZE (1U << TABLE_BITS)
#define PAGE_COUNT ((MEMORY_SIZE + PAGE_SIZE - 1) / PAGE_SIZE)
#define ROOT_COUNT ((PAGE_COUNT + TABLE_SIZE - 1) / TABLE_SIZE)
#define SIGNAL_INTERVAL UINT64_C(16384)

#include "_native_jit.h"

typedef struct {
    uint32_t previous2;
    uint32_t previous1;
    uint32_t value;
} FillStep;

typedef struct {
    size_t refs;
    PyObject *bytes;
    const unsigned char *data;
    uint64_t length;
    uint64_t fill_start;
    int word_size;
    FillStep *fill;
    size_t fill_length;
    size_t cycle_start;
    size_t cycle_length;
} Source;

typedef struct {
    size_t refs;
    uint32_t length;
    uint32_t values[PAGE_SIZE];
    unsigned char written[PAGE_SIZE];
} Page;

typedef struct {
    Page *pages[TABLE_SIZE];
} PageTable;

typedef struct {
    PyObject_HEAD
    Source *source;
    PageTable *tables[ROOT_COUNT];
    uint64_t allocated_count;
    int busy;
    JitRunStats jit_stats;
} NativeMemory;

static uint8_t crazy_quads[81][81];
static const unsigned char encrypt_table[] =
    "5z]&gqtyfr$(we4{WP)H-Zn,[%\\3dL+Q;>U!pJS72FhOA1CB"
    "6v^=I_0/8|jsb9m<.TVac`uY*MK'X~xDl}REokN:#?G\"i@";

static void
initialize_crazy_table(void)
{
    static const uint8_t trits[3][3] = {
        {1, 0, 0}, {1, 0, 2}, {2, 2, 1}
    };
    unsigned a, b;
    for (b = 0; b < 81; ++b) {
        for (a = 0; a < 81; ++a) {
            unsigned left = a, right = b, result = 0, power = 1, i;
            for (i = 0; i < 4; ++i) {
                result += trits[right % 3][left % 3] * power;
                left /= 3;
                right /= 3;
                power *= 3;
            }
            crazy_quads[b][a] = (uint8_t)result;
        }
    }
}

static inline uint32_t
crazy20(uint32_t a, uint32_t b)
{
    /* Five base-81 digits are exactly 20 trits. Higher trits are discarded,
     * matching crazy(a, b, 20), including externally supplied uint32 values. */
    uint32_t result = 0, power = 1;
    unsigned i;
    for (i = 0; i < 5; ++i) {
        result += (uint32_t)crazy_quads[b % 81][a % 81] * power;
        a /= 81;
        b /= 81;
        power *= 81;
    }
    return result;
}

static inline uint32_t
source_cell(const Source *source, uint64_t address)
{
    uint32_t value;
    if (source->word_size == 1) {
        return source->data[(size_t)address];
    }
    /* Native-endian array('I') payload, without alignment/aliasing assumptions. */
    memcpy(&value, source->data + (size_t)address * sizeof(value), sizeof(value));
    return value;
}

static void
source_release(Source *source)
{
    if (source != NULL && --source->refs == 0) {
        Py_XDECREF(source->bytes);
        PyMem_Free(source->fill);
        PyMem_Free(source);
    }
}

static Source *
source_create(PyObject *bytes, int word_size)
{
    Source *source;
    uint32_t previous1, previous2;
    size_t capacity = 0, i;
    Py_ssize_t byte_length = PyBytes_GET_SIZE(bytes);
    if (byte_length % word_size != 0) {
        PyErr_SetString(PyExc_ValueError,
                        "source_bytes length must be divisible by word_size");
        return NULL;
    }
    if ((uint64_t)(byte_length / word_size) > MEMORY_SIZE) {
        PyErr_SetString(PyExc_ValueError, "Source file is too long");
        return NULL;
    }
    source = PyMem_Calloc(1, sizeof(*source));
    if (source == NULL) {
        PyErr_NoMemory();
        return NULL;
    }
    source->refs = 1;
    if (PyBytes_CheckExact(bytes)) {
        Py_INCREF(bytes);
        source->bytes = bytes;
    } else {
        /* Do not retain arbitrary bytes-subclass attributes/finalizers in
         * this non-GC-tracked native ownership graph. */
        source->bytes = PyBytes_FromStringAndSize(PyBytes_AS_STRING(bytes),
                                                  byte_length);
        if (source->bytes == NULL) {
            source_release(source);
            return NULL;
        }
    }
    source->data = (const unsigned char *)PyBytes_AS_STRING(source->bytes);
    source->word_size = word_size;
    source->length = (uint64_t)(byte_length / word_size);
    source->fill_start = source->length < 2 ? 2 : source->length;
    previous1 = source->length > 1 ? source_cell(source, source->length - 1) : 0;
    previous2 = source->length > 1 ? source_cell(source, source->length - 2) :
                (source->length != 0 ? source_cell(source, 0) : 0);

    /* Store transitions until the word pair repeats, just as SparseMemory
     * does. Do not infer a phase from mutated cells or assume no transient. */
    for (;;) {
        uint32_t next;
        for (i = 0; i < source->fill_length; ++i) {
            if (source->fill[i].previous2 == previous2 &&
                source->fill[i].previous1 == previous1) {
                source->cycle_start = i;
                source->cycle_length = source->fill_length - i;
                return source;
            }
        }
        if (source->fill_length == capacity) {
            FillStep *grown;
            size_t next_capacity = capacity == 0 ? 16 : capacity * 2;
            if (next_capacity < capacity ||
                next_capacity > SIZE_MAX / sizeof(*grown)) {
                PyErr_NoMemory();
                source_release(source);
                return NULL;
            }
            grown = PyMem_Realloc(source->fill, next_capacity * sizeof(*grown));
            if (grown == NULL) {
                PyErr_NoMemory();
                source_release(source);
                return NULL;
            }
            source->fill = grown;
            capacity = next_capacity;
        }
        next = crazy20(previous1, previous2);
        source->fill[source->fill_length].previous2 = previous2;
        source->fill[source->fill_length].previous1 = previous1;
        source->fill[source->fill_length].value = next;
        ++source->fill_length;
        previous2 = previous1;
        previous1 = next;
    }
}

static inline uint32_t
initial_value(const Source *source, uint64_t address)
{
    uint64_t offset;
    if (address < source->length) {
        return source_cell(source, address);
    }
    if (address < source->fill_start) {
        return 0;
    }
    offset = address - source->fill_start;
    if (offset >= source->fill_length) {
        offset = source->cycle_start +
                 (offset - source->cycle_start) % source->cycle_length;
    }
    return source->fill[(size_t)offset].value;
}

static void
page_release(Page *page)
{
    if (page != NULL && --page->refs == 0) {
        PyMem_Free(page);
    }
}

static void
memory_clear(NativeMemory *self)
{
    size_t i, j;
    for (i = 0; i < ROOT_COUNT; ++i) {
        PageTable *table = self->tables[i];
        if (table != NULL) {
            for (j = 0; j < TABLE_SIZE; ++j) {
                page_release(table->pages[j]);
            }
            PyMem_Free(table);
            self->tables[i] = NULL;
        }
    }
    source_release(self->source);
    self->source = NULL;
    self->allocated_count = 0;
}

static int
require_initialized(NativeMemory *self)
{
    if (self->source == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "Native memory is not initialized");
        return -1;
    }
    return 0;
}

static int
require_idle(NativeMemory *self)
{
    if (self->busy) {
        PyErr_SetString(PyExc_RuntimeError, "Native memory is already running");
        return -1;
    }
    return 0;
}

static int
address_error(uint64_t address)
{
    PyErr_Format(PyExc_IndexError,
                 "Memory address %llu out of range (0-%llu)",
                 (unsigned long long)address,
                 (unsigned long long)(MEMORY_SIZE - 1));
    return -1;
}

static inline int
memory_read(NativeMemory *self, uint64_t address, uint32_t *value)
{
    uint64_t page_index;
    PageTable *table;
    Page *page;
    if (address >= MEMORY_SIZE) {
        return address_error(address);
    }
    page_index = address >> PAGE_BITS;
    table = self->tables[page_index >> TABLE_BITS];
    page = table == NULL ? NULL : table->pages[page_index & (TABLE_SIZE - 1)];
    *value = page == NULL ? initial_value(self->source, address) :
                           page->values[address & (PAGE_SIZE - 1)];
    return 0;
}

static inline Page *
memory_writable_page(NativeMemory *self, uint64_t address)
{
    uint64_t page_index, start, remaining;
    size_t slot, i;
    PageTable *table;
    Page *page;
    if (address >= MEMORY_SIZE) {
        address_error(address);
        return NULL;
    }
    page_index = address >> PAGE_BITS;
    slot = (size_t)(page_index & (TABLE_SIZE - 1));
    table = self->tables[page_index >> TABLE_BITS];
    if (table == NULL) {
        table = PyMem_Calloc(1, sizeof(*table));
        if (table == NULL) {
            PyErr_NoMemory();
            return NULL;
        }
        self->tables[page_index >> TABLE_BITS] = table;
    }
    page = table->pages[slot];
    if (page == NULL) {
        page = PyMem_Calloc(1, sizeof(*page));
        if (page == NULL) {
            PyErr_NoMemory();
            return NULL;
        }
        page->refs = 1;
        start = page_index << PAGE_BITS;
        remaining = MEMORY_SIZE - start;
        page->length = remaining < PAGE_SIZE ? (uint32_t)remaining : PAGE_SIZE;
        for (i = 0; i < page->length; ++i) {
            page->values[i] = initial_value(self->source, start + i);
        }
        table->pages[slot] = page;
    } else if (page->refs > 1) {
        Page *copy = PyMem_Malloc(sizeof(*copy));
        if (copy == NULL) {
            PyErr_NoMemory();
            return NULL;
        }
        memcpy(copy, page, sizeof(*copy));
        copy->refs = 1;
        page_release(page);
        page = table->pages[slot] = copy;
    }
    return page;
}

static inline int
memory_write(NativeMemory *self, uint64_t address, uint32_t value)
{
    Page *page = memory_writable_page(self, address);
    size_t offset = (size_t)(address & (PAGE_SIZE - 1));
    if (page == NULL) {
        return -1;
    }
    page->values[offset] = value;
    if (address >= self->source->length && !page->written[offset]) {
        page->written[offset] = 1;
        ++self->allocated_count;
    }
    return 0;
}

static int
memory_init(NativeMemory *self, PyObject *args, PyObject *kwargs)
{
    static char *keywords[] = {"source_bytes", "word_size", NULL};
    PyObject *bytes;
    Source *source;
    int word_size = 1;
    if (require_idle(self) < 0) {
        return -1;
    }
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O|i:_Memory", keywords,
                                     &bytes, &word_size)) {
        return -1;
    }
    if (!PyBytes_Check(bytes)) {
        PyErr_SetString(PyExc_TypeError, "source_bytes must be immutable bytes");
        return -1;
    }
    if (word_size != 1 && word_size != 4) {
        PyErr_SetString(PyExc_ValueError, "word_size must be 1 or 4");
        return -1;
    }
    source = source_create(bytes, word_size);
    if (source == NULL) {
        return -1;
    }
    /* Successful construction is atomic with respect to an existing memory. */
    memory_clear(self);
    self->source = source;
    self->allocated_count = source->length;
    memset(&self->jit_stats, 0, sizeof(self->jit_stats));
    return 0;
}

static void
memory_dealloc(NativeMemory *self)
{
    memory_clear(self);
    Py_TYPE(self)->tp_free((PyObject *)self);
}

static Py_ssize_t
memory_length(NativeMemory *self)
{
    (void)self;
    if (MEMORY_SIZE > (uint64_t)PY_SSIZE_T_MAX) {
        PyErr_SetString(PyExc_OverflowError,
                        "Malbolge20 memory length does not fit Py_ssize_t");
        return -1;
    }
    return (Py_ssize_t)MEMORY_SIZE;
}

static int
parse_address(PyObject *key, uint64_t *address)
{
    PyObject *integer = PyNumber_Index(key);
    unsigned long long value;
    if (integer == NULL) {
        return -1;
    }
    value = PyLong_AsUnsignedLongLong(integer);
    if (PyErr_Occurred()) {
        if (PyErr_ExceptionMatches(PyExc_OverflowError)) {
            PyErr_Clear();
            PyErr_Format(PyExc_IndexError,
                         "Memory address %S out of range (0-%llu)", integer,
                         (unsigned long long)(MEMORY_SIZE - 1));
        }
        Py_DECREF(integer);
        return -1;
    }
    Py_DECREF(integer);
    if ((uint64_t)value >= MEMORY_SIZE) {
        return address_error((uint64_t)value);
    }
    *address = (uint64_t)value;
    return 0;
}

static PyObject *
memory_subscript(NativeMemory *self, PyObject *key)
{
    uint64_t address;
    uint32_t value;
    if (require_initialized(self) < 0 || parse_address(key, &address) < 0 ||
        memory_read(self, address, &value) < 0) {
        return NULL;
    }
    return PyLong_FromUnsignedLong(value);
}

static int
memory_ass_subscript(NativeMemory *self, PyObject *key, PyObject *value)
{
    uint64_t address;
    unsigned long long word;
    PyObject *integer;
    if (require_idle(self) < 0 || require_initialized(self) < 0) {
        return -1;
    }
    if (value == NULL) {
        PyErr_SetString(PyExc_TypeError, "Native memory cells cannot be deleted");
        return -1;
    }
    if (parse_address(key, &address) < 0) {
        return -1;
    }
    integer = PyNumber_Index(value);
    if (integer == NULL) {
        return -1;
    }
    word = PyLong_AsUnsignedLongLong(integer);
    Py_DECREF(integer);
    if (PyErr_Occurred()) {
        return -1;
    }
    if (word > UINT32_MAX) {
        PyErr_SetString(PyExc_OverflowError,
                        "Native memory values must fit an unsigned 32-bit integer");
        return -1;
    }
    return memory_write(self, address, (uint32_t)word);
}

static PyObject *
memory_copy(NativeMemory *self, PyObject *unused)
{
    NativeMemory *copy;
    size_t i, j;
    (void)unused;
    if (require_idle(self) < 0 || require_initialized(self) < 0) {
        return NULL;
    }
    if (self->source->refs == SIZE_MAX) {
        return PyErr_NoMemory();
    }
    copy = (NativeMemory *)Py_TYPE(self)->tp_alloc(Py_TYPE(self), 0);
    if (copy == NULL) {
        return NULL;
    }
    copy->source = self->source;
    ++copy->source->refs;
    copy->allocated_count = self->allocated_count;
    for (i = 0; i < ROOT_COUNT; ++i) {
        if (self->tables[i] != NULL) {
            PageTable *table = PyMem_Calloc(1, sizeof(*table));
            if (table == NULL) {
                PyErr_NoMemory();
                Py_DECREF(copy);
                return NULL;
            }
            copy->tables[i] = table;
            for (j = 0; j < TABLE_SIZE; ++j) {
                Page *page = self->tables[i]->pages[j];
                if (page != NULL) {
                    if (page->refs == SIZE_MAX) {
                        PyErr_NoMemory();
                        Py_DECREF(copy);
                        return NULL;
                    }
                    ++page->refs;
                    table->pages[j] = page;
                }
            }
        }
    }
    return (PyObject *)copy;
}

static PyObject *
memory_allocated_count(NativeMemory *self, PyObject *unused)
{
    (void)unused;
    if (require_initialized(self) < 0) {
        return NULL;
    }
    return PyLong_FromUnsignedLongLong((unsigned long long)self->allocated_count);
}

static PyObject *
memory_export_pages(NativeMemory *self, PyObject *unused)
{
    PyObject *result;
    size_t i, j;
    int was_busy;
    (void)unused;
    if (require_initialized(self) < 0) {
        return NULL;
    }
    /* Tuple/dict allocation can invoke GC finalizers. Preserve page pointers
     * throughout export even when a finalizer calls back into this memory.
     * Read-only export is also allowed from a running VM's signal handler. */
    was_busy = self->busy;
    self->busy = 1;
    result = PyDict_New();
    if (result == NULL) {
        self->busy = was_busy;
        return NULL;
    }
    for (i = 0; i < ROOT_COUNT; ++i) {
        PageTable *table = self->tables[i];
        if (table == NULL) {
            continue;
        }
        for (j = 0; j < TABLE_SIZE; ++j) {
            Page *page = table->pages[j];
            PyObject *values, *written, *record, *key;
            int status;
            if (page == NULL) {
                continue;
            }
            values = PyBytes_FromStringAndSize((const char *)page->values,
                         (Py_ssize_t)page->length * (Py_ssize_t)sizeof(uint32_t));
            if (values == NULL) {
                goto error;
            }
            written = PyBytes_FromStringAndSize((const char *)page->written,
                                               (Py_ssize_t)page->length);
            if (written == NULL) {
                Py_DECREF(values);
                goto error;
            }
            record = PyTuple_Pack(2, values, written);
            Py_DECREF(values);
            Py_DECREF(written);
            if (record == NULL) {
                goto error;
            }
            key = PyLong_FromSize_t((i << TABLE_BITS) + j);
            if (key == NULL) {
                Py_DECREF(record);
                goto error;
            }
            status = PyDict_SetItem(result, key, record);
            Py_DECREF(key);
            Py_DECREF(record);
            if (status < 0) {
                goto error;
            }
        }
    }
    self->busy = was_busy;
    return result;
error:
    Py_DECREF(result);
    self->busy = was_busy;
    return NULL;
}

static int
parse_limit(PyObject *value, const char *name, uint64_t *limit, int *enabled)
{
    unsigned long long parsed;
    PyObject *zero;
    int negative;
    *enabled = 0;
    if (value == Py_None) {
        return 0;
    }
    if (!PyLong_CheckExact(value)) {
        PyErr_Format(PyExc_ValueError,
                     "%s must be a nonnegative integer or None", name);
        return -1;
    }
    zero = PyLong_FromLong(0);
    if (zero == NULL) {
        return -1;
    }
    negative = PyObject_RichCompareBool(value, zero, Py_LT);
    Py_DECREF(zero);
    if (negative < 0) {
        return -1;
    }
    if (negative) {
        PyErr_Format(PyExc_ValueError,
                     "%s must be a nonnegative integer or None", name);
        return -1;
    }
    parsed = PyLong_AsUnsignedLongLong(value);
    if (PyErr_Occurred()) {
        if (!PyErr_ExceptionMatches(PyExc_OverflowError)) {
            return -1;
        }
        /* A larger Python budget cannot be reached by the uint64 counter.
         * Accept it; report counter overflow if that boundary is ever reached. */
        PyErr_Clear();
        return 0;
    }
    *limit = (uint64_t)parsed;
    *enabled = 1;
    return 0;
}

static int
append_output(char **buffer, Py_ssize_t *length, Py_ssize_t *capacity,
              unsigned char value)
{
    if (*length == *capacity) {
        Py_ssize_t next_capacity;
        char *grown;
        if (*length == PY_SSIZE_T_MAX) {
            PyErr_SetString(PyExc_OverflowError, "Native output is too large");
            return -1;
        }
        next_capacity = *capacity == 0 ? 4096 :
                        (*capacity > PY_SSIZE_T_MAX / 2 ? PY_SSIZE_T_MAX :
                         *capacity * 2);
        grown = PyMem_Realloc(*buffer, (size_t)next_capacity);
        if (grown == NULL) {
            PyErr_NoMemory();
            return -1;
        }
        *buffer = grown;
        *capacity = next_capacity;
    }
    (*buffer)[(*length)++] = (char)value;
    return 0;
}

static PyObject *
memory_jit_stats(NativeMemory *self, PyObject *unused)
{
    JitRunStats *stats = &self->jit_stats;
    (void)unused;
    if (require_initialized(self) < 0) {
        return NULL;
    }
    /* The capability query is nonallocating. Arena/cache sizes describe the
     * process cache; all execution and compilation counters describe this
     * memory object's most recent valid run request. */
    return Py_BuildValue(
        "{s:O,s:O,s:K,s:K,s:K,s:K,s:K,s:K,s:d,s:d,s:K,s:K,s:K}",
        "enabled", stats->enabled ? Py_True : Py_False,
        "available", jit_probe() ? Py_True : Py_False,
        "compiled_blocks", (unsigned long long)stats->compiled_blocks,
        "compiled_bytes", (unsigned long long)stats->compiled_bytes,
        "jit_blocks", (unsigned long long)stats->jit_blocks,
        "jit_steps", (unsigned long long)stats->jit_steps,
        "guard_failures", (unsigned long long)stats->guard_failures,
        "fallback_steps", (unsigned long long)stats->fallback_steps,
        "compile_cpu_seconds", stats->compile_cpu_seconds,
        "compile_wall_seconds", stats->compile_wall_seconds,
        "cache_entries", (unsigned long long)jit_cache_entries,
        "cache_code_bytes", (unsigned long long)jit_cache_code_bytes,
        "cache_mapped_bytes", (unsigned long long)(jit_arena == NULL ? 0 :
                                                    JIT_ARENA_BYTES));
}

static int
memory_jit_nops(NativeMemory *self, uint64_t c, uint64_t d, uint64_t steps,
                int steps_enabled, uint64_t step_limit)
{
    uint64_t bound = JIT_MAX_CELLS, remaining;
    unsigned residue = (unsigned)(c % 94), shape, span, completed, i;
    JitBlock *block = NULL;
    Page *page;
    size_t offset = (size_t)(c & (PAGE_SIZE - 1));
    /* A signal handler can run a different memory object, catch a failed
     * Linux RX restoration, and return to this already-active run. Check
     * global capability before every dispatch, not just at run entry, so
     * cached pointers are never called after the arena becomes unavailable. */
    if (jit_require_available() < 0) {
        return -1;
    }
    /* Never cross a physical page, memory wrap, signal boundary, budget, or
     * uint64 counter boundary. In particular D outside the address space is
     * incremented normally, as run_memory does, instead of being wrapped. */
    remaining = PAGE_SIZE - offset;
    if (bound > remaining) bound = remaining;
    remaining = MEMORY_SIZE - c;
    if (bound > remaining) bound = remaining;
    remaining = SIGNAL_INTERVAL - (steps & (SIGNAL_INTERVAL - 1));
    if (bound > remaining) bound = remaining;
    remaining = UINT64_MAX - steps;
    if (bound > remaining) bound = remaining;
    remaining = UINT64_MAX - d;
    if (bound > remaining) bound = remaining;
    if (steps_enabled && bound > step_limit - steps) {
        bound = step_limit - steps;
    }
    if (bound < 2) {
        return 0;
    }
    /* Hot code can guard a longer shape than the current NOP run. The kernel
     * returns the exact successful prefix, allowing changed later cells to
     * fall back without rescanning an already-cached shape in the C loop. */
    for (shape = JIT_SHAPES; shape > 0; --shape) {
        JitBlock *candidate = &jit_cache[residue][shape - 1];
        if ((2U << (shape - 1)) <= bound && candidate->kernel != NULL) {
            block = candidate;
            break;
        }
    }
    if (block == NULL || (uint64_t)block->length * 2 <= bound) {
        /* A short early budget must not permanently pin this residue to a
         * short kernel. Inspect only the extra tail when a larger shape can
         * fit; the cached prefix still has machine guards on every cell. */
        for (span = block == NULL ? 0 : block->length; span < bound; ++span) {
            uint32_t raw;
            if (memory_read(self, c + span, &raw) < 0) {
                return -1;
            }
            if (raw != jit_nop_raw(residue + span)) {
                break;
            }
        }
        if (span < 2) {
            return 0;
        }
        shape = 0;
        while (shape + 1 < JIT_SHAPES && (2U << (shape + 1)) <= span) {
            ++shape;
        }
        if (block == NULL || (2U << shape) > block->length) {
            block = jit_compile(residue, shape, encrypt_table, &self->jit_stats);
            if (block == NULL) {
                return -1;
            }
        }
    }
    /* Prepare COW ownership without a fake write. Only cells actually
     * completed by the guarded machine code count as explicit writes. */
    page = memory_writable_page(self, c);
    if (page == NULL) {
        return -1;
    }
    completed = block->kernel(page->values + offset);
    ++self->jit_stats.jit_blocks;
    if (completed > block->length) {
        PyErr_SetString(PyExc_RuntimeError, "ARM64 JIT returned an invalid prefix");
        return -1;
    }
    self->jit_stats.jit_steps += completed;
    if (completed < block->length) {
        ++self->jit_stats.guard_failures;
    }
    if (c + completed > self->source->length) {
        unsigned first = c < self->source->length ?
                         (unsigned)(self->source->length - c) : 0;
        for (i = first; i < completed; ++i) {
            if (!page->written[offset + i]) {
                page->written[offset + i] = 1;
                ++self->allocated_count;
            }
        }
    }
    return (int)completed;
}

static PyObject *
memory_run(NativeMemory *self, PyObject *args, PyObject *kwargs)
{
    static char *keywords[] = {"input_bytes", "max_steps", "max_output",
                               "eof_stop", "jit", NULL};
    PyObject *input, *steps_arg = Py_None, *output_arg = Py_None;
    PyObject *output_bytes, *result;
    const unsigned char *data;
    char *output = NULL;
    const char *reason = NULL;
    uint64_t c = 0, d = 0, steps = 0, step_limit = 0, output_limit = 0;
    uint32_t a = 0;
    Py_ssize_t input_length, position = 0, output_length = 0, capacity = 0;
    int eof_stop = 0, jit = 0, steps_enabled, output_enabled;
    if (require_idle(self) < 0 || require_initialized(self) < 0) {
        return NULL;
    }
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O|OOpp:run", keywords,
                                     &input, &steps_arg, &output_arg, &eof_stop,
                                     &jit)) {
        return NULL;
    }
    if (!PyBytes_Check(input)) {
        PyErr_SetString(PyExc_TypeError, "input_bytes must be immutable bytes");
        return NULL;
    }
    if (parse_limit(steps_arg, "max_steps", &step_limit, &steps_enabled) < 0 ||
        parse_limit(output_arg, "max_output", &output_limit, &output_enabled) < 0) {
        return NULL;
    }
    data = (const unsigned char *)PyBytes_AS_STRING(input);
    input_length = PyBytes_GET_SIZE(input);
    memset(&self->jit_stats, 0, sizeof(self->jit_stats));
    self->jit_stats.enabled = jit;
    self->busy = 1;
    if (jit && jit_prepare(&self->jit_stats) < 0) {
        goto error;
    }
    for (;;) {
        uint32_t raw, value;
        unsigned opcode;
        if ((steps & (SIGNAL_INTERVAL - 1)) == 0 && PyErr_CheckSignals() < 0) {
            goto error;
        }
        if (steps_enabled && steps >= step_limit) {
            reason = "step_limit";
            break;
        }
        if (memory_read(self, c, &raw) < 0) {
            goto error;
        }
        if (raw < 33 || raw > 126) {
            reason = "invalid_instruction";
            break;
        }
        opcode = (unsigned)(((uint64_t)raw + c) % 94);
        if (opcode == 5 && output_enabled &&
            (uint64_t)output_length >= output_limit) {
            reason = "output_limit";
            break;
        }
        if (opcode == 23 && position >= input_length && eof_stop) {
            reason = "input_exhausted";
            break;
        }
        if (steps == UINT64_MAX) {
            PyErr_SetString(PyExc_OverflowError, "Native step counter overflow");
            goto error;
        }
        if (jit && opcode == 68) {
            int completed = memory_jit_nops(self, c, d, steps,
                                            steps_enabled, step_limit);
            if (completed < 0) {
                goto error;
            }
            if (completed != 0) {
                steps += (unsigned)completed;
                c += (unsigned)completed;
                if (c == MEMORY_SIZE) c = 0;
                if (d < MEMORY_SIZE) {
                    d += (unsigned)completed;
                    if (d >= MEMORY_SIZE) d -= MEMORY_SIZE;
                } else {
                    d += (unsigned)completed;
                }
                continue;
            }
        }
        ++steps;
        ++self->jit_stats.fallback_steps;
        switch (opcode) {
        case 4:
            if (memory_read(self, d, &value) < 0) {
                goto error;
            }
            c = value;
            break;
        case 5:
            if (append_output(&output, &output_length, &capacity,
                              (unsigned char)(a & 255)) < 0) {
                goto error;
            }
            break;
        case 23:
            a = position < input_length ? data[position++] : 59049;
            break;
        case 39:
            if (memory_read(self, d, &value) < 0) {
                goto error;
            }
            a = (uint32_t)(ROTATE_MULTIPLIER * (value % 3) + value / 3);
            if (memory_write(self, d, a) < 0) {
                goto error;
            }
            break;
        case 40:
            if (memory_read(self, d, &value) < 0) {
                goto error;
            }
            d = value;
            break;
        case 62:
            if (memory_read(self, d, &value) < 0) {
                goto error;
            }
            a = crazy20(a, value);
            if (memory_write(self, d, a) < 0) {
                goto error;
            }
            break;
        case 81:
            reason = "terminated";
            goto finished;
        default:
            /* Valid printable cells can decode to arbitrary no-op opcodes. */
            break;
        }
        /* Reload at the current C: a jump changed C, or ROT/CRZ may have
         * rewritten this very instruction when D == C. Do not encrypt the
         * previously fetched byte and do not encrypt nonprintable data. */
        if (memory_read(self, c, &value) < 0) {
            goto error;
        }
        if (value >= 33 && value <= 126 &&
            memory_write(self, c, encrypt_table[value - 33]) < 0) {
            goto error;
        }
        c = c == MEMORY_SIZE - 1 ? 0 : c + 1;
        if (d == UINT64_MAX) {
            PyErr_SetString(PyExc_OverflowError, "Native D register overflow");
            goto error;
        }
        d = d == MEMORY_SIZE - 1 ? 0 : d + 1;
    }
finished:
    output_bytes = PyBytes_FromStringAndSize(output, output_length);
    if (output_bytes == NULL) {
        goto error;
    }
    result = Py_BuildValue("(NsKnKKK)", output_bytes, reason,
                          (unsigned long long)steps, position,
                          (unsigned long long)a, (unsigned long long)c,
                          (unsigned long long)d);
    PyMem_Free(output);
    self->busy = 0;
    return result;
error:
    PyMem_Free(output);
    self->busy = 0;
    return NULL;
}

static PyMethodDef memory_methods[] = {
    {"copy", (PyCFunction)memory_copy, METH_NOARGS,
     "Return an independent snapshot with copy-on-write mutable pages."},
    {"get_allocated_count", (PyCFunction)memory_allocated_count, METH_NOARGS,
     "Return source length plus unique writes outside the source."},
    {"export_pages", (PyCFunction)memory_export_pages, METH_NOARGS,
     "Return {page_index: (native uint32 bytes, written bytes)}."},
    {"jit_stats", (PyCFunction)memory_jit_stats, METH_NOARGS,
     "Return last-run JIT counters and bounded process-cache sizes."},
    {"run", (PyCFunction)(void (*)(void))memory_run,
     METH_VARARGS | METH_KEYWORDS,
     "Run with zeroed registers and return output, reason, steps, input, A, C, D."},
    {NULL, NULL, 0, NULL}
};

static PyMappingMethods memory_mapping = {
    (lenfunc)memory_length,
    (binaryfunc)memory_subscript,
    (objobjargproc)memory_ass_subscript
};

static PyTypeObject memory_type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "malbolge._native_vm._Memory",
    .tp_basicsize = sizeof(NativeMemory),
    .tp_dealloc = (destructor)memory_dealloc,
    .tp_as_mapping = &memory_mapping,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "Native paged Malbolge20 memory with immutable source and COW copies.",
    .tp_methods = memory_methods,
    .tp_init = (initproc)memory_init,
    .tp_new = PyType_GenericNew
};

static PyObject *
native_jit_available(PyObject *module, PyObject *unused)
{
    (void)module;
    (void)unused;
    return PyBool_FromLong(jit_probe());
}

static PyMethodDef native_methods[] = {
    {"jit_available", (PyCFunction)native_jit_available, METH_NOARGS,
     "Report target JIT support without allocating executable memory."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef native_module = {
    PyModuleDef_HEAD_INIT,
    "_native_vm",
    "Optional execution core for the Python Malbolge20 interpreter.",
    -1,
    native_methods, NULL, NULL, NULL, NULL
};

PyMODINIT_FUNC
PyInit__native_vm(void)
{
    PyObject *module;
    initialize_crazy_table();
    if (sizeof(encrypt_table) - 1 != 94) {
        PyErr_SetString(PyExc_RuntimeError, "Invalid native encryption table");
        return NULL;
    }
    if (PyType_Ready(&memory_type) < 0) {
        return NULL;
    }
    module = PyModule_Create(&native_module);
    if (module == NULL) {
        return NULL;
    }
    Py_INCREF(&memory_type);
    if (PyModule_AddObject(module, "_Memory", (PyObject *)&memory_type) < 0) {
        Py_DECREF(&memory_type);
        Py_DECREF(module);
        return NULL;
    }
    return module;
}
