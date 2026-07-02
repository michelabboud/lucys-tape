# Plan (roadmap): semantic search over the archive

**Status:** Idea, approved direction (2026-07-02) — not scheduled.

FTS5 keyword search (v0.1) answers "where did we say `XAUTOCLAIM`". Semantic search
answers "that conversation where we felt the deadline slipping" — which is the actual
recall people want from a memory archive.

## Direction

- **Default backend: `sqlite-vec`** — embedded, single file beside `conversations.db`,
  no daemon, fits ADR-0002's zero-daemon soul.
- **Optional backend: Qdrant** — for power users with big archives who already run it;
  same interface, chosen by env/config.
- **Embeddings: local-only and optional** (e.g. a small ONNX/gguf sentence model, or
  the user's own local embedding server). The stdlib-only core path must keep working
  with zero deps; `tape build --semantic` is an opt-in that clearly states what it
  downloads/uses. Nothing in the archive ever leaves the machine — that law is not
  negotiable, including for embedding calls (no cloud embedding APIs by default).

## Open questions for the design pass

- Chunking: per-turn vs sliding-window over dialogue; steps probably excluded by default.
- Incremental embedding on `tape update` (only new/changed conversations).
- Viewer UX: a second search box, or one box with `~semantic` prefix, or blended rank?
- Model choice + license vetting per repo rule (record in docs/reports/).
