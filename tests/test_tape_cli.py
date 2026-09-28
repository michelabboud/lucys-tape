#!/usr/bin/env python3
"""End-to-end tests for `tools/tape update` in a throwaway repo.

Each test builds a private copy of the tool in a temporary git repo with a local
bare remote, a fake HOME holding Claude Code session files, and a fake `gh` that
always fails (so no test can ever reach a real GitHub account). Nothing outside
the temporary directory is touched.

Needs bash and git; skipped where either is missing (native Windows runs the
PowerShell edition's own tests).
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASH = shutil.which("bash")
GIT = shutil.which("git")


class TapeRepoCase(unittest.TestCase):
    """A throwaway tape clone with a local remote; the tests live in subclasses."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tape-cli-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = self.tmp / "tape"
        self.remote = self.tmp / "remote.git"
        self.home = self.tmp / "home"
        shutil.copytree(ROOT / "tools", self.repo / "tools",
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(ROOT / ".gitignore", self.repo / ".gitignore")
        fakebin = self.tmp / "bin"
        fakebin.mkdir()
        (fakebin / "gh").write_text("#!/bin/sh\nexit 1\n")
        (fakebin / "gh").chmod(0o755)
        self.env = {
            "HOME": str(self.home), "PATH": f"{fakebin}{os.pathsep}{os.environ['PATH']}",
            "TMPDIR": str(self.tmp), "NO_COLOR": "1", "LC_ALL": "C",
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
        }
        self.git("init", "-q", "--bare", str(self.remote), cwd=self.tmp)
        self.git("init", "-q", "-b", "main")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "tool")
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "-q", "origin", "main")
        self.git("config", "--local", "tape.destination", str(self.remote))
        self.add_session("-home-u-proj", "aaaa-1111", "hello tape")

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.repo, env=self.env,
                              check=True, capture_output=True, text=True).stdout

    def add_session(self, project, sid, text):
        d = self.home / ".claude" / "projects" / project
        d.mkdir(parents=True, exist_ok=True)
        recs = [
            {"type": "user", "sessionId": sid, "timestamp": "2026-09-01T10:00:00Z",
             "cwd": "/home/u/proj", "message": {"role": "user", "content": text}},
            {"type": "assistant", "sessionId": sid, "timestamp": "2026-09-01T10:00:05Z",
             "message": {"role": "assistant", "model": "claude-test",
                         "content": [{"type": "text", "text": "ok"}]}},
        ]
        (d / f"{sid}.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")

    def update(self):
        return subprocess.run([BASH, str(self.repo / "tools" / "tape"), "update"], cwd=self.tmp,
                              env=self.env, capture_output=True, text=True, timeout=300)

    def remote_files(self):
        return set(self.git("--git-dir", str(self.remote), "ls-tree", "-r", "--name-only", "main",
                            cwd=self.tmp).split())



