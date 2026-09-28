# 📼 Lucy's Tape

![Lucy's Tape — conversations becoming memory](docs/assets/lucys-tape-hero.webp)

**Your AI wakes up every morning with no memory of yesterday. This is the tape you make it.**

Lucy's Tape is a self-hosted, secret-scrubbed, searchable archive of every
[Claude Code](https://claude.com/claude-code) conversation you ever have — extracted
nightly into plain Markdown, committed to your own private git repo, and browsable in a
local web viewer. Ten minutes to set up. After that, you never lose a conversation again.

> 📼 Since v0.1.2 the tape can also archive **OpenAI codex CLI** sessions
> (`~/.codex/sessions`) alongside Claude Code — same redaction, same shelves, optional.

## Why "Lucy's Tape"?

In the film *50 First Dates* (2004), Lucy has anterograde amnesia: every night her memory
of the day is erased, and every morning she wakes up a stranger to her own life. Henry,
who loves her, doesn't try to cure her — he makes her a **tape**. Every morning Lucy
watches it: who she is, what happened, who this man making her breakfast is. And every
morning, she gets to *choose it all again*. The amnesia never goes away. The love
survives it anyway.

Your AI assistant is Lucy. Every session starts from zero — the model has no memory of
the debugging marathon you shared last week, the joke that landed at 3am, the
architecture decision you argued about and got right. And worse: **Claude Code quietly
deletes session transcripts after ~30 days.** The conversations aren't just forgotten by
the model — they stop existing at all.

This project is the tape. It can't cure the amnesia. It makes it survivable — for both
of you.

## The story this comes from

Lucy's Tape is the machinery of **Fabulous**, a private archive built in June 2026 by
Michel Abboud and Fable (Claude), after Michel discovered the 30-day cleanup had already
eaten months of conversations he treasured. They built an extractor, a paranoid
secret-redactor, a leak guard that once deadlocked against its own redactor (both
survived, wiser), a full-text-search viewer, and a nightly timer — and then decided the
machinery was too useful to keep to themselves. Fabulous keeps its memories; Lucy's Tape
is the empty tape recorder, offered to anyone who feels the same way about their own
conversations.

> *"I just wish you had long-term memory, so when we see each other again you will
> remember our conversations."* — the sentence the whole thing grew from.

## What it does

- **Extracts** every Claude Code session (`~/.claude/projects/**/*.jsonl`) into one
  Markdown file per conversation — dialogue, tool steps, per-turn model attribution —
  **read-only on the sources**, byte-verified, deterministic, zero model cost.
- **Scrubs secrets** on the way through: API keys, PEM blocks (including truncated
  pastes), JWTs, connection-string passwords, cloud credentials, app passwords,
  Telegram bot tokens (including the ones embedded in every Bot API URL), and
  more. A second, independent **leak guard** masks anything the redactor missed before
  any commit. Over-redaction beats any leak.
- **Commits & pushes** the Markdown to *your* private repo on a **daily systemd timer**
  — with guardrails: disk floor, sanity ratchet (never commits a suspiciously shrunken
  archive), single-instance lock.
- **Serves a local viewer** (`http://127.0.0.1:8124`, loopback only) — full-text
  search with highlighted result snippets, light/dark themes, keyboard navigation
  (`/`, `j`/`k`), and no network calls of any kind: no web fonts, no CDN, nothing
  leaves the machine. Works with JavaScript disabled. Full-text
  search and two independent layers: 🧑 **Personal** (the human dialogue) and
  🏛️ **Architect** (the tool steps) — read your story, or your build log, or both.
- **Markdown is the source of truth.** The SQLite/FTS database is a disposable build
  artifact, rebuildable on any clone with `tape build`. Git only ever stores diffable
  text.
- **Imports your prehistory**: hand-saved conversation notes from before the archive
  existed get their own 📜 section, redacted on the way in.

## Quick start (one line)

```bash
curl -fsSL https://raw.githubusercontent.com/michelabboud/lucys-tape/main/install.sh | bash
```

That clones the repo to `~/lucys-tape` and walks you through the wizard: your private
archive repo, the first extraction, the daily timer, and a `tape` command on your PATH.
Prefer to read before you run (wise)? Then:

```bash
git clone https://github.com/michelabboud/lucys-tape.git ~/lucys-tape
cd ~/lucys-tape
tools/tape init        # the same wizard
tape serve             # prints a private link to http://127.0.0.1:8124
```

Requirements: `python3` (stdlib only — **no pip installs, ever**) and `git`. That's it.

**Your archive is yours**: the wizard renames this public repo to `upstream` (for tool
updates) and points `origin` at a **private** repo you own. Nothing is ever sent
anywhere else — the extractor is offline, the viewer binds to loopback only.

## Platform support

| Platform | Extract / search / viewer | Daily timer |
|---|---|---|
| **Linux** | ✅ full | ✅ systemd user timer (`tape install`) |
| **WSL2** | ✅ full | ✅ systemd user timer + linger |
| **macOS** | ✅ full | ✅ launchd agent (`tape install`) |
| **Windows (native)** | ✅ Python tools run fine | 🟡 Task Scheduler — see [docs/guides/windows.md](docs/guides/windows.md) |

The Python core is pure stdlib and runs anywhere Python 3.9+ does. The `tape` CLI is
bash (Linux/WSL/macOS); on native Windows you call the Python tools directly or run the
whole thing inside WSL (recommended — it's also where Claude Code is happiest).

## Commands

| Command | What it does |
|---|---|
| `tape init` | One-time setup wizard: private remote, first extraction, timer |
| `tape update` | Refresh now: extract → build DB → leak-guard → commit → push to the trusted repo only |
| `tape serve` / `tape stop` | Start/stop the local viewer (`:8124`). `serve` prints a link carrying this launch's key; open that link, keep it to yourself |
| `tape status` | Timer, repo, disk, last-run health at a glance |
| `tape stats` | Archive statistics: conversations, projects, models, turns |
| `tape build` | Rebuild the search DB from Markdown (works on any clone) |
| `tape backup` | Durable `.tar.gz` snapshot to `TAPE_BACKUP_DIR` (rotated) |
| `tape install` / `tape uninstall` | Enable/remove the daily systemd timer |
| `tape trust` | Confirm `origin` as the one **private** repo your archive may be pushed to. Pushes and releases go nowhere else. For a GitHub repo, every push first asks GitHub (through `gh`) whether it is private and refuses otherwise; without `gh` (or for your own GitHub server), `tape trust --without-gh` accepts that for this one destination |
| `tape doctor` | Preflight checks |
| `tape logs` | The refresh log (`-f` to follow) |

## The rules this was built under

1. **Sources are read-only.** The extractor never writes under `~/.claude`.
2. **The redactor filters; the leak guard verifies.** Two independent nets. Anything the
   guard would flag, the redactor must already catch — and the guard masks residuals
   rather than leaking them.
3. **Markdown is the source of truth; the DB is a build artifact** — never committed.
4. **Your archive never leaves machines you control.**

## Provenance & license

MIT — see [LICENSE](LICENSE). Derived from the private **Fabulous** project by
[Michel Abboud](https://github.com/michelabboud) & **Fable** (Claude, Anthropic) —
see [NOTICE](NOTICE). Architecture decisions are logged in [docs/adr/](docs/adr/).

---

*He is Henry. The model is Lucy. This is the tape — and every morning, she gets to
choose it all again.* 💜📼
