"""
Guards for examples/manifest.json -- the precomputed metadata the web build's
launch screen reads (program size, cell count, step count, whether it wants
input).

The numbers come from actually running each program, which is far too slow for
a unit test (quine.mal is 69.5 million steps), so this checks the manifest's
shape and internal consistency, and re-derives only the cheap entries.

Generator: test/diagnostics/examples_manifest.py
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from malbolge import MalbolgeConfig, MalbolgeDebugger

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "examples", "manifest.json")

#: Cheap enough to re-run in a unit test. quine (69.5M steps) and 99bottles
#: (13.8M) are deliberately not here.
CHEAP = {"hello.mal", "cat2.mal", "cat.mal"}

REQUIRED = {
    "name", "file", "bytes", "cells", "steps", "truncated",
    "stop_reason", "reads_input", "output", "output_len", "output_truncated",
}


class TestExamplesManifest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(MANIFEST, encoding="utf-8") as fh:
            cls.manifest = json.load(fh)

    def test_every_entry_has_the_full_schema(self):
        for entry in self.manifest["programs"]:
            with self.subTest(program=entry.get("file")):
                self.assertEqual(set(entry) & REQUIRED, REQUIRED)

    def test_every_listed_program_exists_and_matches_its_size(self):
        for entry in self.manifest["programs"]:
            with self.subTest(program=entry["file"]):
                path = os.path.join(ROOT, "examples", entry["file"])
                self.assertTrue(os.path.isfile(path))
                self.assertEqual(os.path.getsize(path), entry["bytes"])

    def test_every_example_is_listed(self):
        # A program added to examples/ without regenerating the manifest would
        # silently be missing from the launch screen.
        on_disk = {f for f in os.listdir(os.path.join(ROOT, "examples"))
                   if f.endswith(".mal")}
        listed = {e["file"] for e in self.manifest["programs"]}
        self.assertEqual(on_disk, listed)

    def test_step_count_is_null_exactly_when_truncated(self):
        # "we did not finish" must never be recorded as a number.
        for entry in self.manifest["programs"]:
            with self.subTest(program=entry["file"]):
                self.assertEqual(entry["steps"] is None, entry["truncated"])

    def test_cells_never_exceed_the_address_space(self):
        size = MalbolgeConfig.original().memory_size
        for entry in self.manifest["programs"]:
            with self.subTest(program=entry["file"]):
                self.assertLessEqual(entry["cells"], size)
                self.assertLessEqual(entry["cells"], entry["bytes"])

    def test_cheap_entries_reproduce(self):
        for entry in self.manifest["programs"]:
            if entry["file"] not in CHEAP:
                continue
            with self.subTest(program=entry["file"]):
                path = os.path.join(ROOT, "examples", entry["file"])
                with open(path, encoding="utf-8") as fh:
                    dbg = MalbolgeDebugger(fh.read())
                while not dbg.is_terminated and dbg.step_count < 100000:
                    before = dbg.step_count
                    dbg.step()
                    if dbg.step_count == before:
                        break       # input exhausted: step() is a no-op
                self.assertEqual(dbg.step_count, entry["steps"])
                self.assertEqual(dbg.output[:len(entry["output"])],
                                 entry["output"])


if __name__ == "__main__":
    unittest.main()
