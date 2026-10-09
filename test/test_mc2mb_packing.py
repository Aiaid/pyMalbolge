"""First-fit unit packing keeps page order, occupied keys and data layout."""
import hashlib
import random
import unittest

from malbolge.compiler.mc2mb import _UnitPacker, parse_mc_to_data


def reference_pack(units):
    """Simple first-fit specification using only dictionary key membership."""
    pages, placements = [], []
    for unit in units:
        for index, page in enumerate(pages):
            if any(address in page for address in unit):
                continue
            page.update(unit)
            placements.append(index)
            break
        else:
            placements.append(len(pages))
            pages.append(dict(unit))
    return pages, placements


class UnitPacking(unittest.TestCase):
    def assert_packing(self, units):
        expected_pages, expected_placements = reference_pack(units)
        packer = _UnitPacker()
        actual = [packer.add(unit) for unit in units]
        self.assertEqual(actual, expected_placements)
        self.assertEqual(packer.units, expected_pages)
        return packer, actual

    def test_reuses_the_earliest_compatible_page(self):
        _packer, placements = self.assert_packing([
            {0: 'DUP'}, {1: 'ROT'}, {0: 'JMP'}, {2: 'OPR'}, {1: 'OUTPUT'},
        ])
        self.assertEqual(placements, [0, 0, 1, 0, 1])

    def test_sentinel_values_still_occupy_their_keys(self):
        _packer, placements = self.assert_packing([
            {0: -1}, {0: 'DUP'}, {1: 0}, {1: -1},
        ])
        self.assertEqual(placements, [0, 1, 0, 1])

    def test_sparse_out_of_range_keys_fall_back_without_large_shifts(self):
        self.assert_packing([
            {0: 'DUP'}, {94: 'ROT'}, {0: 'JMP'}, {-1: -1},
            {94: 0}, {10**30: 'OUTPUT'}, {-1: 9}, {93: 'OPR'},
            {10**30: -1}, {94: -1, 95: 'DUP'},
        ])

    def test_empty_units_and_input_dictionaries_keep_their_behavior(self):
        unit = {0: 'DUP'}
        packer, placements = self.assert_packing([{}, {}, unit, {}, {0: 'ROT'}])
        self.assertEqual(placements, [0, 0, 0, 0, 1])
        unit[0] = 'INPUT'
        self.assertEqual(packer.units, [{0: 'DUP'}, {0: 'ROT'}])

    def test_mixed_units_match_the_first_fit_specification(self):
        rng = random.Random(3107)
        addresses = list(range(94)) + [-1, 94, 188, 10**30]
        values = [-1, 0, 'DUP', 'OPR', 'ROT', 'JMP']
        units = [dict((address, rng.choice(values))
                      for address in rng.sample(addresses, rng.randrange(8)))
                 for _ in range(400)]
        self.assert_packing(units)

    def test_raw_unit_preserves_the_data_image(self):
        source = ('PROGRAM_START_TO ENTRY@MAIN\n'
                  'FLAG 0/2, ZERO\nFLAG 1/2, ONE\n'
                  'UNIT {\nCUSTOM:\n5: DUP\n2: OPR\n}\n'
                  'ROUTINE MAIN{\nENTRY:\nCUSTOM\nEND\n}\n')
        image = parse_mc_to_data(source).encode()
        self.assertEqual(hashlib.sha256(image).hexdigest(),
                         '8a4acbe9d739f1b4726ce184d0fecb788eddcd2f564fd1969dc0e9618e74126e')
