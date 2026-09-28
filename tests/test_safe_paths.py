#!/usr/bin/env python3
"""Path containment (LT-SEC-009): sources are read only inside their folders, the archive is
written without following links, and a date in a file name is a date.

The module is tested directly, then each tool that uses it is tested end to end with the
hostile tree it has to survive.

Run: python3 -m unittest discover tests -v
"""
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
BASH = shutil.which("bash")
POSIX = os.name != "nt"


def load(name, argv=None):
    saved = sys.argv
    sys.argv = [f"{name}.py"] + (argv or [])
    try:
        spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.argv = saved


sp = load("safe_paths")


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="safe-paths-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "root"
        self.root.mkdir()
        self.outside = self.tmp / "outside.txt"
        self.outside.write_text("precious, not ours\n")


class DatePrefixTests(unittest.TestCase):
    def test_a_real_timestamp_gives_its_date(self):
        self.assertEqual(sp.date_prefix("2026-09-28T10:00:00Z"), "2026-09-28")

    def test_anything_else_gives_the_no_date_marker(self):
        for bad in ("../../etc/x", "/etc/passwd", "2026-09-2/../", "", None, "yesterday"):
            with self.subTest(bad=bad):
                self.assertEqual(sp.date_prefix(bad), "0000-00-00")


class OpenSourceTests(Tmp):
    def read(self, path, **kw):
        fh, st = sp.open_source(path, self.root, **kw)
        with fh:
            return fh.read()

    def test_a_regular_file_inside_is_read(self):
        (self.root / "a.jsonl").write_bytes(b"hello")
        self.assertEqual(self.read(self.root / "a.jsonl"), b"hello")

    @unittest.skipUnless(POSIX, "symlinks")
    def test_a_link_to_a_sibling_inside_is_followed(self):
        # what Claude Code does for subagent sessions
        (self.root / "real.jsonl").write_bytes(b"sibling")
        (self.root / "link.jsonl").symlink_to(self.root / "real.jsonl")
        self.assertEqual(self.read(self.root / "link.jsonl"), b"sibling")

    @unittest.skipUnless(POSIX, "symlinks")
    def test_a_link_is_refused_where_links_are_not_allowed(self):
        (self.root / "real.md").write_bytes(b"x")
        (self.root / "link.md").symlink_to(self.root / "real.md")
        with self.assertRaises(sp.Refused):
            self.read(self.root / "link.md", follow_links=False)

    @unittest.skipUnless(POSIX, "symlinks")
    def test_a_link_leading_outside_is_refused(self):
        (self.root / "evil.jsonl").symlink_to(self.outside)
        with self.assertRaises(sp.Refused):
            self.read(self.root / "evil.jsonl")

    @unittest.skipUnless(POSIX, "symlinks")
    def test_a_file_under_a_linked_folder_outside_is_refused(self):
        away = self.tmp / "away"
        away.mkdir()
        (away / "s.jsonl").write_bytes(b"x")
        (self.root / "dir").symlink_to(away)
        with self.assertRaises(sp.Refused):
            self.read(self.root / "dir" / "s.jsonl")

    @unittest.skipUnless(POSIX, "symlinks")
    def test_a_symlink_loop_is_refused_not_a_crash(self):
        (self.root / "a.jsonl").symlink_to(self.root / "b.jsonl")
        (self.root / "b.jsonl").symlink_to(self.root / "a.jsonl")
        with self.assertRaises(sp.Refused):
            self.read(self.root / "a.jsonl")

    def test_dot_dot_out_of_the_root_is_refused(self):
        with self.assertRaises(sp.Refused):
            self.read(self.root / ".." / "outside.txt")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "fifos")
    def test_a_fifo_is_refused_without_blocking(self):
        os.mkfifo(self.root / "pipe.jsonl")
        with self.assertRaises(sp.Refused):
            self.read(self.root / "pipe.jsonl")

    def test_a_folder_is_refused(self):
        (self.root / "d.jsonl").mkdir()
        with self.assertRaises(sp.Refused):
            self.read(self.root / "d.jsonl")

    def test_the_refusal_says_why(self):
        with self.assertRaises(sp.Refused) as cm:
            self.read(self.root / ".." / "outside.txt")
        self.assertEqual(cm.exception.strerror, "outside its folder")


