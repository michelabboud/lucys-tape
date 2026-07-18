# lucys-tape hardening finale spec (2026-07-18)

**Scope:** the four deferred Highs from `docs/reports/2026-07-16-fable-codex-security-bughunt.md`, in the spot-review's priority order: LT-SEC-004 → LT-SEC-003 → LT-SEC-001 → LT-SEC-002. One codex lane, four sequential tasks, one commit + tag each. Repo is PUBLIC and a gift — no new deps, no new files except one test module, stdlib + bash only, keep the existing voice (say/ok/warn/die, the 📼).

**Doctrine (binding):** over-redaction beats any leak; **refuse beats wrong-destination**. Local extract/build/commit always allowed; anything that leaves the machine fails closed.

---

## T1 — LT-SEC-004: fail-closed destination enforcement

**Files:** `tools/tape` (new fns + `cmd_update` + `cmd_init` + `cmd_doctor` + dispatch), `tests/test_tape_update.py` (new).

### Mechanism

Trust anchor = a **durable explicit trust assertion** stored in *local* git config (never committed, survives pulls): `tape.pushRemote` (exact URL) and `tape.pushRemoteVerified` (`github-private` | `user-asserted`).

1. **New `_gh_slug()`** — parse `owner/repo` from `https://github.com/owner/repo(.git)` and `git@github.com:owner/repo(.git)`; empty output for anything else. Pure bash/sed, no network.

