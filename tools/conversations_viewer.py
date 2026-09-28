#!/usr/bin/env python3
"""Lucy's Tape — local web viewer for the conversation archive.

Zero dependencies (Python stdlib, see docs/adr/0002). Reads conversations.db and
serves a browsable, searchable, layered UI. Two independent layer toggles:
  🧑 Personal  — the human dialogue.
  🏛️ Architect — the technical tool steps (Write→file, Bash:cmd).
Show either alone or both combined. Each turn carries its model badge.

    python3 conversations_viewer.py [ARCHIVE_DIR] [PORT]   # default :8124

Binds to localhost only — and that alone is not an access control: any local account
or process can reach 127.0.0.1, and a web page can reach it through DNS rebinding. So
every request must name this exact host (Host header), and must carry the session cookie
that only the per-launch link can set (see ACCESS_KEY below; LT-SEC-007).

Design notes worth knowing before editing:

* **No web fonts, ever.** This viewer renders an archive of private
  conversations. Fetching a font from a CDN would leak the fact and timing of
  use to a third party and break the tool offline. Character comes from system
  serif/mono stacks instead (see --font-display).
* **Works without JavaScript.** Search, filtering, paging and the layer toggles
  are plain links and form submits. JS only *enhances*: theme persistence and
  keyboard shortcuts. Never move a core capability into JS.
* **Every response carries a CSP with a per-response nonce.** The archive holds
  arbitrary text from arbitrary sessions; it is all HTML-escaped, and the CSP is
  the second net so that a future escaping mistake cannot become script
  execution against a page that can read the whole archive.
"""
import html
import re
import secrets
import socket
import sqlite3
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

ARCHIVE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "archive"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8124

# Per-launch access. The whole viewer lives under a secret path, /s/<ACCESS_KEY>/, new at
# every launch; every link it renders carries it, and a request outside it is refused before
# the database is touched. The URL is the capability. A cookie would be simpler, but
# browsers send a host's cookies to every port on it, so another service on 127.0.0.1 that
# you visit could collect and replay it (the v0.3.0 known limit). A path is sent only to the
# URL you open. The page sets no-referrer, so the path never leaves in a Referer header.
ACCESS_KEY = secrets.token_urlsafe(32)
PREFIX = f"/s/{ACCESS_KEY}"
MAX_QUERY_CHARS = 500      # a search longer than this is refused, not run (LT-SEC-010)
MAX_CONCURRENT = 16        # requests handled at once; more are closed (LT-SEC-010)
REQUEST_TIMEOUT_S = 30     # a connection is closed this long after it opened, however it trickles (LT-SEC-010)
# until a request has shown the session cookie (or the key), it gets only this long: a browser
# sends its headers at once, and a local process holding slots must let them go quickly
UNAUTH_TIMEOUT_S = 5
DB = ARCHIVE / "conversations.db"

PAGE_SIZE = 50

# Sentinels for snippet() highlighting. Chosen from the C0 control range because
# conversation text never contains them; they are swapped for <mark> only AFTER
# the surrounding text has been escaped, so the highlight can never inject HTML.
HL_OPEN, HL_CLOSE = "\x02", "\x03"

MODEL_COLORS = {
    "fable": "#c9a6ff", "opus": "#f0a35e", "sonnet": "#7fb2ff",
    "haiku": "#5fd6b0", "codex": "#e08ac0", "user": "#a09889",
}

