# Progress

## Done
- v0.1.4 — one unreadable source (dangling subagent symlink, deleted session) no
  longer aborts the whole refresh; skipped sources reported by path + reason.
  Found 2 live instances on the dev machine. 45 → 50 tests.
- v0.1.3 — Telegram bot tokens are scrubbed (they were not: a token inside a Bot API
  URL reached the archive verbatim). Guard clause added as a strict subset; the
  redactor/guard ordering rule written down as ADR 0003. 34 → 45 tests, every new
  one verified red before the fix.
- v0.1.2 — optional codex CLI source (`~/.codex/sessions/**`), same redaction
  pipeline, engine-tagged shelves
- v0.1.1 — independently verified the 2026-07-16 security bughunt; recorded
  zero Critical findings and four confirmed conditional High TODOs
- v0.1.0 — full machinery ported from Fabulous, generalized, tested (see CHANGELOG)

## Next
- Semantic search (docs/plans/semantic-search.md) — sqlite-vec default, Qdrant optional
- `tape.ps1`: full guardrail parity on native Windows
- Title backfill helper for "untitled conversation" archives