class WriteTextTests(Tmp):
    @unittest.skipUnless(sys.platform.startswith(("linux", "darwin")), "POSIX with openat/renameat")
    def test_the_descriptor_walk_is_used_where_the_platform_has_it(self):
        # 0.2.21 tested the wrong capability and silently took the fallback everywhere
        self.assertTrue(sp._HAVE_DIR_FD)

    def test_writes_privately_and_creates_folders(self):
        target = self.root / "conversations" / "p" / "x.md"
        sp.write_text(target, "hello ✓", self.root)
        self.assertEqual(target.read_text(encoding="utf-8"), "hello ✓")
        if POSIX:
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(target.parent.stat().st_mode) & 0o077, 0)

    def test_replaces_an_existing_file(self):
        target = self.root / "x.md"
        target.write_text("old")
        sp.write_text(target, "new", self.root)
        self.assertEqual(target.read_text(), "new")

    @unittest.skipUnless(POSIX, "symlinks")
    def test_a_link_at_the_target_is_replaced_not_written_through(self):
        target = self.root / "INDEX.md"
        target.symlink_to(self.outside)
        sp.write_text(target, "index", self.root)
        self.assertEqual(self.outside.read_text(), "precious, not ours\n")
        self.assertFalse(target.is_symlink())
        self.assertEqual(target.read_text(), "index")

    @unittest.skipUnless(POSIX, "symlinks")
    def test_a_linked_folder_on_the_way_is_refused(self):
        away = self.tmp / "away"
        away.mkdir()
        (self.root / "conversations").symlink_to(away)
        with self.assertRaises(sp.Refused):
            sp.write_text(self.root / "conversations" / "x.md", "x", self.root)
        self.assertEqual(list(away.iterdir()), [])

    @unittest.skipUnless(POSIX, "symlinks")
    def test_a_linked_archive_root_is_refused(self):
        away = self.tmp / "away"
        away.mkdir()
        linked = self.tmp / "linked-root"
        linked.symlink_to(away)
        with self.assertRaises(sp.Refused):
            sp.write_text(linked / "x.md", "x", linked)
        self.assertEqual(list(away.iterdir()), [])

    def test_a_path_outside_the_root_is_refused(self):
        with self.assertRaises(sp.Refused):
            sp.write_text(self.root / ".." / "outside.txt", "x", self.root)
        self.assertEqual(self.outside.read_text(), "precious, not ours\n")

    def test_a_temp_file_left_by_a_killed_run_does_not_block_the_next(self):
        # 0.2.21 named it .<name>.<pid>.tmp; a reused pid made every later write fail
        for pid in (os.getpid(), 1, 99999):
            (self.root / f".x.md.{pid}.tmp").write_text("left behind")
        sp.write_text(self.root / "x.md", "fine", self.root)
        self.assertEqual((self.root / "x.md").read_text(), "fine")
        self.assertNotEqual(sp.temp_name("x.md"), sp.temp_name("x.md"))

    def test_a_failed_write_leaves_no_temporary_file(self):
        (self.root / "x.md").mkdir()  # a folder where the file should go: the rename fails
        with self.assertRaises(OSError):
            sp.write_text(self.root / "x.md", "x", self.root)
        self.assertEqual([p.name for p in self.root.iterdir()], ["x.md"])

    @unittest.skipUnless(POSIX, "symlinks")
    def test_the_fallback_without_folder_descriptors_also_refuses_links(self):
        saved = sp._HAVE_DIR_FD
        sp._HAVE_DIR_FD = False
        try:
            sp.write_text(self.root / "a" / "ok.md", "fine", self.root)
            self.assertEqual((self.root / "a" / "ok.md").read_text(), "fine")
            away = self.tmp / "away"
            away.mkdir()
            (self.root / "b").symlink_to(away)
            with self.assertRaises(sp.Refused):
                sp.write_text(self.root / "b" / "x.md", "x", self.root)
            self.assertEqual(list(away.iterdir()), [])
        finally:
            sp._HAVE_DIR_FD = saved


SESSION = [
    {"type": "user", "timestamp": "2026-08-06T09:00:00Z",
     "message": {"role": "user", "content": [{"type": "text", "text": "hello, do you remember me?"}]}},
    {"type": "assistant", "timestamp": "2026-08-06T09:00:05Z",
     "message": {"role": "assistant", "model": "claude-sonnet-5",
                 "content": [{"type": "text", "text": "I do now."}]}},
]