CSS = """
/* ---------------------------------------------------------------------------
   Lucy's Tape — "the reading room".
   Warm archival palette rather than the usual cold dashboard blue-grey: this is
   somewhere you READ, sometimes for a long time. A serif display face carries
   the titles (system stacks only — see the module docstring on web fonts), a
   copper accent stands in for analog tape, and the conversation runs down a
   vertical spine so a long transcript reads as one continuous reel.
--------------------------------------------------------------------------- */
:root{
  color-scheme: dark;
  --bg:#12110f; --panel:#191815; --elev:#211f1a; --line:#2f2c26; --line-soft:#242119;
  /* --faint carries timestamps, result meta and the result count — all 11.5px,
     which is normal text, so it needs 4.5:1 and not the 3:1 that "it's only a
     caption" reasoning would allow. Measured: 5.18 on --bg, 4.87 on --panel,
     4.52 on --elev. Do not darken it back for looks. */
  --ink:#ece7dd; --dim:#a2998a; --faint:#8d8579;
  --accent:#d98b4a; --accent-ink:#17130f; --accent-soft:rgba(217,139,74,.14);
  --user-bg:#171612; --user-edge:#3a3226;
  --ai-bg:#15161a; --ai-edge:#2b3040;
  --step-bg:#111512; --step-ink:#8fc4a1;
  --mark-bg:#6d4a10; --mark-ink:#ffe6a8;
  --shadow:0 10px 30px rgb(0 0 0 / .45);

  --font-display:"Iowan Old Style","Palatino Linotype",Palatino,"Book Antiqua",Georgia,serif;
  --font-ui:ui-sans-serif,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  --font-mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;
  --radius:11px;
}
html[data-theme="paper"]{
  color-scheme: light;
  --bg:#f5f1e8; --panel:#fffdf7; --elev:#faf6ec; --line:#ded5c4; --line-soft:#e9e1d3;
  /* AA on the paper theme too: 4.53 / 5.02 / 4.73 on bg / panel / elev. */
  --ink:#221f18; --dim:#6b6254; --faint:#766d5d;
  --accent:#a2551b; --accent-ink:#fffdf7; --accent-soft:rgba(162,85,27,.10);
  --user-bg:#fffdf7; --user-edge:#dcd0b8;
  --ai-bg:#f7f8fc; --ai-edge:#ccd3e4;
  --step-bg:#f2f6f2; --step-ink:#2f6b48;
  --mark-bg:#ffe08a; --mark-ink:#3a2a00;
  --shadow:0 10px 26px rgb(70 55 30 / .12);
}

*{box-sizing:border-box}
html,body{height:100%}
body{
  margin:0; background:var(--bg); color:var(--ink);
  font:15px/1.65 var(--font-ui);
  -webkit-font-smoothing:antialiased;
}
a{color:var(--accent); text-decoration:none}
a:hover{text-decoration:underline}
:focus-visible{outline:2px solid var(--accent); outline-offset:2px; border-radius:4px}

.skip{position:absolute;left:-9999px;top:0;z-index:100;padding:10px 14px;background:var(--accent);color:var(--accent-ink);border-radius:0 0 var(--radius) 0}
.skip:focus{left:0}

.wrap{display:flex; min-height:100vh}

/* ---- sidebar ------------------------------------------------------------ */
.side{
  width:372px; min-width:372px; background:var(--panel);
  border-right:1px solid var(--line); display:flex; flex-direction:column;
  height:100vh; position:sticky; top:0;
}
.brand{
  padding:16px 18px 13px; border-bottom:1px solid var(--line);
  display:flex; align-items:baseline; gap:9px;
}
.brand .logo{font-size:19px; line-height:1}
.brand b{font:600 17px/1.2 var(--font-display); letter-spacing:.01em}
.brand small{display:block; color:var(--dim); font-size:11.5px; margin-top:3px; letter-spacing:.03em}
.brand .spacer{margin-left:auto}
.iconbtn{
  background:var(--elev); border:1px solid var(--line); color:var(--dim);
  width:30px; height:30px; border-radius:8px; cursor:pointer; font-size:13px;
  display:inline-flex; align-items:center; justify-content:center;
}
.iconbtn:hover{color:var(--ink); border-color:var(--accent)}

.searchbar{padding:12px 14px; border-bottom:1px solid var(--line); display:grid; gap:7px}
.searchrow{display:flex; gap:7px}
/* The field must be allowed to shrink INSIDE the row. Without min-width:0 a flex
   item refuses to go below its intrinsic width and the button wraps to its own
   line, which on a phone pushed the first result below the fold. */
.searchrow input[type=search]{flex:1; min-width:0; width:auto}
input[type=search],select{
  width:100%; padding:9px 11px; background:var(--bg); color:var(--ink);
  border:1px solid var(--line); border-radius:9px; font:14px var(--font-ui);
}
input[type=search]::placeholder{color:var(--faint)}
input[type=search]:focus,select:focus{border-color:var(--accent); outline:none}
.btn{
  padding:9px 14px; border-radius:9px; border:1px solid var(--line);
  background:var(--elev); color:var(--ink); font:500 13.5px var(--font-ui); cursor:pointer;
  white-space:nowrap;
}
.btn:hover{border-color:var(--accent)}
.btn--go{background:var(--accent); color:var(--accent-ink); border-color:var(--accent)}
.hint{font-size:11.5px; color:var(--faint)}
.hint kbd{
  font:11px var(--font-mono); border:1px solid var(--line); border-bottom-width:2px;
  border-radius:4px; padding:0 4px; color:var(--dim); background:var(--elev);
}

.results{overflow-y:auto; flex:1; scrollbar-width:thin}
.resulthead{
  padding:9px 16px; font-size:11.5px; letter-spacing:.06em; text-transform:uppercase;
  color:var(--faint); border-bottom:1px solid var(--line-soft);
  position:sticky; top:0; background:var(--panel); z-index:2;
}
.item{
  display:block; padding:12px 16px; border-bottom:1px solid var(--line-soft);
  border-left:3px solid transparent; color:inherit;
}
.item:hover{background:var(--elev); text-decoration:none}
.item:focus-visible{outline-offset:-2px}
.item[aria-current="true"]{border-left-color:var(--accent); background:var(--accent-soft)}
.item .t{font:600 14.5px/1.35 var(--font-display); color:var(--ink); display:block}
.item .snip{
  display:block; margin-top:4px; font-size:12.5px; line-height:1.5; color:var(--dim);
  overflow-wrap:anywhere;
}
.item .meta{
  margin-top:5px; font-size:11.5px; color:var(--faint);
  display:flex; flex-wrap:wrap; gap:4px 9px; font-variant-numeric:tabular-nums;
}
.pager{display:flex; gap:8px; align-items:center; justify-content:space-between; padding:12px 16px}
.pager span{font-size:12px; color:var(--faint); font-variant-numeric:tabular-nums}

/* ---- main --------------------------------------------------------------- */
.main{flex:1; min-width:0; padding:26px 34px 90px; max-width:88ch; margin:0 auto; width:100%}
.hdr{border-bottom:1px solid var(--line); padding-bottom:15px}
.hdr h1{
  margin:0 0 9px; font:600 27px/1.25 var(--font-display); letter-spacing:.005em;
  overflow-wrap:anywhere;
}
.tags{display:flex; flex-wrap:wrap; gap:6px}
.tag{
  display:inline-flex; align-items:center; gap:5px; background:var(--elev);
  color:var(--dim); padding:3px 10px; border-radius:999px; font-size:12px;
  border:1px solid var(--line-soft); font-variant-numeric:tabular-nums;
}

.toggles{
  position:sticky; top:0; z-index:5; display:flex; flex-wrap:wrap; gap:8px; align-items:center;
  padding:11px 0; margin-bottom:6px; background:var(--bg); border-bottom:1px solid var(--line-soft);
}
.toggle{
  display:inline-flex; align-items:center; gap:6px; padding:5px 13px; border-radius:999px;
  border:1px solid var(--line); color:var(--dim); font-size:13px; background:var(--panel);
}
.toggle:hover{text-decoration:none; border-color:var(--accent)}
.toggle[aria-pressed="true"]{background:var(--accent-soft); color:var(--ink); border-color:var(--accent)}
.toggle .dot{width:7px; height:7px; border-radius:50%; background:var(--faint)}
.toggle[aria-pressed="true"] .dot{background:var(--accent)}
.count{margin-left:auto; font-size:12px; color:var(--faint); font-variant-numeric:tabular-nums}

/* The reel: one continuous spine down the transcript. */
.reel{position:relative; padding-left:22px; margin-top:14px}
.reel::before{
  content:""; position:absolute; left:5px; top:6px; bottom:6px; width:2px;
  background:linear-gradient(180deg, transparent, var(--line) 6%, var(--line) 94%, transparent);
}
.turn{position:relative; margin:0 0 15px; padding:13px 16px; border-radius:var(--radius); border:1px solid var(--line)}
.turn::before{
  content:""; position:absolute; left:-21px; top:19px; width:9px; height:9px;
  border-radius:50%; background:var(--bg); border:2px solid var(--line);
}
.turn:target{box-shadow:0 0 0 2px var(--accent)}
.turn.user{background:var(--user-bg); border-color:var(--user-edge)}
.turn.user::before{border-color:var(--accent); background:var(--accent)}
.turn.ai{background:var(--ai-bg); border-color:var(--ai-edge)}
.turn.step{
  background:var(--step-bg); border-style:dashed; color:var(--step-ink);
  font:13px/1.55 var(--font-mono); padding:9px 14px; margin-bottom:9px;
}
.turn.step::before{width:6px; height:6px; left:-19.5px; top:15px; border-style:dashed}
.who{
  display:flex; align-items:center; gap:8px; font-weight:600; font-size:13px; margin-bottom:6px;
}
.who .ts{margin-left:auto; color:var(--faint); font-weight:400; font-size:11.5px; font-variant-numeric:tabular-nums}
.who .anchor{color:var(--faint); font-size:12px; opacity:0; transition:opacity .12s}
.turn:hover .who .anchor,.who .anchor:focus{opacity:1}
.badge{
  font:500 11px var(--font-mono); padding:1px 8px; border-radius:999px;
  background:var(--elev); border:1px solid var(--line-soft);
}
.turn pre{white-space:pre-wrap; overflow-wrap:anywhere; margin:0; font:inherit}

mark{background:var(--mark-bg); color:var(--mark-ink); border-radius:3px; padding:0 2px}

.empty{color:var(--dim); padding:56px 24px; text-align:center}
.empty h2{font:600 20px var(--font-display); color:var(--ink); margin:0 0 8px}
.empty p{margin:6px auto; max-width:46ch; font-size:13.5px}
.empty code{font:12.5px var(--font-mono); background:var(--elev); padding:1px 6px; border-radius:5px; color:var(--accent)}

@media (prefers-reduced-motion: reduce){*{animation:none !important; transition:none !important}}

/* ---- narrow viewports ---------------------------------------------------
   The rail stacks above the transcript with its own bounded scroll, so a phone
   user never has to scroll past the whole result list to reach the reading
   column. No drawer: the nav stays visible, just capped. ---------------- */
@media (max-width: 60rem){
  .wrap{flex-direction:column}
  .side{
    width:100%; min-width:0; height:auto; max-height:52vh; position:static;
    border-right:none; border-bottom:1px solid var(--line);
  }
  .main{padding:20px 18px 70px; max-width:none}
  .hdr h1{font-size:22px}
  /* Keyboard hints on a device with no keyboard are pure vertical cost. */
  .hint{display:none}
}
@media (max-width: 30rem){
  .side{max-height:46vh}
  .main{padding:16px 13px 60px}
  .reel{padding-left:16px}
  .turn::before{left:-15px}
  .turn.step::before{left:-13.5px}
  .hdr h1{font-size:20px}
}
"""

