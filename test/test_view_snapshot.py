"""
Tests for the ViewModel layer's snapshot half (malbolge/view/): memory,
timeline, and the build_snapshot() that ties all six together.

Contract: docs/design/tui-web-architecture.md §3.3 / §3.5 / §3.7.
Every ViewModel gets at least one json.dumps() assertion -- that is Rule 2
of malbolge/view/__init__.py, and the cheapest possible guard for it.

Companion to test_view_core.py (§3.1 / §3.2 / §3.4 / §3.6).
"""

import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from malbolge import MalbolgeConfig, MalbolgeDebugger
from malbolge.view import disasm, memory, snapshot, timeline


HELLO_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples", "hello.mal"
)


def _load_hello() -> str:
    with open(HELLO_PATH) as f:
        return f.read()


def _make_dbg(config: MalbolgeConfig) -> MalbolgeDebugger:
    return MalbolgeDebugger(_load_hello(), config=config)


CONFIGS = [
    ("original", MalbolgeConfig.original),
    ("malbolge20", MalbolgeConfig.malbolge20),
]


def _heat_delta(dbg: MalbolgeDebugger):
    """Step once and return the set of addresses whose write heat grew.

    Derived from the public write_heat mapping rather than from the debugger's
    private history, so it is an independent statement of "what did this step
    write" to check `just_written` against.
    """
    before = dict(dbg.write_heat)
    dbg.step()
    after = dict(dbg.write_heat)
    return {addr for addr, count in after.items() if count > before.get(addr, 0)}


