# 0002 — Stdlib-only core; heavy features stay optional

**Status:** Accepted · 2026-07-02

## Context

The pitch is "ten minutes to never lose a conversation again." Every dependency is a
tax on that promise: pip environments break, versions rot, corporate machines block
installs. Meanwhile the actual job — parse JSONL, regex-scrub, write Markdown, build
SQLite FTS, serve loopback HTML — is fully covered by the Python standard library.

## Decision

The core (extractor, redactor, DB builder, viewer, notes importer) uses **only** the
Python 3.9+ standard library. The CLI uses bash + coreutils present on Linux/WSL/macOS.
Optional integrations (gh release snapshots) degrade gracefully when absent.

Future heavy features (semantic search via local embeddings + sqlite-vec, or a Qdrant
backend) ship as **strictly optional** add-ons behind the same interfaces — the
zero-dependency path must keep working forever.

## Alternatives rejected

- **A pip package / uv project:** nicer imports, real dependency management — but the
  target user clones and runs; any install step loses people at the door.
- **Qdrant/vector-first storage:** requires a running service; wrong default for a
  gift. Reconsidered as an optional backend in the semantic-search plan.

## Consequences

- Some code is more hand-rolled than a library would make it (HTTP viewer, arg parsing).
- FTS5 keyword search is the v0.1 search story; semantic search is roadmap
  (docs/plans/semantic-search.md).
