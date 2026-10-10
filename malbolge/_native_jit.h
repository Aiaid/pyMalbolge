/* Guarded ARM64 NOP/self-encryption kernels for _native_vm.c.
 *
 * This header emits actual native instructions from fixed trusted templates;
 * guest memory supplies only guarded uint32 data, never executable bytes.
 * Kernels touch one already-writable COW page and return an executed prefix.
 * The caller owns budgets, register updates, write accounting, and fallbacks.
 *
 * Cache lifetime is the process lifetime, bounded by one 1 MiB arena and 564
 * immutable entries. The extension retains the GIL: no kernel can execute
 * while this module changes executable-page permissions or appends code.
 */
#ifndef MALBOLGE_NATIVE_JIT_H
#define MALBOLGE_NATIVE_JIT_H

#include <errno.h>
#include <stdio.h>
#include <time.h>

#if (defined(__aarch64__) || defined(__arm64__)) && \
    !defined(__arm64e__) && !defined(__AARCH64EB__) && \
    (defined(__APPLE__) || defined(__linux__))
#define NATIVE_JIT_SUPPORTED 1
#include <sys/mman.h>
#if defined(__APPLE__)
#include <pthread.h>
#include <libkern/OSCacheControl.h>
#endif
#else
#define NATIVE_JIT_SUPPORTED 0
#endif

#define JIT_SHAPES 6
#define JIT_MAX_CELLS 64
#define JIT_ARENA_BYTES (1024U * 1024U)

typedef uint32_t (*JitKernel)(uint32_t *cells);

typedef struct {
    JitKernel kernel;
    unsigned length;
    size_t code_bytes;
} JitBlock;

typedef struct {
    int enabled;
    uint64_t compiled_blocks;
    uint64_t compiled_bytes;
    uint64_t jit_blocks;
    uint64_t jit_steps;
    uint64_t guard_failures;
    uint64_t fallback_steps;
    double compile_cpu_seconds;
    double compile_wall_seconds;
} JitRunStats;

static JitBlock jit_cache[94][JIT_SHAPES];
static int jit_capability = -1;
static char jit_unavailable_reason[256] = "unsupported architecture or operating system";
static unsigned char *jit_arena;
static size_t jit_arena_used;
static size_t jit_cache_entries;
static size_t jit_cache_code_bytes;

#if NATIVE_JIT_SUPPORTED
static int jit_cleanup_registered;

static void
jit_cleanup(void)
{
    /* Py_AtExit runs after interpreter teardown, when no kernels are active.
     * The cache deliberately outlives individual modules/memory snapshots. */
    if (jit_arena != NULL) {
        munmap(jit_arena, JIT_ARENA_BYTES);
    }
    jit_arena = NULL;
    jit_arena_used = jit_cache_entries = jit_cache_code_bytes = 0;
    memset(jit_cache, 0, sizeof(jit_cache));
    jit_capability = -1;
    jit_cleanup_registered = 0;
}
#endif

static int
jit_probe(void)
{
    if (jit_capability >= 0) {
        return jit_capability;
    }
    jit_capability = 0;
#if NATIVE_JIT_SUPPORTED
#if defined(__APPLE__)
    if (!pthread_jit_write_protect_supported_np()) {
        snprintf(jit_unavailable_reason, sizeof(jit_unavailable_reason),
                 "thread-local JIT write protection is unavailable");
        return 0;
    }
#endif
    jit_capability = 1;
#endif
    return jit_capability;
}

static int
jit_require_available(void)
{
    if (!jit_probe()) {
        PyErr_Format(PyExc_RuntimeError, "ARM64 JIT unavailable: %s",
                     jit_unavailable_reason);
        return -1;
    }
    return 0;
}

static double
jit_wall_time(void)
{
#if NATIVE_JIT_SUPPORTED
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) == 0) {
        return (double)now.tv_sec + (double)now.tv_nsec * 1e-9;
    }
#endif
    return 0.0;
}

static double
jit_cpu_time(void)
{
    clock_t now = clock();
    return now == (clock_t)-1 ? 0.0 : (double)now / CLOCKS_PER_SEC;
}

