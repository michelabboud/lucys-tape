# Handoff — 2026-09-28, safe-everywhere plan, Phase 1 midway

- **State:** `main` at 0.2.12 (`b00c4ac`), pushed, tagged `checkpoint/0.2.12`. 163 tests pass.
- **Done (each deep-reviewed by a separate Opus 5.5 reviewer, findings fixed):**
  - 1.0 repo paperwork (0.2.3)
  - 1.1 redactor: headless keys, generated key prefixes, LT-SEC-002 shapes, ASCII boundaries (0.2.4–0.2.6)
  - 1.2 LT-SEC-003: archive commit built on a private index, allow-list + staged-blob scan (0.2.7–0.2.9)
  - 1.3 LT-SEC-004/013: one trusted private destination (`tape trust`), strict GitHub URL parsing (0.2.10–0.2.11)
  - 1.4 LT-SEC-001/015: DB built from masked Markdown, atomic swap (0.2.12) — review in flight
- **Next, in order:** 1.5 metadata + paths through the redactor (LT-SEC-005/014: branch, model,
  project names and file paths bypass it today — see tests in `tests/test_tape_cli.py`), 1.6
  permissions/lock/rotation, 1.7 viewer, 1.8 path containment, 1.9 phase gate (Fable high deep
  review) and `v0.3.0`.
- **Gotchas:** `LEAK_RX` must stay a strict subset of the redactor (ADR 0003) and is mirrored in
  `tests/test_redact.py`. Every new DER prefix comes from an openssl-generated key. End-to-end
  tests use a fake `gh` and a local bare remote; never let a test reach GitHub.
- **Left running:** nothing.