class TestMemoryView(unittest.TestCase):
    def test_json_serialisable(self):
        for name, cfg_factory in CONFIGS:
            with self.subTest(variant=name):
                dbg = _make_dbg(cfg_factory())
                for _ in range(5):
                    dbg.step()
                view = memory.build(dbg, count=24)
                json.dumps(view)  # Rule 2 guard

    def test_window_is_centred_on_d_not_anchored_at_it(self):
        # REGRESSION: the first implementation read §3.3's under-specified
        # original literally and used `start = d + offset`, so the window
        # showed only addresses ahead of the data pointer -- never executed,
        # never written, every heat 0. §3.3 now spells the rule out:
        # start = d + offset - count // 2, clamped.
        for name, cfg_factory in CONFIGS:
            with self.subTest(variant=name):
                dbg = _make_dbg(cfg_factory())
                for _ in range(30):
                    dbg.step()
                d = dbg.get_state().d
                view = memory.build(dbg, count=24)

                self.assertEqual(view["start"], d - 24 // 2)
                self.assertEqual(view["d"], d)
                self.assertEqual(view["c"], dbg.get_state().c)
                self.assertEqual(view["offset"], 0)
                self.assertEqual(view["count"], 24)
                self.assertEqual(len(view["cells"]), 24)
                self.assertEqual([c["addr"] for c in view["cells"]],
                                 list(range(view["start"], view["start"] + 24)))

                # D itself is still on screen -- centred, not scrolled away.
                self.assertEqual([c["addr"] for c in view["cells"] if c["is_d"]], [d])

                # The point of centring: the window actually contains
                # recently-written cells for the heat map to show.
                self.assertGreater(view["heat_max"], 0)
                self.assertTrue(any(c["heat"] > 0 for c in view["cells"]))

                # ... and this is what the anchored-at-D window would have
                # shown instead. Kept as an assertion rather than a comment so
                # the regression cannot come back looking harmless.
                self.assertEqual(dbg.get_write_heat(d, 24), [0] * 24)

    def test_offset_scrolls_the_centre(self):
        dbg = _make_dbg(MalbolgeConfig.original())
        for _ in range(30):
            dbg.step()
        d = dbg.get_state().d

        view = memory.build(dbg, offset=7, count=24)
        self.assertEqual(view["start"], d + 7 - 12)
        self.assertEqual(view["offset"], 7)

        view = memory.build(dbg, offset=-7, count=24)
        self.assertEqual(view["start"], d - 7 - 12)
        self.assertEqual(view["offset"], -7)

    def test_clamped_at_low_end_of_address_space(self):
        # D is 0 before the first step, so an uncentred start would be -12.
        for name, cfg_factory in CONFIGS:
            with self.subTest(variant=name):
                dbg = _make_dbg(cfg_factory())
                self.assertEqual(dbg.get_state().d, 0)
                view = memory.build(dbg, count=24)

                self.assertEqual(view["start"], 0)
                self.assertEqual(view["cells"][0]["addr"], 0)
                self.assertTrue(all(c["addr"] >= 0 for c in view["cells"]))
                self.assertEqual(len(view["cells"]), 24)

    def test_clamped_at_high_end_of_address_space(self):
        dbg = _make_dbg(MalbolgeConfig.original())
        for _ in range(5):
            dbg.step()
        memory_size = dbg.config.memory_size

        view = memory.build(dbg, offset=memory_size, count=24)
        self.assertEqual(view["start"], memory_size - 24)
        self.assertEqual(view["cells"][-1]["addr"], memory_size - 1)
        self.assertTrue(all(c["addr"] < memory_size for c in view["cells"]))

    def test_heat_max_is_per_window_not_global(self):
        # hello.mal's hottest cell is written twice; everything else at most
        # once. Scroll the window past that cell and heat_max must drop to 1
        # even though the global maximum is still 2 -- §3.3: the heat map
        # normalises against what is on screen.
        dbg = _make_dbg(MalbolgeConfig.original())
        dbg.run()
        d = dbg.get_state().d

        global_max = max(dbg.write_heat.values())
        hottest = max(dbg.write_heat, key=lambda addr: dbg.write_heat[addr])

        centred = memory.build(dbg, count=24)
        self.assertEqual(centred["heat_max"], global_max)
        self.assertIn(hottest, [c["addr"] for c in centred["cells"]])

        scrolled = memory.build(dbg, offset=6, count=24)
        window = [c["addr"] for c in scrolled["cells"]]
        self.assertNotIn(hottest, window)
        self.assertLess(scrolled["heat_max"], global_max)
        self.assertEqual(scrolled["heat_max"],
                         max(c["heat"] for c in scrolled["cells"]))
        # The window is not simply empty of history -- there is heat in it,
        # just less than the hottest cell outside it.
        self.assertGreater(scrolled["heat_max"], 0)

    def test_just_written_is_only_the_last_step(self):
        for name, cfg_factory in CONFIGS:
            with self.subTest(variant=name):
                dbg = _make_dbg(cfg_factory())

                # Before any step there is no "last step", so nothing is
                # just_written even though every cell holds source bytes.
                view = memory.build(dbg, count=24)
                self.assertEqual([c["addr"] for c in view["cells"] if c["just_written"]], [])

                deltas = [_heat_delta(dbg) for _ in range(6)]

                # A window wide enough to hold every address touched so far,
                # anchored at 0 so it does not move as D walks forward.
                def written_in_window():
                    v = memory.build(dbg, offset=-dbg.get_state().d, count=96)
                    self.assertEqual(v["start"], 0)
                    return {c["addr"] for c in v["cells"] if c["just_written"]}

                self.assertEqual(written_in_window(), deltas[-1])

                # Cells written by *earlier* steps carry heat but are not
                # just_written -- that distinction is the whole field.
                view = memory.build(dbg, offset=-dbg.get_state().d, count=96)
                stale = {c["addr"] for c in view["cells"]
                         if c["heat"] > 0 and not c["just_written"]}
                self.assertTrue(stale)
                self.assertTrue(stale.isdisjoint(deltas[-1]))
                self.assertTrue(stale.issuperset(deltas[0]))

                # Stepping back re-points it at the step before.
                dbg.step_back()
                self.assertEqual(written_in_window(), deltas[-2])

    def test_malbolge20_heat_over_a_huge_address_space(self):
        # SparseMemory: 3.48 billion cells, of which a few dozen have ever
        # been written. get_write_heat must answer 0 for the rest instead of
        # raising or materialising the space, and read_memory_value must
        # serve lazily-initialised cells (whose values exceed one byte, so
        # `char` is "." throughout).
        dbg = _make_dbg(MalbolgeConfig.malbolge20())
        for _ in range(20):
            dbg.step()
        memory_size = dbg.config.memory_size
        self.assertGreater(memory_size, 3_000_000_000)

        far = memory.build(dbg, offset=1_000_000_000, count=24)
        self.assertEqual(far["start"], dbg.get_state().d + 1_000_000_000 - 12)
        self.assertEqual(len(far["cells"]), 24)
        self.assertEqual(far["heat_max"], 0)
        self.assertTrue(all(c["heat"] == 0 for c in far["cells"]))
        self.assertTrue(all(not c["just_written"] for c in far["cells"]))
        self.assertTrue(all(not c["is_d"] and not c["is_c"] for c in far["cells"]))
        json.dumps(far)  # Rule 2 guard: big ints stay ints

        # Written cells still live near the origin, and heat there is intact.
        near = memory.build(dbg, count=24)
        self.assertGreater(near["heat_max"], 0)


class TestTimelineView(unittest.TestCase):
    def test_json_serialisable(self):
        for name, cfg_factory in CONFIGS:
            with self.subTest(variant=name):
                dbg = _make_dbg(cfg_factory())
                dbg.add_breakpoint(7)
                dbg.add_watchpoint(3)
                for _ in range(5):
                    dbg.step()
                view = timeline.build(dbg)
                json.dumps(view)  # Rule 2 guard

    def test_fields_track_the_debugger(self):
        dbg = _make_dbg(MalbolgeConfig.original())
        for _ in range(9):
            dbg.step()
        view = timeline.build(dbg)

        self.assertEqual(view["current"], 9)
        self.assertEqual(view["current"], dbg.step_count)
        self.assertEqual(view["max_reached"], dbg.max_step_reached)
        self.assertEqual(view["seekable"], list(dbg.seekable_range))
        self.assertEqual(view["marks"], [])

    def test_max_reached_outlives_step_back(self):
        dbg = _make_dbg(MalbolgeConfig.original())
        for _ in range(9):
            dbg.step()
        for _ in range(4):
            dbg.step_back()
        view = timeline.build(dbg)

        self.assertEqual(view["current"], 5)
        self.assertEqual(view["max_reached"], 9)
        self.assertEqual(view["seekable"][1], 9)

    def test_seekable_lower_bound_is_not_zero(self):
        # §3.5/§4.3: `seekable`'s low bound is bounded by the history window,
        # not fixed at 0 -- _save_history drops the oldest entry past
        # _max_history and those steps can no longer be reconstructed.
        #
        # Reaching the real bound needs >10000 steps, and hello.mal terminates
        # after 39; a program that runs that long would add ~10k steps of
        # debugger work to a suite that is already ~3.5 minutes, for a
        # property that has nothing to do with the step count itself. So the
        # window is shrunk on the instance instead: same code path, same
        # observable, three orders of magnitude cheaper.
        dbg = _make_dbg(MalbolgeConfig.original())
        dbg._max_history = 5
        for _ in range(20):
            dbg.step()
        view = timeline.build(dbg)

        low, high = view["seekable"]
        self.assertEqual([low, high], list(dbg.seekable_range))
        self.assertGreater(low, 0)          # the point of this test
        self.assertEqual(high, 20)
        self.assertEqual(view["current"], 20)
        self.assertEqual(view["max_reached"], 20)
        # The window is real: below `low`, seek() genuinely cannot go.
        with self.assertRaises(ValueError):
            dbg.seek(low - 1)
        dbg.seek(low)
        self.assertEqual(dbg.step_count, low)

    def test_marks_carry_addresses_and_kinds(self):
        dbg = _make_dbg(MalbolgeConfig.original())
        dbg.add_breakpoint(9)
        dbg.add_breakpoint(2)
        dbg.add_watchpoint(5)
        view = timeline.build(dbg)

        self.assertEqual(view["marks"], [
            {"addr": 2, "kind": "breakpoint"},
            {"addr": 5, "kind": "watchpoint"},
            {"addr": 9, "kind": "breakpoint"},
        ])


class TestBuildSnapshot(unittest.TestCase):
    def test_json_serialisable(self):
        for name, cfg_factory in CONFIGS:
            with self.subTest(variant=name):
                dbg = _make_dbg(cfg_factory())
                dbg.add_breakpoint(6)
                dbg.add_watchpoint(4)
                for _ in range(7):
                    dbg.step()
                snap = snapshot.build_snapshot(dbg)
                json.dumps(snap)  # Rule 2 guard, whole-snapshot

    def test_has_exactly_the_six_parts(self):
        dbg = _make_dbg(MalbolgeConfig.original())
        snap = snapshot.build_snapshot(dbg)
        self.assertEqual(sorted(snap), ["breakpoints", "disasm", "memory",
                                        "registers", "teaching", "timeline"])

    def test_sizing_arguments_are_passed_through(self):
        dbg = _make_dbg(MalbolgeConfig.original())
        for _ in range(20):
            dbg.step()
        snap = snapshot.build_snapshot(dbg, mem_offset=5, mem_count=16,
                                       disasm_count=7)

        self.assertEqual(snap["memory"]["offset"], 5)
        self.assertEqual(snap["memory"]["count"], 16)
        self.assertEqual(snap["memory"]["start"], dbg.get_state().d + 5 - 8)
        self.assertEqual(len(snap["disasm"]["rows"]), 7)

    def test_all_six_parts_describe_one_moment(self):
        # This is the entire reason the snapshot layer exists (§3.7): six
        # panels each asking the debugger for themselves can straddle a step
        # and render disassembly at one moment against memory at another.
        for name, cfg_factory in CONFIGS:
            with self.subTest(variant=name):
                dbg = _make_dbg(cfg_factory())
                dbg.add_breakpoint(3)
                for _ in range(12):
                    dbg.step()
                snap = snapshot.build_snapshot(dbg)

                reg = snap["registers"]
                self.assertEqual(reg["step"], 12)
                # d and c have diverged by now, so agreeing on both is a real
                # constraint rather than 0 == 0.
                self.assertNotEqual(reg["c"], reg["d"])

                self.assertEqual(snap["disasm"]["center"], reg["c"])
                self.assertEqual(snap["memory"]["c"], reg["c"])
                self.assertEqual(snap["memory"]["d"], reg["d"])
                self.assertEqual(snap["timeline"]["current"], reg["step"])
                self.assertEqual(snap["timeline"]["max_reached"], reg["step"])

                current = next(r for r in snap["disasm"]["rows"] if r["is_current"])
                self.assertEqual(current["addr"], reg["c"])
                self.assertEqual(snap["teaching"]["opcode"], current["opcode"])
                self.assertEqual(snap["teaching"]["opcode_calc"]["c"], reg["c"])
                self.assertEqual(snap["teaching"]["opcode_calc"]["mem_c"], current["raw"])
                self.assertEqual(snap["teaching"]["terminated"], reg["terminated"])

                marks = {(m["addr"], m["kind"]) for m in snap["timeline"]["marks"]}
                self.assertEqual(
                    marks,
                    {(bp["addr"], "breakpoint") for bp in snap["breakpoints"]["breakpoints"]}
                    | {(wp["addr"], "watchpoint") for wp in snap["breakpoints"]["watchpoints"]},
                )
                self.assertTrue(
                    any(r["has_breakpoint"] for r in snap["disasm"]["rows"]
                        if r["addr"] == 3)
                    or all(r["addr"] != 3 for r in snap["disasm"]["rows"])
                )

    def test_building_a_snapshot_does_not_move_the_debugger(self):
        dbg = _make_dbg(MalbolgeConfig.original())
        for _ in range(10):
            dbg.step()
        before = (dbg.step_count, dbg.get_state().a, dbg.get_state().c,
                  dbg.get_state().d, dbg.output, dbg.history_size,
                  dict(dbg.write_heat))

        snapshot.build_snapshot(dbg)
        snapshot.build_snapshot(dbg, mem_offset=40, mem_count=64)

        after = (dbg.step_count, dbg.get_state().a, dbg.get_state().c,
                 dbg.get_state().d, dbg.output, dbg.history_size,
                 dict(dbg.write_heat))
        self.assertEqual(before, after)

    def test_snapshot_is_a_value_not_a_live_view(self):
        # A part that handed back a live debugger structure (write_heat's
        # MappingProxy, say) would silently mutate under an already-rendered
        # frame. Take a snapshot, run the program to the end, and the snapshot
        # must still describe the step it was taken at.
        dbg = _make_dbg(MalbolgeConfig.original())
        for _ in range(10):
            dbg.step()
        snap = snapshot.build_snapshot(dbg)
        expected = copy.deepcopy(snap)

        dbg.run()
        self.assertTrue(dbg.is_terminated)
        self.assertGreater(dbg.step_count, 10)

        self.assertEqual(snap, expected)
        self.assertEqual(snap["registers"]["step"], 10)
        self.assertFalse(snap["registers"]["terminated"])

    def test_hand_assembled_frame_can_tear_where_the_snapshot_cannot(self):
        # The failure mode §3.7 is written against, made concrete: two panels
        # fetching for themselves across a step disagree; build_snapshot on
        # the very same debugger does not.
        dbg = _make_dbg(MalbolgeConfig.original())
        for _ in range(12):
            dbg.step()

        torn_disasm = disasm.build(dbg, count=11)
        dbg.step()
        torn_memory = memory.build(dbg, count=24)
        self.assertNotEqual(torn_disasm["center"], torn_memory["c"])

        snap = snapshot.build_snapshot(dbg, mem_count=24, disasm_count=11)
        self.assertEqual(snap["disasm"]["center"], snap["memory"]["c"])


if __name__ == "__main__":
    unittest.main()
