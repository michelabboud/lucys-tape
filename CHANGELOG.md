# Changelog

## v0.3.0 — 2026-09-29 · safe to use

The first phase of the 2026-09-28 plan: every finding of the July security audit
(`docs/reports/2026-07-16-fable-codex-security-bughunt.md`, 4 High, 10 Medium, 1 Low) is fixed
in code, each with a regression test that fails on the code before it. The entries 0.2.3 to
0.2.25 below are the per-task steps; this is what they add up to.

- **Secrets:** the redactor catches headless and DER private keys and the audit's blind spots;
  the leak guard stays a strict subset; the database, backups and release snapshots are built
  only from the masked Markdown; backups hold no database and no logs.
- **Where your archive goes:** only `archive/` output is committed, and the exact staged bytes
  are scanned first; pushes and releases go to the one destination you trusted, and a GitHub
  push needs GitHub to confirm the repo is PRIVATE.
- **The viewer:** answers only its own address and only a browser holding this launch's
  session; every value escaped; inputs and connections bounded.
- **Files:** private permissions; a private lock; sources read only inside their folders;
  archive writes that never follow a link; names that carry a secret shape renamed.
- Tests: 101 → 265.

Release gate: two blind reviews (Claude Fable 5.1: pass; gpt-5.6-sol: blocked), then three
rounds of fixes (0.2.23–0.2.25), each confirmed. Accepted limits are in `SECURITY.md`; the
first is the next task.

## v0.2.25 — 2026-09-29 · rename, never delete; every spelling of GitHub checked

Fixes from the second confirm pass (gpt-5.6-sol, on 0.2.24).

### Fixed

- **0.2.24's cleanup could still lose data.** Matching turn markers do not prove matching text:
  a copy with different text under the same timestamps was deleted. The cleanup is gone. The
  problem it was meant to solve was a file an older version named with a secret shape, which
  the commit gate refused on every run once masking touched it. Such a file or folder is now
  **renamed** to `redacted-<hash>`, content moved byte for byte, never overwriting anything;
  nothing in the archive is deleted. On a real machine's archive this renamed nothing (5,576
  files, twice). Copies of one session under two names stay, as before 0.2.23 (BACKLOG); the
  index and the count list each session once.
- The commit gate refused the removal of a path whose name matches the leak guard. Removing
  a name takes it out of the tree the commit writes, so a removal now passes; a name being
  added or kept is still refused.

### Security

- **LT-SEC-004: `github.com.` (with the trailing dot of a fully qualified name) was not
  recognised as GitHub**, so its pushes skipped the privacy check. The host is now read from
  any address spelling and normalised (case, trailing dots). A host that mentions GitHub
  without being github.com (a look-alike, or your own GitHub Enterprise server) is refused
  unless you accept that exact destination with `tape trust --without-gh`.
- `SECURITY.md` now lists the limits accepted for v0.3.0, as the 0.2.23 entry promised.

## v0.2.24 — 2026-09-29 · the confirm pass: cleanup that cannot lose data, pushes that need proof

Fixes from the second reviewer's confirm pass on 0.2.23 (gpt-5.6-sol blocked; Fable passed).

### Fixed

- **0.2.23's stale-copy cleanup could delete archive content.** It removed every other file
  carrying a session id it had just written. An imported note `foo.txt` (id `note-foo`) was
  deleted when a source named `note-foo.jsonl` appeared, and an older copy holding turns the
  new file lacked was deleted too. A copy is now removed only when its turns (role, kind,
  timestamp) are exactly the first turns of the new file; the text may differ, which is the
  upgrade case (an older redactor masked differently). Every other copy is kept and counted
  ("copies kept (differ)"). 0.2.23 was never released; no user ran it.

### Security

- **LT-SEC-004: a push to GitHub now needs GitHub to confirm the repo is PRIVATE.** Before,
  a push went ahead when `gh` was missing or signed out, relying on the `private` you typed at
  `tape trust`: intent, not proof. The commit is still made locally; only the push waits.
  INTERNAL is refused like PUBLIC. Without `gh`, `tape trust --without-gh` accepts an
  unverified push for that one destination; it never overrides a PUBLIC answer and does not
  carry over to another destination.

### Recorded

- The viewer's cookie reaching other 127.0.0.1 ports stays open for v0.3.0 (SECURITY.md) and
  is the next task. gpt-5.6-sol argued it should block the release; Fable accepted it as
  non-blocking. Ruling: v0.2.2 has no viewer authentication at all, so holding back a
  strictly safer release would leave users on the weaker one.

## v0.2.23 — 2026-09-29 · fixes from the Phase 1 release-gate review

The release gate had two blind reviews: Claude Fable 5.1 (pass, six should-fixes) and
gpt-5.6-sol (blocked, five blockers). Every claim was checked against the code before it was
acted on; this release fixes the confirmed ones.

### Fixed

- **The write protection of 0.2.21 never ran on Linux.** It checked `os.replace` for
  folder-descriptor support, which Python never lists (it lists `os.rename`, which shares the
  call). Every write took the fallback meant for Windows: it refused linked folders too, but
  with a check-then-write race. The descriptor walk now runs on Linux and macOS, and a test
  fails if it is ever unavailable there. Neither review caught this; a new test did.
- **Upgrading could leave an old copy of a conversation for ever**, and, when the old file
  name carried a credential shape that newer masking touched, stop every nightly at the
  commit gate. The extractor now removes an older copy of any session it has just written
  under another name. Only sessions written in that same run are reconciled; imported notes
  and conversations whose source is gone are never touched, and git history keeps the old
  copy. On a real machine's sources this removed nothing (5,571 files before and after).
- A session found in two source folders is now one file and one `INDEX.md` row. The
  "conversations written" count is now the number of conversations, not of writes (it
  counted 17 rewrites twice on the machine above).
