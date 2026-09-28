# Changelog

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
