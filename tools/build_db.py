#!/usr/bin/env python3
"""Lucy's Tape — build the searchable SQLite DB from the committed Markdown.

The Markdown files under <archive>/conversations are the source of truth (see
extract_conversations.py). This rebuilds conversations.db (catalog + per-turn
table + FTS5 index) from them — a pure build artifact, never committed.

It works on any clone of the repo with NO access to ~/.claude: the Markdown
alone fully reconstructs the database. Run via `tape build`.
"""
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

ARCHIVE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "archive"
CONV_DIR = ARCHIVE / "conversations"
# Optional second argument: where to write the DB (tools/tape builds to a side file,
# checks it, then swaps it in). Either way the build goes to a temporary file first and
# replaces the target atomically, so a crash never leaves a half-built or missing DB.
DB_PATH = Path(sys.argv[2]) if len(sys.argv) > 2 else ARCHIVE / "conversations.db"

FAB = re.compile(r"^<!--fab (\{.*\})-->\s*$")
TURN = re.compile(r"^<!--t role=(user|assistant|tool) kind=(dialogue|step|note) model=(\S*) ts=(\S*)-->\s*$")
BODY_ESC = "<!--esc-->"  # see escape_body() in extract_conversations.py

# The schema every metadata value must meet before it reaches the database (LT-SEC-008).
# The viewer escapes on output as well; this is the second wall. Measured on 13,748 real
# files (2026-09-28): ids use only these characters and are at most 55 long, timestamps
# are ISO-8601, counts are integers, the longest free-text field is 350 characters.
SID_RX = re.compile(r"[A-Za-z0-9._:-]{1,128}")
TS_RX = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d(:\d\d(\.\d{1,9})?)?(Z|[+-]\d\d:?\d\d)?")
MAX_COUNT = 10**9
MAX_TEXT = {"project": 1000, "branch": 1000, "models": 2000}
rejected = 0  # metadata values dropped by the schema, reported at the end of a build


def reject(default):
    global rejected
    rejected += 1
    return default


def clean_ts(v):
    if v in ("", None):
        return ""
    return v if isinstance(v, str) and TS_RX.fullmatch(v) else reject("")


def clean_meta(meta, stem):
    """The metadata as the database will hold it, or None when the file has no usable id."""
    if not isinstance(meta, dict):
        meta = reject({})
    sid = meta.get("sid")
    if not (isinstance(sid, str) and SID_RX.fullmatch(sid)):
        if sid not in (None, ""):
            reject(None)
        sid = stem if SID_RX.fullmatch(stem) else None
        if sid is None:
            return None
    out = {"sid": sid, "started": clean_ts(meta.get("started")), "ended": clean_ts(meta.get("ended"))}
    for k in ("n_dialogue", "user_turns", "assistant_turns", "n_steps"):
        v = meta.get(k, 0)
        ok = isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= MAX_COUNT
        out[k] = v if ok else reject(0)
    for k, cap in MAX_TEXT.items():
        v = meta.get(k, "")
        out[k] = v[:cap] if isinstance(v, str) else reject("")
    return out


def parse_md(path):
    meta, turns = None, []
    cur = None      # (role, kind, model, ts)
    buf = []

    def flush():
        if cur is None:
            return
        body = "\n".join(buf)
        # drop the readable "### …" header line that follows each sentinel
        lines = body.split("\n")
        if lines and lines[0].lstrip().startswith("### "):
            lines = lines[1:]
        # undo the extractor's escape of structure-looking body lines (LT-SEC-014)
        lines = [ln[len(BODY_ESC):] if ln.startswith(BODY_ESC) else ln for ln in lines]
        turns.append((*cur, "\n".join(lines).strip()))

    # split on "\n" only, as the extractor writes and escapes: splitlines() also breaks
    # on \r, \f, U+2028 and others, and read_text() turns every \r into \n, both of
    # which let body text start a forged turn (LT-SEC-014). Raw bytes, then "\n".
    for line in (ln[:-1] if ln.endswith("\r") else ln
                 for ln in path.read_bytes().decode("utf-8", "replace").split("\n")):
        m = FAB.match(line)
        if m and meta is None:
            try:
                meta = json.loads(m.group(1))
            except json.JSONDecodeError:
                meta = {}
            continue
        t = TURN.match(line)
        if t:
            flush()
            role, kind, model, ts = t.groups()
            cur = (role, kind, ("" if model == "-" else model), ("" if ts == "-" else ts))
            buf = []
        elif cur is not None:
            buf.append(line)
    flush()
    return meta, turns


