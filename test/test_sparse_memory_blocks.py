"""
Tests for the block-based SparseMemory default-fill scheme and Malbolge20
conformance against the Nagoya reference interpreter.
"""

import os
import subprocess
import sys
import unittest

from malbolge.core import (
    MalbolgeConfig,
    MalbolgeVariant,
    SparseMemory,
    crazy,
    _block_seed_jump_map,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures', 'nagoya')


class TestBlockSeedJumpMap(unittest.TestCase):
    """The per-trit block-seed jump map must match the num0/num1 tables
    hardcoded in the Nagoya reference interpreter (malbolge20.c,
    make_init_mem), which encode the same block-to-block seed transition."""

    NAGOYA_NUM0 = [[0, 1, 2], [0, 1, 1], [0, 2, 2]]
    NAGOYA_NUM1 = [[1, 0, 0], [1, 0, 2], [2, 1, 2]]

    def test_matches_nagoya_tables(self):
        jump = _block_seed_jump_map(59049)
        for t0 in range(3):
            for t1 in range(3):
                self.assertEqual(
                    jump[(t0, t1)],
                    (self.NAGOYA_NUM0[t0][t1], self.NAGOYA_NUM1[t0][t1]),
                    f"jump map disagrees with Nagoya tables at ({t0},{t1})",
                )


class TestSparseMemoryAgainstBruteForce(unittest.TestCase):
    """On a tiny 4-trit config (81 cells, 9-cell blocks) the block-based
    default fill must agree cell-for-cell with a brute-force sequential
    crazy fill, including out-of-order far accesses."""

    CONFIG = MalbolgeConfig(
        variant=MalbolgeVariant.MALBOLGE20,
        trit_width=4,
        memory_size=81,
        rotate_multiplier=27,
        use_sparse_memory=True,
    )

    SOURCES = [
        [],
        [5],
        [7, 11],
        [3, 1, 4, 1, 5, 9, 2, 6, 53, 5, 8],   # ends mid-block
        list(range(20, 38)),                   # ends at a block boundary
        list(range(1, 9)),                     # fill starts in last block cell
    ]

    def brute_force(self, src):
        mem = [0] * 81
        for i, v in enumerate(src):
            mem[i] = v
        for i in range(max(len(src), 2), 81):
            mem[i] = crazy(mem[i - 1], mem[i - 2], 4)
        return mem

    def test_defaults_match_brute_force(self):
        for src in self.SOURCES:
            with self.subTest(source_len=len(src)):
                expected = self.brute_force(src)
                sm = SparseMemory(self.CONFIG)
                sm.initialize_source(list(src))
                # Far/out-of-order accesses first to exercise seed chaining
                for addr in [80, 40, 3, 78, 10] + list(range(81)):
                    self.assertEqual(sm[addr], expected[addr],
                                     f"mismatch at addr {addr}")

    def test_writes_override_defaults(self):
        sm = SparseMemory(self.CONFIG)
        sm.initialize_source([7, 11])
        default_50 = sm[50]
        default_60 = sm[60]
        sm[50] = (default_50 + 1) % 81
        self.assertEqual(sm[50], (default_50 + 1) % 81)
        # Copy shares defaults but not the write overlay
        cp = sm.copy()
        sm[60] = (default_60 + 1) % 81
        self.assertEqual(cp[60], default_60)
        self.assertEqual(cp[50], (default_50 + 1) % 81)


class TestNagoyaHello20(unittest.TestCase):
    """hello20.mb (Nagoya LAL toolchain output, MIT) must run to completion
    and print HelloWorld, matching the reference C interpreter."""

    def test_hello20(self):
        result = subprocess.run(
            [sys.executable, '-m', 'malbolge', '--variant=malbolge20',
             os.path.join(FIXTURES_DIR, 'hello20.mb')],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'HelloWorld')


if __name__ == "__main__":
    unittest.main()