JS = """
// Progressive enhancement ONLY. Every capability below has a no-JS equivalent:
// search and paging are form submits and links, the layer toggles are links.
(function(){
  var root = document.documentElement;
  var KEY = 'lucys-tape-theme';
  function apply(t){ if(t){ root.setAttribute('data-theme', t); } }
  try { apply(localStorage.getItem(KEY)); } catch(e) {}

  var btn = document.getElementById('theme');
  if (btn) btn.addEventListener('click', function(){
    var now = root.getAttribute('data-theme') === 'paper' ? 'reel' : 'paper';
    apply(now);
    try { localStorage.setItem(KEY, now); } catch(e) {}
    btn.setAttribute('aria-label', now === 'paper' ? 'Switch to dark' : 'Switch to light');
  });

  var box = document.querySelector('input[type=search]');
  var items = Array.prototype.slice.call(document.querySelectorAll('.item'));
  var cur = items.findIndex(function(el){ return el.getAttribute('aria-current') === 'true'; });

  document.addEventListener('keydown', function(e){
    var typing = /^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName);
    if (e.key === '/' && !typing) { e.preventDefault(); if (box) { box.focus(); box.select(); } return; }
    if (e.key === 'Escape' && typing) { document.activeElement.blur(); return; }
    if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === 'j' || e.key === 'k') {
      if (!items.length) return;
      e.preventDefault();
      cur = Math.max(0, Math.min(items.length - 1, cur + (e.key === 'j' ? 1 : -1)));
      items[cur].focus();
      items[cur].scrollIntoView({block:'nearest'});
    }
  });

  // Auto-submit the project filter, but only when JS is present; the form still
  // has a real submit button for everyone else.
  var proj = document.querySelector('select[name=project]');
  if (proj) proj.addEventListener('change', function(){ proj.form.submit(); });
})();
"""