- **A long run of digits could stall the nightly.** One redactor rule retried from every digit
  (200,000 digits took 22 seconds in one turn); it is now linear.
- **A Markdown file that is not UTF-8 stopped every nightly** until edited by hand: the masker
  skipped it and the byte-level backstop then refused the commit. It is now masked and
  written back byte for byte.
- A symlink loop in the sources crashed the extractor on Python before 3.13; it is now a
  reported, skipped source.
- `tape build` no longer replaces a database holding conversations with an empty one.

### Security

- **LT-SEC-001, two side doors closed.** `tape serve` masked nothing before building a missing
  database; it now runs the leak guard first, like `update` and `build`. `tape backup` masked
  the Markdown but packed whatever database was on disk, possibly one an older version built
  before masking existed. Backups now hold the masked Markdown and no database (`tape build`
  recreates it after a restore) and no logs (`viewer.log` holds the viewer's keyed link).
- **Links planted in `archive/`.** `tape` refuses to run when `archive/`, its logs, the database
  or the release snapshot path is a symlink, before anything is written; a backup refuses a
  linked target; `safe_paths` refuses a linked archive root.
- **LT-SEC-013:** printed URLs lose their control characters, so a remote URL cannot carry an
  escape sequence to your terminal.

### Accepted, with the reasoning (not fixed in this release)

- ~~With no `gh` signed in, a push is not checked against GitHub's visibility.~~ Reversed in
  0.2.24 after the confirm pass: such pushes are now refused unless accepted per destination.
- **The viewer's cookie reaches other services on 127.0.0.1**, because browsers do not
  separate cookies by port. A service run by another account on the same machine, which you
  then visit in the same browser, could replay it. Anything running as you can already read
  the archive. It is the first task after this release: a per-request capability that is not
  sent to other ports.
- The viewer loads a whole conversation into one page; an enormous conversation is slow to
  open. This is your own data behind your own session; recorded in BACKLOG.

## v0.2.22 — 2026-09-28 · containment, after its review

Fixes from the deep review of 0.2.21 (and the confirm pass on 0.2.20).

### Fixed

- **A run killed mid-write could stop every later refresh.** 0.2.21 named its temporary files
  `.<name>.<pid>.tmp`; when a later run reused that process id, creating the file failed every
  night. The names are now random. A leftover file is excluded from the weekly backup and never
  committed; it stays until you remove it.
- Two writers creating the same folder at once (the notes importer runs outside the refresh
  lock) no longer crash the second one.
- The notes importer checks a file's size before reading it, and skips a capture larger than
  50 MB instead of loading it into memory.

### Security

- A connection that has not shown the session cookie now gets 5 seconds, not 30. A local
  process can still occupy the viewer's 16 slots by reconnecting, but it has to keep doing so
  every 5 seconds; that is accepted as local denial of service, not a data exposure.
- The redirect after the key also strips a leading backslash (`/\host` means `//host` to
  browsers). It needs the key, so this was not exploitable.

### Notes

- A hard link inside a source folder, or a folder swapped mid-run by one of your own processes,
  can still point a read elsewhere; only your own account can do either, and the result lands in
  your private, redacted archive. Accepted.

## v0.2.21 — 2026-09-28 · every file stays in its folder

### Security

- **LT-SEC-009: reads and writes could leave their folders.**
  - A crafted timestamp became part of a file name, so `../` in it could place a
    conversation outside the archive. A file name's date must now be a date
    (`0000-00-00` otherwise).
  - A session or note is read only when it resolves to a regular file inside its source
    folder. Claude Code's links between subagent sessions still work; a link that leads
    outside, a FIFO or a folder is refused and listed with the skipped sources. The check
    is made on the opened file, so it cannot be swapped between check and read, and a
    note's size and date come from that same open.
  - Every archive file (conversations, `INDEX.md`, `REDACTION-REPORT.txt`, imported notes,
    the leak guard's rewrites) is written as a new private file next to the target and
    renamed over it. A link planted at the target is replaced, never written through; a
    linked folder on the way is refused; a crash leaves the old file or the new one.
  - The database builder and the leak guard refuse symlinks in the archive (the tools
    never create one), and the builder reads each file once. Its temporary database is a
    fresh file of its own, not a predictable name.
- Measured on a real machine's sources: 6,383 sessions scanned and 5,580 conversations
  written, identical to 0.2.20; the only files that differed were two sessions still being
  written during the comparison.

### Notes

- Windows has no folder-descriptor calls in Python, so there the folders on the way are
  checked just before writing instead. Phase 2 revisits it.
- A write interrupted by a crash can leave a hidden `.<name>.<pid>.tmp` beside its target;
  git ignores these, and the commit gate never stages them.

## v0.2.20 — 2026-09-28 · the viewer, after its review

Fixes from the deep review of 0.2.19.

### Fixed

- **A cookie from another local web server could lock you out of the viewer.** Browsers send
  every `127.0.0.1` cookie to every port, and Python's cookie parser gave up on the whole header
  at the first cookie it could not read. The viewer now reads its own cookie by hand, and the
  cookie name carries the port (`lt_session_8124`), so two viewers no longer overwrite each
  other's session.
- **Notes with non-English names were left out of the database.** 0.2.19's id schema accepted
  ASCII only; a note named `Café` has the id `note-café-…`. Ids may now hold letters of any
  script. Pages escape and URL-encode them as before.
- **A non-ASCII key or cookie raised an error** instead of a plain refusal.
- **16 slow connections could shut everyone out of the viewer.** The 30-second limit applied
  to each read, so a client sending a byte every 29 seconds held its slot for ever. The limit
  now covers the whole connection.
- A client hanging up no longer writes a traceback into `viewer.log`.

### Security

- The redactor removes the viewer's key from a printed `tape serve` link
  (`127.0.0.1:<port>/?key=…`), so a session that ran `tape serve` does not archive it.
- The redirect after the key always stays on the viewer's own address. (The request parser
  already turned `//host/path` into a path, so this was not reachable; it is defence in depth.)

### Notes

- The key stays valid for the whole launch, and the keyed link stays in browser history until
  the viewer stops. Anyone who can read your browser history on this account can already read
  the archive.

## v0.2.19 — 2026-09-28 · the viewer answers only you

### Security

- **LT-SEC-007: any web page could read the archive through the viewer.** It answered every
  request on `127.0.0.1:8124`, so a page in your browser (with DNS rebinding) or any other local
  program could fetch every conversation. The viewer now answers only when the `Host` header is
  its own loopback address, and only to a browser holding this launch's session cookie. The
  cookie is set when you open the keyed link `tape serve` prints (the key is new on every launch
  and is written only to the owner-only `viewer.log`). The cookie is `HttpOnly` and
  `SameSite=Strict`. A wrong or old key gets a plain refusal.
- **LT-SEC-008: archive metadata reached the page unescaped.** Session ids, timestamps and
  counts are now escaped at every output, ids are URL-encoded in links, and the builder stores
  only metadata that meets a strict schema: ids of `[A-Za-z0-9._:-]` up to 128 characters (else
  the file name, else the file is skipped), ISO-8601 timestamps, non-negative integer counts,
  bounded text fields. The build reports how many values it dropped. All 13,748 files of a real
  archive pass unchanged.
- **LT-SEC-010: unbounded input and concurrency.** Searches longer than 500 characters are
  refused, at most 16 requests are served at once (extra connections are closed), and a
  request that stalls for 30 seconds is dropped. Pages also send `Cache-Control: no-store`
  and `frame-ancestors 'none'`.

### Changed

- Bookmarks to `http://127.0.0.1:8124` stop working: open the link `tape serve` prints
  (`tape serve` again shows it while the viewer runs).

### Fixed

- Five lint errors in the tests (one introduced in 0.2.16).

## v0.2.18 — 2026-09-28 · a lock that survives a reboot cannot outlive its owner

### Fixed

- **A reused process ID could stop every refresh.** Since 0.2.17 the lock lives in a folder that
  survives reboots; after a crash, its recorded PID could belong to an unrelated live process,
  and every nightly would exit quietly as "already running". The lock now records the owner's
  PID and start time and counts as held only while both still match; a lock with no readable
  owner (killed while being taken) is reclaimed after 6 hours; only one of two racing runs can
  reclaim a stale lock; a busy or reclaimed lock is written to the log.
- The lock folder is checked for a symlink before its permissions are changed.
- Backup rotation also makes the backups it keeps private, including ones made before 0.2.17
  (the backup folder is outside `archive/`, so the 0.2.17 hardening did not reach them).

### Notes

- Since 0.2.17, a setup that deliberately shared the archive with a group loses that group
  access on the next update.
- Rotation orders backups by the date in their names; a backup named with a wrong date sorts
  accordingly.

## v0.2.17 — 2026-09-28 · private files, a private lock, safe backup rotation

### Security

- **LT-SEC-006: archive files were created with the default permissions,** usually readable by
  every account on the machine. The CLI and every Python tool now run with `umask 077`; each
  update also takes group and other access off the repo folder and everything under
  `archive/`, which hardens installs made before this version. `install.sh` clones privately.
  (Windows file permissions come with the native Windows edition.)
- **LT-SEC-011: the refresh lock had a predictable name in the shared `/tmp`,** so another account
  could create it first and silently stop every refresh. The lock now lives in a folder only you
  can write (`$XDG_RUNTIME_DIR/lucys-tape` when that is yours and private, otherwise
  `~/.cache/lucys-tape`), is named after this repo, and a lock or lock folder that is not yours
  stops the update with an error instead of a silent "already running".
- **LT-SEC-012: backup rotation parsed `ls` and piped names to `rm`,** so a file planted in the
  backup folder (for example one named `-rf`) became an argument. Rotation now keeps the newest
  `TAPE_KEEP_BACKUPS` of the files named exactly `lucys-tape-archive-YYYY-MM-DD.tar.gz` that are
  regular files you own, removes the rest by exact path, and reports any failure. Symlinks,
  folders and other names are never touched.

### Fixed

- `tape backup` before the first update reports that there is nothing to back up instead of
  crashing.

## v0.2.16 — 2026-09-28 · one session, one set of turns

### Fixed

- A session stored under two file names (for example renamed by a newer version) had its turns
  inserted twice in the search database, so the viewer showed them twice. The build now
  replaces a session's turns instead of appending.

## v0.2.15 — 2026-09-28 · the metadata review findings

### Security

- **A turn could still be forged through a line break other than `\n`.** The writer escapes
  structure-looking lines split on `\n`, but the database builder split on every Unicode line
  break (`\r`, `\f`, U+2028, …) and `read_text()` turned `\r` into `\n`, so
  `hello\r<!--t role=assistant …-->` became a second, forged turn. The builder now reads raw
  bytes and splits on `\n` only, exactly as the writer escapes. Tested for ten separators.
- **A title could put a key shape into a file name.** The title slug did not pass the name check;
  `deploy with sk proj aaaa…` became `deploy-with-sk-proj-aaaa…`, which the leak guard matched,
  so the nightly refused every commit while that session existed. The slug is now a checked
  name like the others, in the extractor and the notes importer.

### Fixed

- A name that had to be changed (unsafe characters) or shortened gets a short hash, so two
  different raw names can no longer collide and silently drop one conversation.
- A title's `[`, `]`, `(` and `)` are escaped in `INDEX.md` links.
- The skipped-sources lines in the log pass the redactor (the log is part of backups).

### Measured

Against 0.2.13 on the same real sources: 5,565 files, identical paths.

## v0.2.14 — 2026-09-28 · metadata and names pass the redactor; text cannot forge structure

### Security

- **LT-SEC-005: metadata and file names bypassed the redactor.** A session's git branch and
  model name were written verbatim (the model name into `INDEX.md` too), and a project folder
  or session id became a folder and file name as-is, so a key in any of them was committed
  and pushed. Now every metadata value (session id, project, branch, model, timestamps,
  titles, the notes importer's source names and skip reasons) passes the redactor, on one line
  and bounded. A folder or file name that redaction would change is replaced by a stable hash
  (`redacted-<hash>`), so a secret can never become a path; any other name keeps its exact
  spelling, and only characters no filesystem accepts are replaced. The notes importer no
  longer writes the absolute path of your notes folder.
- **LT-SEC-014: conversation text could forge turns.** A line in a message that looked like the
  archive's turn marker (`<!--t role=… -->`) was read back by the database builder as a new
  turn, able to change who said what. Such lines, and lines that look like the metadata or
  the escape itself, are now escaped when written (`<!--esc-->` prefix) and unescaped when the
  database is built; turn markers only accept known roles and kinds, and a model or timestamp
  value cannot close the marker early. Existing archives rebuild unchanged.

### Measured

Old and new extractors run over the same real sources (5,564 files): identical file paths, and
identical content except for sessions still being written during the comparison.

## v0.2.13 — 2026-09-28 · the DB-order review findings

### Security

- **A refused refresh no longer feeds the weekly backup or release.** When the commit or its
  checks failed, the Sunday (or `TAPE_FORCE_DB_DAILY`) backup and release snapshot still ran and
  could carry what the check had refused; they are now skipped.
- **The leak guard masks every file the archive publishes:** `INDEX.md` and the redaction report
  as well as the conversations, and its backstop check covers them too.
- **A guard mask covers the whole key.** The guard's pattern names a key's first characters (for
  example 20 after `sk-proj-`); masking stopped there and left the rest of the key visible.
- `tape build` and `tape backup` run the same mask-and-verify step before reading the Markdown,
  in case an update was interrupted between extraction and masking.

### Fixed

- Side files of an interrupted DB build are ignored by git and removed at the start of the next
  update, so they neither pile up nor trigger a nightly "left uncommitted" warning.

### Tests

- The shrink ratchet (a rebuild with less than half the conversations) is now tested directly;
  the earlier test only reached the minimum-count floor.

## v0.2.12 — 2026-09-28 · the database is built from the verified Markdown, and never lost

### Security

- **LT-SEC-001: the search database kept secrets the leak guard had masked.** The update built
  `conversations.db` before the masker ran, so anything the guard masked in the Markdown stayed
  searchable in the database, and from there went into durable backups and the weekly release
  snapshot. The update now extracts, masks, verifies, and only then builds the database from
  the final Markdown.
  Shown by a test: a key in a session's git branch name (a field the redactor does not yet
  cover; fixed at the source in a later task) was masked in the Markdown but kept in the database.

### Fixed

- **LT-SEC-015: a failed or suspicious rebuild destroyed the last good database.** It was
  rebuilt in place. `build_db.py` now writes a temporary file and swaps it in atomically, and
  the update builds to a side file, checks the conversation count on it (the sanity floor and
  the shrink ratchet), and only then replaces the database; a refused rebuild keeps the old one.

## v0.2.11 — 2026-09-28 · the destination check's review findings

### Fixed

- **GitHub addresses in common forms were not recognised,** so the "is this repo public?" check
  was silently skipped for them: a trailing `/` or `.git/`, capital letters, `www.` or `ssh.`
  hosts, ssh with a port, scp-style without a user. The parser is now strict and complete; a
  GitHub address that is not a plain `owner/name` (for example one with `..` segments) is
  refused, not skipped.
- **The public upstream was matched case-sensitively** on the raw address; it is now compared
  as a parsed, lower-cased `owner/name`.
- **`GH_HOST` could send the visibility check and the release to another server.** Every `gh`
  call now names `github.com/owner/name`.
- Credential masking covers a password containing `@` and token-like query values.
- `tape status` shows prominently when pushes are refused and how many commits wait locally.

### Documented

- `SECURITY.md`: the trusted destination binds the push address, not your ssh transport
  settings.

### Tests

- Address forms, invalid paths, other hosts, the upstream in any case, masking, and an
  unparseable destination refused. The tests now load the real script (minus its command
  dispatch) instead of cutting functions out of it.

## v0.2.10 — 2026-09-28 · the archive goes to one trusted private repo, or nowhere

> **Upgrading from an earlier version:** run `tape trust` once. Until you do, the nightly still
> extracts and commits, but keeps the commit local and says why.

### Security

- **LT-SEC-004: pushes and releases were not bound to your private repo.** The weekly database
  snapshot called `gh release` without naming a repo, and in a clone of this project `gh` can
  resolve the public upstream; pushes went wherever `origin` pointed that night. Now:
  - `tape init` records the private repo you give it as the one trusted destination
    (`tape.destination` in the clone's local git config); `tape trust` does the same, with
    confirmation, for an existing setup.
  - Before every push, origin's push address, after git applies any `insteadOf` /
    `pushInsteadOf` rewrite, must be exactly one address, equal to the trusted one, and not the
    public upstream; where GitHub can be asked, it must not report the repo as public.
    Otherwise the commit stays local and the update says why.
  - A release is published only on the trusted destination, only after GitHub confirms that
    repo is **private**, and every `gh` call names it with `--repo`.
  - Setup stops if renaming the public remote or adding yours fails, instead of carrying on.
- **LT-SEC-013: credentials in a remote address were printed verbatim.** Any address with a
  user or token in it (`https://user:token@host/…`) is now shown masked in output and logs.

### Fixed

- Setup and `tape doctor` treated any remote whose address contained "lucys-tape" as the public
  repo, so a private repo named, say, `my-lucys-tape` was renamed to `upstream`. They now match
  the public repo's exact address.

### Tests

- 9 new tests: no recorded destination, a changed push URL, a `pushInsteadOf` rewrite, two push
  URLs, masked credentials, and releases against a scripted `gh` (private: published with
  `--repo`; public, unknown or the public upstream: refused). All fail on 0.2.9.

## v0.2.9 — 2026-09-28 · the archive gate's re-review findings

### Fixed

- A stray file literally named `archive/*` was read as a wildcard when the gate unstaged it,
  unstaging the whole archive, so every nightly reported "no changes". Stray paths are now
  literal (`GIT_LITERAL_PATHSPECS=1`).
- After committing, the update refreshes only the files it committed in the user's index; work
  the user staged under `archive/` stays staged (0.2.8 reset all of `archive/`).
- A symlink or gitlink under an allowed name is skipped as a stray, like any other, instead of
  stopping the nightly.
- The temporary index is removed even if the update is killed mid-way.
- An inherited `GIT_DIR`, `GIT_WORK_TREE` or `GIT_INDEX_FILE` can no longer point the update
  at another repository or index.

### Tests

- The newline-in-a-file-name test now checks what the gate does (the file is left
  uncommitted) rather than passing on the working-tree backstop, and a new test runs the gate
  alone on a private index to prove the byte scan itself catches a key.

### Known limits

- User hooks still run where git runs them for any client: `reference-transaction` on the
  branch update and `pre-push` on push. Neither can change the committed tree.
- The archive commit is made with `commit-tree`, which does not sign: a remote that requires
  signed commits will reject the push.

## v0.2.8 — 2026-09-28 · the archive commit is built on a private index

The deep review of 0.2.7 showed that `git commit` still committed whatever the index held
when it ran, after the check: a `pre-commit` hook that ran `git add`, or anything staged during
a long extraction, was pushed.

### Security

- **The archive commit never goes through the user's index or commit hooks.** The update
  builds it in a private temporary index (`read-tree HEAD`, `add -A -- archive/`), checks it,
  and records it with `write-tree`, `commit-tree` and a compare-and-swap `update-ref` that
  refuses if the branch moved meanwhile. Work the user has staged stays staged and is never
  committed; no hook can add a file. The pre-staged refusal from 0.2.7 is no longer needed and
  is gone.
- **The byte scan reads the exact staged objects.** It takes object ids from
  `git diff --cached --raw -z` and streams them through `git cat-file --batch`, instead of
  asking for paths, which a file name ending in a newline could redirect to another file.
  The allow-list is a full match; gitlinks and other non-file entries are refused.
- **A stray file under `archive/` is skipped, not fatal:** it is left uncommitted and reported,
  so one misplaced file no longer stops every nightly run.

### Measured

10,000 staged files (157 MB): the check takes 5.3 s and 20 MB of memory, against 24.5 s and
252 MB for the 0.2.7 version on the reviewer's run (it held every blob at once).

## v0.2.7 — 2026-09-28 · the nightly commit holds only the archive

### Security

- **LT-SEC-003: the update staged the whole repository.** It ran `git add -A`, so anything in
  the checkout (a note, a local edit, a file someone had staged) went into the archive commit
  and was pushed, while the leak guard only checked `archive/conversations/*.md`. Now:
  - the update refuses to start if anything is already staged;
  - it stages only `archive/`, and every git step's failure stops the commit;
  - before committing, it checks every staged path against an allow-list
    (`archive/INDEX.md`, `archive/REDACTION-REPORT.txt`, `archive/conversations/**.md`) and
    against the leak guard, and scans the exact staged bytes (what git will commit, not the
    working tree) with the leak guard. Any problem unstages the archive and commits nothing.
- The staged-content check also stops a leak found while writing its test (LT-SEC-005, fixed at
  the source in a later task): a secret in a project folder's name reached `archive/INDEX.md`
  and the file path, neither of which the Markdown masker covers.
- The masker's log no longer writes out a file name that itself matches the leak guard.

### Fixed

- **The low-disk refusal never stopped anything.** The free-space check ran inside `$(…)`, so its
  exit only ended a subshell and the update carried on; its message was swallowed too. It now
  stops the update and says why.
- On a fresh install the `archive/` folder did not exist yet, so the first run could not write its
  log. It is created first.

### Tests

- `tests/test_tape_cli.py`: end-to-end runs of `tape update` in a throwaway repo with a local
  remote, a fake home folder and a fake `gh` that always fails, so no test can reach a real
  account. All 5 fail against 0.2.6.

## v0.2.6 — 2026-09-28 · the redactor's re-review findings

### Fixed

- **An AWS key id glued to another key left that key for the guard to find** (ADR 0003): the
  0.2.5 change let the AWS rule stop mid-run, so the `]` of its marker created a word boundary
  in front of an `sk-` or OpenSSH body that the earlier rules had skipped. The rule now takes
  the whole run. A fuzz of 80,000 inputs finds no guard hit on redactor output and no output
  that changes when redacted twice.
- A headless key whose lines are separated by a literal `\r`, and one removed in a diff
  (every line starting with `-`), are redacted.
- The headless scan now runs after the framed-key rules, so a full `BEGIN … END` block comes
  out as one marker exactly as before (no one-time diff in existing archives).
- A redaction marker with spaces is never cut in half by the assignment rules.

## v0.2.5 — 2026-09-28 · the redactor's review findings

A deep review of 0.2.4 found one blocker and four gaps; all are fixed here, each with a test
that failed first.

### Fixed

- **Blocker: the headless private-key rule took quadratic time.** On a long base64 run with no
  `END` footer (a `base64` dump in a tool's output), the regex rescanned every position:
  measured 0.34 s at 10,000 characters, 6 s at 40,000, and roughly half an hour projected
  for 1 MB, on every nightly run. It is now code that walks backwards from each footer, so the
  cost is linear: 1 MB of adversarial input redacts in about 0.1 s.
- **Key formats that got through.** The list of private-key prefixes is now taken from keys
  `openssl` generated, not written by hand. That also showed the ported P-256 prefix
  (`MHQCAQEEI`) matched no real key; real P-256 keys start `MHcCAQEE`. Now covered: PKCS#1 RSA
  of every size (1024 and 3072 were missing), PKCS#8 RSA, P-256/P-384/P-521 in SEC1 and
  PKCS#8, Ed25519, X25519, Ed448, X448, OpenSSH. A single 64-character line before a footer
  (Ed25519) counts as a key body. Public keys still survive.
- **Keys inside JSON strings.** A private key with escaped newlines (`\n`), with or without
  its header, left its body behind.
- **Quoted values went in part.** `{"password": "correct horse battery staple"}` kept three
  words, and short or comma-holding values stayed whole. A quoted value is now redacted up to
  its closing quote.
- **Python and grep disagreed on word boundaries next to non-ASCII text** (`密钥是sk-proj-…`):
  the redactor skipped the key while grep in the C locale flagged it, so the nightly job
  stopped; in a UTF-8 locale both skipped it and it was committed. The redactor and the
  guard's masker now use ASCII rules and the guard's grep runs with `LC_ALL=C`.
- Two keys glued together are both redacted in one pass; a short last line of a cut-off key
  is redacted too.
- **Older guard/redactor mismatches** (ADR 0003): `sk-ant-` with 15–19 characters, `xai-` or
  `AKIA` glued to a word, and `AKIA` with 17+ characters were flagged by the guard but not
  removed by the redactor. The masker caught them, but the invariant was broken; it holds now.

### Corrected

- v0.2.4's entry says 35 new test cases failed first; the reviewer counted 38 failing on the
  base, and the commit message said 40. The count that stands is 38.
- The `sha384-` exclusion added in 0.2.4 never applied (a 48-byte digest fits neither length
  band) and is removed.

### Measured

On the same 1,500-file sample of a real archive, the redactor still hides nothing less than
the one before this work (0 tokens revealed); 34 files differ, all from over-redaction.

## v0.2.4 — 2026-09-28 · the redactor closes its known blind spots

### Security

- **Headless private keys are redacted.** A key body followed by its `END` footer with no
  `BEGIN` header (what `cut -d= -f1` prints for a multi-line value in an env file) used to
  lose only its footer, which was defanged, so the leak guard passed while the whole body
  survived. Now caught three ways: body + footer, a header + body joined by spaces, and a bare
  body recognised by its DER prefix (PKCS#1, PKCS#8, EC, OpenSSH). Public keys, certificates
  and CSRs are left alone. Ported from the private archive this project was extracted from,
  where it was found on 2026-09-03. The leak guard learned the same DER prefixes.
- **LT-SEC-002, credential shapes the July bughunt found** (all were live before this release;
  35 new test cases failed first):
  - `{"password": "…"}` and other quoted keys: a quote between the name and the colon hid the value.
  - `db_password=`, `my_api_key =`, `AWS_SECRET_ACCESS_KEY=`: a name that follows an underscore.
  - `sk-proj-…`, `sk-svcacct-…`, `sk-or-v1-…`, `sk_live_…`, `rk_live_…`: namespaced keys. The
    leak guard learned namespaced `sk-` keys too, as a strict subset of the redactor.
  - Padded base64 keys followed by a space, a quote or the end of the text (`=\b` never matched
    there), or starting with `+` or `/`.
  - Private keys wrapped narrower than 40 columns.
  - Azure `AccountKey=` / `SharedAccessKey=` in connection strings.
- Redacted assignments keep their separator and quotes, so `{"password": "[REDACTED]"}` stays
  valid JSON.

### Measured

On a 1,500-file sample of a real archive: the new redactor hides **nothing less** than the old
one (0 tokens visible that were hidden before). 32 files come out different, all from the wider
name rules; in code, a declaration such as `access_token: Option<String>` now has its type
masked. That over-redaction is deliberate: exempting code-looking values would let through a
password that happens to contain a bracket. CSP / Subresource Integrity hashes (`'sha256-…='`)
were the only new base64 hits in a first sample and are excluded as public digests.

## v0.2.3 — 2026-09-28 · repo paperwork and the safe-everywhere plan

### Added

- Repo paperwork: `PLAN.md`, `BACKLOG.md`, `HANDOFF.md`, `SECURITY.md` (GitHub private vulnerability reporting is on), `CONTRIBUTING.md`, `.env.example`, and the 2026-09-28 safe-everywhere plan.

## v0.2.2 — 2026-08-06 · codex tool steps carry their command again

### Fixed

- **Codex shell steps were archived as a bare tool name, losing the command.**
  Measured on a real archive: 174,092 of 525,768 step turns — **33% of the whole
  Architect layer** — rendered as `exec` or an empty `Bash:`, and every one came
  from a codex model. The command was never missing from the source and was never
  filtered by the viewer; the extractor dropped it on the way in. Three causes:

  1. `exec` carries its payload in `input`, not `arguments`, and the call site read
     only `arguments` — so it arrived as `None`.
  2. That payload is **JavaScript, not JSON** —
     `const r = await tools.exec_command({cmd:"…"})` — often with *unquoted* object
     keys, which `json.loads` cannot parse either way.
  3. codex names the key `cmd`; the labeller read `command`. So even calls whose
     arguments *were* valid JSON produced an empty `Bash: `.

  Recovery on real rollouts: **0.01% → 98%** informative labels (7,347/7,441).

- `exec` is a general JS sandbox, not only a shell. Roughly a sixth of its calls are
  `apply_patch` envelopes, now labelled `apply_patch → <file> (+N more)` rather than
  mislabelled as a command; calls that drive another tool are named
  `exec → tools.<name>`. A shell step whose command genuinely cannot be recovered
  now degrades to the tool name — never a bare `Bash:`, which reads as a step that
  ran an empty command.

### Notes

- This surfaces command text that was previously absent from the archive, so the
  redactor now sees it. Verified: 13,907 recovered labels from real rollouts, **0**
  trip the leak guard after redaction — and the scan was itself controlled with a
  synthetic key, which it caught before redaction and lost after.
- **Existing archives are not rewritten.** Labels are produced at extraction time;
  re-run `tape update` to backfill.


## v0.2.1 — 2026-08-06 · two defects v0.2.0 shipped

Both were found by serving the viewer against a **real** archive (8,936
conversations, 1.05M turns) rather than a test fixture. Neither was visible to the
83-test suite, because the suite was the problem in one case.

### Fixed

- **Every conversation page raised `IndexError` and returned an empty reply.** The
  header read `r["branch"]`; the column produced by `build_db.py` is `git_branch`.
  The tests did not catch it because `tests/test_viewer.py` **hand-wrote its own
  fixture schema**, inventing `branch` and `engine` while production has
  `git_branch` and `md_path` — and a 12-value positional `INSERT` swallowed the
  mismatch. The fixture now **derives the schema from `build_db.py`**, so it cannot
  drift again; re-introducing the bug against the corrected fixture fails 5 tests.
- **Search was quadratic on a real archive.** `snippet()` was computed for every
  matching FTS row before all but one page was discarded. Measured on 8,936
  conversations: a common word (`the`, ~18k matching rows) took **217.8s**. Ranking
  is now done on ids alone and snippets are computed for the current page only.

  ```
  query        before      after
  the         217.82s      1.93s     (113x)
  fox           6.43s      0.17s      (38x)
  redaction     0.51s      0.07s       (7x)
  ```


## v0.2.0 — 2026-08-06 · the viewer, rebuilt

The local viewer had no tests and four real defects. All four were reproduced by
hand against the old code before anything was changed.

### Fixed

- **Ordinary punctuation crashed the search.** The search box was passed straight
  to FTS5 `MATCH`, so typing `"`, `*`, `(`, or the bare word `AND` raised
  `OperationalError` out of the request handler and killed the page. Input is now
  parsed into always-valid FTS5: a `"quoted phrase"` is honoured as a phrase and
  every other token is re-quoted as a literal, so `AND` searches for the *word*
  people meant. A trailing `*` is preserved as a prefix search (`redact*`).
- **Search hits often showed nothing highlighted.** FTS matches case-insensitively
  but the highlighter did not, so a hit on `Fox` while searching `fox` rendered
  with no mark at all.
- **Highlighting corrupted HTML entities.** It ran over already-escaped text, so
  searching `amp` rewrote `&amp;` into `&<mark>amp</mark>;`. Highlighting now runs
  against the raw text and escapes around the matches.
- **Conversations were listed twice.** `build_db` writes one FTS row per *kind*,
  so a term appearing in both a message and a tool step matched twice and the
  JOIN duplicated the conversation. De-duplicated on best rank.
- **Paging past the end reported a false "Nothing matched".** `?q=fox&page=2` on a
  40-result search returned zero rows with a total of 40, rendering an empty state
  byte-for-byte identical to a genuine miss. The page is now clamped before the
  slice.
- **A broken or locked database produced a traceback into a dead socket** instead
  of a page. It now renders a real error page with the reason and the fix.

### Added

- **Result snippets.** Search results show the matching text with the term
  highlighted, so you can see *why* something matched. For an archive whose whole
  purpose is "do you remember…?", this was the biggest gap in the tool.
- **Pagination** with a real result count, replacing a silent `LIMIT 300` that
  truncated without saying so.
- **A light "paper" theme** alongside the dark one, remembered across visits.
- **Keyboard**: `/` focuses search, `j`/`k` move through results, `Esc` unfocuses.
- **Per-turn anchors** — every turn is linkable.
- **Responsive layout.** Previously a fixed 340px rail in a `100vh` flex row, i.e.
  unusable on a phone. Verified over 10 pages × 7 viewport widths, 0 failures —
  with the detector itself checked against a deliberately overflowing control.
- **Security headers**: a per-response CSP nonce, `nosniff`, `no-referrer`. See
  [ADR 0004](docs/adr/0004-viewer-is-offline-first-and-csp-hardened.md).
- **83 tests** where there were none, including the four defects above, XSS
  through archived markup, and two mechanical guards described below.

### Notes

- **WCAG AA**: `--faint` (timestamps, result meta, counts — all 11.5px, i.e.
  normal text) failed at 3.18–3.39:1 in dark and 3.28–3.63:1 in light. Retoned to
  pass 4.5:1 on every surface it is used on. Measured, not eyeballed.
- Two defects in this release were invisible to the test suite and found only by
  opening a browser, so both now have mechanical guards:
  **(a)** the CSP silently drops `style="…"` attributes — a nonce authorises a
  `<style>` element, never a style attribute — which left every model badge
  colourless while all tests passed;
  **(b)** `fill=currentColor/>` parses the value as `currentColor/`, because HTML
  ends an unquoted attribute value at whitespace or `>` and never at `/`. The
  theme icon had correct geometry and painted nothing.

## v0.1.4 — 2026-08-06 · one unreadable source no longer costs you the archive

### Fixed

- **A single unreadable session file aborted the entire refresh.** `parse_session()`
  and `parse_codex_session()` were called bare, so the first `OSError` propagated out
  of `main()` and the run produced nothing — including every healthy conversation
  sitting beside the bad file.

  This is not hypothetical. The most common trigger is a dangling subagent symlink:
  `rglob("*.jsonl")` matches a symlink by *name* without resolving it, so the failure
  lands at the read. A scan of this machine's live sources found **2** of them among
  231 matches. Anyone whose archive silently stopped updating may have been hitting
  exactly this.

  Unreadable sources are now recorded and skipped, and reported by path and reason in
  the refresh log (`tape logs`). Only `OSError` is caught, deliberately — a malformed
  *source* is expected and survivable; a bug in our own parsing is not, and must still
  crash rather than quietly drop conversations.

  This stays fail-**soft** only because the pipeline already fails **closed**
  downstream: the sanity floor and the shrink ratchet in `tools/tape` refuse to commit
  an archive whose conversation count collapses, so mass source loss still aborts the
  run instead of publishing a truncated archive.

- The skipped-source count is printed **even when it is zero**. A metric that only
  appears on failure offers no evidence that it is watching.

### Added

- 5 tests (45 → 50) covering the dangling symlink, an unreadable file (reason must be
  named, not swallowed), the zero-skipped line on a clean run, healthy sessions
  surviving a bad neighbour, and the codex source going through the same seam. All
  five were watched fail first — 4 as errors (the crash) and 1 as a failure (the
  missing metric).

## v0.1.3 — 2026-08-06 · Telegram bot tokens are scrubbed

### Security

- **The redactor had no pattern for Telegram bot tokens** (`<bot_id>:<35-char secret>`).
  A bare token in prose, and — far more importantly — a token inside a Bot API URL,
  passed straight through into the archive.

  The URL case is the one that mattered. Every Bot API request embeds the whole token
  in its path (`https://api.telegram.org/bot<token>/getMe`), and HTTP clients routinely
  put the failing URL into their error message. So an ordinary DNS blip or timeout,
  archived verbatim from a terminal, would have written a live credential into a git
  repository. Anyone using the tape while building a Telegram bot was exposed.

  Two patterns, because the token appears in two shapes and one regex cannot catch
  both: in the URL form the digits follow `bot` with **no word boundary**, so a
  `\b`-anchored pattern misses precisely the most common leak path while passing every
  prose test. The URL form requires digits-then-colon after `/bot`, which leaves
  Telegram's own docs URL (`core.telegram.org/bots/api`) intact rather than mangling
  prose that is printed constantly.

  **This does not retroactively clean an existing archive.** The redactor runs at
  extraction time. If you have been archiving Bot API traffic, scan your own archive
  and rotate any token you find — the guard's silence before this release was silence
  about a pattern it did not have, not evidence that nothing leaked.

- Added the token to the commit-time leak guard (`LEAK_RX`), deliberately **narrower**
  than the redactor's pattern (8+ id digits and exactly 35 secret chars, vs 5+ and 30+)
  so the guard remains a strict subset and can never flag what the redactor missed.
  This invariant is now written down as [ADR 0003](docs/adr/0003-leak-guard-is-a-subset-of-the-redactor.md).

### Added

- **ADR 0003 — the leak guard is a strict subset of the redactor.** Records the
  ordering rule (redactor first and broader, guard second and narrower), the no-trailing-`\b`
  rule, and the 2026-06-14 deadlock that established them.
- 11 tests (34 → 45), each verified to fail before the fix:
  - 8 unit tests over the realistic leak shapes, plus the two negative cases that keep
    prose readable (Telegram's docs URL; ordinary numbers and epoch timestamps).
  - A seeded property test asserting the subset invariant across 500 generated
    guard-matching tokens × 6 contexts, replacing a handful of hand-picked examples.
  - An end-to-end test driving a synthetic session file through `parse_session()`,
    covering the `tool_use → step_label() → redact()` seam that unit tests cannot reach.

### Fixed

- Changelog ordering: the `0.1.2` entry had been appended below `0.1.0` instead of at
  the top. Entries are now newest-first throughout.

## v0.1.2 — 2026-07-18 · codex sessions

### Added
- **Codex source (optional):** the tape now also archives OpenAI codex CLI sessions
  (`~/.codex/sessions/**` rollout JSONL — never auth/sqlite/caches). Same pipeline:
  every stored string passes the redactor; reasoning and tool outputs are not archived
  (dialogue + step labels only, mirroring the Claude source); conversations carry
  `engine:"codex"` in their sentinel. Machines without codex are unaffected.
- 11 unit tests on synthetic rollout fixtures (secret redaction, wrapper stripping,
  developer-role skip, no-outputs guarantee, generic project labeling).

## v0.1.1 — 2026-07-16 · security triage record

- Verified the 2026-07-16 defensive bughunt against the current runtime code:
  the report contains no Critical findings, and all four confirmed High findings
  have explicit trigger or environment prerequisites.
- Added Codex fix notes with confirmed-vs-refuted status, focused verification
  evidence, remediation TODOs, and the secret-rotation assessment.
- No runtime behavior or tests changed in this release: no finding met the
  requested Critical or literal precondition-free High fix threshold.

## v0.1.0 — 2026-07-02 · the tape starts rolling

First public release: the generalized machinery of the private Fabulous archive.

- `tape` CLI: init wizard (private-remote split, PATH link, first extraction, timer),
  update / build / serve / stop / status / stats / backup / logs / doctor
- Extractor: Claude Code JSONL → secret-scrubbed, round-trippable Markdown
  (read-only on sources; per-turn model attribution; sentinel-comment format)
- Redactor (18 pattern families) + independent leak guard (mask-then-verify)
- SQLite + FTS5 build artifact, rebuildable on any clone
- Local web viewer (loopback :8124) with Personal/Architect layer toggles
- Daily timer: systemd (Linux/WSL) + launchd (macOS) + cron fallback;
  guardrails: disk floor, sanity floor + shrink ratchet, portable single-instance lock
- Prehistory importer for hand-saved notes (redacted, dedup'd, `note` kind)
- One-line installer (install.sh); native-Windows guide (Task Scheduler path)
- Tests: redactor contract (incl. guard-sync pin), extract→build round-trip,
  notes importer
