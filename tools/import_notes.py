#!/usr/bin/env python3
"""Lucy's Tape — import your PREHISTORY: hand-saved conversation captures from
before the archive existed.

READ-ONLY on the sources. Point it at a folder of plain-text captures (the
conversations you saved by hand before you had a tape) and each becomes an
archive entry of the distinct `note` kind: no fake turn structure or model
badges — the raw text doesn't carry them, and the archive never invents data.

Why this exists: Claude Code's ~30-day cleanup deletes session JSONL, so for
most people the only surviving copies of their early conversations are manual
saves. This rescues them.

What is deliberately excluded:
  - files under MIN_BYTES: jottings / scraps, not conversations (tiny files are
    also where stray plaintext secrets tend to live — found live, once)
  - captures whose text is contained in a larger capture (incremental re-saves)

Every byte passes the same redactor as the main extractor on the way in.

Idempotent: stable sids derived from filenames; re-runs overwrite the same files.

Usage: python3 tools/import_notes.py <notes_dir> [archive_dir] [--glob 'PATTERN']
       (default glob: *.txt)
"""
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "extract_conversations", Path(__file__).resolve().parent / "extract_conversations.py")
_ec = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ec)
redact, slugify, _red = _ec.redact, _ec.slugify, _ec._red
meta_text, path_component, escape_body = _ec.meta_text, _ec.path_component, _ec.escape_body

_args = [a for a in sys.argv[1:] if not a.startswith("--")]
GLOB = "*.txt"
for i, a in enumerate(sys.argv[1:]):
    if a == "--glob" and i + 2 <= len(sys.argv[1:]):
        GLOB = sys.argv[1:][i + 1]
if not _args:
    sys.exit("Usage: python3 tools/import_notes.py <notes_dir> [archive_dir] [--glob 'PATTERN']")
NOTES = Path(_args[0]).expanduser()
ARCHIVE = Path(_args[1]).expanduser() if len(_args) > 1 else Path(__file__).resolve().parent.parent / "archive"
PROJECT = "notes-prehistory"
OUT_DIR = ARCHIVE / "conversations" / PROJECT
MIN_BYTES = 200


def mtime_iso(path):
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def derive_title(text, fallback):
    for line in text.splitlines():
        line = re.sub(r"[#*`>\-=|]+", " ", line).strip()
        if len(line) >= 8:
            return line[:80]
    return fallback


def load_candidates(notes_dir):
    """Readable captures, redacted, with skip reasons for the rest."""
    kept, skipped = [], []
    for p in sorted(notes_dir.glob(GLOB)):
        try:
            size = p.stat().st_size
            if size < MIN_BYTES:
                skipped.append((p.name, f"jotting ({size}B < {MIN_BYTES}B)"))
                continue
            kept.append((p, redact(p.read_text(encoding="utf-8", errors="replace"))))
        except OSError as e:
            skipped.append((p.name, f"unreadable: {e}"))
    return kept, skipped


def drop_contained(candidates):
    """Drop captures whose normalized text is contained in a larger capture."""
    norm = [(p, t, re.sub(r"\s+", " ", t).strip()) for p, t in candidates]
    norm.sort(key=lambda x: len(x[2]))
    kept, dropped = [], []
    for i, (p, t, n) in enumerate(norm):
        container = next((q.name for q, _, m in norm[i + 1:] if len(m) > len(n) and n in m), None)
        if container:
            dropped.append((p.name, f"contained in {container}"))
        else:
            kept.append((p, t))
    return kept, dropped


def write_note(path, text):
    ts = mtime_iso(path)
    sid = f"note-{path_component(slugify(path.stem))}"
    title = meta_text(derive_title(text, path.stem))
    fab = {"sid": sid, "started": ts, "ended": ts, "models": "", "branch": "",
           "n_dialogue": 1, "user_turns": 1, "assistant_turns": 0, "n_steps": 0,
           "project": PROJECT}
    out = OUT_DIR / f"{ts[:10]}__{slugify(title)}__{sid}.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"<!--fab {json.dumps(fab, separators=(',', ':'))}-->\n\n")
        f.write(f"# {title}\n\n| | |\n|---|---|\n")
        f.write(f"| **Project** | {PROJECT} |\n| **Saved** | {ts} |\n")
        f.write(f"| **Source** | hand-saved capture `{meta_text(path.name, 120)}` (pre-archive era) |\n")
        f.write(f"| **Session** | `{sid}` |\n\n---\n")
        f.write(f"\n<!--t role=user kind=note model=- ts={ts}-->\n")
        f.write(f"### 📜 Note · {ts[:19].replace('T', ' ')}\n\n{escape_body(text)}\n")
    return out


def main():
    if not NOTES.is_dir():
        sys.exit(f"notes folder not found: {NOTES}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    candidates, skipped = load_candidates(NOTES)
    candidates, contained = drop_contained(candidates)
    written = [write_note(p, t) for p, t in candidates]

    with open(OUT_DIR / "README.md", "w", encoding="utf-8") as f:
        f.write("# 📜 notes-prehistory — the manual archive era\n\n"
                f"Hand-saved conversation captures imported from a notes folder (`{meta_text(GLOB, 80)}`) — "
                "the conversations saved by hand before the tape existed. Dates are file "
                "mtimes; titles are derived first lines; every byte passed the redactor "
                "on import.\n\n"
                f"**{len(written)} imported** · {len(skipped)} skipped (jottings/scraps) · "
                f"{len(contained)} skipped (re-saves contained in larger captures)\n\n"
                "Skipped, for the record:\n\n"
                + "".join(f"- `{meta_text(n, 120)}` — {meta_text(why, 200)}\n" for n, why in sorted(skipped + contained)))

    print(f"imported          : {len(written)}")
    print(f"skipped jottings  : {len(skipped)}")
    print(f"skipped re-saves  : {len(contained)}")
    print(f"secret redactions : {sum(_red.values())}")
    for label, n in _red.most_common():
        print(f"  {n:6d}  {label}")


if __name__ == "__main__":
    main()
