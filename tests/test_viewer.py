#!/usr/bin/env python3
"""Tests for the local web viewer (tools/conversations_viewer.py).

The viewer had no tests before 2026-08-06, and four real defects were living in
it — each reproduced by hand against the old code before being fixed here:

  1. the search box was passed straight to FTS5 MATCH, so typing a `"`, a `*`,
     or the word `AND` raised OperationalError and killed the request
  2. highlighting was case-sensitive, so an FTS hit on "Fox" rendered a result
     with nothing marked
  3. highlighting ran over already-escaped text, so searching `amp` rewrote
     `&amp;` into `&<mark>amp</mark>;` and corrupted the output
  4. build_db writes one FTS row per KIND, so a term in both a message and a
     tool step listed the same conversation twice

Run: python3 -m unittest discover tests -v
"""
import importlib.util
import re
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"

def real_schema():
    """The PRODUCTION schema, extracted from build_db.py — never restated here.

    Hand-writing a fixture schema is how a viewer suite passes against a shape the
    real database does not have. This file previously invented `branch` and
    `engine`; production has `git_branch` and `md_path`. A 12-value positional
    INSERT swallowed the mismatch, so every conversation page raised
    `IndexError: No item with that key` in production while every test was green.
    Deriving the schema from the builder makes that class of drift impossible.
    """
    src = (TOOLS / "build_db.py").read_text(encoding="utf-8")
    stmts = re.findall(r"CREATE (?:VIRTUAL )?TABLE [^;]+;", src)
    assert len(stmts) >= 3, f"could not extract schema from build_db.py (found {len(stmts)})"
    return "\n".join(stmts)


SCHEMA = real_schema()

CONV_COLS = ("session_id", "project", "title", "started", "ended", "n_dialogue",
             "user_turns", "assistant_turns", "n_steps", "models", "git_branch", "md_path")