class ExtractorContainmentTests(Tmp):
    def run_extract(self):
        ex = load("extract_conversations")
        ex.PROJECTS = self.root
        ex.CODEX_SESSIONS = self.tmp / "no-codex"
        ex.OUT = self.tmp / "archive"
        ex.CONV_DIR = ex.OUT / "conversations"
        buf = io.StringIO()
        with redirect_stdout(buf):
            ex.main()
        return buf.getvalue(), ex.OUT

    def write_session(self, path, records):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(r) for r in records) + "\n")

    @unittest.skipUnless(POSIX, "symlinks")
    def test_a_session_link_leading_outside_is_skipped_and_reported(self):
        secret_elsewhere = self.tmp / "elsewhere.jsonl"
        self.write_session(secret_elsewhere, [dict(r, sessionId="stolen") for r in SESSION])
        self.write_session(self.root / "-p" / "good.jsonl", SESSION)
        (self.root / "-p" / "evil.jsonl").symlink_to(secret_elsewhere)
        out, archive = self.run_extract()
        self.assertEqual(len(list(archive.rglob("*.md"))) - 1, 1)  # one conversation + INDEX.md
        self.assertIn("sources skipped      : 1", out)
        self.assertIn("outside its folder", out)

    def test_a_crafted_timestamp_cannot_steer_the_file_name(self):
        hostile = [dict(r, timestamp="../../../../tmp/pwned" + r["timestamp"]) for r in SESSION]
        self.write_session(self.root / "-p" / "s.jsonl", hostile)
        _, archive = self.run_extract()
        written = [p for p in archive.rglob("*.md") if p.name != "INDEX.md"]
        self.assertEqual(len(written), 1)
        self.assertTrue(written[0].name.startswith("0000-00-00__"), written[0].name)
        self.assertTrue(written[0].resolve().is_relative_to((archive / "conversations").resolve()))

    @unittest.skipUnless(POSIX, "symlinks")
    def test_a_planted_link_in_the_archive_is_replaced_not_followed(self):
        archive = self.tmp / "archive"
        archive.mkdir()
        (archive / "INDEX.md").symlink_to(self.outside)
        self.write_session(self.root / "-p" / "s.jsonl", SESSION)
        self.run_extract()
        self.assertEqual(self.outside.read_text(), "precious, not ours\n")
        self.assertFalse((archive / "INDEX.md").is_symlink())


