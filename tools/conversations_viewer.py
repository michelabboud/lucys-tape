#!/usr/bin/env python3
"""Lucy's Tape — local web viewer for the conversation archive.

Zero dependencies (Python stdlib). Reads conversations.db and serves a
browsable, searchable, layered UI. Two independent layer toggles:
  🧑 Personal  — the human dialogue.
  🏛️ Architect — the technical tool steps (Write→file, Bash:cmd).
Show either alone or both combined. Each turn carries its model badge.

    python3 conversations_viewer.py [ARCHIVE_DIR] [PORT]   # default :8124

Binds to localhost only.
"""
import html
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ARCHIVE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "archive"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8124
DB = ARCHIVE / "conversations.db"

MODEL_COLORS = {
    "fable": "#b59cff", "opus": "#ffb86b", "sonnet": "#6ea8ff",
    "haiku": "#5ce0b0", "user": "#7d8da3",
}

CSS = """
:root{--bg:#0f1115;--panel:#171a21;--line:#262b36;--ink:#e6e8ee;--dim:#9aa3b2}
*{box-sizing:border-box}body{margin:0;font:15px/1.6 -apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--ink)}
a{color:#8ab4ff;text-decoration:none}a:hover{text-decoration:underline}
.wrap{display:flex;height:100vh}
.side{width:340px;min-width:340px;border-right:1px solid var(--line);overflow:auto;background:var(--panel)}
.main{flex:1;overflow:auto;padding:24px 34px;max-width:920px}
.brand{padding:15px 18px;border-bottom:1px solid var(--line);font-weight:700}
.brand small{display:block;color:var(--dim);font-weight:400;margin-top:3px}
form{padding:12px 14px;border-bottom:1px solid var(--line)}
input,select{width:100%;padding:8px 10px;margin:4px 0;background:#0e1014;border:1px solid var(--line);color:var(--ink);border-radius:7px}
.item{display:block;padding:10px 16px;border-bottom:1px solid var(--line)}
.item:hover{background:#1d2230}.item b{font-weight:600}
.meta{color:var(--dim);font-size:12px;margin-top:2px}
.toggles{position:sticky;top:0;background:var(--bg);padding:10px 0;border-bottom:1px solid var(--line);margin-bottom:10px;z-index:5}
.toggles a{display:inline-block;padding:5px 13px;border:1px solid var(--line);border-radius:20px;margin-right:8px;color:var(--dim)}
.toggles a.on{background:#222838;color:var(--ink);border-color:#445566}
.turn{margin:16px 0;padding:13px 16px;border-radius:10px;border:1px solid var(--line)}
.turn.user{background:#11161f}.turn.ai{background:#15121f}
.turn.step{background:#0e1410;border-style:dashed;font-family:ui-monospace,Menlo,monospace;font-size:13px;color:#9fd6b0}
.who{font-weight:700;font-size:13px;margin-bottom:5px}
.badge{display:inline-block;font-size:11px;padding:1px 7px;border-radius:20px;margin-left:7px;background:#222838}
.who span.t{float:right;color:var(--dim);font-weight:400;font-size:12px}
.turn pre{white-space:pre-wrap;word-wrap:break-word;margin:0;font:inherit}
.step pre{font-family:inherit}
.hdr{border-bottom:1px solid var(--line);padding-bottom:12px;margin-bottom:6px}
.hdr h1{margin:0 0 8px}.tag{display:inline-block;background:#222838;color:var(--dim);padding:2px 9px;border-radius:20px;font-size:12px;margin:2px 6px 2px 0}
mark{background:#5b4a00;color:#ffe98a}.empty{color:var(--dim);padding:40px;text-align:center}
"""


def model_color(model):
    m = (model or "").lower()
    for k, c in MODEL_COLORS.items():
        if k in m:
            return c
    return "#9aa3b2"


def db():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def page(body, title="Lucy's Tape"):
    return (f"<!doctype html><meta charset=utf-8><title>{html.escape(title)}</title>"
            f"<style>{CSS}</style>{body}").encode()