def load_viewer(archive_dir):
    """Load the viewer module pointed at a throwaway archive.

    argv is set before exec because the module resolves ARCHIVE/PORT at import.
    PORT is 0 so a test can never squat the registered port (8124) — binding a
    claimed port from a test suite is how you get a green run against whatever
    server happened to already be listening.
    """
    saved = sys.argv
    sys.argv = ["conversations_viewer.py", str(archive_dir), "0"]
    try:
        spec = importlib.util.spec_from_file_location("conversations_viewer",
                                                      TOOLS / "conversations_viewer.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.argv = saved
    return mod


def make_archive(conversations):
    """conversations: list of (sid, project, title, [(role, kind, text), ...])"""
    td = Path(tempfile.mkdtemp())
    con = sqlite3.connect(td / "conversations.db")
    con.executescript(SCHEMA)
    for sid, project, title, turns in conversations:
        dialogue = [t for t in turns if t[1] in ("dialogue", "note")]
        steps = [t for t in turns if t[1] == "step"]
        con.execute(
            f"INSERT INTO conversations ({','.join(CONV_COLS)}) "
            f"VALUES ({','.join('?' * len(CONV_COLS))})",
            (sid, project, title, "2026-08-06T09:00:00Z", "2026-08-06T09:30:00Z",
             len(dialogue), 1, 1, len(steps), "claude-opus-5", "main", f"{project}/{sid}.md"))
        for i, (role, kind, text) in enumerate(turns):
            con.execute("INSERT INTO turns VALUES (?,?,?,?,?,?,?)",
                        (sid, i, role, kind, "2026-08-06T09:0%d:00Z" % min(i, 9),
                         "claude-opus-5" if role == "assistant" else "", text))
        if dialogue:
            con.execute("INSERT INTO fts VALUES (?,?,?,?,?)",
                        (sid, "dialogue", project, title, "\n".join(t[2] for t in dialogue)))
        if steps:
            con.execute("INSERT INTO fts VALUES (?,?,?,?,?)",
                        (sid, "step", project, title, "\n".join(t[2] for t in steps)))
    con.commit()
    con.close()
    return td


DEMO = [
    ("s1", "fabulous", "The fox and the gate", [
        ("user", "dialogue", "Do you remember the FOX? the fox and a Fox."),
        ("assistant", "dialogue", "I do — tom & jerry were there too."),
        ("tool", "step", "Bash: grep fox tools/"),
    ]),
    ("s2", "mai", "A quiet conversation", [
        ("user", "dialogue", "nothing to see here"),
        ("assistant", "dialogue", "agreed"),
    ]),
]


class QuerySanitisingTests(unittest.TestCase):
    """Bug 1: a human typing ordinary punctuation must not crash the search."""

    @classmethod
    def setUpClass(cls):
        cls.archive = make_archive(DEMO)
        cls.v = load_viewer(cls.archive)

    def test_fts_metacharacters_never_raise(self):
        con = self.v.db()
        try:
            for probe in ('fox"', 'NEAR/', '*', 'AND', 'a OR', '(', '""', 'fox AND "', 'NOT'):
                with self.subTest(probe=probe):
                    rows, total, _ = self.v.search(con, probe, "", 1)  # must not raise
                    self.assertIsInstance(total, int)
        finally:
            con.close()

    def test_ordinary_search_still_finds_things(self):
        con = self.v.db()
        try:
            rows, total, _ = self.v.search(con, "fox", "", 1)
            self.assertEqual(total, 1)
            self.assertEqual(rows[0]["session_id"], "s1")
        finally:
            con.close()

    def test_quoted_phrase_is_searched_literally(self):
        self.assertEqual(self.v.fts_query('say "hi"'), '"say" "hi"')

    def test_trailing_star_is_kept_as_a_prefix_search(self):
        self.assertEqual(self.v.fts_query("redact*"), '"redact"*')
        con = self.v.db()
        try:
            _, total, _ = self.v.search(con, "fo*", "", 1)
            self.assertEqual(total, 1, "prefix search should still match 'fox'")
        finally:
            con.close()

    def test_empty_or_punctuation_only_query_means_browse(self):
        for raw in ("", "   ", '"', "**", "()"):
            with self.subTest(raw=raw):
                self.assertEqual(self.v.fts_query(raw), "")


class HighlightTests(unittest.TestCase):
    """Bugs 2 and 3: highlighting must be case-insensitive and entity-safe."""

    @classmethod
    def setUpClass(cls):
        cls.archive = make_archive(DEMO)
        cls.v = load_viewer(cls.archive)

    def test_highlight_is_case_insensitive(self):
        out = self.v.highlight("FOX and fox and Fox", ["fox"])
        self.assertEqual(out.count("<mark>"), 3)

    def test_highlight_preserves_the_original_casing(self):
        out = self.v.highlight("FOX", ["fox"])
        self.assertIn("<mark>FOX</mark>", out)

    def test_highlight_does_not_corrupt_html_entities(self):
        out = self.v.highlight("tom & jerry", ["amp"])
        self.assertIn("&amp;", out)
        self.assertNotIn("<mark>amp</mark>", out)

    def test_text_is_escaped_even_with_no_terms(self):
        self.assertEqual(self.v.highlight("<script>x</script>", []),
                         "&lt;script&gt;x&lt;/script&gt;")

    def test_a_search_term_cannot_inject_markup(self):
        out = self.v.highlight("look: <script>alert(1)</script>", ["<script>"])
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_snippet_sentinels_become_marks_without_injecting(self):
        raw = f"a {self.v.HL_OPEN}fox{self.v.HL_CLOSE} <b>bold</b>"
        out = self.v.escape_snippet(raw)
        self.assertIn("<mark>fox</mark>", out)
        self.assertIn("&lt;b&gt;", out)
        self.assertNotIn("<b>", out)


class ResultShapeTests(unittest.TestCase):
    """Bug 4: one conversation must appear once, however many FTS rows match."""

    @classmethod
    def setUpClass(cls):
        cls.archive = make_archive(DEMO)
        cls.v = load_viewer(cls.archive)

    def test_term_in_both_dialogue_and_step_yields_one_row(self):
        con = self.v.db()
        try:
            # "fox" appears in the dialogue AND in the Bash step of s1.
            rows, total, _ = self.v.search(con, "fox", "", 1)
            self.assertEqual(len(rows), 1, "conversation listed twice")
            self.assertEqual(total, 1, "count must also be de-duplicated")
        finally:
            con.close()

    def test_search_results_carry_a_snippet(self):
        con = self.v.db()
        try:
            rows, _, _ = self.v.search(con, "fox", "", 1)
            self.assertTrue(rows[0]["snip"], "a result with no snippet cannot show WHY it matched")
            self.assertIn(self.v.HL_OPEN, rows[0]["snip"])
        finally:
            con.close()

    def test_browse_mode_is_newest_first_and_counts_everything(self):
        con = self.v.db()
        try:
            rows, total, _ = self.v.search(con, "", "", 1)
            self.assertEqual(total, 2)
            self.assertEqual(len(rows), 2)
        finally:
            con.close()

    def test_project_filter_applies_to_both_rows_and_total(self):
        con = self.v.db()
        try:
            rows, total, _ = self.v.search(con, "", "mai", 1)
            self.assertEqual(total, 1)
            self.assertEqual(rows[0]["session_id"], "s2")
        finally:
            con.close()

    def test_a_page_past_the_end_clamps_instead_of_reading_as_no_results(self):
        """A page beyond the last one must not render as 'Nothing matched'.

        Before the clamp, /?q=fox&page=2 on a 40-result search returned zero rows
        with total=40, and the sidebar's empty state told the user their search
        found nothing — byte-for-byte identical to a genuine miss.
        """
        many = [(f"p{i}", "bulk", f"conversation {i}",
                 [("user", "dialogue", "hello fox")]) for i in range(60)]
        v = load_viewer(make_archive(many))
        con = v.db()
        try:
            for requested in (2, 3, 99):
                with self.subTest(page=requested):
                    rows, total, page = v.search(con, "fox", "", requested)
                    self.assertEqual(total, 60)
                    self.assertTrue(rows, "clamped page must still return rows")
                    self.assertEqual(page, 2, "should clamp to the last page with rows")
            # and the same for browse mode
            rows, total, page = v.search(con, "", "", 99)
            self.assertTrue(rows)
            self.assertEqual(page, 2)
        finally:
            con.close()

    def test_pagination_splits_and_does_not_lose_rows(self):
        many = [(f"p{i}", "bulk", f"conversation {i}",
                 [("user", "dialogue", "hello")]) for i in range(120)]
        v = load_viewer(make_archive(many))
        con = v.db()
        try:
            p1, total, _ = v.search(con, "", "", 1)
            p2, _, _ = v.search(con, "", "", 2)
            p3, _, _ = v.search(con, "", "", 3)
            self.assertEqual(total, 120)
            self.assertEqual([len(p1), len(p2), len(p3)], [50, 50, 20])
            seen = {r["session_id"] for r in list(p1) + list(p2) + list(p3)}
            self.assertEqual(len(seen), 120, "pages overlap or drop rows")
        finally:
            con.close()


class LayerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive = make_archive(DEMO)
        cls.v = load_viewer(cls.archive)

    def test_personal_layer_hides_steps(self):
        con = self.v.db()
        try:
            out = self.v.render(con, "s1", "", True, False)
            self.assertIn("Do you remember", out)
            self.assertNotIn("grep fox", out)
        finally:
            con.close()

    def test_architect_layer_hides_dialogue(self):
        con = self.v.db()
        try:
            out = self.v.render(con, "s1", "", False, True)
            self.assertIn("grep fox", out)
            self.assertNotIn("Do you remember", out)
        finally:
            con.close()

    def test_both_layers_off_explains_itself(self):
        con = self.v.db()
        try:
            out = self.v.render(con, "s1", "", False, False)
            self.assertIn("Nothing in this layer", out)
        finally:
            con.close()

    def test_turns_are_anchorable(self):
        con = self.v.db()
        try:
            out = self.v.render(con, "s1", "", True, True)
            self.assertIn('id=t0', out)
            self.assertIn('href="#t0"', out)
        finally:
            con.close()


class HttpTests(unittest.TestCase):
    """Drive the real handler over a real socket on an ephemeral port."""

    @classmethod
    def setUpClass(cls):
        cls.archive = make_archive(DEMO)
        cls.v = load_viewer(cls.archive)
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), cls.v.H)
        cls.port = cls.srv.server_address[1]
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.thread.join(timeout=5)

    def get(self, path):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, dict(r.headers), r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read().decode("utf-8")

    def test_index_renders(self):
        code, _, body = self.get("/")
        self.assertEqual(code, 200)
        self.assertIn("Lucy&#39;s Tape", body)
        self.assertIn("<html lang=en", body)
        self.assertIn("name=viewport", body)

    def test_a_crashing_query_now_returns_a_page(self):
        # The exact input that used to raise OperationalError out of do_GET.
        for probe in ('fox%22', 'AND', '%2A'):
            with self.subTest(probe=probe):
                code, _, body = self.get(f"/?q={probe}")
                self.assertEqual(code, 200)
                self.assertIn("</html>", body, "response was truncated by an exception")

    def test_csp_nonce_is_present_and_unique_per_response(self):
        _, h1, b1 = self.get("/")
        _, h2, _ = self.get("/")
        self.assertIn("Content-Security-Policy", h1)
        self.assertIn("default-src 'none'", h1["Content-Security-Policy"])
        self.assertNotEqual(h1["Content-Security-Policy"], h2["Content-Security-Policy"],
                            "a reused nonce is not a nonce")
        nonce = re.search(r"script-src 'nonce-([^']+)'", h1["Content-Security-Policy"]).group(1)
        self.assertIn(f'<script nonce="{nonce}">', b1,
                      "the inline script must carry the nonce or the page is script-less")

    def test_no_inline_style_attributes_anywhere(self):
        """The CSP has no 'unsafe-inline' in style-src, and a nonce authorises a
        <style> ELEMENT, never a style ATTRIBUTE. So any `style="…"` in the markup
        is silently dropped by the browser: the page renders, the tests pass, and
        the styling is simply absent. That is how the model badges lost their
        colour on 2026-08-06 — caught by opening a browser, not by the suite.
        This is the mechanical guard so it cannot recur."""
        for path in ("/", "/c/a1", "/c/s1", "/?q=fox"):
            with self.subTest(path=path):
                _, _, body = self.get(path)
                self.assertNotIn('style="', body,
                                 "inline style attribute will be blocked by the CSP")
                self.assertNotIn("style='", body)

    def test_no_unquoted_attribute_value_absorbs_a_self_closing_slash(self):
        """`<path fill=currentColor/>` parses the value as "currentColor/".

        HTML terminates an unquoted attribute value at whitespace or ">", never
        at "/". The theme icon's half-fill was invisible for exactly this reason:
        valid geometry, invalid colour, nothing painted, no error anywhere.
        """
        for path in ("/", "/c/s1"):
            with self.subTest(path=path):
                _, _, body = self.get(path)
                offender = re.search(r'=[^"\'\s>]+/>', body)
                self.assertIsNone(offender,
                                  f"unquoted attribute swallows the slash: {offender.group(0) if offender else ''}")

    def test_model_badges_are_coloured_by_class(self):
        _, _, body = self.get("/c/s1")
        self.assertIn("badge--opus", body)
        _, _, css = self.get("/")
        self.assertIn(".badge--opus{color:", css, "the class exists but has no rule")

    def test_security_headers(self):
        _, h, _ = self.get("/")
        self.assertEqual(h.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(h.get("Referrer-Policy"), "no-referrer")

    def test_conversation_page(self):
        code, _, body = self.get("/c/s1")
        self.assertEqual(code, 200)
        self.assertIn("The fox and the gate", body)
        self.assertIn("aria-pressed=\"true\"", body)

    def test_unknown_conversation_is_a_404_page_not_a_crash(self):
        code, _, body = self.get("/c/nope")
        self.assertEqual(code, 404)
        self.assertIn("Not found", body)
        self.assertIn("</html>", body)

    def test_unknown_path_is_a_404_page(self):
        code, _, body = self.get("/whatever")
        self.assertEqual(code, 404)
        self.assertIn("</html>", body)

    def test_bad_page_number_does_not_crash(self):
        for probe in ("abc", "-5", "999999"):
            with self.subTest(probe=probe):
                code, _, body = self.get(f"/?page={probe}")
                self.assertEqual(code, 200)
                self.assertIn("</html>", body)

    def test_archived_markup_cannot_execute(self):
        archive = make_archive([("x1", "evil", "<script>alert(1)</script>", [
            ("user", "dialogue", "<img src=x onerror=alert(2)>"),
        ])])
        v = load_viewer(archive)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), v.H)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{srv.server_address[1]}/c/x1", timeout=10) as r:
                body = r.read().decode("utf-8")
        finally:
            srv.shutdown(); srv.server_close(); t.join(timeout=5)
        # What makes the payload dangerous is an unescaped TAG, not the substring
        # "onerror=..." — that appears legitimately as escaped text content, so
        # asserting its absence would be asserting the wrong thing.
        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertNotIn("<img src=x", body, "an unescaped tag reached the page")
        self.assertIn("&lt;img src=x onerror=alert(2)&gt;", body)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", body)
        # Only the two nonce'd blocks the server itself emits may be <script>.
        self.assertEqual(body.count("<script"), 1, "an extra <script> tag exists")


if __name__ == "__main__":
    unittest.main()
