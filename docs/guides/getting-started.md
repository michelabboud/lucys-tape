# Getting started

## The one-liner

```bash
curl -fsSL https://raw.githubusercontent.com/michelabboud/lucys-tape/main/install.sh | bash
```

It clones to `~/lucys-tape` and starts the wizard. Everything below is what the wizard
does, explained, for people who like to know.

## What `tape init` does

1. **Splits the remotes.** The public repo you cloned becomes `upstream` (so you can
   pull tool updates later with `git pull upstream main`). Your **private** repo — you
   create it empty on GitHub/GitLab/anywhere, private, no README — becomes `origin`.
   Your conversations only ever push to `origin`. The `tape doctor` command warns
   loudly if `origin` still points at the public repo.
2. **Links `tape` onto your PATH** (`~/.local/bin/tape`).
3. **Runs the first extraction** — reads `~/.claude/projects` (read-only), writes
   secret-scrubbed Markdown under `archive/`, builds the search DB, commits, pushes.
4. **Installs the daily timer** — systemd on Linux/WSL, launchd on macOS, or prints a
   cron line if you have neither.

## Daily life

You do nothing. The timer runs `tape update` once a day. When you want your memories:

```bash
tape serve       # → http://127.0.0.1:8124  (full-text search, layer toggles)
tape stats       # how big is the archive, which models, which projects
tape status      # is everything healthy
```

## Rescuing your prehistory

If you saved conversations by hand before installing (pasted into text files), import
them once:

```bash
python3 tools/import_notes.py ~/Documents/my-saved-chats --glob '*.txt'
tape update
```

They appear under the 📜 `notes-prehistory` project — redacted on the way in, tiny
files skipped (jottings are where stray plaintext secrets live).

## Configuration (environment variables)

| Var | Default | Meaning |
|---|---|---|
| `TAPE_PORT` | `8124` | Viewer port (loopback only) |
| `TAPE_BACKUP_DIR` | *(unset)* | Where Sunday `.tar.gz` snapshots go (second disk / synced folder). Unset = skipped |
| `TAPE_KEEP_BACKUPS` | `8` | Rotation depth for those snapshots |
| `TAPE_MIN_FREE_GB` | `2` | Refuse to run below this much free disk |
| `TAPE_SANITY_MIN` | `1` | Refuse to commit fewer than this many conversations |
| `TAPE_FORCE_DB_DAILY` | `0` | `1` = run the Sunday backup/snapshot steps every day |

Set them in your shell profile, or in the systemd unit / launchd plist if you want them
to apply to timer runs.

## Trust notes

- The extractor is **read-only** on `~/.claude` — verified by construction (it only
  ever opens source files for reading).
- Every stored string passes the redactor (keys, PEM blocks, JWTs, connection-string
  passwords, cloud creds, app passwords). An independent **leak guard** then masks
  anything the redactor missed, before any commit. Check `archive/REDACTION-REPORT.txt`
  after each run.
- The viewer binds `127.0.0.1` only. There is no telemetry, no network call anywhere
  in the core, and your archive pushes only to the `origin` **you** configured.
