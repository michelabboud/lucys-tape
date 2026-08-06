#!/usr/bin/env python3
"""Tests for the secret-scrubbing redactor in tools/extract_conversations.py.

Focus: PEM private-key handling — the redactor must FILTER everything the
leak guard would flag, so the guard (a deliberately dumb tripwire) never
fires on redactor output. Three PEM cases matter:

  1. full block (BEGIN..END)        -> fully redacted          (secret)
  2. truncated block (BEGIN + body) -> fully redacted          (secret; cut-off paste)
  3. bare header in prose/code      -> defanged, kept readable (harmless mention)

Run: python3 -m unittest discover tests -v
"""
import importlib.util
import json
import random
import re
import string
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "extract_conversations",
    Path(__file__).resolve().parent.parent / "tools" / "extract_conversations.py",
)
extract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(extract)
redact = extract.redact

# Mirror of LEAK_RX in tools/tape — keep in sync (test_guard_regex_in_sync checks).
LEAK_RX = re.compile(
    r"sk-ant-[A-Za-z0-9]{15}|\bsk-[A-Za-z0-9]{20}|xai-[A-Za-z0-9]{20}"
    r"|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    # Telegram bot token. Deliberately NARROWER than the redactor's pattern
    # (8+ id digits and exactly 35 secret chars, vs the redactor's 5+ and 30+),
    # so the guard stays a strict SUBSET and can never flag what the redactor
    # missed — the deadlock this file exists to prevent.
    r"|[0-9]{8,}:[A-Za-z0-9_-]{35}"
)

FAKE_B64 = "MIIEpAIBAAKCAQEA" + "x" * 48  # 64-char base64-ish line, like real PEM body


