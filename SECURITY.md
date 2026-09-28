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
- Your own transport settings. The trusted destination (`tape trust`) binds the push *address*;
  an ssh host alias, `core.sshCommand` or `GIT_SSH_COMMAND` you set can still route a matching
  address elsewhere. It guards against mistakes (a changed remote, a fork, a rewrite rule), not
  against someone who can already edit your git or ssh configuration.

## Known limits

- **The viewer's link is its key.** `tape serve` prints `http://127.0.0.1:8124/s/<key>/`; the key is
  new at every launch and is sent only to that address (no cookie, no Referer). It stays in your
  browser history until the viewer stops; anyone who can read your browser history on this
  account can already read the archive files.
- **A destination that is not on github.com** (a self-hosted git server, a local path) is bound
  by address only: nothing can ask such a host whether the repo is private. A host that looks
  like GitHub but is not github.com (your own GitHub Enterprise server) is refused unless you
  accept it with `tape trust --without-gh`, which also covers a github.com repo when `gh` is not
  available. That choice binds one exact destination and never overrides GitHub saying PUBLIC.

Known open findings and their status are in `docs/reports/2026-07-16-fable-codex-security-bughunt.md`
and `BACKLOG.md`.
