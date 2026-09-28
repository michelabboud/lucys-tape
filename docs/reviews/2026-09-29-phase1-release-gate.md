# Phase 1 release gate — v0.3.0 (2026-09-28 → 2026-09-29)

**What was judged:** the whole of Phase 1 (security), `v0.2.2..e307def`, before tagging `v0.3.0`.
**Result:** tagged `v0.3.0` at `e307def` after one blind round and four confirm rounds.
**Coordinator and implementer:** Claude Opus 5.5. Every finding below was checked against the code
before it was acted on; the rulings are the coordinator's, with the reasoning recorded.

## The reviewers

| Reviewer | Family | Role |
|---|---|---|
| Claude Fable 5.1 | Anthropic | Top-tier gate reviewer, blind |
| gpt-5.6-sol (xhigh, through `hexe`) | OpenAI | Second-family reviewer, blind; then the confirm passes |

Both got one identical brief and their own detached worktree at the reviewed commit. Neither saw
the other's output during the blind round.

## Round by round

| Round | Commit | Fable | sol | What came of it |
|---|---|---|---|---|
| Blind gate | `48dd3f7` (0.2.22) | PASS, 6 should-fixes | BLOCKED, 5 blockers, 4 should-fixes | 0.2.23 (`fc2b6c0`) |
| Confirm 1 | `fc2b6c0` | PASS | BLOCKED: the new stale-copy cleanup deleted data; unverified pushes | 0.2.24 (`9067f46`) |
| Confirm 2 | `9067f46` | — | BLOCKED: cleanup still lost text; `github.com.` bypass; SECURITY.md entry missing | 0.2.25 (`e17f32d`), release commit `9ca7e69` |
| Confirm 3 | `9ca7e69` | — | BLOCKED: rename merged through a linked target; Unicode GitHub hosts | second release commit `e307def` |
| Confirm 4 | `e307def` | — | PASS (with an explicit blocker rule in the brief) | tagged `v0.3.0` |

## What each instrument caught

- **Found by both:** `tape serve` building the DB without the mask pass; `tape backup` packing a DB
  older than the masking; control characters in printed URLs; shell redirections that follow
  planted links.
- **Only Fable:** the redactor's quadratic digit-run rule (200,000 digits, 22 s); the masker's
  strict UTF-8 decode that could stop every nightly; logs (with the viewer's key) in backups; the
  Python-version mismatch in the docs.
- **Only sol:** unverified GitHub pushes; the viewer cookie reaching other loopback ports; old
  credential-shaped file names blocking the gate after an upgrade; symlink loops crashing the
  extractor; an empty rebuild replacing a good DB; a test that never exercised the masker; and,
  in the confirm rounds, every defect in the fixes themselves (data loss twice, the trailing-dot
  and Unicode host bypasses, a merge through a linked folder).
- **Found by neither:** at `48dd3f7` and `fc2b6c0`'s parent, `safe_paths` tested `os.replace` for
  folder-descriptor support, which Python never lists, so the descriptor walk never ran on any
  platform; every write took the Windows fallback. Found by a test written for another fix.
  Fable's own account: it read the walk and ran the suite, but never probed which branch was live
  on the host. A claim about which code path runs needs a runtime check, not a reading.

## Rulings where the reviewers disagreed

1. **Pushes GitHub cannot verify** (sol: blocker; Fable: a documented design choice). First ruled
   non-blocking, reversed after confirm 1: for a privacy tool, typing `private` is intent, not
   proof. Since 0.2.24 a GitHub push needs GitHub to say PRIVATE, or an explicit
   `tape trust --without-gh` for that one destination.
2. **The viewer cookie reaching other 127.0.0.1 ports** (sol: blocker; Fable: accept, narrowly).
   Ruled non-blocking: v0.2.2 had no viewer authentication at all, so holding back a strictly
   safer release keeps users on the weaker one. Recorded in `SECURITY.md`; it is task 1.10, the
   next release. sol's dissent stands on record.
3. **Deleting superseded copies** (added to fix sol's upgrade blocker). Two attempts were unsafe
   (0.2.23 by id, 0.2.24 by turn markers). Replaced in 0.2.25 by renaming, never deleting:
   nothing in the archive is removed; duplicate copies are a BACKLOG item.

## Why confirm 4 converged

Confirm briefs 1–3 asked "is anything wrong", and each round found something real in the newest
code. Brief 4 stated what a blocker is: a leak, a wrong destination or lost archive content,
reachable without the attacker already running code as the owner (SECURITY.md's out-of-scope line),
with content arriving through git or session sources counted as reachable. A state the rule does
not name resolves to a note. That is the residual clause adversarial review needs to converge.

## Numbers

- Tests: 101 at `v0.2.2` → 269 at `v0.3.0`; every fix has a test that fails on the code before it.
- On a real machine's sources (6,383 sessions): the new extractor writes the same conversations as
  the old one, and the rename touched no ordinary name (5,576 files, twice).