class PemRedactionTests(unittest.TestCase):
    def assert_guard_clean(self, text):
        self.assertIsNone(LEAK_RX.search(text),
                          "redactor output would still trip the leak guard")

    def test_full_block_is_redacted(self):
        block = ("-----BEGIN RSA PRIVATE KEY-----\n"
                 f"{FAKE_B64}\n{FAKE_B64}\n"
                 "-----END RSA PRIVATE KEY-----")
        out = redact(f"here is my key\n{block}\ndone")
        self.assertIn("[REDACTED PRIVATE KEY BLOCK]", out)
        self.assertNotIn(FAKE_B64, out)
        self.assert_guard_clean(out)

    def test_truncated_block_is_redacted(self):
        # A cut-off paste: header + body, no END footer. Must be treated as a
        # real secret, NOT defanged-and-kept (that would leak the key body).
        out = redact(f"-----BEGIN OPENSSH PRIVATE KEY-----\n{FAKE_B64}\n{FAKE_B64}")
        self.assertIn("[REDACTED PRIVATE KEY BLOCK]", out)
        self.assertNotIn(FAKE_B64, out)
        self.assert_guard_clean(out)

    def test_bare_header_in_prose_is_defanged_and_readable(self):
        out = redact("the scanner looks for -----BEGIN RSA PRIVATE KEY----- in files")
        self.assert_guard_clean(out)
        # still readable as a PEM-header mention, with the key type preserved
        self.assertIn("BEGIN", out)
        self.assertIn("RSA", out)
        self.assertIn("PRIVATE KEY", out)
        self.assertIn("defanged", out)

    def test_bare_footer_is_defanged_for_symmetry(self):
        out = redact("ends with -----END EC PRIVATE KEY----- on its own line")
        self.assertIn("defanged", out)
        self.assertIn("EC", out)

    def test_typeless_header_is_defanged(self):
        out = redact("generic form: -----BEGIN PRIVATE KEY----- (pkcs8)")
        self.assert_guard_clean(out)
        self.assertIn("defanged", out)

    def test_defang_is_idempotent(self):
        once = redact("see -----BEGIN RSA PRIVATE KEY----- pattern")
        twice = redact(once)
        self.assertEqual(once, twice)

    def test_header_inside_code_span_is_defanged(self):
        out = redact('rx = "-----BEGIN [A-Z ]*PRIVATE KEY-----"')
        self.assert_guard_clean(out)

    def test_anthropic_key_is_redacted(self):
        out = redact("token sk-ant-" + "a1B2" * 10 + " leaked")
        self.assertIn("[REDACTED sk-ant]", out)
        self.assert_guard_clean(out)

    def test_openai_key_followed_by_word_char_is_redacted(self):
        # The deadlock bug (Fabulous, 2026-06-14): an sk- key butted against a
        # word char (e.g. an underscore) trips the guard's boundary-free
        # `\bsk-…{20}` but a trailing \b in the redactor made it MISS. The
        # redactor must catch it so the guard never has to. Cover trailing
        # underscore, letter, and digit.
        for tail in ("_more", "Xmore", "9more"):
            with self.subTest(tail=tail):
                out = redact("here sk-" + "a1B2c3D4" * 3 + tail + " end")  # 24 alnum + word char
                self.assertIn("[REDACTED sk-key]", out)
                self.assert_guard_clean(out)

    def test_openai_key_at_boundary_still_redacted(self):
        # the ordinary case (key ends at whitespace) must keep working
        out = redact("key sk-" + "a1B2c3D4" * 3 + " done")
        self.assertIn("[REDACTED sk-key]", out)
        self.assert_guard_clean(out)

    def test_guard_mask_marker_is_guard_clean_and_idempotent(self):
        # The bash guard masks residual hits with this marker; it must itself never
        # trip LEAK_RX (else the masking pass would loop / fail its own backstop).
        marker = "[****REDACTED-BY-GUARD****]"
        self.assertIsNone(LEAK_RX.search(marker))
        self.assertEqual(redact(marker), marker)  # redactor leaves the marker untouched

    def test_named_env_assignment_is_redacted(self):
        out = redact("export MYAPP_API_KEY=abc123def456ghi789")
        self.assertIn("MYAPP_API_KEY=[REDACTED]", out)
        self.assertNotIn("abc123def456ghi789", out)

    def test_connection_string_password_is_redacted(self):
        out = redact("postgres://admin:hunter2sekret@db.internal:5432/app")
        self.assertIn("[REDACTED-PW]", out)
        self.assertNotIn("hunter2sekret", out)
        self.assertIn("admin", out)  # username survives; only the password dies

    def test_app_password_with_context_is_redacted(self):
        # 4x4 lowercase groups are only a secret NEAR an app-password keyword —
        # context-anchored to avoid eating ordinary four-word prose.
        out = redact("gmail app secret -- Some Label abcd efgh ijkl mnop")
        self.assertNotIn("abcd efgh ijkl mnop", out)
        self.assertIn("[REDACTED google-app-password]", out)
        out2 = redact("my app password: wxyz abcd qrst uvwx (for SMTP)")
        self.assertNotIn("wxyz abcd qrst uvwx", out2)
        # real-world shape: label on one line, password on the next
        out3 = redact("gmail app secret -- Some Label\nabcd efgh ijkl mnop\n")
        self.assertNotIn("abcd efgh ijkl mnop", out3)

    def test_four_word_prose_is_not_redacted(self):
        # the same shape WITHOUT the keyword context must survive untouched
        text = "make sure that they stay calm when this runs"
        self.assertEqual(redact(text), text)

    def test_plain_text_untouched(self):
        text = "a private key is something you should never share"
        self.assertEqual(redact(text), text)

    def test_guard_regex_in_sync(self):
        # If LEAK_RX in tools/tape changes, this mirror must be updated.
        guard_line = next(
            line for line in
            (Path(__file__).resolve().parent.parent / "tools" / "tape")
            .read_text(encoding="utf-8").splitlines()
            if line.startswith("LEAK_RX=")
        )
        self.assertEqual(guard_line.split("=", 1)[1].strip("'"),
                         LEAK_RX.pattern.replace("\n", ""),
                         "tests/test_redact.py LEAK_RX mirror is out of sync with tools/tape")


