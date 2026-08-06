#!/usr/bin/env python3
"""One unreadable source must not cost you the whole archive.

The sources (`~/.claude/projects`, `~/.codex/sessions`) are outside our control
and read-only to us, so we never repair them. In practice they contain files we
cannot open: the CLI deletes a session while a run is in flight, or leaves a
dangling subagent symlink behind — `rglob("*.jsonl")` matches a symlink by name
without resolving it, so the failure happens at the read, one frame deep.

Before this was handled, a single such file raised out of `main()` and the entire
nightly refresh produced nothing — including every healthy conversation sitting
next to it.

This stays fail-SOFT only because the pipeline fails CLOSED downstream: the
sanity floor and shrink ratchet in `tools/tape` refuse to commit an archive that
collapses, so mass source loss still aborts the run rather than quietly
publishing a truncated archive.

Run: python3 -m unittest discover tests -v
"""
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"


def load_extract():
    """Fresh module per test — `main()` mutates module-level state."""
    spec = importlib.util.spec_from_file_location("extract_conversations",
                                                  TOOLS / "extract_conversations.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GOOD_SESSION = [
    {"type": "user", "timestamp": "2026-08-06T09:00:00Z",
     "message": {"role": "user", "content": [{"type": "text", "text": "hello, do you remember me?"}]}},
    {"type": "assistant", "timestamp": "2026-08-06T09:00:05Z",
     "message": {"role": "assistant", "model": "claude-sonnet-5",
                 "content": [{"type": "text", "text": "I do now — the tape works."}]}},
]


class UnreadableSourceTests(unittest.TestCase):
    def _run(self, make_sources):
        """Build a synthetic source tree, run main(), return (stdout, out_dir, module)."""
        ex = load_extract()
        td = Path(tempfile.mkdtemp())
        projects = td / "projects"
        projects.mkdir()
        make_sources(projects)

        ex.PROJECTS = projects
        ex.CODEX_SESSIONS = td / "absent-codex"
        ex.OUT = td / "archive"
        ex.CONV_DIR = ex.OUT / "conversations"

        buf = io.StringIO()
        with redirect_stdout(buf):
            ex.main()
        return buf.getvalue(), ex.CONV_DIR, ex

    @staticmethod
    def _write_good(proj, name="good.jsonl"):
        proj.mkdir(parents=True, exist_ok=True)
        (proj / name).write_text("\n".join(json.dumps(r) for r in GOOD_SESSION) + "\n",
                                 encoding="utf-8")

    def test_dangling_symlink_does_not_abort_the_run(self):
        def sources(projects):
            proj = projects / "-home-u-projects-demo"
            self._write_good(proj)
            # Exactly what a removed subagent session leaves behind.
            (proj / "dangling.jsonl").symlink_to(proj / "does-not-exist.jsonl")

        out, conv_dir, _ = self._run(sources)

        written = list(conv_dir.rglob("*.md"))
        self.assertEqual(len(written), 1,
                         "the healthy conversation next to the bad file must still be archived")
        self.assertIn("sources skipped      : 1", out)
        self.assertIn("dangling.jsonl", out, "a hole in the archive must be reported, never silent")

    def test_unreadable_file_is_reported_with_a_reason(self):
        def sources(projects):
            proj = projects / "-home-u-projects-demo"
            self._write_good(proj)
            bad = proj / "locked.jsonl"
            bad.write_text("{}\n", encoding="utf-8")
            bad.chmod(0o000)

        out, conv_dir, _ = self._run(sources)

        self.assertEqual(len(list(conv_dir.rglob("*.md"))), 1)
        self.assertIn("sources skipped      : 1", out)
        self.assertIn("WARN unreadable source", out)
        self.assertIn("Permission denied", out, "the reason must be named, not swallowed")

    def test_clean_run_reports_zero_skipped(self):
        # The counter must appear even when nothing failed: a metric that only
        # shows up on failure cannot be trusted to be watching.
        def sources(projects):
            self._write_good(projects / "-home-u-projects-demo")

        out, conv_dir, _ = self._run(sources)

        self.assertEqual(len(list(conv_dir.rglob("*.md"))), 1)
        self.assertIn("sources skipped      : 0", out)

    def test_every_healthy_session_survives_a_bad_neighbour(self):
        # The failure must be scoped to the one file, not to its directory.
        def sources(projects):
            proj = projects / "-home-u-projects-demo"
            for i in range(3):
                self._write_good(proj, f"good-{i}.jsonl")
            (proj / "dangling.jsonl").symlink_to(proj / "does-not-exist.jsonl")

        out, conv_dir, _ = self._run(sources)

        self.assertEqual(len(list(conv_dir.rglob("*.md"))), 3)
        self.assertIn("sources skipped      : 1", out)

    def test_unreadable_codex_rollout_is_also_survived(self):
        # The codex source is optional but goes through the same seam; it must
        # not be the one path that still takes the run down.
        ex = load_extract()
        td = Path(tempfile.mkdtemp())
        projects = td / "projects"
        self._write_good(projects / "-home-u-projects-demo")
        codex = td / "codex-sessions" / "2026" / "08"
        codex.mkdir(parents=True)
        (codex / "rollout-broken.jsonl").symlink_to(codex / "gone.jsonl")

        ex.PROJECTS = projects
        ex.CODEX_SESSIONS = td / "codex-sessions"
        ex.OUT = td / "archive"
        ex.CONV_DIR = ex.OUT / "conversations"

        buf = io.StringIO()
        with redirect_stdout(buf):
            ex.main()
        out = buf.getvalue()

        self.assertEqual(len(list(ex.CONV_DIR.rglob("*.md"))), 1)
        self.assertIn("sources skipped      : 1", out)
        self.assertIn("rollout-broken.jsonl", out)


if __name__ == "__main__":
    unittest.main()
