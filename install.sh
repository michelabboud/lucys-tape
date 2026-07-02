#!/usr/bin/env bash
# 📼 Lucy's Tape — one-line bootstrap
#
#   curl -fsSL https://raw.githubusercontent.com/michelabboud/lucys-tape/main/install.sh | bash
#
# Clones the repo to ~/lucys-tape (or $LUCYS_TAPE_DIR) and hands off to the
# interactive `tape init` wizard. Safe to re-run: an existing clone is updated,
# never overwritten, and your archive is never touched.
set -euo pipefail

DIR="${LUCYS_TAPE_DIR:-$HOME/lucys-tape}"
REPO_URL="${LUCYS_TAPE_REPO:-https://github.com/michelabboud/lucys-tape.git}"

say() { printf '📼 %s\n' "$*"; }
die() { printf '  ✗ %s\n' "$*" >&2; exit 1; }

command -v git >/dev/null       || die "git is required — install it and re-run"
command -v python3 >/dev/null   || die "python3 is required (stdlib only, no pip installs)"
[ -d "$HOME/.claude/projects" ] || say "note: ~/.claude/projects not found yet — install/use Claude Code before 'tape update'"

if [ -d "$DIR/.git" ]; then
    say "existing install found at $DIR — updating tools (your archive is untouched)"
    git -C "$DIR" fetch --quiet upstream 2>/dev/null || git -C "$DIR" fetch --quiet origin || true
else
    say "cloning Lucy's Tape → $DIR"
    git clone --quiet "$REPO_URL" "$DIR"
fi

say "handing off to the setup wizard…"
exec "$DIR/tools/tape" init
