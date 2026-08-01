"""Regression tests for the .mb size-optimization investigation (finding I).

Two size optimizations were tried against mc2mb's layout. One was falsified
(§I2); the other's falsification was retracted (§I3) when its counterexample
turned out to fail on the baseline too, which is how §I7 was found. This file
keeps all of it runnable, because results that cannot be re-run are just
anecdotes:

  * the transforms themselves live in `test/diagnostics/optpatch.py`
  * the instruments that found the root causes are the other modules there
  * the counterexample programs are in `test/fixtures/opt/`

The fast tests below pin down what the transforms *do* -- the size reductions
they achieve, and the fact that `print("foo")` survives both, which is exactly
what made them look correct. The slow tests build 31-65 MB programs and run for
millions of steps in pure Python, so they are gated behind
MALBOLGE_SLOW_TESTS=1.

See findings §I2 (falsified), §I3 (retracted) and §I7 (the shipped-compiler
defect that retraction exposed).
"""

import os
import unittest

from malbolge.compiler.mg2mc import translate_mg_to_mc
from malbolge.compiler.py2mg import compile_python_to_mg

from test.diagnostics import optpatch
from test.diagnostics.flag_trace import first_divergence, record
from test.diagnostics.layout_tool import cell_owners, layout_map

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures', 'opt')

SLOW = os.environ.get('MALBOLGE_SLOW_TESTS') == '1'