static int
jit_prepare(JitRunStats *stats)
{
    double cpu_start, wall_start;
    if (jit_require_available() < 0) {
        return -1;
    }
    if (jit_arena != NULL) {
        return 0;
    }
    cpu_start = jit_cpu_time();
    wall_start = jit_wall_time();
#if NATIVE_JIT_SUPPORTED
#if defined(__APPLE__)
    jit_arena = mmap(NULL, JIT_ARENA_BYTES,
                     PROT_READ | PROT_WRITE | PROT_EXEC,
                     MAP_PRIVATE | MAP_ANON | MAP_JIT, -1, 0);
#else
    jit_arena = mmap(NULL, JIT_ARENA_BYTES, PROT_READ | PROT_WRITE,
                     MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
#endif
    if (jit_arena == MAP_FAILED) {
        jit_arena = NULL;
        jit_capability = 0;
        snprintf(jit_unavailable_reason, sizeof(jit_unavailable_reason),
                 "executable arena allocation failed: %s", strerror(errno));
    } else {
#if defined(__APPLE__)
        pthread_jit_write_protect_np(1);
#else
        if (mprotect(jit_arena, JIT_ARENA_BYTES, PROT_READ | PROT_EXEC) < 0) {
            int saved_errno = errno;
            munmap(jit_arena, JIT_ARENA_BYTES);
            jit_arena = NULL;
            jit_capability = 0;
            snprintf(jit_unavailable_reason, sizeof(jit_unavailable_reason),
                     "executable arena protection failed: %s",
                     strerror(saved_errno));
        }
#endif
        if (jit_arena != NULL && !jit_cleanup_registered) {
            if (Py_AtExit(jit_cleanup) == 0) {
                jit_cleanup_registered = 1;
            } else {
                munmap(jit_arena, JIT_ARENA_BYTES);
                jit_arena = NULL;
                jit_capability = 0;
                snprintf(jit_unavailable_reason, sizeof(jit_unavailable_reason),
                         "could not register executable arena cleanup");
            }
        }
    }
#endif
    stats->compile_cpu_seconds += jit_cpu_time() - cpu_start;
    stats->compile_wall_seconds += jit_wall_time() - wall_start;
    return jit_require_available();
}

static inline uint32_t
jit_nop_raw(unsigned residue)
{
    unsigned raw = (68 + 94 - residue % 94) % 94;
    return raw < 33 ? raw + 94 : raw;
}

static int
jit_publish(const uint32_t *words, size_t size, JitBlock *block)
{
#if NATIVE_JIT_SUPPORTED
    unsigned char *destination = jit_arena + jit_arena_used;
#if defined(__APPLE__)
    /* No Python calls or fallible operations occur while writes are enabled.
     * Restore execute mode before exposing the kernel in the cache. */
    pthread_jit_write_protect_np(0);
    memcpy(destination, words, size);
    sys_icache_invalidate(destination, size);
    pthread_jit_write_protect_np(1);
#else
    if (mprotect(jit_arena, JIT_ARENA_BYTES, PROT_READ | PROT_WRITE) < 0) {
        PyErr_SetFromErrno(PyExc_OSError);
        return -1;
    }
    memcpy(destination, words, size);
    __builtin___clear_cache((char *)destination, (char *)destination + size);
    if (mprotect(jit_arena, JIT_ARENA_BYTES, PROT_READ | PROT_EXEC) < 0) {
        int saved_errno = errno;
        /* Previously cached code is no longer executable. Disable dispatch
         * globally so a later run cannot call stale executable pointers. */
        jit_capability = 0;
        snprintf(jit_unavailable_reason, sizeof(jit_unavailable_reason),
                 "restoring executable arena protection failed: %s",
                 strerror(saved_errno));
        errno = saved_errno;
        PyErr_SetFromErrno(PyExc_OSError);
        return -1;
    }
#endif
    block->kernel = (JitKernel)(void *)destination;
    jit_arena_used += size;
    block->code_bytes = size;
    ++jit_cache_entries;
    jit_cache_code_bytes += size;
    return 0;
#else
    (void)words;
    (void)size;
    (void)block;
    return jit_require_available();
#endif
}

static JitBlock *
jit_compile(unsigned residue, unsigned shape, const unsigned char *encryption,
            JitRunStats *stats)
{
    JitBlock *block = &jit_cache[residue][shape];
    uint32_t words[JIT_MAX_CELLS * 7 + 2];
    unsigned length = 2U << shape, i;
    size_t word_count = (size_t)length * 7 + 2;
    size_t size = word_count * sizeof(uint32_t);
    double cpu_start, wall_start;
    if (block->kernel != NULL) {
        return block;
    }
    if (size > JIT_ARENA_BYTES - jit_arena_used) {
        PyErr_SetString(PyExc_RuntimeError, "ARM64 JIT code cache is full");
        return NULL;
    }
    cpu_start = jit_cpu_time();
    wall_start = jit_wall_time();
    for (i = 0; i < length; ++i) {
        uint32_t raw = jit_nop_raw(residue + i);
        uint32_t encrypted = encryption[raw - 33];
        unsigned branch_delta = 5 * length - 3 * i;
        /* LDR W8,[X0,#4*i]; CMP W8,#raw; B.NE exit_i;
         * MOVZ W8,#encrypted; STR W8,[X0,#4*i]. Each guard precedes its
         * store, so self-modification or changed future instructions return
         * the exact completed prefix without executing the changed cell. */
        words[5 * i] = UINT32_C(0xb9400008) | (i << 10);
        words[5 * i + 1] = UINT32_C(0x7100011f) | (raw << 10);
        words[5 * i + 2] = UINT32_C(0x54000001) | (branch_delta << 5);
        words[5 * i + 3] = UINT32_C(0x52800008) | (encrypted << 5);
        words[5 * i + 4] = UINT32_C(0xb9000008) | (i << 10);
        words[5 * length + 2 + 2 * i] = UINT32_C(0x52800000) | (i << 5);
        words[5 * length + 3 + 2 * i] = UINT32_C(0xd65f03c0);
    }
    words[5 * length] = UINT32_C(0x52800000) | (length << 5);
    words[5 * length + 1] = UINT32_C(0xd65f03c0);
    if (jit_publish(words, size, block) < 0) {
        return NULL;
    }
    block->length = length;
    ++stats->compiled_blocks;
    stats->compiled_bytes += size;
    stats->compile_cpu_seconds += jit_cpu_time() - cpu_start;
    stats->compile_wall_seconds += jit_wall_time() - wall_start;
    return block;
}

#endif
