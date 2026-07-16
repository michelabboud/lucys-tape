# Codex fix notes — 2026-07-16 security bughunt

## Scope decision

The source report contains **no Critical findings**. It contains four High
findings, and each one states a concrete trigger or environment prerequisite.
This pass interpreted Michel's “no-precondition High” threshold literally:
trigger input, local checkout mutation, destination misconfiguration, or
publication credentials are preconditions. Runtime code was therefore not
changed outside the authorized finding class.

No reported finding was treated as a false positive. The High findings were
checked as an extra defensive measure so the remaining risk is explicit rather
than silently deferred.

## Critical findings — confirmed vs refuted

There were zero Critical entries to confirm or refute. The bughunt's statement
“No Critical issue was confirmed” accurately describes its own finding set; it
is not a refutation of any enumerated Critical.

## High findings checked

| Finding | Verdict | Why it is outside the literal no-precondition threshold |
|---|---|---|
| LT-SEC-001 | Confirmed | The stale database path requires the fallback guard to alter Markdown after the database build. Viewer, backup, and release disclosure add their own run/configuration conditions. |
| LT-SEC-002 | Confirmed | Each deterministic blind spot requires a real credential in an uncovered representation that does not overlap a stronger signature. Publication adds the normal pipeline conditions. |
| LT-SEC-003 | Confirmed | An unrelated/pre-staged/concurrent checkout change must reach the commit path; remote disclosure additionally requires an accepting destination. |
| LT-SEC-004 | Confirmed | A wrong or public destination and write-capable Git or GitHub credentials are required; snapshots also require the weekly/forced release path. |

Two conditions are already present in this checkout and make the TODOs urgent:

- Unignored root diagnostic logs exist, so the whole-repository `git add -A`
  path could stage them. Their contents were deliberately not read.
- The GitHub CLI's implicit destination currently resolves to a public
  repository, and the authenticated principal has administrative write
  permission there. No URL, account identity, or credential value was printed.

Safe metadata-only checks found no current evidence that this path already
published private archive data: the public branch contains zero tracked
conversation/database paths, and the public release state contains zero assets
and zero snapshot releases.

## What changed

No production code changed, because no finding met the requested severity and
precondition class. Consequently there was no behavior for which a new happy
path or failure-path regression test could be written honestly. Adding a test
without its authorized fix would only codify known failing behavior.

This report, `CHANGELOG.md`, `PROGRESS.md`, and `VERSION` were updated to record
the verified outcome. The version moved from `0.1.0` to `0.1.1` per repository
closeout convention.

## Verification

- Current runtime and tests are unchanged from the bughunt's reviewed commit:
  `git diff --quiet d4b7394..HEAD -- tools tests` returned success before these
  documentation-only edits.
- Focused baseline redactor verification passed all 17 existing tests.
- Boolean-only synthetic probes reproduced the quoted assignment, padded
  base64, namespaced `sk-`, cloud secret-assignment, and short-wrapped truncated
  private-key blind spots without printing candidate values.
- Shell syntax validation passed for `tools/tape`.
- Final changed-file whitespace and repository-state checks are recorded in the
  commit closeout.

No clean, full rebuild, installer, application server, or full test suite was
run; this respects the constrained-disk verification rule.

## TODOs left

1. **LT-SEC-004 — fail closed on publication destination.** Persist and verify
   one exact trusted private destination, validate every effective push URL,
   make init remote failures fatal, and bind every `gh release` call to the
   verified repository. Until then, do not rely on implicit GitHub resolution.
2. **LT-SEC-003 — isolate the commit index.** Require a clean initial index,
   stage only generated archive paths, check every Git status, and scan the exact
   staged blobs before commit. Apply the same gate to the Windows workflow.
3. **LT-SEC-001 — build only from final masked Markdown.** Reorder update to
   extract, mask and verify, then build and sanity-check the database before any
   backup or snapshot.
4. **LT-SEC-002 — close deterministic redaction gaps.** Add boundary-aware
   quoted assignments, correct padded-base64 delimiters, supported namespaced
   key alphabets, cloud secret-access assignments, and stateful truncated-key
   handling, with an independently defined guard and synthetic regressions.

The remaining Medium and Low findings from the source report remain outside
this pass and retain their documented remediation order.

## Secret rotation

No specific exposed secret was identified, and the safe publication checks
found no tracked archive/database content or release assets on the public
destination. **No mandatory credential rotation is indicated by the evidence
available in this pass.**

If Michel independently knows that a real credential in one of LT-SEC-002's
uncovered shapes was processed and published elsewhere, that credential should
be revoked and replaced; this review found no evidence that such publication
occurred.