@unittest.skipUnless(BASH and GIT and os.name != "nt", "needs bash and git (POSIX)")
class TapeUpdateTests(TapeRepoCase):
    def test_update_commits_and_pushes_only_the_archive(self):
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        new = self.remote_files() - {p for p in self.remote_files() if p.startswith(("tools/", ".gitignore"))}
        self.assertTrue(new)
        self.assertTrue(all(p in ("archive/INDEX.md", "archive/REDACTION-REPORT.txt") or
                            (p.startswith("archive/conversations/") and p.endswith(".md")) for p in new), new)

    def db_text(self):
        import sqlite3
        con = sqlite3.connect(self.repo / "archive" / "conversations.db")
        rows = con.execute("SELECT * FROM conversations").fetchall() + con.execute("SELECT * FROM turns").fetchall()
        con.close()
        return repr(rows)

    def test_a_suspicious_rebuild_keeps_the_last_good_db(self):
        for i in range(12):
            self.add_session("-home-u-proj", f"keep-{i:04d}", f"conversation {i}")
        self.assertEqual(self.update().returncode, 0)
        before = self.db_text()
        shutil.rmtree(self.home / ".claude" / "projects")
        (self.home / ".claude" / "projects").mkdir()
        for p in (self.repo / "archive" / "conversations").rglob("*.md"):
            p.unlink()
        r = self.update()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("previous DB kept", r.stdout)
        self.assertEqual(self.db_text(), before)
        self.assertFalse(list((self.repo / "archive").glob("conversations.db.*")))

    def test_the_shrink_ratchet_keeps_the_last_good_db(self):
        for i in range(12):
            self.add_session("-home-u-proj", f"keep-{i:04d}", f"conversation {i}")
        self.assertEqual(self.update().returncode, 0)
        before = self.db_text()
        for i in range(8):  # 13 conversations -> 5: less than half, but above the floor
            (self.home / ".claude" / "projects" / "-home-u-proj" / f"keep-{i:04d}.jsonl").unlink()
        for p in (self.repo / "archive" / "conversations").rglob("*keep-000[0-7]*.md"):
            p.unlink()
        r = self.update()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("shrank", r.stdout)
        self.assertEqual(self.db_text(), before)

    def test_a_guard_mask_covers_the_whole_key(self):
        d = self.home / ".claude" / "projects" / "-home-u-proj"
        recs = [{"type": "user", "sessionId": "iiii-9999", "timestamp": "2026-09-01T10:00:00Z", "cwd": "/home/u/proj",
                 "gitBranch": "sk-proj-" + "A" * 20 + "TAILTAILTAILTAIL", "message": {"role": "user", "content": "hi"}},
                {"type": "assistant", "sessionId": "iiii-9999", "timestamp": "2026-09-01T10:00:05Z",
                 "message": {"role": "assistant", "model": "m", "content": [{"type": "text", "text": "ok"}]}}]
        (d / "iiii-9999.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")
        self.update()
        md = next((self.repo / "archive" / "conversations").rglob("*iiii-9999.md")).read_text()
        self.assertNotIn("TAILTAIL", md)
        self.assertNotIn("TAILTAIL", self.db_text())

    def test_leftovers_of_an_interrupted_build_are_cleaned(self):
        self.update()
        a = self.repo / "archive"
        for name in ("conversations.db.next", "conversations.db.next.tmp-123", "conversations.db.tmp-456"):
            (a / name).write_bytes(b"x")
        self.add_session("-home-u-proj", "jjjj-0000", "more")
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(sorted(p.name for p in a.glob("conversations.db*")), ["conversations.db"])
        self.assertNotIn("left uncommitted", r.stdout)

    def remote_blob_text(self):
        return self.git("--git-dir", str(self.remote), "log", "-p", "--all", "--format=%H", cwd=self.tmp)

    def test_secret_in_a_project_name_never_reaches_a_path_or_file(self):
        # LT-SEC-005: a project folder named after a key used to reach INDEX.md and the
        # file path verbatim. The folder is now named by a hash and nothing leaks.
        self.add_session("-home-u-sk-proj-" + "C" * 30, "cccc-3333", "hi")
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        files = self.remote_files()
        self.assertTrue(any(p.startswith("archive/conversations/redacted-") for p in files), files)
        self.assertFalse(any("C" * 20 in p for p in files))
        self.assertNotIn("C" * 20, self.remote_blob_text())
        self.assertNotIn("C" * 20, self.db_text())

    def test_metadata_fields_pass_the_redactor(self):
        d = self.home / ".claude" / "projects" / "-home-u-proj"
        recs = [{"type": "user", "sessionId": "hhhh-8888", "timestamp": "2026-09-01T10:00:00Z", "cwd": "/home/u/proj",
                 "gitBranch": "sk-proj-" + "B" * 30, "message": {"role": "user", "content": "hi"}},
                {"type": "assistant", "sessionId": "hhhh-8888", "timestamp": "2026-09-01T10:00:05Z",
                 "message": {"role": "assistant", "model": "sk-proj-" + "M" * 30,
                             "content": [{"type": "text", "text": "ok"}]}}]
        (d / "hhhh-8888.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("output already clean", r.stdout)  # the redactor got it, not the guard
        for secret in ("B" * 20, "M" * 20):
            self.assertNotIn(secret, self.remote_blob_text())
            self.assertNotIn(secret, self.db_text())

    def test_a_session_id_carrying_a_key_is_not_a_file_name(self):
        self.add_session("-home-u-proj", "sk-proj-" + "S" * 30, "hi")
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(any("S" * 20 in p for p in self.remote_files()))
        self.assertNotIn("S" * 20, self.remote_blob_text())

    def test_the_db_is_built_from_the_masked_markdown(self):
        # A Markdown file with no source (an imported note, a hand edit) is never
        # re-extracted, so only the guard's masker can clean it; the DB must be built
        # from the masked text (LT-SEC-001).
        self.update()
        d = self.repo / "archive" / "conversations" / "-home-u-proj"
        (d / "2026-09-01__hand__hand-1.md").write_text(
            '<!--fab {"sid":"hand-1","project":"-home-u-proj","started":"2026-09-01T00:00:00Z"}-->\n\n# hand\n'
            "\n<!--t role=user kind=note model=- ts=-->\n### note\n\nkey sk-proj-" + "B" * 30 + "\n")
        r = self.update()
        self.assertIn("guard masked", r.stdout)
        self.assertNotIn("B" * 20, self.db_text())

    def test_weekly_backup_and_release_skip_a_failed_refresh(self):
        backups = self.tmp / "backups"
        self.env.update(TAPE_FORCE_DB_DAILY="1", TAPE_BACKUP_DIR=str(backups))
        self.git("config", "--local", "--unset", "tape.destination")  # the push is refused
        r = self.update()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("skipped the weekly backup", r.stdout)
        self.assertFalse(backups.exists() and any(backups.iterdir()))

    def test_everything_the_archive_holds_is_private(self):
        os.chmod(self.repo, 0o755)
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(os.stat(self.repo).st_mode & 0o077, 0)
        for p in [self.repo / "archive", *(self.repo / "archive").rglob("*")]:
            with self.subTest(p=p.name):
                self.assertEqual(p.stat().st_mode & 0o077, 0, oct(p.stat().st_mode))

    def test_an_existing_loose_install_is_hardened(self):
        self.update()
        loose = next((self.repo / "archive" / "conversations").rglob("*.md"))
        os.chmod(loose, 0o644)
        self.add_session("-home-u-proj", "kkkk-1111", "more")
        self.update()
        self.assertEqual(loose.stat().st_mode & 0o077, 0)

    def test_the_lock_is_private_and_not_in_tmp(self):
        self.update()
        rundir = self.home / ".cache" / "lucys-tape"
        self.assertTrue(rundir.is_dir())
        self.assertEqual(rundir.stat().st_mode & 0o077, 0)
        self.assertFalse(list(self.tmp.glob("lucys-tape-refresh*")))

    def test_a_lock_that_is_not_ours_is_a_visible_failure(self):
        self.update()
        rundir = self.home / ".cache" / "lucys-tape"
        elsewhere = self.tmp / "planted"
        elsewhere.mkdir()
        lock_id = subprocess.run(["sh", "-c", f"printf %s '{self.repo}' | cksum | cut -d' ' -f1"],
                                 capture_output=True, text=True).stdout.strip()
        (rundir / f"refresh-{lock_id}.lock.d").symlink_to(elsewhere)
        r = self.update()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not ours", r.stdout)

    def lockdir(self):
        lock_id = subprocess.run(["sh", "-c", f"printf %s '{self.repo}' | cksum | cut -d' ' -f1"],
                                 capture_output=True, text=True).stdout.strip()
        d = self.home / ".cache" / "lucys-tape" / f"refresh-{lock_id}.lock.d"
        d.parent.mkdir(parents=True, exist_ok=True)
        return d

    def start_of(self, pid):
        return " ".join(subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)],
                                       capture_output=True, text=True).stdout.split())

    def test_a_reused_pid_does_not_hold_the_lock(self):
        # a live process (this test) that did not start when the lock says it did
        d = self.lockdir()
        d.mkdir()
        (d / "owner").write_text(f"{os.getpid()} Thu Jan  1 00:00:00 1970\n")
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("already running", r.stdout)

    def test_a_live_owner_holds_the_lock(self):
        sleeper = subprocess.Popen(["sleep", "30"])
        self.addCleanup(sleeper.kill)
        d = self.lockdir()
        d.mkdir()
        (d / "owner").write_text(f"{sleeper.pid} {self.start_of(sleeper.pid)}\n")
        r = self.update()
        self.assertIn("already running", r.stdout)

    def test_a_lock_without_an_owner_waits_then_is_reclaimed(self):
        d = self.lockdir()
        d.mkdir()
        self.assertIn("already running", self.update().stdout)  # fresh: could be starting up
        old = time.time() - 7 * 3600
        os.utime(d, (old, old))
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("reclaimed a stale refresh lock", (self.repo / "archive" / "refresh.log").read_text())

    def test_backup_rotation_touches_only_its_own_files(self):
        backups = self.tmp / "backups"
        backups.mkdir()
        keep_me = backups / "-rf"
        keep_me.write_text("planted")
        target = self.tmp / "victim.txt"
        target.write_text("must survive")
        (backups / "lucys-tape-archive-2000-01-01.tar.gz").symlink_to(target)
        (backups / "lucys-tape-archive-2000-01-02.tar.gz").mkdir()
        for day in ("01", "02", "03"):
            (backups / f"lucys-tape-archive-2001-01-{day}.tar.gz").write_bytes(b"old")
        (self.repo / "README.md").write_text("readme\n")
        self.update()
        self.env.update(TAPE_BACKUP_DIR=str(backups), TAPE_KEEP_BACKUPS="2")
        r = subprocess.run([BASH, str(self.repo / "tools" / "tape"), "backup"], cwd=self.tmp, env=self.env,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        names = sorted(p.name for p in backups.iterdir())
        self.assertIn("-rf", names)
        self.assertTrue(target.exists())
        self.assertIn("lucys-tape-archive-2000-01-01.tar.gz", names)  # a symlink: not ours to rotate
        self.assertIn("lucys-tape-archive-2000-01-02.tar.gz", names)  # a directory: same
        dated = [n for n in names if n.startswith("lucys-tape-archive-20") and (backups / n).is_file()
                 and not (backups / n).is_symlink()]
        self.assertEqual(len(dated), 2, names)
        for n in dated:  # kept backups are private, including ones made before 0.2.17
            self.assertEqual(os.stat(backups / n).st_mode & 0o077, 0)

    def test_low_disk_refusal_stops_the_update(self):
        self.env["TAPE_MIN_FREE_GB"] = "999999999"
        head = self.git("rev-parse", "HEAD")
        r = self.update()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("refusing to run", r.stdout)
        self.assertNotIn("extracting", r.stdout)
        self.assertEqual(self.git("rev-parse", "HEAD"), head)

    def test_work_already_staged_stays_staged_and_is_not_committed(self):
        (self.repo / "notes.txt").write_text("my own work in progress\n")
        self.git("add", "notes.txt")
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("notes.txt", self.remote_files())
        self.assertEqual(self.git("diff", "--cached", "--name-only").split(), ["notes.txt"])
        self.assertEqual(self.git("status", "--porcelain", "--", "archive/"), "")

    def test_a_commit_hook_cannot_add_files(self):
        hook = self.repo / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\necho leaked > secret-notes.txt\ngit add secret-notes.txt\n")
        hook.chmod(0o755)
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("secret-notes.txt", self.remote_files())

    def test_a_stray_file_under_archive_is_skipped_not_fatal(self):
        self.update()
        (self.repo / "archive" / "my-notes.txt").write_text("private\n")
        self.add_session("-home-u-proj", "dddd-4444", "second")
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("left uncommitted", r.stdout)
        self.assertNotIn("archive/my-notes.txt", self.remote_files())
        self.assertTrue(any("dddd-4444" in p for p in self.remote_files()))

    def test_a_file_name_with_a_newline_is_left_uncommitted(self):
        self.update()
        d = self.repo / "archive" / "conversations" / "-home-u-proj"
        (d / "note.md\n").write_text("harmless\n")
        self.add_session("-home-u-proj", "eeee-5555", "more")
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("left uncommitted", r.stdout)
        self.assertFalse(any("\n" in p for p in self.git(
            "--git-dir", str(self.remote), "ls-tree", "-r", "-z", "--name-only", "main", cwd=self.tmp).split("\0")))

    def test_the_gate_scans_the_committed_bytes(self):
        # Call the gate directly on a private index holding a key under an allowed name,
        # so neither the redactor nor the working-tree backstop is involved.
        self.update()
        f = self.repo / "archive" / "conversations" / "-home-u-proj" / "x.md"
        f.write_text("key sk-proj-" + "D" * 30 + "\n")
        src = (self.repo / "tools" / "tape").read_text()
        gate = src[src.index("archive_gate() {"):src.index("\nPY\n}\n", src.index("archive_gate() {")) + 6]
        rx = src.split("LEAK_RX='", 1)[1].split("'\n", 1)[0]
        script = (f"{gate}\nexport GIT_INDEX_FILE=\"$1\"\ngit read-tree HEAD && git add -A -- archive/ && archive_gate")
        env = {**self.env, "LEAK_RX": rx, "LOG": str(self.tmp / "gate.log")}
        r = subprocess.run([BASH, "-c", script, "gate", str(self.tmp / "idx")], cwd=self.repo, env=env,
                           capture_output=True, text=True)
        self.assertEqual(r.stdout.split()[0], "1", r.stdout + r.stderr)
        self.assertIn("staged content of archive/conversations/-home-u-proj/x.md", (self.tmp / "gate.log").read_text())

    def test_a_stray_named_like_a_wildcard_does_not_unstage_the_archive(self):
        self.update()
        (self.repo / "archive" / "*").write_text("stray\n")
        self.add_session("-home-u-proj", "ffff-6666", "wild")
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(any("ffff-6666" in p for p in self.remote_files()))
        self.assertNotIn("archive/*", self.remote_files())

    def test_staged_work_under_archive_is_not_dropped(self):
        self.update()
        (self.repo / "archive" / "my-notes.txt").write_text("mine\n")
        self.git("add", "archive/my-notes.txt")
        self.add_session("-home-u-proj", "gggg-7777", "again")
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("archive/my-notes.txt", self.git("diff", "--cached", "--name-only"))
        self.assertNotIn("archive/my-notes.txt", self.remote_files())

    def test_unstaged_work_outside_the_archive_is_left_alone(self):
        (self.repo / "notes.txt").write_text("untracked scratch\n")
        with open(self.repo / "tools" / "tape", "a") as f:
            f.write("# local edit\n")
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("notes.txt", self.remote_files())
        status = self.git("status", "--porcelain")
        self.assertIn("?? notes.txt", status)
        self.assertIn(" M tools/tape", status)


def tape_library(repo):
    """Bash that defines every function in tools/tape without running a command:
    the script up to its dispatch section, exactly as it ships."""
    return f"source <(sed '/^# ---- dispatch/,$d' '{repo / 'tools' / 'tape'}')"


@unittest.skipUnless(BASH and GIT and os.name != "nt", "needs bash and git (POSIX)")
class DestinationTests(TapeRepoCase):
    """LT-SEC-004: the archive goes to one trusted private destination, or nowhere."""

    def remote_commits(self):
        return int(self.git("--git-dir", str(self.remote), "rev-list", "--count", "main", cwd=self.tmp))

    def assert_not_pushed(self, r, reason):
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not pushed", r.stdout)
        self.assertIn(reason, r.stdout)
        self.assertEqual(self.remote_commits(), 1)

    def test_no_recorded_destination_means_no_push(self):
        self.git("config", "--local", "--unset", "tape.destination")
        r = self.update()
        self.assert_not_pushed(r, "tape trust")
        self.assertEqual(self.git("log", "-1", "--format=%s").split()[0], "chore:")  # kept locally

    def test_a_changed_push_url_is_refused(self):
        other = self.tmp / "other.git"
        self.git("init", "-q", "--bare", str(other), cwd=self.tmp)
        self.git("remote", "set-url", "--push", "origin", str(other))
        self.assert_not_pushed(self.update(), "not the trusted")
        self.assertEqual(self.git("--git-dir", str(other), "rev-list", "--all", cwd=self.tmp), "")

    def test_an_insteadof_rewrite_is_seen(self):
        other = self.tmp / "other.git"
        self.git("init", "-q", "--bare", str(other), cwd=self.tmp)
        self.git("config", "--local", f"url.{other}.pushInsteadOf", str(self.remote))
        self.assert_not_pushed(self.update(), "not the trusted")

    def test_two_push_urls_are_refused(self):
        self.git("remote", "set-url", "--add", "--push", "origin", str(self.remote))
        self.git("remote", "set-url", "--add", "--push", "origin", str(self.tmp / "x.git"))
        self.assert_not_pushed(self.update(), "exactly one")

    def test_credentials_in_urls_are_never_printed(self):
        url = "https://user:s3cr3t-t0ken@example.invalid/me/private.git"
        self.git("remote", "set-url", "--push", "origin", url)
        r = self.update()
        self.assertNotIn("s3cr3t-t0ken", r.stdout + r.stderr)
        self.assertNotIn("s3cr3t-t0ken", (self.repo / "archive" / "refresh.log").read_text())
        self.assertIn("***@example.invalid", r.stdout)

    # --- releases: run the functions alone with a scripted gh ------------------
    def run_release(self, dest, visibility):
        calls = self.tmp / "gh-calls.txt"
        gh = self.tmp / "bin" / "gh"
        gh.write_text(f"""#!/bin/sh
echo "$@" >> {calls}
case "$1 $2" in
  "auth status") exit 0 ;;
  "repo view") echo {visibility} ; exit 0 ;;
  "release view") exit 1 ;;
  "release create") exit 0 ;;
esac
exit 1
""")
        self.git("remote", "set-url", "origin", dest)
        self.git("config", "--local", "tape.destination", dest)
        (self.repo / "archive").mkdir(exist_ok=True)
        db = self.repo / "archive" / "conversations.db"
        db.write_bytes(b"x")
        script = (f"{tape_library(self.repo)}\nARCHIVE='{self.repo / 'archive'}'; DB='{db}'; LOG=/dev/null\n"
                  "ok(){ echo \"ok $*\"; }; warn(){ echo \"warn $*\"; }; bad(){ echo \"bad $*\"; }; log(){ :; }\n"
                  "_publish_db_snapshot")
        r = subprocess.run([BASH, "-c", script], cwd=self.repo, env=self.env, capture_output=True, text=True)
        return r, (calls.read_text() if calls.exists() else "")

    def test_release_goes_only_to_a_repo_github_confirms_private(self):
        r, calls = self.run_release("git@github.com:me/my-archive.git", "PRIVATE")
        self.assertIn("release create", calls, r.stdout + r.stderr)
        for line in calls.splitlines():
            if line.startswith("release"):
                self.assertIn("--repo github.com/me/my-archive", line)

    def test_release_refused_when_github_says_public(self):
        r, calls = self.run_release("git@github.com:me/my-archive.git", "PUBLIC")
        self.assertNotIn("release create", calls)
        self.assertIn("PUBLIC", r.stdout)

    def test_release_refused_when_visibility_is_unknown(self):
        r, calls = self.run_release("https://github.com/me/my-archive", "")
        self.assertNotIn("release create", calls)

    def test_release_never_targets_the_public_upstream(self):
        r, calls = self.run_release("https://github.com/michelabboud/lucys-tape.git", "PRIVATE")
        self.assertNotIn("release create", calls)
        self.assertIn("PUBLIC lucys-tape", r.stdout)


    # --- address parsing ---------------------------------------------------------
    def call(self, fn, arg):
        script = f"{tape_library(self.repo)}\n{fn} \"$1\"; echo \" rc=$?\""
        return subprocess.run([BASH, "-c", script, "x", arg], env=self.env, capture_output=True,
                              text=True).stdout

    def test_github_addresses_in_every_usual_form(self):
        for url in ("https://github.com/me/r", "https://github.com/me/r/", "https://github.com/me/r.git/",
                    "https://GitHub.com/Me/R", "https://www.github.com/me/r", "git@github.com:me/r.git",
                    "ssh://git@github.com:22/me/r.git", "ssh://git@ssh.github.com:443/me/r.git",
                    "github.com:me/r", "https://user:tok@github.com/me/r.git"):
            with self.subTest(url=url):
                self.assertEqual(self.call("github_slug", url).split(" rc=")[0], "me/r")

    def test_github_address_without_a_plain_owner_and_name_is_invalid(self):
        for url in ("https://github.com/../..", "https://github.com/me/x/../../michelabboud/lucys-tape",
                    "https://github.com/me", "https://github.com/me/r/extra"):
            with self.subTest(url=url):
                self.assertEqual(self.call("github_slug", url).split(" rc=")[0], "INVALID")

    def test_other_hosts_have_no_slug(self):
        self.assertEqual(self.call("github_slug", "https://gitlab.com/me/r.git").split(" rc=")[0], "")

    def test_the_public_upstream_is_recognised_in_any_case(self):
        for url in ("https://github.com/MichelAbboud/Lucys-Tape.git", "git@github.com:michelabboud/lucys-tape",
                    "https://www.github.com/michelabboud/lucys-tape/"):
            with self.subTest(url=url):
                self.assertIn("rc=0", self.call("is_public_upstream", url))
        self.assertIn("rc=1", self.call("is_public_upstream", "git@github.com:me/my-lucys-tape.git"))

    def test_safe_url_masks_every_credential_shape(self):
        for url, secret in (("https://u:p@ss@host/x", "p@ss"), ("https://host/x?access_token=abc123", "abc123"),
                            ("http://t0k3n@host/x", "t0k3n")):
            with self.subTest(url=url):
                self.assertNotIn(secret, self.call("safe_url", url))

    def test_an_unparseable_github_destination_is_refused(self):
        dest = "https://github.com/me/x/../../michelabboud/lucys-tape"
        self.git("remote", "set-url", "origin", dest)
        self.git("config", "--local", "tape.destination", dest)
        r = self.update()
        self.assertIn("not pushed", r.stdout)
        self.assertIn("plain owner/name", r.stdout)


if __name__ == "__main__":
    unittest.main()