def fixture(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return f.read()


def build(py_name):
    """Compile a fixture .py down to .mc."""
    return translate_mg_to_mc(compile_python_to_mg(fixture(py_name)))


class LayoutMap(unittest.TestCase):
    """layout_tool must keep tracking mc2mb's layout as mc2mb evolves.

    It works by re-executing a source-rewritten copy of mc2mb, so it breaks
    silently if the anchors move. These assertions are the alarm.
    """

    def setUp(self):
        self.mc = fixture('foo.mc')
        self.lm = layout_map(self.mc)

    def test_every_declared_flag_is_placed(self):
        declared = {line.split(',')[1].strip()
                    for line in self.mc.splitlines()
                    if line.startswith('FLAG ')}
        self.assertTrue(declared <= set(self.lm['flags']))

    def test_regions_are_ordered_and_disjoint(self):
        m = self.lm['meta']
        self.assertLess(m['UT_dir_firstOffset'], m['RT_firstOffset'])
        self.assertLess(m['RT_firstOffset'], m['UT_indir_firstOffset'])

    def test_nonzero_flags_land_in_the_indirect_region(self):
        # This is the cost model's premise: a nonzero initial value has no
        # legal instruction character, so the page is pushed indirect.
        self.assertEqual(self.lm['flags']['FLAG10'][0], 'indir')
        self.assertEqual(self.lm['flags']['FLAG_REV_OPR_ROT'][0], 'dir')

    def test_one_decision_cell_per_unit(self):
        owners = cell_owners(self.lm)
        placed = [a for _area, a in self.lm['flags'].values() if a is not None]
        self.assertEqual(len(owners), len(placed))


class FlagTrace(unittest.TestCase):
    """The event recorder must see the program's flag reads, in order."""

    def test_baseline_foo_traces_and_runs(self):
        mc = fixture('foo.mc')
        events, info = record(optpatch.assemble(mc), mc)
        self.assertEqual(info['output'], 'foo\n')
        self.assertEqual(info['reason'], 'end')
        self.assertTrue(events)

        # Return dispatch is a linear scan, which is the shape of the
        # asymptotic defect in §I5: a numbered flag reading MOV_D (40) is the
        # match and jumps out via FLAG_JMP; any other reading means "not my
        # call site" and falls through to the next flag in the chain. The cost
        # of a return is therefore the number of call sites, O(n), even though
        # CALL/RETURN themselves use DJMP for O(1) jumps.
        numbered = [(i, e) for i, e in enumerate(events)
                    if e[0].startswith('FLAG') and e[0][4:].isdigit()]
        self.assertTrue(numbered)
        for i, (label, value, _step) in numbered:
            if i + 1 >= len(events):
                continue
            following = events[i + 1][0]
            if value == 40:
                # FLAG_JMP for a return to a call site, END for the last one.
                self.assertIn(following, ('FLAG_JMP', 'END'), label)
            else:
                self.assertTrue(
                    following.startswith('FLAG') and following[4:].isdigit(),
                    '%s read OFF but did not fall through to another flag '
                    '(got %s)' % (label, following))

    def test_identical_builds_do_not_diverge(self):
        mc = fixture('foo.mc')
        mb = optpatch.assemble(mc)
        a, _ = record(mb, mc)
        b, _ = record(mb, mc)
        self.assertIsNone(first_divergence(a, b))


class TransformSizes(unittest.TestCase):
    """Both transforms shrink foo substantially -- and foo still works.

    This is the trap the investigation fell into, pinned as a test: the size
    win is real and the obvious program passes. Correctness is decided by the
    counterexamples below, not by these numbers.
    """

    def setUp(self):
        self.mc = fixture('foo.mc')
        self.baseline = optpatch.assemble(self.mc)

    def test_baseline_size(self):
        # ~1.06 MB for 25 flags: the §I1 cost model's headline case.
        self.assertAlmostEqual(len(self.baseline), 1_061_167, delta=20_000)

    def test_option_one_shrinks_foo_to_about_a_quarter(self):
        mc1 = optpatch.option_one(self.mc)
        mb1 = optpatch.assemble(mc1)
        self.assertLess(len(mb1), 0.3 * len(self.baseline))
        _events, info = record(mb1, mc1)
        self.assertEqual(info['output'], 'foo\n')

    def test_option_two_shrinks_foo_to_about_a_quarter(self):
        mb2 = optpatch.assemble(self.mc, option_two=True)
        self.assertLess(len(mb2), 0.3 * len(self.baseline))
        _events, info = record(mb2, self.mc)
        self.assertEqual(info['output'], 'foo\n')

    def test_option_one_leaves_zero_flags_alone(self):
        mc1 = optpatch.option_one(self.mc)
        self.assertIn('FLAG 0/2, FLAG_REV_OPR_ROT', mc1)
        self.assertNotIn('FLAG 1/2', mc1)

    def test_option_one_can_target_a_single_flag(self):
        mc1 = optpatch.option_one(self.mc, flags={'FLAG10'})
        self.assertIn('FLAG 0/2, FLAG10', mc1)
        self.assertIn('FLAG 1/2, FLAG11', mc1)
        self.assertEqual(mc1.count('  NEXT FLAG10'),
                         self.mc.count('  NEXT FLAG10') + 1)


@unittest.skipUnless(SLOW, 'set MALBOLGE_SLOW_TESTS=1 (builds 31 MB programs '
                           'and runs millions of steps)')
class Counterexamples(unittest.TestCase):
    """§I2, §I3 and §I7, re-run from source.

    If any of these changes outcome the corresponding finding is wrong and
    needs revisiting -- that would be a result, not a broken test.
    """

    def test_i2_option_one_breaks_single_level_recursion(self):
        mc = build('f1_recursion.py')
        mc1 = optpatch.option_one(mc, flags={'FLAG10'})

        base, base_info = record(optpatch.assemble(mc), mc)
        var, var_info = record(optpatch.assemble(mc1), mc1)

        self.assertEqual(base_info['output'], 'A')
        self.assertNotEqual(var_info['output'], 'A')

        # The streams agree for thousands of events, then one flag reads the
        # other way round. That is the whole point: this is not a build error.
        i = first_divergence(base, var)
        self.assertIsNotNone(i)
        self.assertGreater(i, 1000)
        self.assertEqual(base[i][0], var[i][0])   # same flag
        self.assertNotEqual(base[i][1], var[i][1])  # opposite reading

    def test_i3_counterexample_does_not_distinguish_the_two_builds(self):
        """§I3 retracted: fib(2)+while passes under *both* builds.

        This was recorded as option two's falsification. It is not one — it
        never had a control.
        """
        mc = build('fib2_loop.py')

        _base, base_info = record(optpatch.assemble(mc), mc)
        _var, var_info = record(optpatch.assemble(mc, option_two=True), mc)

        self.assertEqual(base_info['output'], '1')
        self.assertEqual(var_info['output'], '1')

    def test_i7_is_not_monotone_in_program_size(self):
        """§I7: the pair that rules out every source-level explanation.

        d(1) fails with no loop; d(2) passes while doing strictly more work
        through the same machinery. They differ by one constant -- 9,306 bytes
        -- and the same delta breaks fib(2)-in-a-loop in the other direction.
        """
        _e1, i1 = record(optpatch.assemble(build('d1_fails.py')),
                         build('d1_fails.py'))
        _e2, i2 = record(optpatch.assemble(build('d2_passes.py')),
                         build('d2_passes.py'))

        self.assertEqual(i1['output'], '')
        self.assertEqual(i1['reason'], 'illegal')
        self.assertEqual(i2['output'], '@')
        self.assertEqual(i2['reason'], 'end')

    def test_i7_shipped_chain_miscompiles_fib3_in_loop(self):
        """§I7: a known defect in the shipped compiler, pinned as a test.

        Do not read the fixture name as the characterization. "Recursion in a
        loop" was the first description of this defect and it is wrong —
        `d(1)` fails with no loop at all, and `d(2)` passes while doing
        strictly more work. What tracks the failures is layout position, not
        any source-level shape. This test pins one known-failing program.

        When it starts failing the bug is fixed — update §I7 and turn the
        assertion around rather than deleting it.
        """
        mc = build('fib3_in_loop.py')

        _base, base_info = record(optpatch.assemble(mc), mc)
        self.assertEqual(base_info['output'], '',
                         'I7 appears to be fixed: the shipped chain now '
                         'produces output for recursion inside a loop')
        self.assertEqual(base_info['reason'], 'illegal')

        # And the same source under option two's layout is correct, which is
        # what invalidated §I3.
        _var, var_info = record(optpatch.assemble(mc, option_two=True), mc)
        self.assertEqual(var_info['output'], '2')


if __name__ == '__main__':
    unittest.main()
