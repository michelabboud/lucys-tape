# 0003 — The leak guard is a strict SUBSET of the redactor

**Status:** Accepted · 2026-08-06

## Context

Secrets are kept out of the archive by two independent layers:

1. **The redactor** (`tools/extract_conversations.py`, `REDACTIONS`) — the primary
   filter. Runs on every string before it is written to Markdown.
2. **The leak guard** (`tools/tape`, `LEAK_RX`) — a deliberately dumb tripwire that
   re-scans the finished archive and masks anything the redactor missed, before any
   commit.

The instinct is to make the guard as broad as possible: it is the last line of
defence, so surely it should catch the most. That instinct is wrong, and it cost
this codebase a production incident.

If the guard can match something the redactor cannot, the pipeline reaches a state
it cannot resolve on its own. The original symptom (Fabulous, 2026-06-14) was an
OpenAI key butted against a word character: the guard's boundary-free
`\bsk-[A-Za-z0-9]{20}` matched it, while a trailing `\b` in the redactor's pattern
made it *miss*. Every refresh produced output the guard rejected, and the nightly
push deadlocked. The guard was doing exactly what it was written to do, which is
precisely why nobody looked at it.

The masking guard introduced later (mask-in-place rather than abort) removes the
hard deadlock, but not the underlying problem: a guard broader than the redactor
silently shreds archive text with `[****REDACTED-BY-GUARD****]` markers on every
run, degrading readability forever while the real gap at the source is never fixed.

## Decision

**Every guard pattern must be a strict subset of what the redactor already
catches.** The guard exists to catch *bugs in the redactor*, not categories the
redactor was never taught.

Three rules follow, and they apply to every future secret family:

1. **Redactor first, and broader.** Add the pattern to `REDACTIONS` before adding
   anything to `LEAK_RX`. The guard entry is optional; the redactor entry is not.
2. **Deliberately narrow the guard.** Where the redactor is loose, the guard is
   tight. Telegram bot tokens are the worked example: the redactor accepts
   `\d{5,}:[A-Za-z0-9_\-]{30,}`, the guard only `[0-9]{8,}:[A-Za-z0-9_-]{35}`. The
   guard cannot fire on anything the redactor would pass over.
3. **No trailing `\b` in redactor patterns.** A tail anchor is what created the
   original mismatch. Secrets are found by their prefix and length, never by what
   follows them.

The mirror of `LEAK_RX` in `tests/test_redact.py` is pinned to the real one by
`test_guard_regex_in_sync`, so the two cannot drift silently. The subset property
itself is asserted by `test_redactor_is_a_superset_of_the_guard`, which generates
seeded guard-matching tokens across six realistic contexts rather than trusting a
handful of hand-picked examples.

## Alternatives rejected

- **A broad, independent guard ("defence in depth").** Sounds stronger, behaves
  worse: it converts every redactor gap into either a stuck pipeline or permanent
  archive damage, and it removes the pressure to fix the gap at source. Depth here
  comes from the two layers being *ordered*, not from them being *independent*.
- **Guard only, no redactor patterns.** The guard runs after the text is already
  written to disk; the secret exists in the working tree in the meantime. Masking
  also destroys context, where the redactor can replace surgically and keep the
  line readable (`api.telegram.org/bot[REDACTED-telegram-bot-token]/getMe`).
- **Redactor only, drop the guard.** Loses the backstop that catches a regression
  in the redactor itself. The guard is cheap and its logs are the only signal that
  a redactor pattern has a hole.

## Consequences

- Adding a secret family is a two-step chore with a fixed order, and the sync test
  will fail loudly if the steps are done out of order. That failure is the feature.
- The guard will never be the thing that catches a *new* secret category. That is
  intended; new categories are the redactor's job, and the guard's silence must
  never be read as evidence that the archive is clean.
- Replacement markers must be space-free (`[REDACTED-telegram-bot-token]`, not
  `[REDACTED telegram-bot-token]`) so that later rules such as `assignment` and
  `env_named`, which match `\S+`, can still collapse a whole `NAME=<secret>` line
  instead of stopping at the space and leaving a dangling fragment.
