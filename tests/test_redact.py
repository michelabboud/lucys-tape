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
import re
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


if __name__ == "__main__":
    unittest.main()
