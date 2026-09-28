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


class NameSafetyTests(unittest.TestCase):
    def test_a_name_needing_redaction_becomes_a_hash(self):
        name = extract.path_component("sk-proj-" + "A" * 30)
        self.assertTrue(name.startswith("redacted-"))
        self.assertNotIn("AAAA", name)

    def test_ordinary_names_keep_their_exact_spelling(self):
        for name in ("webapp", "my project", "Ångström-2", "a.b_c-d"):
            self.assertEqual(extract.path_component(name), name)

    def test_unsafe_characters_and_dots_are_neutralised(self):
        self.assertEqual(extract.path_component("../../etc"), "-..-etc")
        self.assertEqual(extract.path_component(".."), "unknown")
        self.assertEqual(extract.path_component("a/b\\c:d*e"), "a-b-c-d-e")

    def test_metadata_text_is_redacted_and_one_line(self):
        self.assertEqual(extract.meta_text("main\nsk-proj-" + "A" * 30), "main [REDACTED sk-key]")

if __name__ == "__main__":
    unittest.main()
