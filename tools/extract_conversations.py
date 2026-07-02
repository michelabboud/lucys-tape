#!/usr/bin/env python3
"""Lucy's Tape — extract Claude Code conversations from session JSONL into
complete, secret-scrubbed, round-trippable Markdown. Deterministic, offline,
zero model cost.

READ-ONLY on the sources (~/.claude/projects).

This writes the SOURCE OF TRUTH: one Markdown file per conversation, holding the
full record (dialogue + tool steps + per-turn model). Each turn is preceded by a
tiny machine-readable sentinel comment (invisible when the Markdown is rendered)
so build_db.py can round-trip it losslessly back into the SQLite DB + FTS index.

The DB is NOT produced here — it is a build artifact (see build_db.py), so git
only ever stores diffable text and never a binary blob.

  <out>/conversations/<project>/<date>__<title>__<sid>.md
  <out>/INDEX.md
  <out>/REDACTION-REPORT.txt
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "archive"
CONV_DIR = OUT / "conversations"

# ---- secret scrubbing (applied to every stored string) ----------------------
# The redactor is the PRIMARY filter. tools/tape carries an independent leak
# guard (LEAK_RX) that masks anything the redactor missed before any commit —
# the redactor's pattern set must always be a superset of the guard's.
REDACTIONS = [
    ("private_key_block", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----", re.S), "[REDACTED PRIVATE KEY BLOCK]"),
    # Truncated paste: header + base64 body but no END footer. Must be eaten as a
    # real secret — only after this can a surviving header be presumed bare.
    ("private_key_truncated", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----(?:[ \t]*\r?\n[ \t]*[A-Za-z0-9+/=]{40,})+"), "[REDACTED PRIVATE KEY BLOCK]"),
    # Bare header/footer in prose or code (a *mention*, no key material): defang so
    # the stored text can never trip the pre-commit leak guard, but stays readable.
    ("pem_header_bare", re.compile(r"-----BEGIN ([A-Z0-9 ]*)PRIVATE KEY-----"), r"-----BEGIN (defanged) \1PRIVATE KEY-----"),
    ("pem_footer_bare", re.compile(r"-----END ([A-Z0-9 ]*)PRIVATE KEY-----"), r"-----END (defanged) \1PRIVATE KEY-----"),
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"), "[REDACTED sk-ant]"),
    # NOTE: no trailing \b. The leak guard greps `\bsk-[A-Za-z0-9]{20}`
    # (boundary-free at the tail), so a key butting up against a word char
    # (e.g. sk-…<underscore>) tripped the guard while a trailing \b here made the
    # redactor miss it — a redactor/guard deadlock, found the hard way. Dropping
    # the anchor keeps the redactor a superset of the guard. The leading \b stays
    # (a key starts at a word boundary).
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}"), "[REDACTED sk-key]"),
    ("xai_key", re.compile(r"\bxai-[A-Za-z0-9]{20,}"), "[REDACTED xai-key]"),
    ("github_pat", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b"), "[REDACTED github-token]"),
    ("github_fine_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b"), "[REDACTED github-pat]"),
    ("aws_akid", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED aws-key-id]"),
    ("google_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), "[REDACTED google-key]"),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "[REDACTED slack-token]"),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"), "[REDACTED jwt]"),
    ("bearer", re.compile(r"(?i)\b(bearer|authorization:?\s*bearer)\s+[A-Za-z0-9._\-]{20,}"), "[REDACTED bearer-token]"),
    ("conn_string_pw", re.compile(r"\b((?:postgres|postgresql|mysql|mongodb|redis|amqp)://[^:/\s]+:)[^@/\s]+(@)"), r"\1[REDACTED-PW]\2"),
    ("b64_32", re.compile(r"\b[A-Za-z0-9+/]{42,43}=\b"), "[REDACTED base64-key]"),
    ("b64_64", re.compile(r"\b[A-Za-z0-9+/]{85,87}=\b"), "[REDACTED base64-key]"),
    ("assignment", re.compile(r"""(?ix)\b(password|passwd|pwd|secret|secret[_-]?key|token|service[_-]?token|api[_-]?key|apikey|access[_-]?key|client[_-]?secret|private[_-]?key|enc[_-]?key|master[_-]?key|vault[_-]?key)\b\s*[:=]\s*["']?([^\s"',;]{6,})"""), r"\1=[REDACTED]"),
    ("env_named", re.compile(r"\b([A-Z0-9_]*_(?:API_KEY|SECRET|TOKEN|PASSWORD|ENC_KEY|PRIVATE_KEY))\s*=\s*\S+"), r"\1=[REDACTED]"),
    # App password: four 4-letter lowercase groups. That shape alone is ordinary
    # prose ("make sure that they ..."), so it is only treated as a secret within
    # 60 chars of an app-password keyword.
    ("google_app_pw", re.compile(r"(?is)(\b(?:app|application)[ _-]?(?:password|secret|pw)\b.{0,60}?)\b[a-z]{4}[ -][a-z]{4}[ -][a-z]{4}[ -][a-z]{4}\b"), r"\1[REDACTED google-app-password]"),
]
_red = Counter()