def model_slug(model):
    """Map a model name onto a badge CSS class.

    This returns a CLASS, not a colour, because the page's CSP has no
    'unsafe-inline' in style-src — and a nonce authorises a <style> ELEMENT,
    never a style ATTRIBUTE. An inline `style="color:…"` is therefore silently
    dropped by the browser: the page still renders, the tests still pass, and the
    badge is simply colourless. Found only by opening it in a browser.
    """
    m = (model or "").lower()
    for k in MODEL_COLORS:
        if k in m:
            return k
    return "default"


def model_css():
    """Badge colours, generated from MODEL_COLORS so the map stays single-source."""
    rules = "".join(f".badge--{k}{{color:{c}}}" for k, c in MODEL_COLORS.items())
    return rules + ".badge--default{color:var(--dim)}"


def db():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


# Characters that are FTS5 query syntax rather than content. Stripped from every
# bare token, because we re-quote each token into a literal phrase anyway.
_FTS_SYNTAX = re.compile(r'["*()^:]')
# A "quoted phrase", or a run of non-space non-quote characters. Ordering the
# alternatives this way keeps the user's terms in the order they typed them, and
# an unterminated quote simply matches nothing and is dropped.
_TOKEN = re.compile(r'"([^"]*)"|([^\s"]+)')


def fts_query(raw):
    """Turn arbitrary user input into a MATCH expression that cannot be a syntax error.

    FTS5's query language treats `"`, `*`, `AND`, `OR`, `NOT`, `NEAR`, `(` and `:`
    as syntax. Passing a raw search box straight to MATCH means an ordinary human
    typing `what did he say about "the fox"` gets an OperationalError and a dead
    page.

    So: a properly "quoted phrase" is honoured as a phrase, and every remaining
    token is re-quoted into a literal phrase, which is always valid — that is what
    makes bare `AND`/`OR`/`NEAR` searchable as the words people meant rather than
    operators they did not know they typed.

    A single trailing `*` is preserved as a prefix search, because it is the one
    piece of query syntax people actually reach for and `"fox"*` is legal FTS5.

    Returns "" when nothing searchable survives, which callers treat as "browse".
    """
    parts = []
    for m in _TOKEN.finditer(raw or ""):
        quoted, bare = m.group(1), m.group(2)
        if quoted is not None:
            phrase = _FTS_SYNTAX.sub(" ", quoted).strip()
            if phrase:
                parts.append(f'"{phrase}"')
            continue
        prefix = len(bare) > 1 and bare.endswith("*")
        core = _FTS_SYNTAX.sub("", bare[:-1] if prefix else bare).strip()
        if core:
            parts.append(f'"{core}"' + ("*" if prefix else ""))
    return " ".join(parts)


def highlight_terms(raw):
    """The bare words a user typed, for highlighting inside a rendered turn."""
    return [t for t in (re.sub(r'["*()]', " ", raw or "")).split() if len(t) > 1]


