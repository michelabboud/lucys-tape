# Backlog

Dated one-liners for everything deferred or spotted and not done. An item leaves only by being
done or by the maintainer's word. Format: `date · source · status · item`.

- 2026-07-16 · security bughunt · planned (Phase 1) · LT-SEC-001–015, see `docs/reports/2026-07-16-fable-codex-security-bughunt.md`; tracked task by task in the 2026-09-28 plan.
- 2026-09-28 · repo review · planned (Phase 1, task 1.1) · port the headless private-key redaction from the private sibling (2026-09-03).
- 2026-09-28 · repo review · planned (Phase 2) · CI on Linux, macOS and Windows; native `tape.ps1` with Task Scheduler.
- 2026-09-28 · repo review · planned (Phase 3) · PROGRESS stops at v0.2.0; GitHub release pages missing for v0.1.3–v0.2.2.
- 2026-09-28 · repo review · open · v0.1.1 and v0.1.2 appear in CHANGELOG but were never tagged; history is not rewritten, the gap is noted in CHANGELOG instead.
- 2026-07 · plans · parked · semantic search (`docs/plans/semantic-search.md`).
- 2026-07 · README "Next" · open · title-backfill helper.
- 2026-09-28 · metadata review · planned (Phase 2, Windows) · Windows-reserved names (`CON`, `nul`, `aux.txt`) pass `path_component` unchanged; a UTF-8 BOM added by an editor stops the metadata line matching in `build_db`; `os.replace`/`mv -f` fail while the viewer holds the DB open.
- 2026-09-28 · metadata review · open · a file renamed by a newer version leaves its old copy on disk (the extractor never deletes); the DB no longer duplicates it (0.2.16), but the stale Markdown stays until removed by hand.
