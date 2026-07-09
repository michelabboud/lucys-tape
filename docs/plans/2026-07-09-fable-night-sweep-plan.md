# Fable Night Sweep — lucys-tape (2026-07-09)

Fleet-wide sweep for small, safe fix/improvement plans (Michel's directive). This is a
small **public** repo (github.com/michelabboud/lucys-tape) — a gift, never monetized —
so this pass is deliberately light-touch: verify it presents well, note only safe,
additive ideas, and **no restructuring**. **This is a plan document only — nothing
below has been implemented.**

## Health snapshot

- **Version:** `0.1.0`, clean working tree, single public release (2026-07-02) plus a
  README hero-image follow-up commit.
- **Presents well.** `README.md` reads warmly and coherently: the *50 First Dates*
  framing lands, the feature list is concrete (not marketing fluff), the quick-start is
  copy-pasteable, the platform-support table is honest about Windows being partial, and
  provenance/license are both stated plainly at the bottom. Hero image
  (`docs/assets/lucys-tape-hero.webp`) is referenced correctly and present on disk.
- **Tests pass:** `python3 -m unittest discover tests` → **24/24 OK** (stdlib-only,
  no pip install needed or performed, per the project's own "no pip installs, ever"
  rule).
- **License/provenance is properly handled** — `LICENSE` (MIT) and `NOTICE` both name
  Michel Abboud & Fable (Claude, Anthropic) as authors and `NOTICE` explicitly states
  this is Fabulous's machinery ported out with personal data/memories removed. This
  matches rule 5a (vendored/derived code needs provenance) even though this isn't
  vendored third-party code — it's a correct, voluntary application of the same
  principle to a derived-from-private-project release.
- **`.gitignore` is correct** — `__pycache__/` and `*.pyc` are excluded, and verified
  via `git ls-files` that no `__pycache__` artifacts are actually tracked (the
  directory exists locally from running tests this pass, but git doesn't see it).
- **`install.sh`** (the public curl-pipe-bash entry point) is short, uses
  `set -euo pipefail`, checks for `git`/`python3` before doing anything, and is
  idempotent on re-run (updates an existing clone rather than clobbering it). No
  concerns.

## Defects (file:line)

None found. Read the full README, LICENSE, NOTICE, install.sh, PROGRESS.md,
CHANGELOG.md, and ran the test suite — no inconsistencies, broken links, or stale
claims surfaced.

## Ranked improvements

All items below are optional polish for a repo that already presents well — none are
required, and none should be acted on without confirming they fit the "gift, keep it
simple" spirit of this project.

**S (small, safe, additive only):**
- `PROGRESS.md`'s "Next" section already lists three concrete, scoped items in the
  project's own words: semantic search (`docs/plans/semantic-search.md`, sqlite-vec
  default / Qdrant optional), full guardrail parity for `tape.ps1` on native Windows,
  and a title-backfill helper for "untitled conversation" archives. All independently
  shippable when picked up — surfacing here only because they're the project's own
  stated next steps, not a new suggestion.
- Optional: a `CONTRIBUTING.md` for external contributors, since this is a public repo
  that might attract outside PRs — not currently present. Genuinely optional; the repo
  is small enough that its absence isn't a real gap.

**M / L:**
- None identified this pass beyond what `docs/plans/semantic-search.md` already scopes
  out for the semantic-search work — that document exists and describes its own
  trade-offs; no need to duplicate it here.

## What was skipped this pass

- Did not attempt to run `tools/tape init`/`serve` end-to-end (would touch a real
  `~/.claude/projects` extraction and a private-remote wizard flow — out of scope for
  a static review, and not something to run against Michel's live archive without
  being asked).
- Did not review `docs/plans/semantic-search.md` in detail — it's already an existing,
  scoped design doc, not a gap this sweep needed to fill.