def highlight(text, terms):
    """Escape `text`, wrapping case-insensitive matches of `terms` in <mark>.

    Highlighting must happen against the RAW text and escape around the matches.
    Escaping first and then string-replacing (the obvious approach) is wrong twice
    over: it is case-sensitive, so an FTS hit on "Fox" shows a result with nothing
    marked; and it matches inside HTML entities, so searching `amp` rewrites
    `&amp;` into `&<mark>amp</mark>;` and corrupts the output.
    """
    if not terms:
        return html.escape(text)
    rx = re.compile("|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True)), re.I)
    out, last = [], 0
    for m in rx.finditer(text):
        out.append(html.escape(text[last:m.start()]))
        out.append(f"<mark>{html.escape(m.group(0))}</mark>")
        last = m.end()
    out.append(html.escape(text[last:]))
    return "".join(out)


def escape_snippet(snip):
    """Escape a snippet() result, then turn its sentinels into <mark>."""
    return (html.escape(snip or "")
            .replace(HL_OPEN, "<mark>").replace(HL_CLOSE, "</mark>"))


def as_int(value):
    """A count from the DB, as a number whatever the archive stored (LT-SEC-008)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def url(path, **params):
    """A link inside this launch's viewer: path is the route ("/", "/c/<id>")."""
    clean = {k: v for k, v in params.items() if v not in ("", None)}
    return f"{PREFIX}{path}?{urlencode(clean)}" if clean else f"{PREFIX}{path}"


def clamp_page(page, total):
    """Last page for `total` rows, never below 1."""
    return max(1, min(page, max(1, -(-total // PAGE_SIZE))))


def search(con, q, project, page):
    """Return (rows, total, page). One row per conversation, best-ranked snippet kept.

    `page` is CLAMPED to the last page that has rows, and the clamped value is
    returned so the caller can render honest pagination. Slicing past the end
    instead would return zero rows with a non-zero total, and the empty state
    would tell a user whose search matched 40 conversations that nothing
    matched — indistinguishable from a genuine miss.

    build_db writes one FTS row per KIND (dialogue, step), so a term present in
    both a message and a tool step matches twice and a naive JOIN lists the same
    conversation twice. Grouping by session_id and ordering by MIN(rank) collapses
    them while keeping the best match — DISTINCT would drop the rank instead.
    """
    match = fts_query(q)

    if not match:
        where, args = ("WHERE project = ?", [project]) if project else ("", [])
        total = con.execute(f"SELECT COUNT(*) FROM conversations {where}", args).fetchone()[0]
        page = clamp_page(page, total)
        rows = con.execute(
            f"SELECT * FROM conversations {where} ORDER BY started DESC LIMIT ? OFFSET ?",
            args + [PAGE_SIZE, (page - 1) * PAGE_SIZE]).fetchall()
        return [dict(r, snip=None) for r in rows], total, page

    # snippet() and rank are FTS5 *auxiliary* functions: legal in a plain query
    # over the fts table (a JOIN is fine), but NOT in an aggregate context. Any
    # GROUP BY here — including one hidden inside a subquery, which SQLite's
    # flattener will inline — raises "unable to use function snippet in the
    # requested context". So the de-duplication happens in Python instead, which
    # also keeps this working on whatever SQLite a user's Python happens to bundle
    # rather than depending on optimizer behaviour or a MATERIALIZED CTE.
    # PHASE 1 — rank and de-duplicate ids only. Deliberately NO snippet() here.
    # snippet() is expensive and computing it for every match just to throw all
    # but one page away is quadratic misery on a real archive: measured 217.8s
    # for q="the" over 8,936 conversations (~18k matching FTS rows), against
    # 0.5s for a rare term. Ids alone are cheap.
    sql = ("SELECT f.session_id AS sid FROM fts f "
           "JOIN conversations c ON c.session_id = f.session_id WHERE fts MATCH ?")
    args = [match]
    if project:
        sql += " AND c.project = ?"
        args.append(project)
    sql += " ORDER BY rank"
    try:
        hits = con.execute(sql, args).fetchall()
    except sqlite3.OperationalError:
        # Backstop. fts_query is meant to make this unreachable; if a query shape
        # still slips through, an empty result set is survivable and a traceback
        # into a half-written socket is not.
        return [], 0, 1

    # build_db writes one FTS row per KIND, so a term present in both a message
    # and a tool step matches twice. Rows arrive best-ranked first and dict
    # preserves insertion order, so this keeps each conversation at its best rank.
    seen = {}
    for h in hits:
        seen.setdefault(h["sid"], None)

    sids = list(seen)
    total = len(sids)
    page = clamp_page(page, total)
    offset = (page - 1) * PAGE_SIZE
    window = sids[offset:offset + PAGE_SIZE]
    if not window:
        return [], total, page

    # PHASE 2 — snippets for THIS PAGE only: at most PAGE_SIZE conversations, so
    # at most 2*PAGE_SIZE rows regardless of how many matched overall.
    placeholders = ",".join("?" * len(window))
    best = {}
    for r in con.execute(
            f"SELECT session_id AS sid, snippet(fts, 4, ?, ?, '…', 14) AS snip "
            f"FROM fts WHERE fts MATCH ? AND session_id IN ({placeholders}) ORDER BY rank",
            [HL_OPEN, HL_CLOSE, match] + window):
        best.setdefault(r["sid"], r["snip"])

    by_id = {r["session_id"]: r for r in con.execute(
        f"SELECT * FROM conversations WHERE session_id IN ({placeholders})", window)}
    return [dict(by_id[s], snip=best.get(s)) for s in window if s in by_id], total, page


def sidebar(con, q="", project="", page=1, active=""):
    projects = [(r["project"], r["n"]) for r in con.execute(
        "SELECT project, COUNT(*) n FROM conversations GROUP BY project ORDER BY n DESC")]
    opts = "".join(
        f'<option value="{html.escape(p)}"{" selected" if p == project else ""}>'
        f'{html.escape(p)} ({n})</option>' for p, n in projects)

    rows, total, page = search(con, q, project, page)
    pages = max(1, -(-total // PAGE_SIZE))

    items = []
    for r in rows:
        snip = escape_snippet(r["snip"]) if r["snip"] else ""
        is_active = r["session_id"] == active
        items.append(
            f'<a class=item href="{html.escape(url("/c/" + quote(r["session_id"], safe=""), q=q, project=project, page=page))}"'
            f'{" aria-current=true" if is_active else ""}>'
            f'<span class=t>{html.escape(r["title"])}</span>'
            + (f'<span class=snip>{snip}</span>' if snip else "")
            + f'<span class=meta><span>{html.escape((r["started"] or "")[:10])}</span>'
              f'<span>{html.escape(r["project"])}</span>'
              f'<span>💬 {as_int(r["n_dialogue"])}</span><span>🔧 {as_int(r["n_steps"])}</span>'
              f'<span>{html.escape((r["models"] or "?").split(",")[0].strip())}</span></span></a>')

    if items:
        label = (f"{total:,} result{'' if total == 1 else 's'}" if q
                 else f"{total:,} conversation{'' if total == 1 else 's'}")
        head = f'<div class=resulthead>{label}{f" · page {page} of {pages}" if pages > 1 else ""}</div>'
        body = "".join(items)
    elif q:
        head = '<div class=resulthead>no results</div>'
        body = ('<div class=empty><h2>Nothing matched</h2>'
                f'<p>No conversation contains {html.escape(repr(q))}.</p>'
                '<p>Words are searched literally and combined with AND. '
                'Add <code>*</code> for a prefix search, e.g. <code>redact*</code>.</p></div>')
    else:
        head = '<div class=resulthead>empty archive</div>'
        body = ('<div class=empty><h2>No conversations yet</h2>'
                '<p>Run <code>tape update</code> to extract, or <code>tape build</code> '
                'on a fresh clone.</p></div>')

    pager = ""
    if pages > 1:
        prev = (f'<a class=btn href="{html.escape(url("/", q=q, project=project, page=page - 1))}">← prev</a>'
                if page > 1 else '<span class=btn aria-disabled=true>← prev</span>')
        nxt = (f'<a class=btn href="{html.escape(url("/", q=q, project=project, page=page + 1))}">next →</a>'
               if page < pages else '<span class=btn aria-disabled=true>next →</span>')
        pager = f'<div class=pager>{prev}<span>{page} / {pages}</span>{nxt}</div>'

    return (
        '<nav class=side aria-label="Archive">'
        '<div class=brand><span class=logo aria-hidden=true>📼</span>'
        "<div><b>Lucy&#39;s Tape</b>"
        f'<small>{len(projects)} projects · full-text search</small></div>'
        '<span class=spacer></span>'
        # Inline SVG, not a "◐" glyph: U+25D0 is missing from plenty of system
        # font stacks and renders as tofu. An icon that depends on a font the
        # user may not have is a coin flip.
        '<button class=iconbtn id=theme type=button aria-label="Switch theme" '
        'title="Switch theme (light / dark)">'
        # Attribute values are QUOTED. In HTML an unquoted attribute value ends at
        # whitespace or ">", never at "/", so `fill=currentColor/>` parses as the
        # value "currentColor/" — an invalid colour that silently paints nothing.
        # The geometry was correct and the icon was simply blank.
        '<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true" focusable="false">'
        '<circle cx="8" cy="8" r="6.2" fill="none" stroke="currentColor" stroke-width="1.4" />'
        '<path d="M8 1.8a6.2 6.2 0 0 0 0 12.4z" fill="currentColor" /></svg></button>'
        '</div>'
        f'<form class=searchbar method=get action="{html.escape(url("/"))}" role=search>'
        f'<div class=searchrow>'
        f'<input type=search name=q placeholder="search every conversation…" '
        f'value="{html.escape(q)}" aria-label="Search conversations">'
        f'<button class="btn btn--go" type=submit>Search</button></div>'
        f'<select name=project aria-label="Filter by project">'
        f'<option value="">all projects</option>{opts}</select>'
        f'<div class=hint><kbd>/</kbd> search · <kbd>j</kbd>/<kbd>k</kbd> move · <kbd>Esc</kbd> unfocus</div>'
        f'</form>'
        f'<div class=results>{head}{body}{pager}</div></nav>')


def render(con, sid, q, show_personal, show_arch):
    rows = con.execute(
        "SELECT role,kind,ts,model,text FROM turns WHERE session_id=? ORDER BY idx", [sid]).fetchall()
    terms = highlight_terms(q)
    out, shown = [], 0
    for i, r in enumerate(rows):
        kind, role, model, text = r["kind"], r["role"], r["model"], r["text"]
        # 'note' (hand-saved prehistory captures) rides the Personal toggle: it IS
        # the human dialogue, just without turn structure. Unknown kinds must be
        # filtered too — an unmatched kind would otherwise always render.
        if kind in ("dialogue", "note") and not show_personal:
            continue
        if kind == "step" and not show_arch:
            continue
        shown += 1
        body = highlight(text, terms)
        ts = html.escape((r["ts"] or "")[:19].replace("T", " "))
        anchor = f"t{i}"
        if kind == "step":
            out.append(f'<div class="turn step" id={anchor}><pre>🔧 {body}</pre></div>')
            continue
        if kind == "note":
            who, cls, badge = "📜 Note", "user", ""
        else:
            cls = "user" if role == "user" else "ai"
            who = "🧑 You" if role == "user" else "🤖 Claude"
            badge = ("" if role == "user" else
                     f'<span class="badge badge--{model_slug(model)}">'
                     f'{html.escape(model or "?")}</span>')
        out.append(
            f'<div class="turn {cls}" id={anchor}><div class=who>{who}{badge}'
            f'<a class=anchor href="#{anchor}" aria-label="Link to this turn">#</a>'
            f'<span class=ts>{ts}</span></div><pre>{body}</pre></div>')
    if not shown:
        return ('<div class=empty><h2>Nothing in this layer</h2>'
                '<p>Both layers are off, or this conversation has no turns of the '
                'kind you are showing. Toggle 🧑 Personal or 🏛️ Architect back on.</p></div>')
    return f'<div class=reel>{"".join(out)}</div>'


def page(body, nonce, title="Lucy's Tape"):
    return (
        "<!doctype html><html lang=en data-theme=reel><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        '<meta name=color-scheme content="dark light">'
        f"<title>{html.escape(title)}</title>"
        f'<style nonce="{nonce}">{CSS}{model_css()}</style></head><body>'
        '<a class=skip href="#main">Skip to conversation</a>'
        f"{body}"
        f'<script nonce="{nonce}">{JS}</script></body></html>').encode()


def same(given, expected):
    """Constant-time comparison that also takes non-ASCII input (compare_digest refuses
    non-ASCII str with an exception)."""
    return given is not None and secrets.compare_digest(given.encode(), expected.encode())


class H(BaseHTTPRequestHandler):
    server_version = "LucysTape"
    sys_version = ""
    timeout = REQUEST_TIMEOUT_S

    def log_message(self, *a):
        pass

    def send(self, data, nonce, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        # The archive is arbitrary text from arbitrary sessions. It is escaped on
        # the way out; this is the second net, so an escaping mistake can never
        # become script execution on a page that can read the whole archive.
        self.send_header("Content-Security-Policy",
                         f"default-src 'none'; style-src 'nonce-{nonce}'; "
                         f"script-src 'nonce-{nonce}'; form-action 'self'; base-uri 'none'; "
                         "frame-ancestors 'none'")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(data)

    def plain(self, code, text, extra=()):
        data = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def route(self, u):
        """The route inside this launch's viewer ("/", "/c/<id>"), or None when the request
        may not read the archive (it has then been answered)."""
        port = self.server.server_address[1]
        if self.headers.get("Host", "") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            self.plain(403, "This viewer only answers at its own address (127.0.0.1).")
            return None
        key, slash, rest = u.path[len("/s/"):].partition("/") if u.path.startswith("/s/") else ("", "", "")
        if not same(key, ACCESS_KEY):
            self.plain(401, "Open the link `tape serve` printed; it carries this launch's key.")
            return None
        self.server.arm(self.request, REQUEST_TIMEOUT_S)  # the user: the full time to answer
        return "/" + rest

    def do_GET(self):
        nonce = secrets.token_urlsafe(16)
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        path = self.route(u)
        if path is None:
            return
        q = qs.get("q", [""])[0]
        if len(q) > MAX_QUERY_CHARS:
            self.send(page(f'<div class=empty><h2>Search too long</h2><p>Keep it under {MAX_QUERY_CHARS} '
                           'characters. <a href="' + html.escape(url("/")) + '">Back to the archive</a>.</p></div>', nonce, "Search too long"),
                      nonce, 400)
            return
        project = qs.get("project", [""])[0]
        try:
            page_no = max(1, int(qs.get("page", ["1"])[0]))
        except ValueError:
            page_no = 1
        p_on = qs.get("personal", ["1"])[0] != "0"
        a_on = qs.get("arch", ["1"])[0] != "0"

        con = None
        try:
            con = db()
            if path == "/":
                body = (f'<div class=wrap>{sidebar(con, q, project, page_no)}'
                        '<main class=main id=main><div class=empty>'
                        "<h2>Pick a conversation</h2>"
                        "<p>Or search the whole archive — every word of every "
                        "conversation is indexed.</p></div></main></div>")
                self.send(page(body, nonce), nonce)
            elif path.startswith("/c/"):
                sid = unquote(path[3:])
                r = con.execute("SELECT * FROM conversations WHERE session_id=?", [sid]).fetchone()
                if not r:
                    self.send(page('<div class=empty><h2>Not found</h2>'
                                   '<p>No conversation with that id. <a href="' + html.escape(url("/")) + '">Back to the archive</a>.</p>'
                                   '</div>', nonce, "Not found"), nonce, 404)
                    return
                base = url(f"/c/{quote(sid, safe='')}", q=q, project=project, page=page_no)
                sep = "&" if "?" in base else "?"
                tg = (
                    '<div class=toggles>'
                    f'<a class=toggle aria-pressed="{"true" if p_on else "false"}" '
                    f'href="{html.escape(base + sep)}personal={0 if p_on else 1}&arch={1 if a_on else 0}">'
                    '<span class=dot></span>🧑 Personal</a>'
                    f'<a class=toggle aria-pressed="{"true" if a_on else "false"}" '
                    f'href="{html.escape(base + sep)}personal={1 if p_on else 0}&arch={0 if a_on else 1}">'
                    '<span class=dot></span>🏛️ Architect</a>'
                    f'<span class=count>{as_int(r["n_dialogue"])} turns · {as_int(r["n_steps"])} steps</span></div>')
                hdr = (f'<header class=hdr><h1>{html.escape(r["title"])}</h1><div class=tags>'
                       f'<span class=tag>📁 {html.escape(r["project"])}</span>'
                       f'<span class=tag>📅 {html.escape((r["started"] or "")[:16].replace("T", " "))}</span>'
                       f'<span class=tag>🤖 {html.escape(r["models"] or "?")}</span>'
                       + (f'<span class=tag>🌿 {html.escape(r["git_branch"])}</span>' if r["git_branch"] else "")
                       + '</div></header>')
                body = (f'<div class=wrap>{sidebar(con, q, project, page_no, active=sid)}'
                        f'<main class=main id=main>{hdr}{tg}'
                        f'{render(con, sid, q, p_on, a_on)}</main></div>')
                self.send(page(body, nonce, r["title"]), nonce)
            else:
                self.send(page('<div class=empty><h2>404</h2>'
                               '<p><a href="' + html.escape(url("/")) + '">Back to the archive</a></p></div>', nonce, "404"),
                          nonce, 404)
        except sqlite3.Error as e:
            # A broken/locked DB must render a page, not a bare traceback into a
            # dead socket. The reason is shown because this is a loopback tool
            # whose only user is the person who can fix it.
            self.send(page('<div class=empty><h2>The archive could not be read</h2>'
                           f'<p><code>{html.escape(str(e))}</code></p>'
                           '<p>Try <code>tape build</code> to rebuild the database.</p></div>',
                           nonce, "Archive error"), nonce, 500)
        finally:
            if con is not None:
                con.close()


class Server(ThreadingHTTPServer):
    """Thread per request, at most MAX_CONCURRENT at once; beyond that a connection is
    closed at once instead of queuing a thread for it (LT-SEC-010)."""
    daemon_threads = True

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.slots = threading.BoundedSemaphore(MAX_CONCURRENT)
        self.deadlines = {}   # request socket → its running deadline timer
        self.deadlines_lock = threading.Lock()

    def arm(self, request, seconds):
        """(Re)start the deadline after which this connection is cut."""
        timer = threading.Timer(seconds, close_socket, (request,))
        timer.daemon = True
        with self.deadlines_lock:
            old = self.deadlines.pop(request, None)
            self.deadlines[request] = timer
        if old is not None:
            old.cancel()
        timer.start()

    def disarm(self, request):
        with self.deadlines_lock:
            timer = self.deadlines.pop(request, None)
        if timer is not None:
            timer.cancel()

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def handle_error(self, request, client_address):
        # a client that hung up (or was cut at the deadline) is not a server error;
        # anything else keeps the full traceback in viewer.log
        if isinstance(sys.exc_info()[1], ConnectionError):
            return
        super().handle_error(request, client_address)

    def process_request_thread(self, request, client_address):
        # the handler's timeout bounds each read; this bounds the whole connection, so a
        # client sending one byte just inside the timeout cannot hold a slot for ever
        self.arm(request, UNAUTH_TIMEOUT_S)
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.disarm(request)
            self.slots.release()


def close_socket(sock):
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass  # already closed by the handler: nothing left to cut


def main():
    if not DB.exists():
        print(f"No database at {DB}. Run: tape update  (or tape build on a clone)")
        sys.exit(1)
    srv = Server(("127.0.0.1", PORT), H)
    # the only place the key is shown: this goes to viewer.log (owner-only), which
    # `tape serve` reads to print the link
    print(f"open: http://127.0.0.1:{PORT}{PREFIX}/", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
