# Changelog

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