def redact(text):
    if not text:
        return text
    for label, rx, repl in REDACTIONS:
        text, n = rx.subn(repl, text)
        if n:
            _red[label] += n
    return text


SYSREMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
LOCALCMD = re.compile(r"<(command-name|command-message|command-args|command-stdout|local-command-[a-z]+)>.*?</\1>", re.S)


def short_path(p):
    p = str(p)
    for marker in ("/projects/", "/.claude/"):
        i = p.find(marker)
        if i != -1:
            return p[i + len(marker):]
    return p


def step_label(name, inp):
    if not isinstance(inp, dict):
        inp = {}
    if name == "Bash":
        return f"Bash: {' '.join(str(inp.get('command', '')).split())[:120]}"
    if name in ("Read", "Write", "Edit", "NotebookEdit"):
        return f"{name} → {short_path(inp.get('file_path', inp.get('notebook_path', '?')))}"
    if name in ("Grep", "Glob"):
        return f"{name} {inp.get('pattern', inp.get('glob', ''))!r}"
    if name in ("WebFetch", "WebSearch"):
        return f"{name}: {inp.get('url', inp.get('query', ''))}"
    if name == "Skill":
        return f"Skill: {inp.get('command', inp.get('skill', '?'))}"
    if name in ("Task", "Agent"):
        return f"Agent: {inp.get('description', inp.get('subagent_type', 'task'))}"
    if name == "TodoWrite":
        return "TodoWrite (task list update)"
    for k in ("description", "path", "name", "url", "query"):
        if k in inp:
            return f"{name}: {str(inp[k])[:90]}"
    return name


def clean_user(text):
    return LOCALCMD.sub("", SYSREMINDER.sub("", text or "")).strip()


def parse_session(path):
    title = None
    started = ended = None
    models, branches, cwds = set(), set(), set()
    turns = []   # (role, kind, ts, model, text)
    u = a = steps = 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = o.get("type")
            if t == "ai-title" and not title:
                title = o.get("aiTitle")
            if o.get("gitBranch"):
                branches.add(o["gitBranch"])
            if o.get("cwd"):
                cwds.add(o["cwd"])
            if t not in ("user", "assistant"):
                continue
            msg = o.get("message") or {}
            role = msg.get("role", t)
            model = msg.get("model") or ""
            if model and model != "<synthetic>":
                models.add(model)
            ts = o.get("timestamp") or ""
            content = msg.get("content")
            blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                bt = b.get("type")
                if bt == "text":
                    text = clean_user(b.get("text", "")) if role == "user" else (b.get("text", "") or "").strip()
                    if not text:
                        continue
                    turns.append((role, "dialogue", ts, model if role == "assistant" else "", redact(text)))
                    started = started or ts
                    ended = ts or ended
                    u += role == "user"
                    a += role == "assistant"
                elif bt == "tool_use":
                    turns.append(("tool", "step", ts, model, redact(step_label(b.get("name", "?"), b.get("input")))))
                    steps += 1
                    started = started or ts
                    ended = ts or ended
    if not any(k == "dialogue" for _, k, _, _, _ in turns):
        return None
    return {
        "sid": path.stem, "title": redact(title or "untitled conversation"),
        "project": None, "started": started or "", "ended": ended or "",
        "models": ", ".join(sorted(models)), "branch": ", ".join(sorted(branches)),
        "n_dialogue": u + a, "user_turns": u, "assistant_turns": a, "n_steps": steps,
        "turns": turns, "chars": sum(len(x[4]) for x in turns),
    }


def slugify(s, n=50):
    s = re.sub(r"[^\w\s-]", "", s or "").strip().lower()
    return (re.sub(r"[\s_-]+", "-", s)[:n].strip("-")) or "untitled"


