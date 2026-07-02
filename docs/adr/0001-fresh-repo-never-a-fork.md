# 0001 — Fresh repo, never a fork of Fabulous

**Status:** Accepted · 2026-07-02

## Context

Lucy's Tape is the public generalization of Fabulous, a private conversation archive.
Fabulous's git history *is* its authors' conversation archive — every commit since the
first carries personal conversations. A fork or history-carrying export would ship that.

## Decision

Lucy's Tape is born as a brand-new repository. Commit #1 contains only generalized
tooling and docs. Code was ported file-by-file with personal data, hardcoded paths,
usernames, and machine-specific defaults removed (see NOTICE for provenance).

## Alternatives rejected

- **Fork + history rewrite (filter-repo):** one missed blob = a permanent leak of
  private conversations; unverifiable at scale; violates the project's own "over-
  redaction beats any leak" law.
- **Public branch in the private repo:** same risk, plus permanent operational
  confusion about which branch may be pushed where.

## Consequences

- Upstream (Fabulous) fixes must be ported by hand; the two code bases may drift.
  Accepted: the tape's surface is small (~1.3k lines) and the safety property is worth it.
- Users' own clones invert the model: THEIR archive is committed on top of this public
  history in their private `origin` (the `tape init` wizard enforces the remote split).
