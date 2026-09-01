"""
Tests for the ViewModel layer (malbolge/view/): registers, disasm, teaching,
breakpoints.

Contract: docs/design/tui-web-architecture.md §3.1 / §3.2 / §3.4 / §3.6.
Every ViewModel gets at least one json.dumps() assertion -- that is Rule 2
of malbolge/view/__init__.py, and the cheapest possible guard for it.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from malbolge import MalbolgeConfig, MalbolgeDebugger
from malbolge.view import registers, disasm, teaching, breakpoints


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


class TestRegisterView(unittest.TestCase):
    def test_json_serialisable(self):
        for name, cfg_factory in CONFIGS:
            with self.subTest(variant=name):
                dbg = _make_dbg(cfg_factory())
                for _ in range(5):
                    dbg.step()
                view = registers.build(dbg)
                json.dumps(view)  # Rule 2 guard

    def test_fields_after_a_few_steps(self):
        dbg = _make_dbg(MalbolgeConfig.original())
        for _ in range(3):
            dbg.step()
        view = registers.build(dbg)

        self.assertEqual(view["step"], 3)
        self.assertEqual(view["a"], dbg.registers["a"])
        self.assertEqual(view["c"], dbg.registers["c"])
        self.assertEqual(view["d"], dbg.registers["d"])
        self.assertIn(view["a_char"], list(chr(i) for i in range(33, 127)) + ["."])
        self.assertFalse(view["terminated"])
        self.assertEqual(view["stop_reason"], "running")
        self.assertEqual(view["history_size"], dbg.history_size)
        self.assertEqual(view["output_len"], len(dbg.output))
        self.assertEqual(view["input_consumed"], 0)
        self.assertEqual(view["input_total"], 0)
        # next_* come from preview_next_instruction()'s register_changes;
        # at minimum c/d are always predicted (unless terminated).
        self.assertIsNotNone(view["next_c"])
        self.assertIsNotNone(view["next_d"])

    def test_terminated_state(self):
        dbg = _make_dbg(MalbolgeConfig.original())
        dbg.run()
        view = registers.build(dbg)

        self.assertTrue(view["terminated"])
        self.assertEqual(view["stop_reason"], "terminated")
        self.assertEqual(view["output_len"], len("Hello World!"))

    def test_input_total_reflects_set_input(self):
        dbg = _make_dbg(MalbolgeConfig.original())
        dbg.set_input("abc123")
        view = registers.build(dbg)
        self.assertEqual(view["input_total"], 6)
        self.assertEqual(view["input_consumed"], 0)


class TestDisasmView(unittest.TestCase):
    def test_json_serialisable(self):
        for name, cfg_factory in CONFIGS:
            with self.subTest(variant=name):
                dbg = _make_dbg(cfg_factory())
                for _ in range(4):
                    dbg.step()
                view = disasm.build(dbg, count=11)
                json.dumps(view)  # Rule 2 guard

    def test_window_and_rows_shape(self):
        dbg = _make_dbg(MalbolgeConfig.original())
        view = disasm.build(dbg, count=11)

        self.assertEqual(view["center"], dbg.get_state().c)
        self.assertEqual(len(view["window"]), 2)
        self.assertLessEqual(view["window"][0], view["window"][1])
        self.assertEqual(len(view["rows"]), 11)

        current_rows = [r for r in view["rows"] if r["is_current"]]
        self.assertEqual(len(current_rows), 1)
        self.assertEqual(current_rows[0]["addr"], dbg.get_state().c)

    def test_legal_row_has_effect_and_mnemonic(self):
        dbg = _make_dbg(MalbolgeConfig.original())
        view = disasm.build(dbg, count=11)
        current = next(r for r in view["rows"] if r["is_current"])

        self.assertTrue(current["legal"])
        self.assertIsNotNone(current["opcode"])
        self.assertNotEqual(current["effect"], "")
        # jmp/mov's effect is exactly OPCODE_HELP pseudocode with '<-'.
        if current["mnemonic"] == "jmp":
            self.assertEqual(current["effect"], "c ← mem[d]")
        if current["mnemonic"] == "mov":
            self.assertEqual(current["effect"], "d ← mem[d]")

    def test_illegal_row_is_not_legal_and_has_no_opcode(self):
        dbg = _make_dbg(MalbolgeConfig.original())
        # Walk forward until an illegal (out-of-source, zeroed) cell enters
        # the disassembly window, or give up after a bound on steps.
        view = None
        for _ in range(200):
            view = disasm.build(dbg, count=21)
            if any(not r["legal"] for r in view["rows"]):
                break
            if dbg.is_terminated:
                break
            dbg.step()
        illegal_rows = [r for r in view["rows"] if not r["legal"]]
        if illegal_rows:
            row = illegal_rows[0]
            self.assertIsNone(row["opcode"])
            self.assertEqual(row["effect"], "")
            self.assertFalse(row["legal"])


class TestTeachingView(unittest.TestCase):
    def test_json_serialisable(self):
        for name, cfg_factory in CONFIGS:
            with self.subTest(variant=name):
                dbg = _make_dbg(cfg_factory())
                for _ in range(6):
                    dbg.step()
                view = teaching.build(dbg)
                json.dumps(view)  # Rule 2 guard

    def test_effects_ordered_and_kinds_valid(self):
        dbg = _make_dbg(MalbolgeConfig.original())
        view = teaching.build(dbg)

        self.assertFalse(view["terminated"])
        self.assertGreater(len(view["effects"]), 0)
        orders = [e["order"] for e in view["effects"]]
        self.assertEqual(orders, list(range(1, len(orders) + 1)))
        for effect in view["effects"]:
            self.assertIn(effect["kind"], {"register", "memory", "encrypt", "io", "note"})

    def test_opcode_calc_and_help_populated(self):
        dbg = _make_dbg(MalbolgeConfig.original())
        view = teaching.build(dbg)

        self.assertGreaterEqual(view["opcode"], 0)
        self.assertNotEqual(view["opcode_name"], "N/A")
        self.assertNotEqual(view["syntax"], "")
        self.assertNotEqual(view["description"], "")
        self.assertEqual(view["opcode_calc"]["opcode"], view["opcode"])

    def test_terminated_program_has_empty_teaching_fields(self):
        dbg = _make_dbg(MalbolgeConfig.original())
        dbg.run()
        view = teaching.build(dbg)

        self.assertTrue(view["terminated"])
        self.assertEqual(view["effects"], [])
        self.assertIsNone(view["encrypt"])
        self.assertIsNone(view["ternary"])

    def test_rotr_produces_rotate_ternary_with_highlights(self):
        dbg = _make_dbg(MalbolgeConfig.original())
        view = None
        for _ in range(2000):
            preview = dbg.preview_next_instruction()
            if preview.get("opcode_name") == "rotr":
                view = teaching.build(dbg)
                break
            if dbg.is_terminated:
                break
            dbg.step()

        if view is not None:
            self.assertIsNotNone(view["ternary"])
            self.assertEqual(view["ternary"]["kind"], "rotate")
            self.assertEqual(len(view["ternary"]["a"]), dbg.config.trit_width)
            self.assertEqual(len(view["ternary"]["result"]), dbg.config.trit_width)
            self.assertIsNone(view["ternary"]["b"])
            self.assertEqual(view["ternary"]["highlight_before"], 0)
            self.assertEqual(view["ternary"]["highlight_after"], dbg.config.trit_width - 1)

    def test_crz_produces_crazy_ternary(self):
        dbg = _make_dbg(MalbolgeConfig.original())
        view = None
        for _ in range(2000):
            preview = dbg.preview_next_instruction()
            if preview.get("opcode_name") == "crz":
                view = teaching.build(dbg)
                break
            if dbg.is_terminated:
                break
            dbg.step()

        if view is not None:
            self.assertIsNotNone(view["ternary"])
            self.assertEqual(view["ternary"]["kind"], "crazy")
            self.assertIsNotNone(view["ternary"]["b"])
            # Known upstream quirk: MalbolgeDebugger.explain_crazy_operation()
            # hardcodes `range(10)` instead of `self._config.trit_width`, so
            # its ternary lists are always length 10 -- even under
            # malbolge20's 20-trit config. This test pins today's actual
            # behaviour rather than papering over it; see the report to the
            # coordinating agent.
            self.assertEqual(len(view["ternary"]["a"]), 10)


class TestBreakpointView(unittest.TestCase):
    def test_json_serialisable(self):
        for name, cfg_factory in CONFIGS:
            with self.subTest(variant=name):
                dbg = _make_dbg(cfg_factory())
                dbg.add_breakpoint(5)
                dbg.add_watchpoint(3)
                view = breakpoints.build(dbg)
                json.dumps(view)  # Rule 2 guard

    def test_breakpoint_fields(self):
        dbg = _make_dbg(MalbolgeConfig.original())
        dbg.add_breakpoint(5, temporary=True)
        dbg.add_breakpoint(2, condition=lambda state: True)
        view = breakpoints.build(dbg)

        self.assertEqual([bp["addr"] for bp in view["breakpoints"]], [2, 5])
        by_addr = {bp["addr"]: bp for bp in view["breakpoints"]}
        self.assertTrue(by_addr[5]["temporary"])
        self.assertFalse(by_addr[5]["has_condition"])
        self.assertTrue(by_addr[2]["has_condition"])
        self.assertEqual(by_addr[5]["hit_count"], 0)
        self.assertTrue(by_addr[5]["enabled"])
        # 'condition' itself (a Callable) must never appear anywhere.
        self.assertNotIn("condition", by_addr[2])

    def test_watchpoint_fields(self):
        dbg = _make_dbg(MalbolgeConfig.original())
        dbg.add_watchpoint(3)
        view = breakpoints.build(dbg)

        self.assertEqual(len(view["watchpoints"]), 1)
        wp = view["watchpoints"][0]
        self.assertEqual(wp["addr"], 3)
        self.assertTrue(wp["enabled"])
        self.assertIn("last_value", wp)

    def test_empty_when_no_breakpoints(self):
        dbg = _make_dbg(MalbolgeConfig.original())
        view = breakpoints.build(dbg)
        self.assertEqual(view["breakpoints"], [])
        self.assertEqual(view["watchpoints"], [])


if __name__ == "__main__":
    unittest.main()