class TelegramBotTokenTests(unittest.TestCase):
    """Telegram bot tokens: ``<bot_id>:<35-char secret>``.

    Why this shape gets its own pattern set rather than relying on the generic
    ``assignment``/``env_named`` rules: those only fire on ``NAME=value`` lines.
    A Telegram token leaks most often in neither form. EVERY Bot API request
    embeds the whole token in the URL path::

        https://api.telegram.org/bot<token>/getMe

    and HTTP clients routinely put the failing URL into their error message. So
    an ordinary DNS blip or timeout, archived verbatim from a terminal, publishes
    a live credential into a git repository. The archive is the exact place that
    text ends up.
    """

    # Syntactically valid shape, deliberately not a credential: 10-digit bot id,
    # 35-char secret half (the real format).
    FAKE = "1234567890:AAFakeFakeFakeFakeFakeFakeFakeFake9"

    def assert_scrubbed(self, text):
        out = redact(text)
        self.assertNotIn(self.FAKE, out, f"whole token survived: {out}")
        self.assertNotIn(self.FAKE.split(":")[1], out, f"secret half survived: {out}")
        self.assertIsNone(LEAK_RX.search(out), "output would still trip the leak guard")
        return out

    def test_bare_token_in_prose(self):
        self.assert_scrubbed(f"the token is {self.FAKE} ok")

    def test_token_inside_a_bot_api_url(self):
        # The dominant leak path. Note there is NO word boundary between "bot"
        # and the digits, so a \b-anchored pattern misses this case entirely —
        # i.e. it would miss the most common one while passing every prose test.
        out = self.assert_scrubbed(f"GET https://api.telegram.org/bot{self.FAKE}/getMe")
        self.assertIn("api.telegram.org/bot", out,
                      "URL context should survive so the line stays readable")

    def test_token_in_an_http_error_message(self):
        self.assert_scrubbed(
            f"error sending request for url (https://api.telegram.org/bot{self.FAKE}/getUpdates)"
        )

    def test_env_assignment_collapses_to_one_marker(self):
        out = self.assert_scrubbed(f"TELEGRAM_BOT_TOKEN={self.FAKE}")
        self.assertEqual(out, "TELEGRAM_BOT_TOKEN=[REDACTED]")

    def test_shell_export_with_quotes(self):
        self.assert_scrubbed(f"export TELEGRAM_BOT_TOKEN='{self.FAKE}'")

    def test_no_word_boundary_before_the_digits(self):
        # Guarantees the redactor stays a SUPERSET of a boundary-free guard
        # pattern — the redactor/guard deadlock this file already documents.
        self.assert_scrubbed(f"xxbot{self.FAKE}/getMe")

    def test_telegrams_documentation_url_is_left_intact(self):
        # /bots/api also begins with "/bot" and is printed constantly. Requiring
        # digits-then-colon after "/bot" is what keeps ordinary prose readable.
        text = "see https://core.telegram.org/bots/api first"
        self.assertEqual(redact(text), text)

    def test_ordinary_numbers_and_timestamps_are_not_touched(self):
        for benign in ("finished in 12345 ms with 463 tests",
                       "at 1785974400: all good",
                       "ratio 30.5 over 173472 bytes"):
            with self.subTest(benign=benign):
                self.assertEqual(redact(benign), benign)

    def test_redactor_is_a_superset_of_the_guard(self):
        """Property check: anything the GUARD can catch, the REDACTOR must catch first.

        This is the invariant whose violation deadlocked the pipeline once
        already (see ``test_openai_key_followed_by_word_char_is_redacted``). Nine
        hand-picked examples cannot establish it; this generates guard-matching
        tokens across every context they realistically appear in and asserts
        none survives the redactor.

        Seeded, so a failure is reproducible rather than a flake.
        """
        rng = random.Random(20260806)
        alphabet = string.ascii_letters + string.digits + "_-"
        contexts = (
            "token {t}",
            "https://api.telegram.org/bot{t}/getMe",
            "curl -s https://api.telegram.org/bot{t}/sendMessage -d chat_id=1",
            "TELEGRAM_BOT_TOKEN={t}",
            'BOT_TOKEN="{t}"',
            "failed: url (https://api.telegram.org/bot{t}/getUpdates): timeout",
        )
        for _ in range(500):
            token = (f"{rng.randrange(10**7, 10**12)}:"
                     + "".join(rng.choice(alphabet) for _ in range(35)))
            for tmpl in contexts:
                out = redact(tmpl.format(t=token))
                self.assertIsNone(LEAK_RX.search(out),
                                  f"guard would fire on redactor output: {out}")


