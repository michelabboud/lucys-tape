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


def build(db_path):
    con = sqlite3.connect(db_path)
    init_db(con)
    n = 0
    for md in sorted(CONV_DIR.rglob("*.md")):
        meta, turns = parse_md(md)
        if meta is None:
            continue
        sid = meta.get("sid") or md.stem
        rel = str(md.relative_to(ARCHIVE))
        # the same session can exist under two file names (renamed by a newer version);
        # replace its turns, never append a second copy
        con.execute("DELETE FROM turns WHERE session_id = ?", (sid,))
        con.execute("DELETE FROM fts WHERE session_id = ?", (sid,))
        con.execute("INSERT OR REPLACE INTO conversations VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (sid, meta.get("project", ""), title_of(md), meta.get("started", ""), meta.get("ended", ""),
                     meta.get("n_dialogue", 0), meta.get("user_turns", 0), meta.get("assistant_turns", 0),
                     meta.get("n_steps", 0), meta.get("models", ""), meta.get("branch", ""), rel))
        dbody, sbody = [], []
        for i, (role, kind, model, ts, text) in enumerate(turns):
            con.execute("INSERT INTO turns VALUES (?,?,?,?,?,?,?)", (sid, i, role, kind, ts, model, text))
            (dbody if kind in ("dialogue", "note") else sbody).append(text)
        proj = meta.get("project", "")
        title = title_of(md)
        con.execute("INSERT INTO fts VALUES (?,?,?,?,?)", (sid, "dialogue", proj, title, "\n".join(dbody)))
        if sbody:
            con.execute("INSERT INTO fts VALUES (?,?,?,?,?)", (sid, "step", proj, title, "\n".join(sbody)))
        n += 1
    con.commit()
    con.close()
    return n


if __name__ == "__main__":
    main()
