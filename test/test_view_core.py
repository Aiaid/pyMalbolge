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
        # `effect` is a semantic key, not display text: the wording differs
        # per renderer (the web build's is not English), so the key set is
        # the contract. Every row must land inside it.
        self.assertIn(current["effect"], disasm.EFFECT_KEYS)
        for row in view["rows"]:
            self.assertIn(row["effect"], disasm.EFFECT_KEYS)
        # For an executable opcode the key IS the mnemonic.
        if current["mnemonic"] in {"jmp", "mov", "out", "in",
                                   "rotr", "crz", "nop", "end"}:
            self.assertEqual(current["effect"], current["mnemonic"])

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
            self.assertFalse(row["legal"])
            # "illegal" and "unknown_opcode" are different sentences: the
            # machine STOPS at an illegal cell, but skips an unknown opcode
            # and carries on. A renderer must be able to tell them apart from
            # this field alone.
            self.assertEqual(row["effect"], "illegal")
            self.assertNotIn("unknown_opcode",
                             [r["effect"] for r in illegal_rows])


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

    def test_condition_text_is_carried_through_verbatim(self):
        # The web canvas shows the condition itself ("a==72"), which a
        # Callable cannot supply -- so the caller passes the text and this
        # layer must not touch it.
        dbg = _make_dbg(MalbolgeConfig.original())
        dbg.add_breakpoint(5, condition=lambda s: s.a == 72,
                           condition_text="a == 72")
        bp = breakpoints.build(dbg)["breakpoints"][0]
        self.assertEqual(bp["condition_text"], "a == 72")
        self.assertTrue(bp["has_condition"])

    def test_condition_without_text_and_text_without_condition(self):
        # The two fields answer different questions, so all four combinations
        # are reachable and none of them is an error.
        dbg = _make_dbg(MalbolgeConfig.original())
        dbg.add_breakpoint(5, condition=lambda s: True)   # predicate, no text
        dbg.add_breakpoint(7)                             # neither
        by_addr = {b["addr"]: b
                   for b in breakpoints.build(dbg)["breakpoints"]}

        self.assertTrue(by_addr[5]["has_condition"])
        self.assertIsNone(by_addr[5]["condition_text"])
        self.assertFalse(by_addr[7]["has_condition"])
        self.assertIsNone(by_addr[7]["condition_text"])

    def test_condition_text_survives_json(self):
        dbg = _make_dbg(MalbolgeConfig.original())
        dbg.add_breakpoint(5, condition=lambda s: s.a == 72,
                           condition_text="a == 72")
        # Rule 2: the predicate must not leak into the payload, the text must.
        payload = json.dumps(breakpoints.build(dbg))
        self.assertIn("a == 72", payload)
        self.assertNotIn("lambda", payload)


class TestRegisterCharClassification(unittest.TestCase):
    """a_char_kind / a_char_symbol -- §3.1.

    A is a full ternary word (it routinely reaches five figures), so the
    classification is of ``a % 256``: the byte ``out a`` would emit.
    """

    def _view_with_a(self, value):
        dbg = _make_dbg(MalbolgeConfig.original())
        dbg._a = value
        return registers.build(dbg)

    def test_printable(self):
        view = self._view_with_a(ord("K"))
        self.assertEqual(view["a_char_kind"], "printable")
        self.assertEqual(view["a_char_symbol"], "K")

    def test_control_character_gets_a_visible_symbol(self):
        # The canvas shows A=7 as "␇ 控制符", not as ".".
        view = self._view_with_a(7)
        self.assertEqual(view["a_char_kind"], "control")
        self.assertEqual(view["a_char_symbol"], "␇")
        # a_char keeps its old meaning, which the TUI depends on.
        self.assertEqual(view["a_char"], ".")

    def test_delete_is_a_control_character(self):
        view = self._view_with_a(127)
        self.assertEqual(view["a_char_kind"], "control")
        self.assertEqual(view["a_char_symbol"], "␡")

    def test_high_byte_is_other_with_no_invented_symbol(self):
        # 0x80..0xFF is not a character until an encoding is chosen.
        view = self._view_with_a(200)
        self.assertEqual(view["a_char_kind"], "other")
        self.assertIsNone(view["a_char_symbol"])

    def test_classification_is_of_the_low_byte_not_the_word(self):
        # 29,527 % 256 == 87 -> 'W'. Classifying the word itself would fall
        # through to "other" and lose the character entirely.
        view = self._view_with_a(29527)
        self.assertEqual(view["a"], 29527)
        self.assertEqual(view["a_char_kind"], "printable")
        self.assertEqual(view["a_char_symbol"], "W")

    def test_space_differs_between_a_char_and_the_symbol(self):
        # Deliberate: a_char uses the memory-cell bound (33..126, a space is
        # not a legal instruction character) while the classification uses the
        # output-byte bound (32..126, a space is an ordinary output byte).
        view = self._view_with_a(32)
        self.assertEqual(view["a_char"], ".")
        self.assertEqual(view["a_char_kind"], "printable")
        self.assertEqual(view["a_char_symbol"], " ")

    def test_survives_json(self):
        for value in (7, 32, 75, 127, 200, 29527):
            with self.subTest(a=value):
                json.dumps(self._view_with_a(value))


if __name__ == "__main__":
    unittest.main()