class ExtractionPipelineLeakTests(unittest.TestCase):
    """End-to-end: a secret in a session file must not reach the archive.

    The unit tests above prove ``redact()`` in isolation. They cannot prove the
    *pipeline*, because text does not reach the redactor unchanged — tool steps
    go through ``step_label()`` first, which reformats and truncates. A pattern
    that is correct in isolation can still miss if the seam ahead of it mangles
    the value, so this drives a synthetic session file through the real
    ``parse_session()`` and asserts nothing survives anywhere in the output.
    """

    FAKE = "1234567890:AAFakeFakeFakeFakeFakeFakeFakeFake9"
    SECRET_HALF = FAKE.split(":")[1]

    def _session(self, *records):
        return "\n".join(json.dumps(r) for r in records) + "\n"

    def test_token_does_not_survive_any_realistic_leak_path(self):
        jsonl = self._session(
            {"type": "ai-title", "aiTitle": f"debugging bot {self.FAKE}"},
            # The way it really happens: a shell command with the token in the URL.
            {"type": "assistant", "timestamp": "2026-08-06T09:00:00Z",
             "message": {"role": "assistant", "model": "claude-sonnet-5", "content": [
                 {"type": "tool_use", "name": "Bash", "input": {
                     "command": f"curl -s https://api.telegram.org/bot{self.FAKE}/getMe"}}]}},
            # An HTTP client echoing the failing URL into an error string.
            {"type": "assistant", "timestamp": "2026-08-06T09:00:01Z",
             "message": {"role": "assistant", "model": "claude-sonnet-5", "content": [
                 {"type": "text",
                  "text": f"error sending request for url (https://api.telegram.org/bot{self.FAKE}/getUpdates)"}]}},
            # A human pasting it in plainly.
            {"type": "user", "timestamp": "2026-08-06T09:00:02Z",
             "message": {"role": "user", "content": [
                 {"type": "text", "text": f"here is the token: {self.FAKE}"}]}},
            # And in an env-var assignment, which the generic rules also cover.
            {"type": "user", "timestamp": "2026-08-06T09:00:03Z",
             "message": {"role": "user", "content": [
                 {"type": "text", "text": f"export TELEGRAM_BOT_TOKEN={self.FAKE}"}]}},
        )
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "synthetic-session.jsonl"
            src.write_text(jsonl, encoding="utf-8")
            meta = extract.parse_session(src)
            self.assertIsNotNone(meta, "fixture produced no dialogue — the test would be vacuous")

            out = Path(td) / "out.md"
            extract.write_markdown(meta, "test-project", out)
            written = out.read_text(encoding="utf-8")

        # Every surface: the title, each turn, and the rendered Markdown.
        self.assertNotIn(self.FAKE, meta["title"])
        for role, kind, ts, model, text in meta["turns"]:
            self.assertNotIn(self.FAKE, text, f"token survived in a {kind}: {text}")
            self.assertNotIn(self.SECRET_HALF, text, f"secret half survived in a {kind}: {text}")
        self.assertNotIn(self.FAKE, written, "token survived into the written Markdown")
        self.assertNotIn(self.SECRET_HALF, written, "secret half survived into the written Markdown")
        self.assertIsNone(LEAK_RX.search(written),
                          "written Markdown would trip the commit-time leak guard")
        # The archive must still be readable, not shredded into markers.
        self.assertIn("api.telegram.org", written)
        self.assertIn("[REDACTED-telegram-bot-token]", written)


if __name__ == "__main__":
    unittest.main()
