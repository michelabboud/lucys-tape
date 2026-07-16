# Changelog

## v0.1.1 — 2026-07-16 · security triage record

- Verified the 2026-07-16 defensive bughunt against the current runtime code:
  the report contains no Critical findings, and all four confirmed High findings
  have explicit trigger or environment prerequisites.
- Added Codex fix notes with confirmed-vs-refuted status, focused verification
  evidence, remediation TODOs, and the secret-rotation assessment.
- No runtime behavior or tests changed in this release: no finding met the
  requested Critical or literal precondition-free High fix threshold.

## v0.1.0 — 2026-07-02 · the tape starts rolling

First public release: the generalized machinery of the private Fabulous archive.

- `tape` CLI: init wizard (private-remote split, PATH link, first extraction, timer),
  update / build / serve / stop / status / stats / backup / logs / doctor
- Extractor: Claude Code JSONL → secret-scrubbed, round-trippable Markdown
  (read-only on sources; per-turn model attribution; sentinel-comment format)
- Redactor (18 pattern families) + independent leak guard (mask-then-verify)
- SQLite + FTS5 build artifact, rebuildable on any clone
- Local web viewer (loopback :8124) with Personal/Architect layer toggles
- Daily timer: systemd (Linux/WSL) + launchd (macOS) + cron fallback;
  guardrails: disk floor, sanity floor + shrink ratchet, portable single-instance lock
- Prehistory importer for hand-saved notes (redacted, dedup'd, `note` kind)
- One-line installer (install.sh); native-Windows guide (Task Scheduler path)
- Tests: redactor contract (incl. guard-sync pin), extract→build round-trip,
  notes importer
