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
# Optional second source: OpenAI codex CLI rollout sessions. Scope is STRICTLY
# ~/.codex/sessions/** — never auth.json, sqlite stores, caches, or worktrees.
# A machine without codex simply has no such dir and the tape skips it.
CODEX_SESSIONS = Path.home() / ".codex" / "sessions"
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
    # Telegram bot tokens: <bot_id>:<35-char secret>. Two patterns, because the
    # token appears in two shapes and one regex cannot catch both:
    #   1. embedded in EVERY Bot API request URL — https://api.telegram.org/bot<token>/getMe
    #      — where the digits follow "bot" with NO word boundary, so a \b-anchored
    #      pattern silently misses the single most common way it leaks (an HTTP
    #      client putting the failing URL into an error message, which then gets
    #      archived verbatim from the terminal).
    #   2. bare, pasted into prose or a config line.
    # The URL form requires digits-then-colon after "/bot", which is what leaves
    # Telegram's own docs URL (core.telegram.org/bots/api) intact — it is printed
    # constantly and mangling it would corrupt readable prose for no gain.
    # NEITHER is \b-anchored at the tail, deliberately: a trailing \b is exactly
    # what made `openai_key` miss what the guard caught (see the note above), and
    # the redactor must stay a SUPERSET of LEAK_RX or the push pipeline deadlocks.
    # The marker is space-free so `assignment`/`env_named` can still collapse a
    # NAME=<token> line to a single [REDACTED] instead of matching only up to the
    # space and leaving "telegram-bot-token]" dangling in the output.
    ("telegram_bot_url", re.compile(r"(?i)(/bot)\d{5,}:[A-Za-z0-9_\-]{30,}"), r"\1[REDACTED-telegram-bot-token]"),
    ("telegram_bot_token", re.compile(r"\d{5,}:[A-Za-z0-9_\-]{30,}"), "[REDACTED-telegram-bot-token]"),
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
_skipped = []   # (path, reason) for every source we could not read


def safe_parse(parse, path):
    """Parse one session file, surviving a source we cannot read.

    The sources are outside our control and READ-ONLY to us, so we never repair
    them: the CLI can delete a session mid-run, or leave a dangling subagent
    symlink behind (rglob matches a symlink by name without resolving it, so the
    read is where it fails). One such file must never cost the whole refresh —
    it is recorded and skipped, and reported loudly at the end.

    Only OSError is caught, deliberately: a malformed *source* is expected and
    survivable, whereas a bug in our own parsing is not, and must still crash
    rather than quietly drop conversations.

    This stays fail-SOFT only because the pipeline fails CLOSED downstream: the
    sanity floor and shrink ratchet in `tools/tape` refuse to commit an archive
    whose conversation count collapses, so mass source loss still aborts the run.
    """
    try:
        return parse(path)
    except OSError as e:
        _skipped.append((path, e.strerror or e.__class__.__name__))
        return None


def report_skipped():
    """Print every source we could not read. A hole in the archive is never
    allowed to pass silently — this lands in the refresh log (`tape logs`).

    The count is printed even when it is zero: a metric that only appears on
    failure gives no evidence that it is watching."""
    print(f"sources skipped      : {len(_skipped)}")
    for path, reason in _skipped:
        print(f"  WARN unreadable source, skipped: {path} — {reason}")


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



# ---- codex source (rollout JSONL) -------------------------------------------
# Observed format (codex CLI 0.14x): typed JSONL — {"timestamp","type","payload"}
# with session_meta (id, cwd, git{branch}), turn_context (per-turn `model`),
# response_item (message | function_call | custom_tool_call | reasoning | ...),
# event_msg (duplicate message stream + telemetry — skipped). Reasoning and tool
# OUTPUTS are deliberately not archived, mirroring the Claude source. Everything
# stored passes redact().

CODEX_WRAPPER = re.compile(
    r"<(environment_context|user_instructions|ENVIRONMENT_CONTEXT|permissions|INSTRUCTIONS)>.*?</\1>",
    re.S)


def codex_project_label(cwd):
    """Shelf name for a codex session cwd — generic for ANY user (no hardcoded
    usernames): the segment after a `projects` dir when present, else basename."""
    if not cwd:
        return "codex-misc"
    parts = Path(cwd).parts
    if "projects" in parts:
        i = parts.index("projects")
        if len(parts) > i + 1:
            return parts[i + 1]
    if str(Path(cwd)) == str(Path.home()):
        return "home"
    return Path(cwd).name or "codex-misc"