2. **New `_record_trust()`** (shared by `init` and a new `tape trust` command, for existing installs):
   - Read `git remote get-url --push origin`; if none → local-only mode, unset both keys, `ok`.
   - If `_gh_slug` parses it **and** `gh auth status` succeeds: `gh api "repos/$slug" --jq .private` must print `true` → record `github-private`. Prints `false` → **refuse to record** (`die "…is PUBLIC — your archive must never push there"`); no override env var. (An operator who truly wants public can hand-set the git config keys; document that in `tape help` one-liner, don't build a flag.)
   - GitHub URL but no `gh` / not authed, or non-GitHub remote: interactive explicit confirm ("Is this repo PRIVATE and yours? [y/N]", default **No**) → record `user-asserted`, else refuse.
   - Never echo the raw URL (LT-SEC-013 adjacent): display host + path with userinfo stripped — `sed -E 's#//[^@/]+@#//#'` — in all trust/doctor/status output touched by this task.

3. **New `verify_destination()`** — called in `cmd_update` immediately before the push at `tools/tape:199`, and by `_publish_db_snapshot`:
   - `tape.pushRemote` unset → fail.
   - `git remote get-url --push origin` ≠ recorded URL (byte-exact) → fail.
   - If recorded `github-private` and `gh` is usable: re-check `gh api … --jq .private`. Output `false` → fail. **Transport/API error → warn "privacy re-check unavailable (offline?)" and pass** — the standing assertion + exact URL match remain the gate; a hard network dependency would break every offline daily run for no confidentiality gain.
   - On fail: `warn`, `log`, skip push, `rc=1`. The commit stays local (Markdown never leaves the machine). Message: "destination unverified — run: tape trust".

4. **Bind every `gh release` call** in `_publish_db_snapshot` (`tools/tape:229-234`): derive `slug="$(_gh_slug "$(git config --local tape.pushRemote)")"`; if `verify_destination` fails or slug is empty → `warn "snapshot skipped (no verified private GitHub destination)"; return 1` (return 0 only for the empty-slug non-GitHub case — that's config, not failure). Add `--repo "$slug"` to `gh release view`, `create`, and `upload`. No implicit resolution remains — this is the exact defect the fix-notes confirmed live (implicit `gh` currently resolves to the public repo with admin write).

5. **`cmd_init` step 1 (`tools/tape:457-473`) becomes fatal on remote mutation failure:** `git remote rename … || die`, `git remote add … || die`; then call `_record_trust`. `cmd_doctor` (`tools/tape:434-441`): replace the substring heuristic with trust-state reporting (recorded? matches origin? verification class?), keep the existing public-repo warning as a fallback.

6. Dispatch: add `trust)  cmd_trust "$@" ;;` and a help line.

### Failure semantics
Wrong/missing/mutated destination → local commit preserved, **zero network writes**, `rc=1`, actionable message. Michel's dev checkout (origin = public lucys-tape) becomes structurally unable to push archive data: `tape update` there now refuses at step 3 — that is the desired behavior, not a regression.

### Tests
- `test_gh_release_calls_are_repo_bound` — source assertion (idiom precedent: `test_guard_regex_in_sync`, `tests/test_redact.py:148`): every `gh release` line in `tools/tape` contains `--repo`.
- Integration (harness below): `test_update_refuses_unverified_destination` — sandbox repo with a bare local remote but **no** `tape.pushRemote`: update warns/rc=1, new commit exists locally, bare remote received **nothing**.
- `test_update_pushes_when_destination_trusted` — same sandbox with `git config tape.pushRemote <bare-path>` + `tape.pushRemoteVerified user-asserted`: push lands in the bare repo. (Local-path remote deliberately exercises the non-GitHub trust path; GitHub API path is covered by the source assertion + refusal logic, not live network.)

---

## T2 — LT-SEC-003: allowlist staging

**Files:** `tools/tape` (`cmd_update` step 3), `docs/guides/windows.md:29,48`, tests.

### Mechanism

Replace `git add -A` + unchecked commit (`tools/tape:196-201`) with a new `stage_archive()`, five steps:

```bash
stage_archive() {
    git diff --cached --quiet \
        || die "index already has staged changes — refusing to mix them into the archive commit (git reset, or commit them first)"
    git add -A -- archive/conversations archive/INDEX.md archive/REDACTION-REPORT.txt \
        || die "git add failed"
    local bad
    bad="$(git diff --cached --name-only --no-renames \
           | grep -vE '^archive/(INDEX\.md|REDACTION-REPORT\.txt|conversations/.+\.md)$' || true)"
    if [ -n "$bad" ]; then git reset -q; die "unexpected staged path(s) — refusing to commit: $bad"; fi
    # scan the EXACT blobs that would be committed (closes the TOCTOU gap):
    if git grep --cached -qE "$LEAK_RX" -- 'archive/conversations' 2>/dev/null; then
        git reset -q; die "leak guard: STAGED blob matches after masking — refusing to commit"
    fi
}
```

Then in `cmd_update`: `stage_archive`, and the existing `git diff --cached --quiet` no-change short-circuit / commit / push flow stays as-is. `git add -A -- <pathspec>` still picks up deletions *within* the allowlisted paths (renamed/removed conversations keep working), which is why the pathspec form is used rather than enumerating files.

**Windows guide:** replace both root `git add -A` occurrences (`docs/guides/windows.md:29,48`) with `git add -A -- archive/conversations archive/INDEX.md archive/REDACTION-REPORT.txt` plus one sentence stating the Bash CLI additionally verifies staged paths and blobs.

### Failure semantics
Pre-staged user work → refuse (never silently absorb or reset someone else's index). Stray path in the staged set → unstage + refuse. Staged blob matching `LEAK_RX` → unstage + refuse. Every failure is a `die` with the path names (paths only — never contents).

### Tests (integration harness)
- **Exploit red:** `test_rogue_root_file_never_committed` — plant `sandbox/repo/.fake-diag.log` (repo root, unignored, containing a synthetic `AKIA`+16 shape) and `archive/conversations/testproj/evil.txt` (non-md) before update. After update: commit exists, `git show --name-only HEAD` contains only allowlist-matching paths; both rogue files absent from every commit; the rogue file still on disk untouched. This is the exact live chain the spot review disarmed via gitignore — now dead by construction.
- **Exploit red:** `test_pre_staged_index_refused` — `git add` a rogue file first; update must fail (rc≠0), `git log` unchanged, staged entry still staged (user's work untouched).
- **Legit green:** `test_normal_refresh_commits_archive` — clean sandbox update produces a commit containing `archive/INDEX.md` + the generated conversation `.md`.

---

## T3 — LT-SEC-001: mask before build

**Files:** `tools/tape` (`cmd_update` only), tests.

### Mechanism

Pure block reorder inside `cmd_update` — no new code. Move the leak-guard block (`tools/tape:176-191`: `mask_leaks` call, warn/ok reporting, and the post-mask backstop `grep -rlqE`) to directly **after** the extractor step (`tools/tape:166`) and **before** the DB build (`tools/tape:168`). Resulting order:

1. extract → 2. mask + backstop-verify (fail-closed) → 3. build DB → 4. count/ratchet sanity → 5. `stage_archive` + commit + push → 6. weekly backup/snapshot.

The DB, the backup tarball, and the release asset are now all derived from **final masked Markdown** — the "rebuild if the masker changed anything" branch from the bughunt's fix direction becomes unnecessary because the build never sees pre-mask bytes. The Sunday paths at `tools/tape:207-210` need no change; they already run last.

One knock-on: `prev_count` (`tools/tape:163`) still reads the *old* DB before extraction — unaffected by the reorder; ratchet semantics unchanged.

### Failure semantics
Unchanged from current: masker crash → die before any artifact is built; backstop still matching → die. What improves: a die at the mask stage now leaves the **previous** DB intact instead of a freshly built dirty one.

### Tests
- `test_mask_runs_before_db_build` — source assertion on the `cmd_update` body (extract the text between `cmd_update()` and the next top-level definition): index of `mask_leaks` < index of `"$BUILD"`. Structural, but this ordering *is* the invariant, and a behavioral test is impossible by design — the redactor is a superset of the guard (`extract_conversations.py:31-33`), so no fixture input can make the guard fire without first breaking that superset. State this in the test docstring.
- Behavioral backstop, integration: `test_db_contains_no_leak_rx_match` — after the sandbox update (whose jsonl contains a synthetic `AKIA` shape and a synthetic `sk-` key), open `archive/conversations.db` read-only and assert no stored string matches the `LEAK_RX` mirror.

---

## T4 — LT-SEC-002: close the deterministic redaction gaps

**Files:** `tools/extract_conversations.py:34-68` (five pattern edits, nothing else), `tests/test_redact.py`.

Guard (`LEAK_RX`, `tools/tape:35`) stays **unchanged** — it is the deliberately dumb tripwire; only the redactor-superset property must hold, and every edit below widens the redactor, so the property is preserved (assert it in tests, don't restate it in code).

### Edits

1. **Quoted JSON/YAML assignments** (`:62` `assignment`): allow an optional quote around the name and drop the leading `\b` (which silently missed every `foo_token` / `my_api_key` style name — underscore kills the boundary):
   `(?ix)(?<![A-Za-z0-9])["']?(password|…|vault[_-]?key)["']?\s*[:=]\s*["']?([^\s"',;]{6,})` (alternation list unchanged). A leftover closing quote in the output is fine — readable, no leak.
2. **Padded base64 delimiter** (`:60-61`): replace the trailing `=\b` with `=(?![+/=])` in both `b64_32` and `b64_64`. This is provably a strict superset of `=\b` (the union of "next is word char" and "next is not a b64 char" excludes only `+ / =`), so zero regression risk on existing matches.
3. **Namespaced `sk-` keys** (`:50`): `\bsk-(?:[A-Za-z0-9]+[_-])*[A-Za-z0-9]{20,}` — catches `sk-proj-…`, `sk-or-v1-…`; `sk-ant` still hits the earlier dedicated rule first. Prose like `sk-learn` cannot match (final segment must be ≥20 alnum). Keep the existing no-trailing-`\b` comment block (`:44-49`) — it is load-bearing history.
4. **Cloud env names** (`:63` `env_named`): add `ACCESS_KEY` to the suffix alternation → `_(API_KEY|SECRET|TOKEN|PASSWORD|ENC_KEY|PRIVATE_KEY|ACCESS_KEY)`. Covers `AWS_SECRET_ACCESS_KEY=…`; the lowercase `aws_secret_access_key: …` form is covered by edit 1's lookbehind change.
5. **Short-wrapped truncated PEM** (`:38`): body-line requirement `{40,}` → `{16,}` with a line-end anchor so short-wrapped keys are eaten while prose after a bare-header *mention* is not:
   `-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----(?:[ \t]*\r?\n[ \t]*[A-Za-z0-9+/=]{16,}[ \t]*(?=\r?\n|$))+`
   **Stated assumption:** the bughunt's "stateful parse to footer/EOF" is deliberately not built — a full parser is against this repo's size/spirit, and the anchored ≥16 form covers every realistic re-wrap width. Record this in the CHANGELOG entry.

### Tests (extend `tests/test_redact.py`, one new `RedactionGapTests` class, synthetic non-secrets only)

Red (each asserts the label marker present, the synthetic value absent, and `assert_guard_clean`):
`'{"api_key": "abc123def456"}'`; `"password": "hunter2sekret"`; 42-char b64 + `="` and + `=,`; `sk-proj-` + 24 alnum; `sk-or-v1-` + 24 alnum; `AWS_SECRET_ACCESS_KEY=` + synthetic value; `aws_secret_access_key: ` + synthetic value; `my_api_key: abcdef123456` (the lookbehind regression case); PEM header + three 20-char b64 lines, no footer.

Green (must survive byte-identical):
`"use sk-learn for the model"`; `"phototoken: holidays2026"` (alnum-preceded name must NOT match); the existing `test_four_word_prose` / `test_plain_text_untouched` stay as the prose canaries; one 42-char b64 followed by `+` (still unmatched — padding rule intact).

---

## Shared integration harness (lands with T2, extended by T1/T3)

New `tests/test_tape_update.py`, stdlib only (`unittest`, `subprocess`, `tempfile`, `sqlite3`). Per-test sandbox:

- `HOME=<tmp>/home` containing `.claude/projects/-<flattened-home>-projects-testproj/s1.jsonl` (two-line user/assistant session; `_HOME_KEY` in the extractor derives from `Path.home()`, which follows `$HOME`, so the project label resolves cleanly).
- Repo: `git init` + minimal tree (`tools/` copied from the real repo, `.gitignore` copied), local `user.name`/`user.email`, `origin` → a `git init --bare` sibling.
- Env: `TMPDIR=<tmp>/run` (isolates `LOCKDIR`, `tools/tape:16`), `NO_COLOR=1`, `TAPE_MIN_FREE_GB=1`, `TAPE_BACKUP_DIR` unset. Sunday runs are safe by construction after T1: trusted remote is a local path → snapshot path skips (no GitHub slug).
- Run `subprocess.run([bash, tape, "update"], env=…, capture_output=True)`; assert on rc, `git -C bare log`, `git show --name-only`, and the sqlite DB. Never print sandbox "secret" shapes in assertion messages.

Budget: ~180 lines. If any harness test proves flaky under CI-less WSL, fix the harness — do not skip-decorate it.

---

## Sequencing, close-out, and the one gate

1. **T1 → T2 → T3 → T4**, strictly serial (all four touch `cmd_update` or its inputs; T2's harness depends on T1's trust keys, T3's DB test depends on T2's harness).
2. Per task: implement → `python3 -m unittest discover tests -v` (full suite: 24 existing + new; all green, output shown) → `bash -n tools/tape` → docs (`CHANGELOG.md`, `PROGRESS.md`; `README.md` gains the `tape trust` command) → bump `VERSION` (0.1.2 → 0.1.5, patch per task) → commit + tag locally.
3. Existing local commit `2c272c4` (gitignore mitigation) stays; do not rebase it.
4. Update `docs/reports/2026-07-16-codex-fix-notes.md` TODO list → mark 1–4 done with commit hashes, and mirror the close-out to `Fabulous/docs/fleet/lucys-tape/`.

> **GATE (the only one): pushing to origin.** Origin is the PUBLIC repo. All four commits + tags stay local until Michel says push — consistent with his standing rotate-secrets-then-push ruling. Note for the close-out: after T2 lands, the push itself is safe by construction (allowlist + staged-blob scan), but the ruling is his, not ours.

**Out of scope (unchanged, documented):** LT-SEC-005..015 retain the bughunt's remediation order; nothing here regresses them, and T1 opportunistically improves LT-SEC-013 only where it touches the same lines.
