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

    def test_secret_in_a_project_name_is_never_committed(self):
        # A project folder named after a key reaches INDEX.md and the file path, which
        # the Markdown masker does not cover (LT-SEC-005). The staged-content check must
        # refuse the whole commit rather than push it.
        self.add_session("-home-u-sk-proj-" + "C" * 30, "cccc-3333", "hi")
        head = self.git("rev-parse", "HEAD")
        r = self.update()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("nothing committed", r.stdout)
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "")
        log = (self.repo / "archive" / "refresh.log").read_text()
        self.assertNotIn("C" * 30, log)


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
