"""Byte-exact streaming and compact assembler source-storage regressions."""
import hashlib
from pathlib import Path
import random
import unittest

from malbolge.compiler.mc2mb import (
    _Assembler, _PagedCode, _LEGAL, _rev_xlat1_c,
    assemble_mc_to_mb, iter_mc_to_mb,
)


class PagedSourceMapping(unittest.TestCase):
    def test_matches_dict_under_sparse_updates_and_zero_values(self):
        code = _PagedCode()
        reference = {}
        rng = random.Random(1974)
        positions = [-1, 0, 1, 4095, 4096, 4097, 10**9]
        positions += [rng.randrange(20000) for _ in range(100)]
        for step in range(1000):
            address = rng.choice(positions)
            if rng.randrange(4) == 0 and address in reference:
                del reference[address]
                del code[address]
            else:
                value = rng.choice([0, 0, 33, 81, 82, 126, 255])
                reference[address] = value
                code[address] = value
            if step % 37 == 0:
                self.assertEqual(len(code), len(reference))
                self.assertEqual(dict(code), reference)
                self.assertEqual(dict(code.items()), reference)
                self.assertEqual(code.get(10**9 + 1, 17), 17)
        self.assertEqual(list(code), sorted(reference))
        self.assertEqual(code.copy(), reference)

    def test_zero_is_present_and_last_page_cache_survives_deletion(self):
        code = _PagedCode()
        code[4096] = 0
        self.assertIn(4096, code)
        self.assertEqual(code[4096], 0)
        self.assertEqual(len(code), 1)
        code[4096] = 81
        self.assertEqual(dict(code), {4096: 81})
        code[4096] = 0
        self.assertEqual(dict(code), {4096: 0})
        del code[4096]
        self.assertNotIn(4096, code)
        code[4097] = 82
        self.assertEqual(dict(code), {4097: 82})
        code.clear()
        self.assertEqual(dict(code), {})
        code[4097] = 0
        self.assertEqual(dict(code), {4097: 0})

    def test_distant_addresses_do_not_allocate_the_intervening_source(self):
        code = _PagedCode()
        code[0] = 33
        code[3**20 - 1] = 126
        self.assertEqual(len(code._pages), 2)
        self.assertLess(sum(len(page.data) for page in code._pages.values()), 10000)
        self.assertEqual(dict(code), {0: 33, 3**20 - 1: 126})
        self.assertRaises(TypeError, code.__setitem__, 1.5, 33)
        self.assertRaises(ValueError, code.__setitem__, 2, 256)
        self.assertEqual(len(code), 2)


class StreamedAssembler(unittest.TestCase):
    @staticmethod
    def synthetic(mapping):
        asm = _Assembler()
        asm.code = mapping
        asm.code_size = 9001
        for position, value in [(0, 33), (1, 0), (93, 126), (375, 81),
                                (376, 0), (4095, 82), (4096, 33),
                                (4097, 126), (8999, 81)]:
            asm.code[position] = value
        return asm

    def test_page_runs_match_scalar_padding_across_chunk_boundaries(self):
        for chunk_size in (1, 7, 94, 376, 997, 4096, 65536):
            with self.subTest(chunk_size=chunk_size):
                asm = self.synthetic(_PagedCode())
                actual = b''.join(asm.iter_finish(chunk_size))
                expected = bytes(
                    asm.code.get(position, 0) or
                    _rev_xlat1_c(ord(_LEGAL[position % 8]), position)
                    for position in range(asm.code_size))
                self.assertEqual(actual, expected)
                # Compatibility with diagnostic callers replacing the mapping.
                scalar = self.synthetic({})
                self.assertEqual(actual, b''.join(scalar.iter_finish(chunk_size)))

    def test_finish_is_idempotent_and_does_not_materialize_padding(self):
        asm = self.synthetic(_PagedCode())
        first = asm.finish()
        after = dict(asm.code)
        size = asm.code_size
        self.assertEqual(first, asm.finish())
        self.assertEqual(first.encode(), b''.join(asm.iter_finish(997)))
        self.assertEqual(dict(asm.code), after)
        self.assertEqual(asm.code_size, size)
        self.assertLess(len(asm.code), 20)
        for invalid in (0, -1, True, 1.5):
            self.assertRaises(ValueError, lambda: list(asm.iter_finish(invalid)))

    def test_frozen_small_corpus_hash_and_public_api(self):
        source = (Path(__file__).parent / 'fixtures' / 'nagoya' /
                  'mg_a_minimal.mc').read_text()
        chunks = list(iter_mc_to_mb(source, 997))
        self.assertTrue(all(isinstance(chunk, bytes) and 0 < len(chunk) <= 997
                            for chunk in chunks))
        image = b''.join(chunks)
        self.assertEqual(image.decode(), assemble_mc_to_mb(source))
        self.assertEqual(hashlib.sha256(image).hexdigest(),
                         '9cd064c41ec8b699a3287f980197a78da7268464e1fec85ab4a0dceffa7aa4a0')