# Claude Code names each project dir after the cwd with "/" flattened to "-",
# e.g. /home/ada/projects/webapp -> -home-ada-projects-webapp. Strip the
# user-specific prefix dynamically so archive folders read as plain project
# names on ANY machine (no hardcoded usernames).
_HOME_KEY = "-" + str(Path.home()).strip("/").replace("/", "-") + "-"


def project_label(d):
    for prefix in (_HOME_KEY + "projects-", _HOME_KEY):
        if d.startswith(prefix):
            return d[len(prefix):] or "home"
    if d.strip("-") == _HOME_KEY.strip("-"):
        return "home"
    return d or "unknown"


def write_markdown(meta, project, path):
    fab = {k: meta[k] for k in ("sid", "started", "ended", "models", "branch",
                                "n_dialogue", "user_turns", "assistant_turns", "n_steps")}
    fab["project"] = project
    with open(path, "w", encoding="utf-8") as out:
        out.write(f"<!--fab {json.dumps(fab, separators=(',', ':'))}-->\n\n")
        out.write(f"# {meta['title']}\n\n| | |\n|---|---|\n")
        out.write(f"| **Project** | {project} |\n| **Started** | {meta['started']} |\n")
        out.write(f"| **With** | {meta['models'] or '?'} |\n")
        out.write(f"| **Dialogue** | {meta['n_dialogue']} ({meta['user_turns']} you / {meta['assistant_turns']} assistant) |\n")
        out.write(f"| **Tool steps** | {meta['n_steps']} |\n| **Session** | `{meta['sid']}` |\n\n---\n")
        for role, kind, ts, model, text in meta["turns"]:
            out.write(f"\n<!--t role={role} kind={kind} model={model or '-'} ts={ts or '-'}-->\n")
            if kind == "step":
                who = "🔧 step"
            elif role == "user":
                who = "🧑 You"
            else:
                who = f"🤖 {model or 'Claude'}"
            stamp = f" · {ts[:19].replace('T', ' ')}" if ts else ""
            out.write(f"### {who}{stamp}\n\n{text}\n")


def main():
    if not PROJECTS.is_dir():
        sys.exit(f"source dir not found: {PROJECTS} — is Claude Code installed and used on this machine?")
    CONV_DIR.mkdir(parents=True, exist_ok=True)
    seen, index, scanned, kept = {}, [], 0, 0
    for proj_dir in sorted(p for p in PROJECTS.iterdir() if p.is_dir()):
        files = list(proj_dir.rglob("*.jsonl"))
        if not files:
            continue
        label = project_label(proj_dir.name)
        for f in files:
            scanned += 1
            meta = parse_session(f)
            if not meta:
                continue
            sid = meta["sid"]
            if sid in seen and meta["chars"] <= seen[sid]:
                continue
            seen[sid] = meta["chars"]
            proj_out = CONV_DIR / label
            proj_out.mkdir(parents=True, exist_ok=True)
            date = (meta["started"] or "0000-00-00")[:10]
            write_markdown(meta, label, proj_out / f"{date}__{slugify(meta['title'])}__{sid}.md")
            index.append((meta["started"] or "", label, meta["title"], meta["n_dialogue"], meta["n_steps"], meta["models"],
                          f"conversations/{label}/{date}__{slugify(meta['title'])}__{sid}.md"))
            kept += 1
    index.sort(reverse=True)
    with open(OUT / "INDEX.md", "w", encoding="utf-8") as idx:
        idx.write(f"# 📼 Lucy's Tape — Conversation Archive\n\n**{kept} conversations**, secret-scrubbed, "
                  f"from {scanned} session files. The DB is rebuilt from these files with "
                  f"`tape build`. Newest first.\n\n---\n\n")
        cur = None
        for started, label, title, nd, ns, models, rel in index:
            if label != cur:
                idx.write(f"\n## {label}\n\n")
                cur = label
            idx.write(f"- `{(started or '')[:10]}` [{title}]({rel}) — {nd} turns · {ns} steps · {(models.split(',')[0].strip() if models else '?')}\n")
    with open(OUT / "REDACTION-REPORT.txt", "w", encoding="utf-8") as rep:
        rep.write(f"Secret-scrub report — {sum(_red.values())} redactions (values never stored).\n\n")
        for label, n in _red.most_common():
            rep.write(f"  {n:6d}  {label}\n")
    print(f"sessions scanned     : {scanned}")
    print(f"conversations written: {kept}")
    print(f"secret redactions    : {sum(_red.values())}")


if __name__ == "__main__":
    main()