def _js_object_candidates(s):
    """Every balanced {...} span in `s`, outermost-first, as raw text."""
    out = []
    start = s.find("{")
    while start != -1 and len(out) < 8:
        depth, in_str, esc, quote = 0, False, False, ""
        for i in range(start, len(s)):
            ch = s[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == quote:
                    in_str = False
                continue
            if ch in '"\'':
                in_str, quote = True, ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    out.append(s[start:i + 1])
                    break
        start = s.find("{", start + 1)
    return out


def _first_json_object(s):
    """The first balanced {...} in `s` that parses as a JSON object, else None.

    Needed because codex's `exec` tool does not hand over JSON at all — it hands
    over JavaScript:

        const r = await tools.exec_command({"cmd": "...", "workdir": "..."});

    A brace scan (rather than a regex) is what keeps a command containing braces
    or quotes — `awk '{print $1}'` — from truncating the object early.
    """
    start = s.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(s)):
            ch = s[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(s[start:i + 1])
                    except (json.JSONDecodeError, ValueError):
                        break
                    if isinstance(parsed, dict):
                        return parsed
                    break
        start = s.find("{", start + 1)
    return None


# A bare JS identifier used as an object key: `{cmd:"…"}` rather than `{"cmd":"…"}`.
# Legal JavaScript, illegal JSON, and the single most common `exec` payload shape.
_JS_BARE_KEY = re.compile(r'([{,]\s*)([A-Za-z_$][\w$]*)\s*:')
# The tool a sandbox script actually calls: `await tools.write_stdin({…})`.
_JS_TOOL_CALL = re.compile(r"\btools\.([A-Za-z_$][\w$]*)\s*\(")


def codex_args(payload):
    """Best-effort dict from a codex tool payload (JSON, or JS wrapping JSON)."""
    if isinstance(payload, dict):
        return payload
    if not isinstance(payload, str) or not payload.strip():
        return {}
    try:
        parsed = json.loads(payload)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    obj = _first_json_object(payload)
    if obj is not None:
        return obj
    # Last resort: the object literal is JS, not JSON — quote its bare keys and
    # retry. Gated behind the strict parses above, and a mangled result simply
    # fails to parse and falls through to {}, so this can only ever recover.
    for raw in _js_object_candidates(payload):
        try:
            parsed = json.loads(_JS_BARE_KEY.sub(r'\1"\2":', raw))
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def codex_inner_tool(payload):
    """The tool a sandbox script calls, e.g. `write_stdin` — else None.

    `exec` is a JavaScript sandbox, so the interesting name is usually the tool
    invoked *inside* the script, not the sandbox itself. Naming it beats emitting
    a bare "exec" that says nothing about what happened.
    """
    if not isinstance(payload, str):
        return None
    names = [n for n in _JS_TOOL_CALL.findall(payload) if n != "exec"]
    return names[0] if names else None


# Every codex tool name that means "run a shell command". `exec` is the current
# one and was missing, which alone blanked 107,953 step labels in the archive.
CODEX_SHELL_TOOLS = ("shell", "exec", "exec_command", "local_shell")

# `exec` is a general JavaScript sandbox, not only a shell: roughly three quarters
# of real `exec` calls are apply_patch envelopes rather than commands, and calling
# those "Bash:" would swap one wrong label for another. The envelope names each
# file it touches on its own directive line.
CODEX_PATCH_FILE = re.compile(r"^\*\*\* (?:Update|Add|Delete) File: (.+)$", re.M)


def codex_patch_label(payload):
    """`apply_patch → <file>` for a patch envelope, else None.

    Recognises the envelope wherever it appears in the payload — it arrives as a
    JS string literal (`const patch = "*** Begin Patch\\n..."`), so the directive
    lines are escaped and must be read after unescaping.
    """
    if not isinstance(payload, str) or "*** Begin Patch" not in payload:
        return None
    body = payload.replace("\\n", "\n").replace('\\"', '"')
    files = [short_path(f.strip()) for f in CODEX_PATCH_FILE.findall(body)]
    if not files:
        return "apply_patch (edit)"
    head = files[0]
    return (f"apply_patch → {head}" if len(files) == 1
            else f"apply_patch → {head} (+{len(files) - 1} more)")


def codex_step_label(name, arguments):
    """One-line label for a codex function/tool call (mirrors step_label)."""
    inp = codex_args(arguments)
    patch = codex_patch_label(arguments)
    if patch:
        return patch
    if name in CODEX_SHELL_TOOLS:
        # codex names the key `cmd`; `command` is the Claude-side spelling. Reading
        # only `command` is why calls whose arguments WERE valid JSON still
        # rendered as an empty "Bash: " — 66,139 of them.
        cmd = inp.get("cmd") or inp.get("command") or ""
        if isinstance(cmd, list):
            cmd = " ".join(str(c) for c in cmd)
        cmd = " ".join(str(cmd).split())[:120]
        if cmd:
            return f"Bash: {cmd}"
        # Never emit a bare "Bash:" — a label with nothing after the colon reads
        # as a step that ran an empty command, which is a lie about the record.
        # Name the tool the sandbox script actually called, if it called one.
        inner = codex_inner_tool(arguments)
        if inner:
            return f"{name} → tools.{inner}"
        return name or "?"
    if name == "apply_patch":
        return "apply_patch (edit)"
    for k in ("path", "file_path", "pattern", "query", "url", "description", "prompt"):
        if k in inp:
            return f"{name}: {str(inp[k])[:90]}"
    return name or "?"
def codex_title(user_msgs, n=80):
    for m in user_msgs or ():
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m or "")).strip()
        if t:
            if len(t) > n:
                cut = t[:n]
                if " " in cut:
                    cut = cut.rsplit(" ", 1)[0]
                t = cut.rstrip(" ,.;:-")
            return t
    return None