class SupersededCopyTests(Tmp):
    """A session written under a new name leaves no older copy behind (0.3.0 gate review)."""

    def run_extract(self):
        ex = load("extract_conversations")
        ex.PROJECTS = self.root
        ex.CODEX_SESSIONS = self.tmp / "no-codex"
        ex.OUT = self.tmp / "archive"
        ex.CONV_DIR = ex.OUT / "conversations"
        buf = io.StringIO()
        with redirect_stdout(buf):
            ex.main()
        return buf.getvalue(), ex.OUT

    def session(self, name, sid, text, project="-p"):
        recs = [dict(r, sessionId=sid) for r in SESSION]
        recs[0] = dict(recs[0], message={"role": "user", "content": [{"type": "text", "text": text}]})
        p = self.root / project / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(json.dumps(r) for r in recs) + "\n")

    def md_files(self, archive):
        return sorted(p.name for p in (archive / "conversations").rglob("*.md"))

    def test_an_old_copy_under_another_name_is_removed(self):
        self.session("s.jsonl", "abc-1", "a first question about foxes")
        _, archive = self.run_extract()
        (only,) = self.md_files(archive)
        old = archive / "conversations" / "-p" / "2026-08-06__an-older-name__abc-1.md"
        old.write_bytes((archive / "conversations" / "-p" / only).read_bytes())
        out, _ = self.run_extract()
        self.assertEqual(self.md_files(archive), [only])
        self.assertIn("stale copies removed : 1", out)

    def test_an_older_copy_redacted_differently_is_still_removed(self):
        # the upgrade case: same turns, text masked differently by an older redactor
        self.session("s.jsonl", "abc-1", "a first question about foxes")
        _, archive = self.run_extract()
        (only,) = self.md_files(archive)
        text = (archive / "conversations" / "-p" / only).read_text()
        old = archive / "conversations" / "-p" / "2026-08-06__redacted-0123456789ab__abc-1.md"
        old.write_text(text.replace("foxes", "[an older mask]"))
        out, _ = self.run_extract()
        self.assertEqual(self.md_files(archive), [only])
        self.assertIn("stale copies removed : 1", out)

    def test_a_note_that_shares_an_id_is_never_removed(self):
        # sol, confirm pass: an imported note "foo.txt" has the id note-foo; a source named
        # note-foo.jsonl then gets the same id. Different turns: the note must stay.
        self.session("note-foo.jsonl", "note-foo", "a real session that happens to share the id")
        notes = self.tmp / "archive" / "conversations" / "notes-prehistory"
        notes.mkdir(parents=True)
        note = notes / "2026-01-01__my-note__note-foo.md"
        note.write_text('<!--fab {"sid":"note-foo","project":"notes-prehistory"}-->\n\n# my note\n'
                        "\n<!--t role=user kind=note model=- ts=2026-01-01T00:00:00Z-->\n### note\n\nprecious\n")
        out, _ = self.run_extract()
        self.assertTrue(note.exists())
        self.assertIn("copies kept (differ) : 1", out)

    def test_an_older_copy_with_more_turns_is_never_removed(self):
        # sol, confirm pass: a source that lost turns must not delete the copy that has them
        self.session("s.jsonl", "abc-1", "a first question about foxes")
        _, archive = self.run_extract()
        (only,) = self.md_files(archive)
        longer = (archive / "conversations" / "-p" / only).read_text() + (
            "\n<!--t role=user kind=dialogue model=- ts=2026-08-06T09:05:00Z-->\n### You\n\na turn the source lost\n")
        old = archive / "conversations" / "-p" / "2026-08-06__older__abc-1.md"
        old.write_text(longer)
        out, _ = self.run_extract()
        self.assertTrue(old.exists())
        self.assertIn("copies kept (differ) : 1", out)

    def test_files_of_sessions_not_written_this_run_are_kept(self):
        self.session("s.jsonl", "abc-1", "a first question about foxes")
        _, archive = self.run_extract()
        conv = archive / "conversations" / "notes-prehistory"
        conv.mkdir()
        (conv / "2026-01-01__n__note-x.md").write_text('<!--fab {"sid":"note-x"}-->\n# n\n')
        (conv / "no-metadata.md").write_text("# hand notes\n")
        out, _ = self.run_extract()
        self.assertIn("2026-01-01__n__note-x.md", self.md_files(archive))
        self.assertIn("no-metadata.md", self.md_files(archive))
        self.assertIn("stale copies removed : 0", out)

    @unittest.skipUnless(POSIX, "symlinks")
    def test_a_link_carrying_a_written_id_is_left_alone(self):
        self.session("s.jsonl", "abc-1", "a first question about foxes")
        _, archive = self.run_extract()
        (only,) = self.md_files(archive)
        elsewhere = self.tmp / "elsewhere.md"
        elsewhere.write_bytes((archive / "conversations" / "-p" / only).read_bytes())
        (archive / "conversations" / "-p" / "linked.md").symlink_to(elsewhere)
        self.run_extract()
        self.assertTrue(elsewhere.exists())
        self.assertTrue((archive / "conversations" / "-p" / "linked.md").is_symlink())

    def test_one_session_in_two_sources_is_one_file_and_one_index_row(self):
        # the id is the file name: the same session reached through two folders
        self.session("dup-1.jsonl", "dup-1", "short title one", project="-p")
        self.session("dup-1.jsonl", "dup-1", "a much longer and different title " + "x" * 400, project="-q")
        out, archive = self.run_extract()
        self.assertEqual(len(self.md_files(archive)), 1)
        index = (archive / "INDEX.md").read_text()
        self.assertEqual(index.count("dup-1"), 1)
        self.assertIn("conversations written: 1", out)


