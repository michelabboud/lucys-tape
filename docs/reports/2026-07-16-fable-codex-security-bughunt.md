# Lucy's Tape Defensive Security Bughunt

- **Date:** 2026-07-16
- **Auditor:** Codex (defensive, authorized review of Michel's repository)
- **Reviewed commit:** `d4b739433dd564c3755f0b8ea5cd96ff47df1c18` (`main`)
- **Method:** static source review only

## Scope and constraints

The review covered the Python extractor, Markdown-to-SQLite builder, note
importer, local HTTP viewer, Bash control CLI, bootstrap installer, relevant
tests, and operator documentation. It focused on authentication and
authorization, trust-boundary validation, secret handling, injection, unsafe
deserialization, path and symlink safety, races, resource exhaustion, and
error-path disclosure.

No source was changed. No compiler, application build/check/test, installer,
package manager, download, server, or application command was run. No `target/`
directory or other build artifact was created. Potential credentials were
inspected only by name/pattern/length; no secret value was opened or printed.
Two pre-existing, untracked root log files were left untouched and their
contents were not read.

## Executive summary

No Critical issue was confirmed. Four High-severity confidentiality defects
were confirmed:

1. The database is built before fallback masking, so fallback-masked secrets
   remain in the viewer DB, backups, and optional release assets.
2. The primary redactor and fallback guard have deterministic credential-shape
   blind spots.
3. The daily job guards one Markdown subtree but stages and pushes the entire
   repository.
4. Neither Git pushes nor GitHub release uploads fail closed on an unverified
   private destination.

The loopback viewer also lacks authentication and Host validation; crafted
archive metadata reaches stored-XSS sinks; sensitive artifacts inherit the
caller's filesystem permissions; and several local filesystem, availability,
and integrity boundaries are insufficiently constrained.

| ID | Severity | Finding |
|---|---|---|
| LT-SEC-001 | High | Fallback-masked secrets remain in SQLite, backups, and release snapshots |
| LT-SEC-002 | High | Secret redaction has deterministic credential-shape blind spots |
| LT-SEC-003 | High | Whole-repository staging bypasses the leak guard |
| LT-SEC-004 | High | Private push/release destination is not enforced |
| LT-SEC-005 | Medium | Stored metadata and filenames bypass redaction |
| LT-SEC-006 | Medium | Sensitive artifacts inherit permissive filesystem modes |
| LT-SEC-007 | Medium | The loopback viewer has no authentication or Host validation |
| LT-SEC-008 | Medium | Unvalidated archive metadata reaches stored-XSS sinks |
| LT-SEC-009 | Medium | Path containment and symlink protections are missing |
| LT-SEC-010 | Medium | Unbounded inputs and request concurrency permit resource exhaustion |
| LT-SEC-011 | Medium | A predictable shared lock permits silent refresh denial |
| LT-SEC-012 | Medium | Backup rotation permits filename-to-argument injection |
| LT-SEC-013 | Medium | Credential-bearing remote URLs are printed verbatim |
| LT-SEC-014 | Medium | Conversation text can inject structural turn sentinels |
| LT-SEC-015 | Low | In-place database rebuilds destroy the last good read model |

## Findings

### LT-SEC-001 — High — Fallback-masked secrets remain in SQLite, backups, and release snapshots

**Locations:** `tools/tape:164-191`, `tools/tape:203-209`,
`tools/tape:223-243`, `tools/conversations_viewer.py:69-72`

The update order is extract, build `conversations.db`, then run the fallback
masker over Markdown. If the masker changes a file, the database is not rebuilt.
The local viewer therefore continues serving the pre-mask value. The weekly
backup archives the whole `archive` directory, including that database, and the
optional release path compresses and uploads the same stale database.

**Concrete impact:** a credential that the primary redactor misses but the
fallback guard masks is absent from the committed Markdown while remaining in
the local searchable database, durable backup, and potentially a GitHub release
asset. This defeats the advertised two-layer confidentiality invariant exactly
when the second layer is needed.

**Preconditions:** the fallback guard must mask at least one residual. Backup
exposure additionally requires `TAPE_BACKUP_DIR`; release exposure requires the
weekly/forced path, authenticated `gh`, and a resolvable release repository.

**Fix direction:** mask and verify the final Markdown before building any
derived artifact. If masking changes anything, rebuild the database from the
verified Markdown. Treat the database, backup input, and release asset as final
outputs that require an independent clean-state gate before publication.

### LT-SEC-002 — High — Secret redaction has deterministic credential-shape blind spots

**Locations:** `tools/extract_conversations.py:35-67`, especially
`tools/extract_conversations.py:38`, `tools/extract_conversations.py:50`,
`tools/extract_conversations.py:60-63`; fallback pattern at `tools/tape:35`;
Windows limitation at `docs/guides/windows.md:65-70`

Several intended patterns cannot match common representations:

- The generic assignment rule expects `password`, `token`, `api_key`, and
  similar names to be followed immediately by whitespace and `:`/`=`. A quoted
  JSON key has a closing quote in between, so ordinary JSON credential
  properties bypass it.
- Both base64 rules end with `=\b`. Because `=` is a non-word character, there
  is no word boundary when a normally delimited value is followed by whitespace,
  punctuation, a quote, or end of string.
- The generic `sk-` rule requires uninterrupted alphanumerics after the prefix.
  Namespaced variants containing a hyphen or underscore before 20 alphanumerics
  bypass both the primary rule and the fallback guard.
- A conventional `AWS_SECRET_ACCESS_KEY` assignment is not matched by the
  uppercase environment-name rule; the leading word boundary also prevents the
  shorter `access_key` alternative from starting after an underscore.
- The truncated private-key rule requires every captured encoded line to be at
  least 40 characters. A footerless key wrapped at a shorter width misses it;
  the later bare-header rule then defangs only the header, preventing the
  header-only fallback guard from recognizing the remaining body.

**Concrete impact:** an affected credential in archived dialogue, a tool label,
or imported notes can be written to Markdown and SQLite and, when the respective
pipeline paths succeed, to Git history, backups, and the configured remote. The
native-Windows documented pipeline has no fallback guard, so it relies entirely
on these primary rules.

**Preconditions:** a credential must appear in one of the uncovered forms and
must not also match a stronger signature, such as a fully terminated PEM block
or an explicit supported bearer format. A private remote limits audience but
does not remove disclosure into Git history, backups, collaborators, or release
assets.

**Fix direction:** use boundary-aware patterns and structured handling for
quoted JSON/YAML assignments; use a delimiter lookahead rather than a word
boundary after padding; explicitly support the documented alphabets and prefixes
for every promised provider; cover common cloud environment names; and, when a
private-key header is followed by plausible encoded key material, parse and
redact statefully through the footer or EOF independent of line width. Add
synthetic, non-secret adversarial cases for each shape to both the primary
redactor and a genuinely independent staged-output guard.

### LT-SEC-003 — High — Whole-repository staging bypasses the leak guard

**Locations:** `tools/tape:80-103`, `tools/tape:176-200`, `.gitignore:1-7`,
`docs/guides/windows.md:29`, `docs/guides/windows.md:48`

The guard walks only `archive/conversations` and only files ending in `.md`.
After checking that working-tree subtree, the job executes `git add -A` at the
repository root. This stages every tracked modification, deletion, and
unignored file—including source, diagnostics, credentials, pre-existing staged
work, and files written after the guard check. The command's result is not
checked, so a failed add can still be followed by a commit of whatever index
state already exists, including pre-existing staged entries. The Windows guide
repeats root-wide `git add -A` without the Bash guard at all.

There is also a time-of-check/time-of-use gap: the guard scans working-tree
bytes, not the exact Git blobs that are committed. A concurrent writer can
change an allowed file between the final grep and staging.

**Concrete impact:** a daily timer can automatically commit and push an
unrelated secret-bearing file or source edit that never passed redaction. An
actor able to write the checkout but unable to use the victim's remote
credentials can use the scheduled job as a publishing deputy.

**Preconditions:** an unguarded change must exist or be introduced in the
checkout, and `origin` must accept the push. Ordinary developer activity or
diagnostic tooling is enough; no code execution in the tape process is needed.

**Fix direction:** require a clean pre-existing index (or use a dedicated archive
worktree/repository), then stage only an exact allowlist such as
`archive/conversations`, `archive/INDEX.md`, and
`archive/REDACTION-REPORT.txt`; reject any other staged path; inspect the exact
staged blobs; then commit that verified index. Do not advance `HEAD` with an
alternate index unless the user's real index is explicitly reconciled afterward.
Check every Git command and apply the same allowlist/staged-blob gate to the
Windows workflow.

### LT-SEC-004 — High — Private push/release destination is not enforced

**Locations:** `tools/tape:199`, `tools/tape:225-234`,
`tools/tape:434-472`, `tools/tape:490`

`cmd_update` pushes to `origin` without checking visibility. `cmd_doctor` only
warns when a URL contains the substring `lucys-tape`; that is neither a privacy
nor ownership check, and doctor is not a mandatory update gate. During init,
remote rename/add failures are non-fatal because the script does not use
`set -e` or explicitly abort, yet initialization can continue into `cmd_update`.

The snapshot path checks only that `gh` is authenticated. Its release commands
do not specify an exact repository, so resolution can depend on GitHub CLI
default/remote selection and can select a wrong or public repository in a
misconfigured or upstream-only checkout.

**Concrete impact:** the entire conversation archive or compressed searchable
database can be pushed/uploaded to a public or otherwise unintended repository.
This is catastrophic confidentiality loss even though it requires
misconfiguration rather than a remote unauthenticated attacker.

**Preconditions:** `origin` or the GitHub CLI's resolved repository must be
public/wrong, and the user's credentials must permit the write. The release path
also requires the weekly/forced snapshot path. Most users cannot write the
public upstream, but maintainers, fork owners, and users who accidentally choose
a public repository can.

**Fix direction:** allow local extraction/build, but fail closed before any
push/release unless one canonical destination is resolved, owned/expected, and
verified private through the provider API, a durable explicit trust assertion
for a private non-GitHub remote, or an explicit local-only mode. Re-read and
validate `origin` after setup, abort on remote mutation failure, bind every `gh`
call to the exact verified repository, and never fall back to `upstream` or an
implicit default.

### LT-SEC-005 — Medium — Stored metadata and filenames bypass redaction

**Locations:** `tools/extract_conversations.py:140-151`,
`tools/extract_conversations.py:175-179`,
`tools/extract_conversations.py:204-224`,
`tools/extract_conversations.py:236-263`, `tools/import_notes.py:106`,
`tools/import_notes.py:121-130`

Redaction is applied to dialogue text, generated step labels, and title, but not
to session ID, project label, branch, model, timestamp, note source path, note
filename, glob, or skipped-file diagnostic. Several of those values are written
into committed Markdown metadata, headings, index entries, or Git pathnames.
The content-only guard cannot mask a credential embedded in a filename.

**Concrete impact:** a sensitive branch/project/session name or credential-like
metadata value can be committed and pushed despite the claim that every stored
string passes the redactor. The importer also commits the user-supplied,
tilde-expanded source path, which can disclose usernames and private directory
names.

**Preconditions:** sensitive data must occur in metadata or a path. This is less
common than dialogue leakage but plausible for branch names, project folders,
tampered session files, and manually named captures.

**Fix direction:** define and enforce a schema for every stored field. Redact
display metadata, reject control characters, and separately encode filesystem
components with a strict allowlist. Do not persist absolute source paths or raw
filenames when a sanitized relative label or stable hash is sufficient. Scan
both staged contents and staged pathnames.

### LT-SEC-006 — Medium — Sensitive artifacts inherit permissive filesystem modes

**Locations:** `install.sh:9-26`, `tools/tape:8`, `tools/tape:47`,
`tools/tape:228`, `tools/tape:243`, `tools/tape:259`,
`tools/extract_conversations.py:208`, `tools/extract_conversations.py:230`,
`tools/extract_conversations.py:254`, `tools/extract_conversations.py:264`,
`tools/build_db.py:85`, `tools/import_notes.py:102`,
`tools/import_notes.py:121`

Neither the bootstrap, CLI, nor direct Python entry points set a private umask
or explicit restrictive modes. The repository, `.git` objects/config, Markdown,
database, logs, backups, and imported notes inherit the caller's defaults. In
this checkout, the repository, `.git`, and `archive` directories are `0775`, and
`.git/config` is `0664`, demonstrating the inherited-mode outcome (the parent
home directory currently limits traversal, but the project does not enforce
that protection).

**Concrete impact:** on a multi-user host with a traversable home/project path,
another local account or group member can read private conversations, database,
logs, Git history, backups, and possibly credential-bearing Git configuration.
A group-writable checkout also enables the symlink and scheduled-publisher
attacks described elsewhere.

**Preconditions:** another account can traverse the parent path, or the project
group contains another principal. A private `0700` home mitigates the read path
but is an environmental accident rather than an application guarantee.

**Fix direction:** set `umask 077` before cloning or creating any artifact;
create the repository/archive directories as `0700` and sensitive files as
`0600`; verify ownership; harden existing installations; and document/apply the
equivalent Windows ACL. Direct Python entry points must enforce the same policy
with explicit modes in `main()` or a scoped/restored umask, not a process-wide
module-import side effect or reliance solely on the Bash wrapper.

### LT-SEC-007 — Medium — The loopback viewer has no authentication or Host validation

**Locations:** `tools/conversations_viewer.py:130-179`

Every GET request reaching the listener can enumerate the sidebar, run searches,
and retrieve all conversation and tool-step text. There is no authentication,
authorization, Host allowlist, Origin check, or per-launch capability. Binding
to `127.0.0.1` blocks remote TCP peers but not other local accounts/processes in
the same network namespace. Arbitrary Host acceptance also leaves a classical
DNS-rebinding path from a malicious website.

**Concrete impact:** a low-privileged local account can read the full private
archive through HTTP even when filesystem permissions block direct access. A
successful DNS-rebinding page can do the same from the victim's browser.

**Preconditions:** the viewer is running. Local exploitation requires access to
the host. Browser exploitation requires a victim visit plus a browser/network
configuration that permits rebinding/private-network requests; same-origin and
modern private-network protections block some variants.

**Fix direction:** validate Host against the exact loopback host/port and require
a high-entropy per-launch capability exchanged for an `HttpOnly`,
`SameSite=Strict` session cookie before any database access. Add
`Cache-Control: no-store`, a restrictive Content Security Policy, and
`frame-ancestors 'none'`. Document that loopback binding alone is not an
authorization boundary.

### LT-SEC-008 — Medium — Unvalidated archive metadata reaches stored-XSS sinks

**Locations:** `tools/build_db.py:89-100`,
`tools/conversations_viewer.py:92-94`,
`tools/conversations_viewer.py:117-126`,
`tools/conversations_viewer.py:134-137`,
`tools/conversations_viewer.py:159-167`

The builder accepts FAB metadata without type or character validation. The
viewer HTML-escapes titles, projects, models, and turn bodies, but inserts
session IDs, timestamps, and count fields raw into HTML text or quoted hrefs.
There is no CSP to contain successful markup injection.

**Concrete impact:** a crafted archive Markdown entry can break out of an href
through `sid` or inject markup through another raw field. Merely loading the
sidebar/detail page can execute attacker-controlled script in the loopback
origin; that script can fetch every conversation and exfiltrate it.

**Preconditions:** malicious metadata must enter an archive the victim rebuilds
and views—for example through a compromised/shared archive, malicious commit, or
tampered local session producer. Ordinary dialogue text is escaped at display,
but an exact sentinel-shaped dialogue line can be reparsed as raw turn metadata
through `LT-SEC-014`, including the timestamp sink.

**Fix direction:** schema-validate all metadata in the builder (strict SID and
timestamp formats, integer counts, bounded string lengths); HTML-escape every
value at its output context; URL-encode path components and build query strings
with URL utilities; add hostile-metadata regressions; and deploy a restrictive
CSP as defense in depth.

### LT-SEC-009 — Medium — Path containment and symlink protections are missing

**Locations:** `tools/extract_conversations.py:151`,
`tools/extract_conversations.py:175`, `tools/extract_conversations.py:208`,
`tools/extract_conversations.py:248-249`,
`tools/extract_conversations.py:254`, `tools/extract_conversations.py:264`,
`tools/build_db.py:40`, `tools/build_db.py:85`,
`tools/import_notes.py:65-76`, `tools/import_notes.py:94-121`

The extractor uses the first ten timestamp characters verbatim inside an output
path. An absolute prefix or parent components in a crafted timestamp can escape
the intended project directory. Output creation uses normal `open(..., "w")`,
which follows pre-existing symlinks, including predictable index/report/note
paths. The builder likewise follows Markdown/DB symlinks. The importer accepts a
user-controlled glob, follows matching file symlinks, separates `stat()` from
`read_text()`, and follows output symlinks.

**Concrete impact:** a malicious/corrupt session can write a generated Markdown
file outside its project directory. An actor able to plant a symlink in a
shared/writable source or archive can make the victim process ingest an
arbitrary readable file into the archive or truncate/replace another file the
victim can write.

**Preconditions:** malicious local JSONL/Markdown, an untrusted import tree/glob,
or another principal able to write the source/archive directory. Normal Claude
timestamps are ISO-formatted, so timestamp traversal is not a remote
prompt-only primitive. Arbitrary clobber requires a predictable planted symlink
or a target compatible with the generated suffix.

**Fix direction:** strictly parse timestamps; sanitize every path component;
resolve roots and enforce containment; reject symlinks and non-regular input;
open inputs/outputs with no-follow semantics and validate the opened descriptor
with `fstat`; use private directories; and write atomically through a trusted
directory descriptor (or equivalent) and same-directory temporary file followed
by a verified replace so the parent cannot be swapped mid-operation.

### LT-SEC-010 — Medium — Unbounded inputs and request concurrency permit resource exhaustion

**Locations:** `tools/extract_conversations.py:128-169`,
`tools/extract_conversations.py:232-253`, `tools/build_db.py:40`,
`tools/build_db.py:75`, `tools/build_db.py:88-106`,
`tools/import_notes.py:65-86`, `tools/conversations_viewer.py:84-98`,
`tools/conversations_viewer.py:101-127`,
`tools/conversations_viewer.py:130-179`, `tools/tape:145-147`,
`tools/tape:259`

The offline pipeline has no per-line, per-file, file-count, turn-count, or
aggregate-byte limits. Extractor and builder retain large structures in memory;
the builder reads Markdown repeatedly; and the importer retains full files plus
normalized copies, then performs quadratic containment searches. The disk floor
is checked only before extraction, not against expected output growth.

The viewer accepts arbitrary FTS syntax without an application length/term guard
or exception handling (the HTTP base class still caps the request line at about
64 KiB), fetches every turn of a selected conversation, and uses an unbounded
thread-per-connection server with no explicit socket timeout. Malformed FTS
queries raise into the default server error path; `tape serve` redirects those
tracebacks into a log that is unrotated and unbounded for the process lifetime
(it is truncated only when the viewer restarts).

**Concrete impact:** a large/corrupt input can exhaust memory, CPU, or disk and
stop scheduled refreshes. A local HTTP client can create many slow connections
or repeat malformed/expensive searches, consuming threads and growing the log
until service or filesystem exhaustion.

**Preconditions:** offline exhaustion requires attacker-controlled/corrupt local
input or unusually large organic history. HTTP exhaustion requires loopback
reachability; there is no direct external listener.

**Fix direction:** impose configurable per-record/file/count/aggregate budgets;
stream instead of duplicating content; quarantine malformed records with bounded
diagnostics; and make an exceeded budget fail the refresh or record a conspicuous
omission—never silently truncate/skip content while passing the count ratchet.
Estimate/check output space during processing; cap query length and term count;
catch FTS errors as a small `400`; bound worker concurrency; set read/write
timeouts and response-size limits; and rotate/cap viewer logs.

### LT-SEC-011 — Medium — A predictable shared lock permits silent refresh denial

**Locations:** `tools/tape:16`, `tools/tape:61-70`, `tools/tape:153`

When `TMPDIR` is unset or shared, users/installations share the predictable
`lucys-tape-refresh.lock.d` path (under `/tmp` by default). Multiple installations
within even a private `TMPDIR` also collide because the name is not
repository-specific. On a shared sticky `/tmp`, another local account can
pre-create a foreign-owned directory/PID file that the victim cannot remove. The
update then reports that another refresh is running and exits successfully. PID
reuse and the check/remove/reacquire sequence also make stale-lock reclamation
raceable.

**Concrete impact:** another local user can indefinitely suppress extraction,
secret masking, pushes, and backups while the timer appears to complete without
an error.

**Preconditions:** a multi-user POSIX host with shared `/tmp` and the ability to
create the predictable path before the victim.

**Fix direction:** use a per-user private runtime directory such as a validated
`$XDG_RUNTIME_DIR`, include a repository identity in the lock name, require
correct ownership/mode, and use an OS lock or atomic lock file whose identity is
verified before cleanup. Treat unexpected foreign locks as a visible failure,
not success.

### LT-SEC-012 — Medium — Backup rotation permits filename-to-argument injection

**Locations:** `tools/tape:157`, `tools/tape:239-246`

Rotation parses `ls -1t` output with whitespace-oriented `xargs rm`. POSIX
filenames may contain spaces, quotes, backslashes, and newlines. A crafted backup
filename can therefore become multiple `rm` arguments, including an option and
relative operand. In the scheduled update path the current directory is the
repository, making unintended repository deletion possible. Rotation errors are
followed by an unconditional success return, so portability/parser failures can
also silently disable retention and consume disk.

**Concrete impact:** an actor able to write a shared/synchronized backup
directory can plant an old-enough matching name that makes rotation delete files
chosen relative to the tape process. On implementations such as GNU `rm` that
continue option parsing after operands, injected options can make deletion
recursive. Benign whitespace in paths can cause incorrect deletion or retention
failure across implementations.

**Preconditions:** backup rotation is enabled and over its retention threshold;
arbitrary deletion requires an attacker-writable or adversarially synchronized
backup directory and control of a matching filename/mtime.

**Fix direction:** never parse `ls`. Enumerate candidates as exact path objects,
use `lstat`, verify regular-file ownership and containment, sort by metadata,
and unlink selected exact paths through a safe API. Propagate every rotation
failure.

### LT-SEC-013 — Medium — Credential-bearing remote URLs are printed verbatim

**Locations:** `tools/tape:357`, `tools/tape:434-440`,
`tools/tape:458-472`

Status, doctor, and init echo the raw Git remote URL. HTTPS Git URLs can contain
userinfo credentials, and Git configuration can contain terminal control
characters. These commands are likely to be copied into support transcripts,
logs, screenshots, or archived conversations.

**Concrete impact:** an embedded access token/password can be disclosed to
observers or support artifacts. Crafted control characters can forge/mislead
terminal output and, depending on the terminal, trigger unsafe escape-sequence
behavior.

**Preconditions:** the configured/pasted remote contains userinfo credentials or
control characters. SSH remotes and credential-helper-based HTTPS URLs usually
do not.

**Fix direction:** never echo the pasted/raw URL. Parse it, remove userinfo,
strip/reject control characters, and display only a sanitized host/path or a
hash. Apply the same sanitizer to error/log paths that might include Git remote
output.

### LT-SEC-014 — Medium — Conversation text can inject structural turn sentinels

**Locations:** `tools/extract_conversations.py:215-224`,
`tools/import_notes.py:108-109`, `tools/build_db.py:48-55`

The extractor writes turn text verbatim after a machine-readable sentinel. The
builder treats any later line matching the same sentinel grammar as a new turn,
including a line originating inside user/assistant content. There is no escaping
or framing that distinguishes data from structure.

**Concrete impact:** malicious conversation content can forge role, kind, model,
and timestamp metadata for subsequent text, move content between Personal and
Architect layers, and corrupt search/audit history. This undermines the archive's
round-trip and attribution integrity even when it does not execute code.

**Preconditions:** archived dialogue contains an exact sentinel-shaped line,
accidentally or deliberately. This can originate in normal conversation content;
local filesystem tampering is not required.

**Fix direction:** reversibly escape sentinel-looking body lines or introduce a
versioned, backward-compatible unambiguous length-prefixed/structured framing so
existing committed archives remain rebuildable. Validate role/kind/model/
timestamp values and add hostile-body round-trip tests.

### LT-SEC-015 — Low — In-place database rebuilds destroy the last good read model

**Locations:** `tools/build_db.py:60-71`, `tools/build_db.py:81-109`,
`tools/conversations_viewer.py:69-72`,
`tools/conversations_viewer.py:148-172`, `tools/tape:166-168`

The builder opens the live database, drops/recreates its schema without one
explicit transaction, and then parses and inserts archive content. A malformed
field, unreadable file, FTS error, disk failure, or interruption can leave an
empty or partially recreated schema. Concurrent requests can see missing/empty
schema or lock errors and, because a page performs separate queries, can mix
old/empty/new logical snapshots across a rebuild.

**Concrete impact:** persistent or transient viewer outage and loss of the last
known-good search index until a successful rebuild. No source Markdown loss was
demonstrated.

**Preconditions:** a rebuild overlaps viewing or fails after destructive schema
initialization.

**Fix direction:** validate inputs and build a new mode-`0600` database in the
same directory, commit and sanity-check it, close it, then atomically replace the
live DB on POSIX. On Windows, coordinate viewer quiescence/retry or use versioned
database files with a safely switched pointer because replacing an open SQLite
file can fail. Keep the previous DB until the switch succeeds and return a
bounded `503` only as fallback error handling for read races.

## Important non-findings and scope limits

- **No SQL injection was found.** Viewer and builder data values use SQLite
  parameters; dynamic viewer SQL fragments are fixed constants. FTS query syntax
  can cause availability errors but does not become arbitrary SQL.
- **No unsafe-deserialization RCE was found.** Archive data uses standard
  `json.loads` without object hooks; there is no pickle, YAML object construction,
  or dynamic evaluator applied to deserialized content.
- **No SSRF path was found in the viewer.** It makes no outbound request; URL
  parsing is only for the inbound request target.
- **Normal conversation-body XSS is escaped.** The XSS finding is limited to
  unvalidated/raw metadata sinks. Search-highlight terms are escaped before
  insertion.
- **No conventional CSRF state change was found.** Viewer routes are read-only
  GETs. Blind requests can still exercise the availability paths.
- **Properly terminated PEM private-key blocks are covered.** The confirmed PEM
  issue is the footerless/short-wrap case.
- **SQLite is gitignored.** Its disclosure paths are local viewing, whole-archive
  backup, and release upload—not the ordinary Git staging path.
- Quoted shell arguments for configured directories, ports, and remotes were not
  promoted as command injection. Scenarios requiring prior control of the
  invoking user's environment were treated as same-privilege configuration,
  not a privilege-crossing exploit.

## Recommended remediation order

1. Reorder masking before DB construction and disable DB snapshot publication
   until the rebuilt-final-output invariant is enforced (`LT-SEC-001`).
2. Replace root-wide staging with an isolated allowlisted index and verify the
   exact staged blobs (`LT-SEC-003`).
3. Make private destination verification mandatory and bind all GitHub actions
   to that exact repository (`LT-SEC-004`).
4. Harden secret formats/field coverage with adversarial synthetic regression
   cases (`LT-SEC-002`, `LT-SEC-005`).
5. Enforce private filesystem modes and harden the viewer's authentication,
   HTML contexts, and resource limits (`LT-SEC-006` through `LT-SEC-010`).
6. Close the remaining local integrity/availability issues (`LT-SEC-011`
   through `LT-SEC-015`).

Because this audit was constrained to static analysis, no exploit payload was
executed and no remediation was dynamically validated.