def parse_codex_session(path):
    """Parse one codex rollout JSONL into the shared conversation meta shape."""
    sid = path.stem
    started = ended = None
    models, branches = set(), set()
    cwd = None
    turns = []
    u = a = steps = 0
    cur_model = ""
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
            p = o.get("payload")
            if not isinstance(p, dict):
                continue
            ts = o.get("timestamp") or ""
            if t == "session_meta":
                sid = p.get("id") or p.get("session_id") or sid
                cwd = p.get("cwd") or cwd
                git = p.get("git")
                if isinstance(git, dict) and git.get("branch"):
                    branches.add(git["branch"])
                started = started or p.get("timestamp") or ts
            elif t == "turn_context":
                if p.get("model"):
                    cur_model = p["model"]
                    models.add(cur_model)
                if p.get("cwd"):
                    cwd = cwd or p["cwd"]
            elif t == "response_item":
                pt = p.get("type")
                if pt == "message":
                    role = p.get("role")
                    if role not in ("user", "assistant"):
                        continue
                    texts = []
                    content = p.get("content")
                    blocks = content if isinstance(content, list) else []
                    for b in blocks:
                        if isinstance(b, dict) and b.get("type") in ("input_text", "output_text"):
                            texts.append(b.get("text") or "")
                    text = "\n".join(x for x in texts if x).strip()
                    if role == "user":
                        text = CODEX_WRAPPER.sub("", text).strip()
                    if not text:
                        continue
                    turns.append((role, "dialogue", ts,
                                  cur_model if role == "assistant" else "", redact(text)))
                    started = started or ts
                    ended = ts or ended
                    u += role == "user"
                    a += role == "assistant"
                elif pt in ("function_call", "custom_tool_call", "web_search_call",
                            "tool_search_call", "image_generation_call"):
                    # `arguments` for function_call, `input` for custom_tool_call —
                    # the `exec` tool uses the latter, and reading only `arguments`
                    # is why it arrived as None and labelled itself "exec".
                    label = codex_step_label(p.get("name", pt),
                                             p.get("arguments") or p.get("input"))
                    turns.append(("tool", "step", ts, cur_model, redact(label)))
                    steps += 1
                    started = started or ts
                    ended = ts or ended
    if not any(k == "dialogue" for _, k, _, _, _ in turns):
        return None
    user_msgs = [tx for (r, k, _ts, _m, tx) in turns if r == "user" and k == "dialogue"]
    return {
        "sid": sid, "engine": "codex",
        "title": redact(codex_title(user_msgs) or "codex session"),
        "project": codex_project_label(cwd),
        "started": started or "", "ended": ended or "",
        "models": ", ".join(sorted(models)), "branch": ", ".join(sorted(branches)),
        "n_dialogue": u + a, "user_turns": u, "assistant_turns": a, "n_steps": steps,
        "turns": turns, "chars": sum(len(x[4]) for x in turns),
    }


def write_markdown(meta, project, path):
    fab = {k: meta[k] for k in ("sid", "started", "ended", "models", "branch",
                                "n_dialogue", "user_turns", "assistant_turns", "n_steps")}
    fab["project"] = project
    if meta.get("engine"):          # absent = claude (back-compat)
        fab["engine"] = meta["engine"]
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
    if not PROJECTS.is_dir() and not CODEX_SESSIONS.is_dir():
        sys.exit(f"no sources found: {PROJECTS} (Claude Code) nor {CODEX_SESSIONS} (codex) — nothing to archive")
    CONV_DIR.mkdir(parents=True, exist_ok=True)
    seen, index, scanned, kept = {}, [], 0, 0
    for proj_dir in sorted(p for p in PROJECTS.iterdir() if p.is_dir()) if PROJECTS.is_dir() else []:
        files = list(proj_dir.rglob("*.jsonl"))
        if not files:
            continue
        label = project_label(proj_dir.name)
        for f in files:
            scanned += 1
            meta = safe_parse(parse_session, f)
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
    # ---- codex source (optional; same shelves, same pipeline) ----------------
    if CODEX_SESSIONS.is_dir():
        for f in sorted(CODEX_SESSIONS.rglob("rollout-*.jsonl")):
            scanned += 1
            meta = safe_parse(parse_codex_session, f)
            if not meta:
                continue
            sid = meta["sid"]
            if sid in seen and meta["chars"] <= seen[sid]:
                continue
            seen[sid] = meta["chars"]
            label = meta["project"]
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
    report_skipped()


if __name__ == "__main__":
    main()
