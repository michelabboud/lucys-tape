# Contributing

## Setup

Python 3.10+ and bash. No third-party packages: the core is standard library only (ADR 0002).

```bash
git clone https://github.com/michelabboud/lucys-tape.git
cd lucys-tape
python3 -m unittest discover tests     # the test suite
bash -n tools/tape                     # the CLI parses
ruff check tools tests                 # lint, if you have ruff
```

## Rules that matter here

- **The redactor filters; the leak guard checks.** Any pattern the guard (`LEAK_RX` in
  `tools/tape`) looks for, the redactor must scrub first (ADR 0003). A new redaction pattern
  comes with tests for the shape it catches and for a near-miss it must leave alone.
- **Never put a real secret in a test, an issue or a commit.** Build fixtures from obviously
  fake material.
- **The Markdown archive is the source of truth; the database is a build artifact** and is never
  committed.
- Tests for every change, including the failure path. A bug fix starts with a test that fails.

## Versions and commits

`VERSION` holds the version and is the only source for it. Every change bumps it, gets a
`CHANGELOG.md` entry, and is tagged `checkpoint/<VERSION>`; a release is tagged `v<VERSION>`
(tags before 2026-09-28 used `v*` for every version). Security issues go through `SECURITY.md`, not
public issues.
