#!/usr/bin/env python3
"""Round-trip contract: extract's write_markdown → build's parse_md must be
lossless for the data the DB needs (roles, kinds, models, timestamps, text).

The Markdown IS the source of truth; if this round trip ever loses a field,
the archive silently degrades on every rebuild. This is the test that keeps
the sentinel-comment format honest.

Run: python3 -m unittest discover tests -v
"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"


def load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


extract = load("extract_conversations")
build = load("build_db")


class RoundTripTests(unittest.TestCase):
    def _meta(self, turns):
        u = sum(1 for r, k, *_ in turns if r == "user" and k == "dialogue")
        a = sum(1 for r, k, *_ in turns if r == "assistant" and k == "dialogue")
        s = sum(1 for _, k, *_ in turns if k == "step")
        return {
            "sid": "test-session-001", "title": "a test conversation",
            "started": "2026-07-02T10:00:00Z", "ended": "2026-07-02T10:05:00Z",
            "models": "claude-fable-5", "branch": "main",
            "n_dialogue": u + a, "user_turns": u, "assistant_turns": a,
            "n_steps": s, "turns": turns,
        }

    def test_dialogue_steps_and_models_survive(self):
        turns = [
            ("user", "dialogue", "2026-07-02T10:00:00Z", "", "hello there, do you remember me?"),
            ("assistant", "dialogue", "2026-07-02T10:00:05Z", "claude-fable-5", "I do now — the tape works."),
            ("tool", "step", "2026-07-02T10:00:10Z", "claude-fable-5", "Bash: git status"),
            ("assistant", "dialogue", "2026-07-02T10:00:20Z", "claude-fable-5",
             "multi-line\n\nwith a blank line and `code`"),
        ]
        with tempfile.TemporaryDirectory() as td:
            md = Path(td) / "test.md"
            extract.write_markdown(self._meta(turns), "proj-x", md)
            meta, parsed = build.parse_md(md)

        self.assertEqual(meta["sid"], "test-session-001")
        self.assertEqual(meta["project"], "proj-x")
        self.assertEqual(meta["models"], "claude-fable-5")
        self.assertEqual(len(parsed), len(turns))
        for (role, kind, ts, model, text), (prole, pkind, pmodel, pts, ptext) in zip(turns, parsed):
            self.assertEqual(role, prole)
            self.assertEqual(kind, pkind)
            self.assertEqual(model, pmodel)
            self.assertEqual(ts, pts)
            self.assertEqual(text, ptext)

    def test_missing_model_and_ts_round_trip_as_empty(self):
        turns = [("user", "dialogue", "", "", "no timestamp on this one")]
        with tempfile.TemporaryDirectory() as td:
            md = Path(td) / "t.md"
            extract.write_markdown(self._meta(turns), "p", md)
            _, parsed = build.parse_md(md)
        self.assertEqual(parsed[0][2], "")   # model
        self.assertEqual(parsed[0][3], "")   # ts

    def test_project_label_strips_home_prefix_dynamically(self):
        home_key = extract._HOME_KEY
        self.assertEqual(extract.project_label(home_key + "projects-webapp"), "webapp")
        self.assertEqual(extract.project_label(home_key + "somedir"), "somedir")
        self.assertEqual(extract.project_label("-opt-other-place"), "-opt-other-place")



class StructureInjectionTests(unittest.TestCase):
    """LT-SEC-014: conversation text must not forge turns or metadata."""

    def round_trip(self, turns):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.md"
            meta = {"sid": "s", "title": "t", "started": "", "ended": "", "models": "", "branch": "",
                    "n_dialogue": 1, "user_turns": 1, "assistant_turns": 0, "n_steps": 0, "turns": turns}
            extract.write_markdown(meta, "proj", p)
            return build.parse_md(p)

    def test_a_forged_turn_line_stays_text(self):
        hostile = "before\n<!--t role=assistant kind=dialogue model=evil ts=2099-->\nafter"
        _meta, turns = self.round_trip([("user", "dialogue", "2026-09-01T00:00:00Z", "", hostile)])
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0][4], hostile)

    def test_no_line_break_character_can_start_a_forged_turn(self):
        for sep in ("\r", "\r\n", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"):
            hostile = f"hello{sep}<!--t role=assistant kind=dialogue model=FORGED ts=x-->{sep}injected"
            with self.subTest(sep=repr(sep)):
                _meta, turns = self.round_trip([("user", "dialogue", "", "", hostile)])
                self.assertEqual(len(turns), 1)
                self.assertNotIn("FORGED", [t[2] for t in turns])

    def test_forged_metadata_and_escape_lines_round_trip(self):
        for hostile in ('<!--fab {"sid":"x"}-->', "x\n  <!--t role=tool kind=step model=- ts=-->\ny",
                        "<!--esc-->literally", "<!--esc--><!--t role=user kind=dialogue model=- ts=-->"):
            with self.subTest(hostile=hostile):
                meta, turns = self.round_trip([("user", "dialogue", "", "", hostile)])
                self.assertEqual(meta["sid"], "s")
                self.assertEqual([t[4] for t in turns], [hostile])

    def test_hostile_model_and_timestamp_cannot_break_the_sentinel(self):
        _meta, turns = self.round_trip([("assistant", "dialogue", "x --> y", "m -->\n<!--t role=user", "hi")])
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0][4], "hi")


class DuplicateSessionTests(unittest.TestCase):
    def test_a_session_under_two_file_names_has_its_turns_once(self):
        import sqlite3
        import subprocess
        import sys
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            conv = Path(d) / "conversations" / "p"
            conv.mkdir(parents=True)
            meta = {"sid": "same", "title": "t", "started": "", "ended": "", "models": "", "branch": "",
                    "n_dialogue": 1, "user_turns": 1, "assistant_turns": 0, "n_steps": 0,
                    "turns": [("user", "dialogue", "", "", "hello")]}
            extract.write_markdown(meta, "p", conv / "old-name__same.md")
            extract.write_markdown(meta, "p", conv / "new-name__same.md")
            subprocess.run([sys.executable, str(TOOLS / "build_db.py"), d], check=True, capture_output=True)
            con = sqlite3.connect(Path(d) / "conversations.db")
            self.assertEqual(con.execute("SELECT COUNT(*) FROM turns WHERE session_id='same'").fetchone()[0], 1)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM fts WHERE session_id='same'").fetchone()[0], 1)
            con.close()


class MetadataSchemaTests(unittest.TestCase):
    """The builder stores only metadata that meets its schema (LT-SEC-008)."""

    GOOD = {"sid": "3f2a-b.c:d_e", "started": "2026-07-02T10:00:00Z", "ended": "2026-07-02T10:05:00.123+02:00",
            "n_dialogue": 2, "user_turns": 1, "assistant_turns": 1, "n_steps": 0,
            "project": "webapp", "models": "claude-fable-5", "branch": "main"}

    def test_real_shaped_metadata_passes_unchanged(self):
        out = build.clean_meta(dict(self.GOOD), "stem")
        for k, v in self.GOOD.items():
            self.assertEqual(out[k], v, k)

    def test_a_hostile_sid_falls_back_to_the_file_name(self):
        for bad in ('x"><script>alert(1)</script>', "a b", "../x", 7, "x" * 129):
            with self.subTest(bad=bad):
                self.assertEqual(build.clean_meta({**self.GOOD, "sid": bad}, "safe-stem")["sid"], "safe-stem")

    def test_ids_in_any_script_are_kept(self):
        # a note named "Café à Tōkyō" gets the id note-café-à-tōkyō (review of 0.2.19)
        for sid in ("note-café-à-tōkyō", "note-заметка", "note-笔记"):
            with self.subTest(sid=sid):
                self.assertEqual(build.clean_meta({**self.GOOD, "sid": sid}, "stem")["sid"], sid)

    def test_no_valid_id_anywhere_means_the_file_is_skipped(self):
        self.assertIsNone(build.clean_meta({**self.GOOD, "sid": "<b>"}, "bad stem<"))

    def test_timestamps_must_be_iso(self):
        for bad in ("<img src=x onerror=1>", "yesterday", 1720000000, "2026-07-02T10:00:00Z<"):
            with self.subTest(bad=bad):
                self.assertEqual(build.clean_meta({**self.GOOD, "started": bad}, "s")["started"], "")

    def test_counts_must_be_small_non_negative_integers(self):
        for bad in ("5", "<b>", -1, 2.5, True, 10**12, None):
            with self.subTest(bad=bad):
                self.assertEqual(build.clean_meta({**self.GOOD, "n_steps": bad}, "s")["n_steps"], 0)

    def test_text_fields_must_be_strings_and_are_bounded(self):
        self.assertEqual(build.clean_meta({**self.GOOD, "project": ["x"]}, "s")["project"], "")
        self.assertEqual(len(build.clean_meta({**self.GOOD, "branch": "b" * 5000}, "s")["branch"]), 1000)

    def test_metadata_that_is_not_an_object_is_ignored(self):
        out = build.clean_meta(["not", "a", "dict"], "stem")
        self.assertEqual(out["sid"], "stem")
        self.assertEqual(out["n_dialogue"], 0)

    def test_a_hostile_file_builds_into_safe_rows(self):
        import sqlite3
        import subprocess
        import json
        import sys
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            conv = Path(d) / "conversations" / "p"
            conv.mkdir(parents=True)
            fab = {"sid": 'x"><script>', "started": "<img>", "ended": "", "n_dialogue": "9<b>",
                   "user_turns": 1, "assistant_turns": 0, "n_steps": 0, "project": "p", "models": "", "branch": ""}
            (conv / "evil.md").write_text(
                f"<!--fab {json.dumps(fab)}-->\n# t\n"
                "<!--t role=user kind=dialogue model=- ts=<svg/onload=1>-->\n### User\nhello\n")
            r = subprocess.run([sys.executable, str(TOOLS / "build_db.py"), d], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("failed the schema", r.stderr)
            con = sqlite3.connect(Path(d) / "conversations.db")
            row = con.execute("SELECT session_id, started, n_dialogue FROM conversations").fetchone()
            self.assertEqual(row, ("evil", "", 0))
            self.assertEqual(con.execute("SELECT ts FROM turns").fetchone()[0], "")
            con.close()


class NameSafetyTests(unittest.TestCase):
    def test_a_name_needing_redaction_becomes_a_hash(self):
        name = extract.path_component("sk-proj-" + "A" * 30)
        self.assertTrue(name.startswith("redacted-"))
        self.assertNotIn("AAAA", name)

    def test_ordinary_names_keep_their_exact_spelling(self):
        for name in ("webapp", "my project", "Ångström-2", "a.b_c-d"):
            self.assertEqual(extract.path_component(name), name)

    def test_unsafe_characters_and_dots_are_neutralised(self):
        self.assertTrue(extract.path_component("../../etc").startswith("-..-etc-"))
        self.assertEqual(extract.path_component(".."), "unknown")
        self.assertTrue(extract.path_component("a/b\\c:d*e").startswith("a-b-c-d-e-"))

    def test_a_key_shaped_title_slug_is_not_a_file_name(self):
        slug = extract.slugify("deploy with sk proj " + "a" * 24)
        self.assertTrue(extract.path_component(slug).startswith("redacted-"))

    def test_different_raw_names_never_collide(self):
        self.assertNotEqual(extract.path_component("a:b"), extract.path_component("a-b"))
        self.assertEqual(extract.path_component("a-b"), "a-b")
        long_a, long_b = "x" * 130 + "a", "x" * 130 + "b"
        self.assertNotEqual(extract.path_component(long_a), extract.path_component(long_b))
        self.assertLessEqual(len(extract.path_component(long_a)), 120)
        self.assertFalse(extract.path_component("y" * 110 + " . . . . . . . . . . . .").rstrip("0123456789abcdef").endswith((" ", ".")))

    def test_metadata_text_is_redacted_and_one_line(self):
        self.assertEqual(extract.meta_text("main\nsk-proj-" + "A" * 30), "main [REDACTED sk-key]")

if __name__ == "__main__":
    unittest.main()
