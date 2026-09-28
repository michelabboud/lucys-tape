#!/usr/bin/env python3
"""Tests for tools/import_notes.py — the prehistory importer.

Covers the three protection rules:
  1. tiny files (jottings — where stray plaintext secrets live) are skipped
  2. captures contained in a larger capture (re-saves) are dropped
  3. everything imported passes the redactor

Run: python3 -m unittest discover tests -v
"""
import importlib.util
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"


def load_import_notes(argv):
    old = sys.argv
    sys.argv = ["import_notes.py"] + argv
    try:
        spec = importlib.util.spec_from_file_location("import_notes", TOOLS / "import_notes.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.argv = old


class ImportNotesTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._td = tempfile.TemporaryDirectory()
        self.notes = Path(self._td.name) / "notes"
        self.archive = Path(self._td.name) / "archive"
        self.notes.mkdir()
        self.mod = load_import_notes([str(self.notes), str(self.archive)])

    def tearDown(self):
        self._td.cleanup()

    def test_tiny_files_are_skipped_as_jottings(self):
        (self.notes / "scrap.txt").write_text("just a password jotting")
        kept, skipped = self.mod.load_candidates(self.notes)
        self.assertEqual(kept, [])
        self.assertEqual(len(skipped), 1)
        self.assertIn("jotting", skipped[0][1])

    def test_contained_resave_is_dropped(self):
        small = "A conversation about foxes. " * 20
        big = small + "And then it continued much further. " * 20
        (self.notes / "new1.txt").write_text(small)
        (self.notes / "new2.txt").write_text(big)
        kept, _ = self.mod.load_candidates(self.notes)
        kept, dropped = self.mod.drop_contained(kept)
        self.assertEqual(len(kept), 1)
        self.assertEqual(len(dropped), 1)
        self.assertIn("contained in", dropped[0][1])

    def test_imported_note_is_redacted_and_parseable(self):
        secret = "sk-" + "a1B2c3D4" * 3
        (self.notes / "new3.txt").write_text(
            "A long conversation capture with a leaked key " + secret + "\n" + "more text " * 40)
        kept, _ = self.mod.load_candidates(self.notes)
        self.assertEqual(len(kept), 1)
        path, text, mtime = kept[0]
        self.assertNotIn(secret, text)
        self.assertIn("[REDACTED sk-key]", text)
        # and the written note round-trips through the build parser
        self.archive.mkdir()
        out = self.mod.write_note(path, text, mtime)
        spec = importlib.util.spec_from_file_location("build_db", TOOLS / "build_db.py")
        build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build)
        meta, turns = build.parse_md(out)
        self.assertEqual(meta["project"], "notes-prehistory")
        self.assertEqual(turns[0][1], "note")
        self.assertIn("[REDACTED sk-key]", turns[0][4])

    def test_title_derived_from_first_substantial_line(self):
        self.assertEqual(self.mod.derive_title("# Big Fix Tonight\nrest", "fb"), "Big Fix Tonight")
        self.assertEqual(self.mod.derive_title("x\ny\n", "fallback"), "fallback")


if __name__ == "__main__":
    unittest.main()