def sidebar(con, q="", project=""):
    projects = [r["project"] for r in con.execute(
        "SELECT project,COUNT(*) n FROM conversations GROUP BY project ORDER BY n DESC")]
    opts = "".join(f'<option value="{html.escape(p)}"{" selected" if p==project else ""}>{html.escape(p)}</option>' for p in projects)
    if q:
        rows = con.execute("SELECT c.* FROM fts f JOIN conversations c ON c.session_id=f.session_id WHERE fts MATCH ? "
                           + ("AND c.project=? " if project else "") + "ORDER BY rank LIMIT 300",
                           ([q, project] if project else [q])).fetchall()
    else:
        rows = con.execute("SELECT * FROM conversations " + ("WHERE project=? " if project else "")
                           + "ORDER BY started DESC LIMIT 300", ([project] if project else [])).fetchall()
    items = "".join(
        f'<a class=item href="/c/{r["session_id"]}?q={html.escape(q)}"><b>{html.escape(r["title"])}</b>'
        f'<div class=meta>{(r["started"] or "")[:10]} · {html.escape(r["project"])} · {r["n_dialogue"]} turns · '
        f'{r["n_steps"]} steps · {html.escape((r["models"] or "?").split(",")[0])}</div></a>' for r in rows)
    return (f'<div class=side><div class=brand>📼 Lucy\'s Tape<small>{len(projects)} projects · full-text search</small></div>'
            f'<form method=get action=/><input name=q placeholder="search all conversations…" value="{html.escape(q)}" autofocus>'
            f'<select name=project onchange="this.form.submit()"><option value="">all projects</option>{opts}</select></form>'
            f'{items or "<div class=empty>no matches</div>"}</div>')


def render(con, sid, q, show_personal, show_arch):
    rows = con.execute("SELECT role,kind,ts,model,text FROM turns WHERE session_id=? ORDER BY idx", [sid]).fetchall()
    out = []
    for r in rows:
        kind, role, model, text = r["kind"], r["role"], r["model"], r["text"]
        # 'note' (hand-saved prehistory captures) rides the Personal toggle: it IS
        # the human dialogue, just without turn structure. Unknown kinds must be
        # filtered too — an unmatched kind would otherwise always render.
        if kind in ("dialogue", "note") and not show_personal:
            continue
        if kind == "step" and not show_arch:
            continue
        body = html.escape(text)
        if q:
            for term in set(t for t in q.split() if len(t) > 1):
                body = body.replace(html.escape(term), f"<mark>{html.escape(term)}</mark>")
        ts = (r["ts"] or "")[:19].replace("T", " ")
        if kind == "step":
            out.append(f'<div class="turn step"><pre>🔧 {body}</pre></div>')
        elif kind == "note":
            out.append(f'<div class="turn user"><div class="who">📜 Note<span class=t>{ts}</span></div><pre>{body}</pre></div>')
        else:
            cls = "user" if role == "user" else "ai"
            who = "🧑 You" if role == "user" else "🤖 Claude"
            badge = "" if role == "user" else f'<span class=badge style="color:{model_color(model)}">{html.escape(model or "?")}</span>'
            out.append(f'<div class="turn {cls}"><div class="who">{who}{badge}<span class=t>{ts}</span></div><pre>{body}</pre></div>')
    return "".join(out) or '<div class=empty>(nothing in this layer — toggle the other one on)</div>'


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        q = qs.get("q", [""])[0]
        project = qs.get("project", [""])[0]
        # layer toggles: default both on
        p_on = qs.get("personal", ["1"])[0] != "0"
        a_on = qs.get("arch", ["1"])[0] != "0"
        con = db()
        if u.path == "/":
            self.send(page(f'<div class=wrap>{sidebar(con,q,project)}<div class=main>'
                           f'<div class=empty>Pick a conversation, or search.</div></div></div>'))
        elif u.path.startswith("/c/"):
            sid = u.path[3:]
            r = con.execute("SELECT * FROM conversations WHERE session_id=?", [sid]).fetchone()
            if not r:
                self.send(page("<div class=empty>not found</div>"), 404)
                con.close()
                return
            base = f'/c/{sid}?q={html.escape(q)}'
            tg = (f'<div class=toggles>'
                  f'<a class="{"on" if p_on else ""}" href="{base}&personal={0 if p_on else 1}&arch={1 if a_on else 0}">🧑 Personal</a>'
                  f'<a class="{"on" if a_on else ""}" href="{base}&personal={1 if p_on else 0}&arch={0 if a_on else 1}">🏛️ Architect</a></div>')
            hdr = (f'<div class=hdr><h1>{html.escape(r["title"])}</h1>'
                   f'<span class=tag>📁 {html.escape(r["project"])}</span>'
                   f'<span class=tag>📅 {(r["started"] or "")[:16].replace("T"," ")}</span>'
                   f'<span class=tag>🤖 {html.escape(r["models"] or "?")}</span>'
                   f'<span class=tag>💬 {r["n_dialogue"]} · 🔧 {r["n_steps"]}</span></div>')
            self.send(page(f'<div class=wrap>{sidebar(con,q,project)}<div class=main>{hdr}{tg}'
                           f'{render(con,sid,q,p_on,a_on)}</div></div>', r["title"]))
        else:
            self.send(page("<div class=empty>404</div>"), 404)
        con.close()


def main():
    if not DB.exists():
        print(f"No database at {DB}. Run: tape update  (or tape build on a clone)")
        sys.exit(1)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()


if __name__ == "__main__":
    main()