def init_db(con):
    con.executescript("""
    DROP TABLE IF EXISTS conversations; DROP TABLE IF EXISTS turns; DROP TABLE IF EXISTS fts;
    CREATE TABLE conversations (session_id TEXT PRIMARY KEY, project TEXT, title TEXT,
        started TEXT, ended TEXT, n_dialogue INT, user_turns INT, assistant_turns INT,
        n_steps INT, models TEXT, git_branch TEXT, md_path TEXT);
    CREATE TABLE turns (session_id TEXT, idx INT, role TEXT, kind TEXT, ts TEXT, model TEXT, text TEXT);
    CREATE VIRTUAL TABLE fts USING fts5(session_id UNINDEXED, kind UNINDEXED, project, title, body);
    CREATE INDEX ix_proj ON conversations(project);
    CREATE INDEX ix_started ON conversations(started);
    CREATE INDEX ix_turns ON turns(session_id, idx);
    """)


def title_of(path):
    # split on "\n" only, as the extractor writes and escapes: splitlines() also breaks
    # on \r, \f, U+2028 and others, and read_text() turns every \r into \n, both of
    # which let body text start a forged turn (LT-SEC-014). Raw bytes, then "\n".
    for line in (ln[:-1] if ln.endswith("\r") else ln
                 for ln in path.read_bytes().decode("utf-8", "replace").split("\n")):
        if line.startswith("# "):
            return line[2:].strip()
    return "untitled conversation"


def main():
    if not CONV_DIR.exists():
        print(f"No conversations at {CONV_DIR}. Run extract first.")
        sys.exit(1)
    tmp = DB_PATH.with_name(f"{DB_PATH.name}.tmp-{os.getpid()}")
    tmp.unlink(missing_ok=True)
    try:
        n = build(tmp)
        os.replace(tmp, DB_PATH)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    print(f"built {DB_PATH} from {n} conversations")
    if rejected:
        print(f"{rejected} metadata value(s) failed the schema and were dropped", file=sys.stderr)


def build(db_path):
    con = sqlite3.connect(db_path)
    init_db(con)
    n = 0
    for md in sorted(CONV_DIR.rglob("*.md")):
        meta, turns = parse_md(md)
        if meta is None:
            continue
        meta = clean_meta(meta, md.stem)
        if meta is None:
            print(f"skipped {md.name}: no valid session id", file=sys.stderr)
            continue
        sid = meta["sid"]
        rel = str(md.relative_to(ARCHIVE))
        # the same session can exist under two file names (renamed by a newer version);
        # replace its turns, never append a second copy
        con.execute("DELETE FROM turns WHERE session_id = ?", (sid,))
        con.execute("DELETE FROM fts WHERE session_id = ?", (sid,))
        con.execute("INSERT OR REPLACE INTO conversations VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (sid, meta["project"], title_of(md), meta["started"], meta["ended"],
                     meta["n_dialogue"], meta["user_turns"], meta["assistant_turns"],
                     meta["n_steps"], meta["models"], meta["branch"], rel))
        dbody, sbody = [], []
        for i, (role, kind, model, ts, text) in enumerate(turns):
            con.execute("INSERT INTO turns VALUES (?,?,?,?,?,?,?)",
                        (sid, i, role, kind, clean_ts(ts), model[:MAX_TEXT["models"]], text))
            (dbody if kind in ("dialogue", "note") else sbody).append(text)
        proj = meta["project"]
        title = title_of(md)
        con.execute("INSERT INTO fts VALUES (?,?,?,?,?)", (sid, "dialogue", proj, title, "\n".join(dbody)))
        if sbody:
            con.execute("INSERT INTO fts VALUES (?,?,?,?,?)", (sid, "step", proj, title, "\n".join(sbody)))
        n += 1
    con.commit()
    con.close()
    return n


if __name__ == "__main__":
    os.umask(0o077)  # what we write is private, however we are started (LT-SEC-006)
    main()
