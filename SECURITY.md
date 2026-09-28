# Security policy

Lucy's Tape archives your AI conversations and scrubs secrets from them before anything is
committed. A bug here can leak a credential, so reports are welcome and taken seriously.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting: the **Security** tab of
<https://github.com/michelabboud/lucys-tape> → **Report a vulnerability**. Please do not open a
public issue for a security problem, and never paste a real secret into a report; describe its
shape (for example "a PEM body with no header line") instead.

## Supported versions

Only the latest release on `main` gets fixes.

## In scope

- Secrets that survive redaction into the archive, the database, backups or release snapshots.
- Anything that commits, pushes or releases archive content to a destination the user did not
  choose.
- The local viewer: cross-site scripting, DNS rebinding, reading files outside the archive.
- File permissions, locks and paths that let another local user read or tamper with the archive.

## Out of scope

- Secrets the user commits to the archive by hand, outside `tape`.
- Anything that needs the attacker to already run code as the archive's owner.

Known open findings and their status are in `docs/reports/2026-07-16-fable-codex-security-bughunt.md`
and `BACKLOG.md`.
