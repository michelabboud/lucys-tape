# 0004 — The viewer is offline-first, CSP-hardened, and works without JavaScript

**Status:** Accepted · 2026-08-06

## Context

`tools/conversations_viewer.py` renders an archive of somebody's private
conversations, on their own machine, from a loopback port. That single sentence
constrains the front end more than any aesthetic goal does, and the constraints
are easy to violate by reflex — every modern front-end habit assumes a network,
a CDN, and a build step.

Three specific temptations, each of which looks harmless:

1. **Load a nice font from a CDN.** A `@font-face` pointing at Google Fonts turns
   every page view into a request to a third party, revealing that this person is
   reading their archive and when. It also means the tool renders wrong on a
   plane, on an air-gapped machine, or after the CDN changes a URL.
2. **Move features into JavaScript.** Search-as-you-type, client-side filtering
   and infinite scroll are all nicer — right up until JS is disabled, fails to
   parse on an older browser, or the archive is opened in something minimal.
3. **Sprinkle `style="…"` for the small stuff.** One inline style is never a
   problem. It is a problem the moment a Content-Security-Policy exists.

## Decision

**No network at render time. No web fonts, no CDN, no external anything.**
Typographic character comes from system stacks — a serif display face
(`Iowan Old Style`/`Palatino`/`Georgia`) against a sans UI face and a mono face
for tool steps. All three are present on ordinary machines and cost nothing.

**Every capability works without JavaScript.** Search and paging are form submits
and links; the Personal/Architect layer toggles are links that change a query
parameter. JS is confined to genuine enhancement: theme persistence and keyboard
shortcuts (`/`, `j`/`k`, `Esc`). If a capability cannot be expressed as a link or
a form, that is a signal to reconsider the capability, not to reach for JS.

**Every response carries a Content-Security-Policy with a per-response nonce:**

```
default-src 'none'; style-src 'nonce-…'; script-src 'nonce-…';
form-action 'self'; base-uri 'none'
```

plus `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`.

The archive is arbitrary text captured from arbitrary sessions — including, very
often, text *about* HTML and JavaScript. It is all escaped on the way out; the
CSP is the second net, so that a future escaping mistake cannot become script
execution on a page that can read the entire archive.

**A consequence with teeth: no `style="…"` attributes, anywhere.** A nonce
authorises a `<style>` *element*; it can never authorise a style *attribute*.
An inline style under this CSP is silently dropped — the page renders, the tests
pass, and the styling is simply absent. This is exactly how the model badges lost
their colour on the day this was written; it was found by opening a browser, not
by the suite. Per-instance styling is therefore expressed as a CSS class, with
the rules generated from the single source map (`MODEL_COLORS`). The rule is
pinned by `tests/test_viewer.py::test_no_inline_style_attributes_anywhere`.

## Alternatives rejected

- **Ship a webfont as base64 inside the file.** Keeps offline and privacy intact,
  but adds hundreds of kilobytes to a single-file stdlib tool for one typeface,
  on every page load. The system serif is 90% of the benefit at zero cost.
- **`style-src 'unsafe-inline'`.** Would make inline styles work and gut the
  policy's main value at the same time, since the archive is full of untrusted
  text. Rejected: the constraint is the point.
- **Drop the CSP** — "it's loopback, there's no attacker." The threat is not a
  remote attacker; it is *our own* escaping bug meeting archived text that
  contains a `<script>` tag, on a page with read access to everything.
- **A small front-end framework and a build step.** Contradicts ADR 0002 and
  turns "clone and run" into "install a toolchain".

## Consequences

- Styling changes are always CSS-file changes, never one-off attributes. That is
  more disciplined but slightly less convenient.
- The keyboard shortcuts and theme toggle are the only things a no-JS user loses,
  and neither is load-bearing.
- Any future feature that genuinely needs to fetch (live-updating counts, say)
  must add an explicit `connect-src` and justify it here rather than widening
  `default-src`.
