# Lucy's Tape — Architecture

```
~/.claude/projects/**/*.jsonl          (Claude Code's session files — READ-ONLY)
        │
        ▼  tools/extract_conversations.py   (offline, deterministic, stdlib-only)
        │      • parses dialogue + tool_use steps + per-turn model
        │      • REDACTS every stored string (keys, PEM, JWTs, passwords…)
        ▼
archive/conversations/<project>/<date>__<title>__<sid>.md      ← SOURCE OF TRUTH
archive/INDEX.md · archive/REDACTION-REPORT.txt                  (committed, diffable)
        │
        ├──▶ tools/build_db.py  →  archive/conversations.db     ← build artifact
        │        (SQLite: catalog + turns + FTS5 — git-ignored,  (never committed)
        │         rebuildable on ANY clone from the Markdown)
        │
        ├──▶ tools/conversations_viewer.py  →  http://127.0.0.1:8124
        │        (stdlib HTTP, loopback only; 🧑 Personal / 🏛️ Architect layers)
        │
        └──▶ tools/tape update   (the daily pipeline, run by the timer)
                 1. preflight: disk floor, single-instance lock (portable mkdir lock)
                 2. extract → build → SANITY: floor + ratchet (never commit an
                    archive that shrank by more than half — broken extraction)
                 3. LEAK GUARD: independent regex net MASKS anything the redactor
                    missed (over-redaction beats any leak), then verifies clean
                 4. commit Markdown only → push to YOUR private origin
                 5. Sundays: tar.gz backup (TAPE_BACKUP_DIR) + compressed-DB
                    GitHub Release snapshot (optional, needs gh)
```

## The invariants

1. **Sources are read-only.** Nothing ever writes under `~/.claude`.
2. **Markdown is the source of truth; the DB is a build artifact.** Git stores only
   diffable text. Any clone reconstructs the DB with `tape build`, no `~/.claude` needed.
3. **The redactor filters; the leak guard verifies.** Two independent nets with one
   contract: the redactor's pattern set is a superset of the guard's (`tests/test_redact.py::
   test_guard_regex_in_sync` pins it). The guard masks residuals instead of aborting —
   a stuck pipeline protects nobody — then fail-closes if masking itself failed.
4. **Round-trip losslessness.** Each turn carries a sentinel comment
   (`<!--t role=… kind=… model=… ts=…-->`); `write_markdown → parse_md` is lossless
   (`tests/test_roundtrip.py` pins it).
5. **Loopback only.** The viewer binds 127.0.0.1 (default port 8124).

## The format

Each conversation file opens with `<!--fab {json}-->` (catalog metadata), then a
human-readable header table, then turns. Turn kinds: `dialogue` (human/assistant),
`step` (tool call), `note` (hand-saved prehistory imports — no invented structure).

## Timers per platform

- **Linux/WSL** — systemd user units (`lucys-tape-refresh.{service,timer}`,
  `OnCalendar=daily` + `Persistent=true` + 30m jitter), linger enabled where possible.
- **macOS** — launchd agent `com.lucys-tape.refresh` (daily 03:30).
- **Anything else** — cron line printed by `tape install`.

## Roadmap (docs/plans/)

- Semantic search over the archive: local embeddings + `sqlite-vec` as the default
  (embedded, single file — fits the zero-daemon soul), optional Qdrant backend for
  power users. Strictly local-and-optional: the stdlib-only core never grows a
  mandatory dependency.
