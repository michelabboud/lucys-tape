# Progress

## Done
- v0.3.0 (2026-09-29) — Phase 1, safe to use: all 15 findings of the July security audit
  fixed in code (0.2.3–0.2.25), redactor level with its private sibling, the viewer behind a
  per-launch key, archive writes that never follow a link. 101 → 265 tests, every fix red
  first. Release gate: two blind reviews (Fable 5.1, gpt-5.6-sol), confirmed after three rounds
  of fixes (0.2.23–0.2.25). v0.2.3–v0.2.22 are per-task checkpoints (`checkpoint/0.2.x`); the history
  between v0.2.0 and them is caught up in Phase 3.
- v0.2.0 — viewer rebuilt: search that cannot crash, result snippets, pagination,
  light/dark themes, keyboard nav, responsive, CSP-hardened. Four pre-existing
  defects fixed, two more found only by opening a browser. 0 → 83 tests. ADR 0004.
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