@unittest.skipUnless(POSIX, "symlinks")
class ImporterContainmentTests(Tmp):
    def test_an_oversized_note_is_skipped_before_it_is_read(self):
        (self.root / "huge.txt").write_text("x" * 5000)
        mod = load("import_notes", [str(self.root), str(self.tmp / "archive")])
        mod.MAX_BYTES = 1000
        kept, skipped = mod.load_candidates(self.root)
        self.assertEqual(kept, [])
        self.assertIn("too large", skipped[0][1])

    def test_a_note_link_leading_outside_is_refused(self):
        notes = self.root
        (notes / "real.txt").write_text("A real saved conversation. " * 20)
        big_outside = self.tmp / "private.txt"
        big_outside.write_text("Something private elsewhere on the disk. " * 20)
        (notes / "evil.txt").symlink_to(big_outside)
        mod = load("import_notes", [str(notes), str(self.tmp / "archive")])
        kept, skipped = mod.load_candidates(notes)
        self.assertEqual([p.name for p, _, _ in kept], ["real.txt"])
        self.assertEqual(skipped[0][0], "evil.txt")
        self.assertIn("outside its folder", skipped[0][1])


@unittest.skipUnless(POSIX, "symlinks")
class BuilderContainmentTests(Tmp):
    def test_an_empty_build_never_replaces_a_good_db(self):
        import sqlite3
        archive = self.root
        conv = archive / "conversations" / "p"
        conv.mkdir(parents=True)
        fab = {"sid": "s1", "started": "", "ended": "", "n_dialogue": 1, "user_turns": 1,
               "assistant_turns": 0, "n_steps": 0, "project": "p", "models": "", "branch": ""}
        md = conv / "s1.md"
        md.write_text(f"<!--fab {json.dumps(fab)}-->\n# t\n<!--t role=user kind=dialogue model=- ts=- -->\n### U\nhi\n")
        def run():
            return subprocess.run([sys.executable, str(TOOLS / "build_db.py"), str(archive)],
                                  capture_output=True, text=True)
        self.assertEqual(run().returncode, 0)
        md.write_text("no metadata line: nothing here parses\n")
        r = run()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("keeping", r.stderr)
        con = sqlite3.connect(archive / "conversations.db")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM conversations").fetchone()[0], 1)
        con.close()

    def test_a_linked_markdown_file_is_not_built(self):
        archive = self.root
        conv = archive / "conversations" / "p"
        conv.mkdir(parents=True)
        fab = {"sid": "outside", "started": "", "ended": "", "n_dialogue": 1, "user_turns": 1,
               "assistant_turns": 0, "n_steps": 0, "project": "p", "models": "", "branch": ""}
        foreign = self.tmp / "foreign.md"
        foreign.write_text(f"<!--fab {json.dumps(fab)}-->\n# t\n"
                           "<!--t role=user kind=dialogue model=- ts=- -->\n### User\nnot from the archive\n")
        (conv / "linked.md").symlink_to(foreign)
        r = subprocess.run([sys.executable, str(TOOLS / "build_db.py"), str(archive)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("skipped linked.md: a symlink", r.stderr)
        import sqlite3
        con = sqlite3.connect(archive / "conversations.db")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM conversations").fetchone()[0], 0)
        con.close()


@unittest.skipUnless(BASH and POSIX, "needs bash")
class MaskerContainmentTests(Tmp):
    def test_the_masker_never_rewrites_through_a_link(self):
        repo = self.tmp / "tape"
        shutil.copytree(TOOLS, repo / "tools", ignore=shutil.ignore_patterns("__pycache__"))
        archive = repo / "archive"
        (archive / "conversations" / "p").mkdir(parents=True)
        leak = "AKIA" + "Z" * 16
        self.outside.write_text(f"someone else's notes mention {leak}\n")
        (archive / "conversations" / "p" / "evil.md").symlink_to(self.outside)
        (archive / "conversations" / "p" / "real.md").write_text(f"a real leak {leak}\n")
        log = self.tmp / "log"
        lib = f"source <(sed '/^# ---- dispatch/,$d' '{repo / 'tools' / 'tape'}')"
        r = subprocess.run([BASH, "-c", f"{lib}\nREPO='{repo}'; ARCHIVE='{archive}'; LOG='{log}'\nmask_leaks"],
                           capture_output=True, text=True, env={**os.environ, "LC_ALL": "C"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split(), ["1", "1"])
        self.assertIn(leak, self.outside.read_text())
        self.assertTrue((archive / "conversations" / "p" / "evil.md").is_symlink())
        self.assertNotIn(leak, (archive / "conversations" / "p" / "real.md").read_text())
        self.assertIn("WARN skipped", log.read_text())


if __name__ == "__main__":
    unittest.main()
