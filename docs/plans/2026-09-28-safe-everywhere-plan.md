# Plan: safe to use, runs everywhere (2026-09-28)

**Status:** approved 2026-09-28 (Michel: "go ahead an fix the repo"). Running.
**Written by:** Claude Opus 5.5, coordinating. Per the house rules, planning belongs to the top model:
Claude Fable 5.1 reviews this plan and the Phase 1 code before the Phase 1 release.
**Tasks run back to back:** when a task closes, the next one starts in the same session.

## Why

Lucy's Tape is public, and people install it to keep their own conversations private. On
2026-09-28 a review found:

1. **The July security bughunt was never fixed in code.** `docs/reports/2026-07-16-fable-codex-security-bughunt.md`
   lists 15 findings (4 High, 10 Medium, 1 Low). The July lane triaged and deferred all of them;
   only the root-log `.gitignore` mitigation landed.
2. **The redactor fell behind its private sibling.** The private archive that this project was
   extracted from (Fabulous) added headless private-key redaction on 2026-09-03 after a real
   incident. The public tape never got it.
3. **Windows is second-class.** Linux (systemd) and macOS (launchd) are scheduled by `tools/tape`;
   native Windows has only a manual guide. Nothing runs the tests on any OS in CI.
4. **Housekeeping.** The repo lacks BACKLOG, PLAN, HANDOFF, SECURITY, CONTRIBUTING and
   `.env.example`; PROGRESS stops at v0.2.0; GitHub shows only a v0.1.0 release although tags go to
   v0.2.2.

## Execution and communication

- One session coordinates and implements (Claude Opus 5.5, the Strong tier, where security work
  starts). Tasks that share a file run in sequence; nothing here is parallel-safe except the CI
  and Windows tasks of Phase 2.
- **Reviews.** Every security task is in a risk class, so each gets a **deep review at task grain**
  (Strong tier: a separate Opus 5.5 reviewer reading the pinned commit, not the working tree).
  Findings are fixed on the same task before the next one starts. Phase 1 ends with a **high deep
  review** (Top tier: Fable 5.1, plus a second-family reviewer when one is available) before
  `v0.3.0` is tagged. That review is a gate.
- **Evidence.** Each task: a regression test that fails before the fix and passes after,
  `python3 -m unittest discover tests` output, `bash -n tools/tape`, and `ruff check tools tests`.
- **Versioning.** Each task bumps the patch (`0.2.x`), is committed, tagged `checkpoint/<VERSION>`
  and pushed to `main` (one maintainer, so the repo is solo and `main` is the branch). Phase
  releases are tagged `v<VERSION>` and get a GitHub release page. Before 2026-09-28 every version
  was tagged `v*`; those tags are history and stay as they are.

## Phase 1 — safe to use (security) → release v0.3.0

| # | Task | Findings | Files | Depends on |
|---|---|---|---|---|
| 1.0 | Repo files: BACKLOG, PLAN, HANDOFF, SECURITY (private vulnerability reporting, enabled 2026-09-28), CONTRIBUTING, `.env.example` | — | root docs | — |
| 1.1 | Redactor catches up and closes its blind spots: headless private keys (port of the 2026-09-03 fix) plus the LT-SEC-002 shapes (quoted assignments, padded base64, namespaced `sk-`, cloud secret assignments, short-wrapped key bodies). The guard stays a strict subset (ADR 0003). | 002 | `tools/extract_conversations.py`, `tools/tape` (LEAK_RX), `tests/test_redact.py` | 1.0 |
| 1.2 | Commit only what the job generated: require a clean index, stage only archive paths, fail on any git error, scan the exact staged blobs before commit. | 003 | `tools/tape` | 1.1 |
| 1.3 | Fail closed on the destination: record one trusted private destination at init, verify every effective push URL against it, refuse to push or release otherwise, bind `gh release` to that repo. | 004, 013 | `tools/tape` | 1.2 |
| 1.4 | The database and backups are built only from the final masked Markdown; rebuild into a temporary file and swap atomically. | 001, 015 | `tools/tape`, `tools/build_db.py` | 1.3 |
| 1.5 | Metadata, titles and filenames pass through the redactor; conversation text cannot forge turn boundaries. | 005, 014 | `tools/extract_conversations.py` | 1.4 |
| 1.6 | Private by default: archive, database, backups and logs are created owner-only. Lock in a private per-user location, not a predictable shared path. Backup rotation never passes a filename as an option. | 006, 011, 012 | `tools/tape`, Python writers | 1.5 |
| 1.7 | The viewer: Host-header validation and a per-run access token on loopback, escaping on every metadata sink, bounded inputs and concurrency. | 007, 008, 010 | `tools/conversations_viewer.py` | 1.6 |
| 1.8 | Path containment: sources resolved inside their roots, symlinks refused or contained. | 009 | extractor, importers | 1.7 |
| 1.9 | Phase close: high deep review (gate), security notes in CHANGELOG, the bughunt report annotated with each finding's fix commit, `v0.3.0` + GitHub release. | all | docs | 1.8 |

## Phase 2 — runs everywhere → release v0.4.0

| # | Task | Files | Depends on |
|---|---|---|---|
| 2.1 | CI on GitHub Actions: tests + ruff on Ubuntu, macOS and Windows; `bash -n` + shellcheck on the CLI. Runs on push and pull request, publishes nothing. | `.github/workflows/ci.yml` | 1.9 |
| 2.2 | Python tools audited for Windows: paths, owner-only permissions (ACLs where POSIX modes don't apply), locks. | `tools/*.py` | 2.1 |
| 2.3 | macOS: `tools/tape` runs under the system bash 3.2 and BSD userland; launchd path tested in CI where possible. | `tools/tape` | 2.1 |
| 2.4 | Native Windows `tools/tape.ps1`: the same commands and the same guardrails as 1.2–1.6 (staged-blob scan, trusted destination, private files), scheduled through Task Scheduler. | `tools/tape.ps1`, `docs/guides/windows.md` | 2.2 |
| 2.5 | Installers verified on all three systems; getting-started covers each. Phase close: deep review, `v0.4.0` + release. | `install.sh`, `install.ps1`, guides | 2.3, 2.4 |

## Phase 3 — TLC → release v0.4.1

| # | Task | Depends on |
|---|---|---|
| 3.1 | PROGRESS caught up; README pass (what it protects against, platforms, honest limits); release pages backfilled for v0.1.3–v0.2.2 from CHANGELOG. | 2.5 |

After Phase 3, an aitamer.news piece about the tape (outside this repo).

## Out of scope, recorded in BACKLOG

Semantic search (its own plan), a title-backfill helper, anything that changes the archive format
without a migration.
