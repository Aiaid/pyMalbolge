"""Semantic checks for grouped-trit runtime arithmetic, without timing gates."""
from pathlib import Path
import random
import unittest
from unittest.mock import patch

from malbolge import core


def reference_crazy(a, b, width):
    """Independent per-trit definition, including Python floor-division rules."""
    result = 0
    place = 1
    for _ in range(width):
        result += core.TABLE_CRAZY[(b // place) % 3][(a // place) % 3] * place
        place *= 3
    return result


class TestGroupedCrazy(unittest.TestCase):
    def test_every_four_trit_operand_pair(self):
        for a in range(81):
            for b in range(81):
                self.assertEqual(core.crazy(a, b, 4), reference_crazy(a, b, 4),
                                 (a, b))

    def test_arbitrary_widths_signed_and_oversized_operands(self):
        randomizer = random.Random(73021)
        for width in (-9, -1, 0, 1, 2, 3, 5, 6, 7, 10, 20, 21, 33, 65):
            values = [-3**80, -59049, -1, 0, 1, 59048, 3**80]
            pairs = [(a, b) for a in values for b in values]
            pairs += [(randomizer.randrange(-3**80, 3**80),
                       randomizer.randrange(-3**80, 3**80)) for _ in range(100)]
            for a, b in pairs:
                self.assertEqual(core.crazy(a, b, width),
                                 reference_crazy(a, b, width), (a, b, width))

    def test_width_preserves_range_index_protocol(self):
        class Width:
            def __index__(self):
                return 10

        self.assertEqual(core.crazy(-7, 123456, Width()),
                         reference_crazy(-7, 123456, 10))
        with self.assertRaises(TypeError):
            core.crazy(0, 0, 10.0)

    def test_compiled_execution_matches_per_trit_reference(self):
        config = core.MalbolgeConfig.malbolge20()
        directory = Path(__file__).parent / 'fixtures' / 'nagoya'
        grouped = core.crazy
        for name, data in [('mg_b_hi', b''), ('mg_c_echo', b'XYZ')]:
            source = (directory / (name + '.mb')).read_bytes()
            cells = core.parse_source(source, config)
            for limits in ({'max_steps': 100}, {'max_steps': 200000},
                           {'max_steps': 200000, 'max_output': 0}):
                outcomes = []
                for operation in (reference_crazy, grouped):
                    with patch.object(core, 'crazy', operation):
                        memory = core.create_memory(config)
                        memory.initialize_source(cells)
                        result = core.run_memory(memory, config, data, **limits)
                    # Include every mutable page and debugger write marker,
                    # not only the program's externally visible output.
                    pages = {page: (list(block.values), bytes(block.written))
                             for page, block in memory._blocks.items()}
                    outcomes.append((result, pages, memory.get_allocated_count()))
                self.assertEqual(outcomes[0], outcomes[1], (name, limits))


if __name__ == '__main__':
    unittest.main()
