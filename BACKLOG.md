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
- 2026-09-28 · viewer task (1.7) · open · `tape serve`/`tape stop` find the viewer with `pgrep -f conversations_viewer.py`, which also matches any command line containing that name (another checkout's viewer, an editor, a shell loop); `tape stop` could kill the wrong process. Track the viewer by a pid file instead.
- 2026-09-28 · containment task (1.8) · planned (Phase 2, task 2.2) · on Windows `safe_paths.write_text` checks the folders on the way before writing instead of walking them by descriptor; someone who can rename folders inside the archive during a run could race it. Also: `O_NOFOLLOW` does not exist there.
- 2026-09-28 · containment review (0.2.21) · open · shell redirections in `tools/tape` (`>"$ARCHIVE/viewer.log"`, `gzip -c > "$gz"`, `>>"$LOG"`) still follow a planted symlink; only a tracked symlink arriving by git could plant one under `archive/`. Route them through `safe_paths` or check `-L` first.
- 2026-09-28 · containment review (0.2.21) · planned (Phase 2, task 2.2) · the Windows fallback in `safe_paths.write_text` creates folders through a link before refusing, and `resolve() != parent` can misfire on case, 8.3 names, `subst` drives and OneDrive redirection.
- 2026-09-28 · containment review (0.2.22) · open · a temp file left by a killed run (`archive/**/.*.tmp`) is never removed automatically; `tape doctor` could list them.
- 2026-09-29 · release-gate review (sol) · done 0.3.1 · the viewer's session cookie is sent by browsers to every service on 127.0.0.1; replace it with a per-request capability that other ports never receive.
- 2026-09-29 · release-gate review (sol) · open · the viewer renders a whole conversation in one page and search materialises every matching id; add paging and result limits.
- 2026-09-29 · release-gate review (sol) · open · the extractor and the staged-blob scan have no aggregate size budget.
- 2026-09-29 · release-gate confirm passes · open · one session reached through two source folders (or renamed by a newer version) leaves two Markdown files; the index lists it once. Removing the older copy needs a proof that the newer holds all its content; two attempts (0.2.23, 0.2.24) were not safe and were withdrawn in 0.2.25. Candidate: choose the winning source by size before writing, so the smaller copy is never written.
- 2026-09-29 · 0.3.1 deep review (sol) · open · `/s/<exact-key>;extra` opens the root: `urlparse()` strips `;params` from the last segment. Needs the full key, so harmless; use `urlsplit()` or reject `u.params` for an exact path.
