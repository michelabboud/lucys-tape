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
    # Headless private-key bodies by DER prefix — the same alternatives as the
    # redactor's private_key_der_body, so the guard stays a subset.
    r"|\b(MII[A-Za-z0-9+/]{3}IBAAK[BC]|MII[A-Za-z0-9+/]{3}IBADANBgkqhkiG9w0BAQEFAASC|MHcCAQEE|MIGkAgEBBD|MIHcAgEBBE"
    r"|MIGHAgEAMBMGByqGSM49|MIG2AgEAMBAGByqGSM49|MIHuAgEAMBAGByqGSM49"
    r"|MC4CAQAwBQYDK2V[uw]|MEcCAQAwBQYDK2Vx|MEYCAQAwBQYDK2Vv|b3BlbnNzaC1rZXktdjE)"
    # Namespaced sk- keys (sk-proj-, sk-svcacct-, …): narrower than the redactor's
    # openai_ns_key (lowercase namespace, hyphen only), so the guard stays a subset.
    r"|\bsk-[a-z]{2,12}-[A-Za-z0-9_-]{20}",
    re.ASCII,  # tools/tape compiles it the same way and greps with LC_ALL=C
)

FAKE_B64 = "MIIEpAIBAAKCAQEA" + "x" * 48  # 64-char base64-ish line, like real PEM body


class ViewerKeyTests(unittest.TestCase):
    def test_a_printed_viewer_link_loses_its_key(self):
        key = "Zx9_-" + "q" * 38
        out = extract.redact(f"viewer up → http://127.0.0.1:8124/?key={key}  (stop: tape stop)")
        self.assertNotIn(key, out)
        self.assertIn("http://127.0.0.1:8124/?key=[REDACTED viewer key]", out)

    def test_an_ordinary_query_parameter_is_left_alone(self):
        text = "see http://127.0.0.1:8124/?q=key%3Dvalue and ?key=short"
        self.assertEqual(extract.redact(text), text)


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

    def test_headless_body_with_footer_is_redacted(self):
        # Body + END footer, NO BEGIN header. The footer used to be defanged (guard
        # passes) while every body token survived: a key shipped in the archive.
        body = "y" * 64
        out = redact(f"{body}\n{body}\n{body}\n-----END RSA PRIVATE KEY-----")
        self.assertIn("[REDACTED PRIVATE KEY BLOCK]", out)
        self.assertNotIn(body, out)
        self.assert_guard_clean(out)

    def test_env_file_cut_shape_is_redacted_but_names_survive(self):
        # `cut -d= -f1` over an env file holding a multi-line PEM value prints the
        # names, then the key's DER-prefixed first line, body tokens joined by spaces,
        # the END footer with a stray quote, then more names. Body and prefix must go;
        # the variable NAMES (harmless) stay readable.
        prefix = "MIIEowIBAAKCAQEA13FNXnq6"
        b1, b2 = "y" * 64, "z" * 64
        text = (f"SERVICE_API_KEY APP_PRIVATE_KEY {prefix} {b1} {b2} "
                f'-----END RSA PRIVATE KEY-----" APP_KEY_ALIAS OTHER_API_KEY')
        out = redact(text)
        for secret in (prefix, b1, b2):
            self.assertNotIn(secret, out)
        self.assertIn("APP_PRIVATE_KEY", out)
        self.assertIn("APP_KEY_ALIAS", out)
        self.assert_guard_clean(out)

    def test_der_body_without_any_framing_is_redacted(self):
        # PKCS#8: no header, no footer, just the base64, recognised by its DER prefix.
        head = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQ"
        out = redact(f"key: {head}{'y' * 40} {'z' * 64} end")
        self.assertIn("[REDACTED PRIVATE KEY BODY]", out)
        self.assertNotIn("AASCBKcw", out)
        self.assertNotIn("z" * 64, out)
        self.assertIn("end", out)
        self.assert_guard_clean(out)

    def test_space_joined_truncated_block_is_redacted(self):
        # Header + body joined by SPACES on one line, no footer. The old truncated
        # rule only accepted newline-separated bodies.
        body = "y" * 64
        out = redact(f"-----BEGIN RSA PRIVATE KEY----- {body} {body}")
        self.assertIn("[REDACTED PRIVATE KEY BLOCK]", out)
        self.assertNotIn(body, out)
        self.assert_guard_clean(out)

    def test_public_key_certificate_and_csr_survive(self):
        # Failure path for the DER rule: PUBLIC material must NOT be eaten. A public
        # key reads ...AAOCAQ8..., a certificate ...TCCA..., a CSR ...ICAQAw...; none
        # carry the private OCTET STRING marker.
        for public in (
            "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA" + "y" * 40,
            "MIIDXTCCAkWgAwIBAgIJAJC1HiIAZAiIMA0GCSqGSIb3DQEBBQUAMEUx" + "y" * 40,
            "MIICijCCAXICAQAwRTELMAkGA1UEBhMCQVUxEzARBgNVBAgMClNvbWUtU3RhdGUx" + "y" * 40,
        ):
            with self.subTest(public=public[:20]):
                out = redact(f"cert: {public}")
                self.assertEqual(out, f"cert: {public}")
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


class CredentialShapeBlindSpotTests(unittest.TestCase):
    """LT-SEC-002: credential shapes the redactor used to miss (July 2026 bughunt).

    Every value below is fake. Each test names the shape and asserts the value is
    gone; the near-miss tests at the end assert ordinary text survives.
    """

    def assert_gone(self, text, secret):
        out = redact(text)
        self.assertNotIn(secret, out, f"survived: {out}")
        self.assertIsNone(LEAK_RX.search(out), f"guard would fire: {out}")
        return out

    def test_quoted_json_keys(self):
        secret = "Zq8vLm2pXw7rTn4k"
        for text in (f'{{"password": "{secret}"}}', f"{{'api_key': '{secret}'}}",
                     f'{{"client_secret":"{secret}"}}', f'"token" : "{secret}",'):
            with self.subTest(text=text):
                self.assert_gone(text, secret)

    def test_quoted_json_key_keeps_the_name_and_structure(self):
        out = redact('{"password": "Zq8vLm2pXw7rTn4k", "user": "ada"}')
        self.assertIn('"password"', out)
        self.assertIn('"user": "ada"', out)

    def test_prefixed_lowercase_names(self):
        secret = "Zq8vLm2pXw7rTn4k"
        for text in (f"db_password={secret}", f"smtp_password: {secret}",
                     f"my_api_key = {secret}", f"stripe_secret_key={secret}"):
            with self.subTest(text=text):
                self.assert_gone(text, secret)

    def test_cloud_secret_assignments(self):
        aws = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYzq8vLm2pXw"  # 40 chars, AWS secret shape
        for text in (f"AWS_SECRET_ACCESS_KEY={aws}", f"export AWS_SECRET_ACCESS_KEY='{aws}'",
                     f"aws_secret_access_key = {aws}", f'"AWS_SECRET_ACCESS_KEY": "{aws}"',
                     f"AWS_SECRET_ACCESS_KEY: {aws}"):
            with self.subTest(text=text):
                self.assert_gone(text, aws)

    def test_azure_account_key_in_connection_string(self):
        key = "Zq8vLm2pXw7rTn4kQ1s9Yb3cVd6fGh0jKl5mNo8pRs2tUv4wXy7zAa1bCc3dEe6fGg9hHi2jJk5lLm8nNo1pPq4r+w=="
        out = self.assert_gone(
            f"DefaultEndpointsProtocol=https;AccountName=acct;AccountKey={key};EndpointSuffix=core.windows.net",
            key)
        self.assertIn("AccountName=acct", out)

    def test_padded_base64_followed_by_delimiters(self):
        k32 = "Zq8vLm2pXw7rTn4kQ1s9Yb3cVd6fGh0jKl5mNo8pRs2="   # 44 chars: 32 bytes
        k31 = "Zq8vLm2pXw7rTn4kQ1s9Yb3cVd6fGh0jKl5mNo8pRs=="   # double padding
        for key in (k32, k31):
            for text in (f"key {key} end", f'"{key}"', f"key={key},", f"{key}"):
                with self.subTest(text=text):
                    self.assert_gone(text, key)

    def test_base64_starting_with_slash_or_plus(self):
        key = "/q8vLm2pXw7rTn4kQ1s9Yb3cVd6fGh0jKl5mNo8pRs2="
        self.assert_gone(f"secret {key} here", key[1:])

    def test_namespaced_sk_keys(self):
        body = "Zq8vLm2pXw7rTn4kQ1s9Yb3cVd6fGh0j"
        for key in (f"sk-proj-{body}", f"sk-svcacct-{body}", f"sk-admin-{body}",
                    f"sk-or-v1-{body}", f"sk_live_{body}", f"sk_test_{body}",
                    f"rk_live_{body}", f"sk-proj-{body[:10]}_{body[10:]}"):
            with self.subTest(key=key):
                self.assert_gone(f"key {key} leaked", body[-20:])

    def test_short_wrapped_truncated_private_key(self):
        # Footerless key wrapped at 32 columns: every body line is under 40 chars.
        lines = ["Zq8vLm2pXw7rTn4kQ1s9Yb3cVd6fGh0j", "Kl5mNo8pRs2tUv4wXy7zAa1bCc3dEe6f",
                 "Gg9hHi2jJk5lLm8nNo1pPq4rSs7tTu0v"]
        out = redact("-----BEGIN PRIVATE KEY-----\n" + "\n".join(lines) + "\n")
        for line in lines:
            self.assertNotIn(line, out)
        self.assertIsNone(LEAK_RX.search(out))

    def test_short_wrapped_headless_private_key(self):
        lines = ["Zq8vLm2pXw7rTn4kQ1s9Yb3cVd6fGh0j", "Kl5mNo8pRs2tUv4wXy7zAa1bCc3dEe6f"]
        out = redact("\n".join(lines) + "\n-----END PRIVATE KEY-----")
        for line in lines:
            self.assertNotIn(line, out)

    def test_namespaced_sk_guard_hit_is_always_redacted(self):
        """The guard learned namespaced sk- keys; the redactor must stay a superset."""
        rng = random.Random(20260928)
        alphabet = string.ascii_letters + string.digits + "_-"
        for _ in range(500):
            ns = "".join(rng.choice(string.ascii_lowercase) for _ in range(rng.randint(2, 12)))
            key = f"sk-{ns}-" + "".join(rng.choice(alphabet) for _ in range(rng.randint(20, 60)))
            for tmpl in ("key {k}", "OPENAI_API_KEY={k}", '"api_key": "{k}"', "x={k}_y"):
                out = redact(tmpl.format(k=key))
                self.assertIsNone(LEAK_RX.search(out), f"guard would fire: {out}")

    def test_near_misses_survive(self):
        for text in (
            "the password field is required",          # no value after a separator
            "use scikit-learn and sk-learn-style APIs", # short sk- words
            "password_hint = remember the dog",         # a different name
            "git sha 3f2c1a9b8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b",
            "a=b and c=d",
            "https://example.com/a/b?x=1&y=2",
            # CSP / Subresource Integrity hashes are public digests
            "script-src 'self' 'sha256-uoFkiLr290rm6B9wdpdUCNJZ13JE4Zq8vLm2pXw7rTn='",
            'integrity="sha384-' + "Zq8vLm2pXw7rTn4kQ1s9Yb3cVd6fGh0jKl5mNo8pRs2tUv4wXy7zAa1bCc3dEe6f" + '"',
        ):
            with self.subTest(text=text):
                self.assertEqual(redact(text), text)


class RedactorReviewRegressionTests(unittest.TestCase):
    """Findings from the deep review of the 0.2.4 redactor (2026-09-28)."""

    # First 24 chars of keys openssl generated on 2026-09-28 (the tails are random
    # and not included). Every one is a PRIVATE key.
    GENERATED_PREFIXES = {
        "rsa1024 pkcs1": "MIICXgIBAAKBgQDC39XUyYNW", "rsa1024 pkcs8": "MIICdwIBADANBgkqhkiG9w0B",
        "rsa2048 pkcs1": "MIIEowIBAAKCAQEAwJN7dKeJ", "rsa2048 pkcs8": "MIIEvwIBADANBgkqhkiG9w0B",
        "rsa3072 pkcs1": "MIIG5AIBAAKCAYEAsoM9+DT6", "rsa3072 pkcs8": "MIIG/QIBADANBgkqhkiG9w0B",
        "rsa4096 pkcs1": "MIIJKAIBAAKCAgEAmEc6qAaj", "rsa4096 pkcs8": "MIIJQQIBADANBgkqhkiG9w0B",
        "p256 sec1": "MHcCAQEEIIIDD7i/xJM1/j8p", "p256 pkcs8": "MIGHAgEAMBMGByqGSM49AgEG",
        "p384 sec1": "MIGkAgEBBDDdYt1yxsJ++M5Z", "p384 pkcs8": "MIG2AgEAMBAGByqGSM49AgEG",
        "p521 sec1": "MIHcAgEBBEIBKj9RposaZ2zl", "p521 pkcs8": "MIHuAgEAMBAGByqGSM49AgEG",
        "ed25519": "MC4CAQAwBQYDK2VwBCIEIHGu", "x25519": "MC4CAQAwBQYDK2VuBCIEIBCl",
        "ed448": "MEcCAQAwBQYDK2VxBDsEOXaF", "x448": "MEYCAQAwBQYDK2VvBDoEOGBd",
    }
    # PKCS#8 bodies continue with this for RSA (bytes 0x0D.. of the header).
    RSA_PKCS8_TAIL = "AQEFAASC"

    def test_every_generated_private_key_type_is_redacted_without_framing(self):
        for kind, prefix in self.GENERATED_PREFIXES.items():
            body = prefix + (self.RSA_PKCS8_TAIL if prefix.endswith("9w0B") else "") + "Q" * 40
            with self.subTest(kind=kind):
                out = redact(f"value: {body} {'Z' * 64}")
                self.assertIn("[REDACTED PRIVATE KEY BODY]", out)
                self.assertNotIn(body[:20], out)
                self.assertIsNone(LEAK_RX.search(out))

    def test_ed25519_public_key_survives(self):
        pub = "MCowBQYDK2VwAyEAz3Ph73SY" + "Q" * 20
        self.assertEqual(redact(f"pub: {pub}"), f"pub: {pub}")

    def test_prefix_list_matches_the_guard(self):
        guard = LEAK_RX.pattern
        for alt in extract.DER_PRIVATE_PREFIXES.split("|"):
            with self.subTest(alt=alt):
                self.assertIn(alt, guard)

    def test_headless_footer_scan_is_linear(self):
        import time
        blobs = ("A" * 200_000, " ".join(["A" * 76] * 3000), "\n".join(["A" * 76] * 3000))
        for blob in blobs:
            start = time.perf_counter()
            redact(blob)
            self.assertLess(time.perf_counter() - start, 2.0)

    def test_single_long_line_before_footer_is_redacted(self):
        # Ed25519 PKCS#8 is one 64-char line: body + footer, no header.
        line = "MC4CAQAwBQYDK2VwBCIEIHGu" + "Q" * 40
        out = redact(f"{line}\n-----END PRIVATE KEY-----")
        self.assertNotIn(line[24:], out)
        self.assertIsNone(LEAK_RX.search(out))

    def test_headless_body_after_a_label_is_redacted_label_kept(self):
        body = "Q" * 64
        out = redact(f"KEY={body}\n{body}\n-----END RSA PRIVATE KEY-----")
        self.assertNotIn(body, out)
        self.assertIn("KEY=", out)

    def test_escaped_newlines_in_a_json_string(self):
        body = "MIIEowIBAAKCAQEAwJN7dKeJ" + "Q" * 40
        for text in ('{"k": "-----BEGIN RSA PRIVATE KEY-----\\n' + body + '\\n' + "Z" * 64 + '\\n',
                     '{"k": "' + "Y" * 64 + '\\n' + "Z" * 64 + '\\n-----END RSA PRIVATE KEY-----\\n"}'):
            with self.subTest(text=text[:30]):
                out = redact(text)
                for secret in ("Q" * 40, "Z" * 64, "Y" * 64):
                    self.assertNotIn(secret, out)
                self.assertIsNone(LEAK_RX.search(out))

    def test_short_last_line_of_a_truncated_key(self):
        out = redact("-----BEGIN PRIVATE KEY-----\n" + "Q" * 64 + "\nZq8vLm2p==\nnext line")
        self.assertNotIn("Zq8vLm2p", out)
        self.assertIn("next line", out)

    def test_quoted_values_go_whole(self):
        for value in ("correct horse battery staple", "ab,cdefghij", "hunt2", 'with \\" quote'):
            with self.subTest(value=value):
                out = redact(f'{{"password": "{value}", "user": "ada"}}')
                self.assertEqual(out, '{"password": "[REDACTED]", "user": "ada"}')

    def test_non_ascii_neighbour_does_not_hide_a_key(self):
        for pre in ("密钥是", "é", "ключ"):
            with self.subTest(pre=pre):
                out = redact(pre + "sk-proj-" + "A" * 25)
                self.assertNotIn("A" * 25, out)
                self.assertIsNone(LEAK_RX.search(out))
                self.assertIsNone(re.search(LEAK_RX.pattern.encode(), out.encode(), re.ASCII))

    def test_glued_base64_keys_go_in_one_pass(self):
        k = "Zq8vLm2pXw7rTn4kQ1s9Yb3cVd6fGh0jKl5mNo8pRs2="
        once = redact(f"x {k}{k} y")
        self.assertNotIn(k[:20], once)
        self.assertEqual(redact(once), once)

    def test_guard_never_fires_on_redactor_output_for_older_shapes(self):
        # ADR 0003 violations that predate this work: guard patterns the redactor
        # used to leave behind (sk-ant- with 15-19 chars; xai- and AKIA glued to a
        # word; AKIA with 17+ chars).
        for text in ("sk-ant-" + "a1B2c" * 3, "foo_xai-" + "A" * 20, "xAKIA" + "A" * 16,
                     "AKIA" + "B" * 17, "id_AKIA" + "C" * 16):
            with self.subTest(text=text):
                self.assertIsNone(LEAK_RX.search(redact(text)), redact(text))


class RedactorReReviewTests(unittest.TestCase):
    """Findings from the re-review of 0.2.5 (2026-09-28)."""

    def test_aws_key_glued_to_another_key_leaves_nothing_for_the_guard(self):
        for tail in ("sk-proj-" + "B" * 24, "sk-" + "B" * 20, "b3BlbnNzaC1rZXktdjE" + "B" * 20):
            with self.subTest(tail=tail[:12]):
                out = redact("AKIA" + "A" * 16 + tail)
                self.assertIsNone(LEAK_RX.search(out), out)
                self.assertEqual(redact(out), out)

    def test_escaped_carriage_returns_separate_key_lines(self):
        body = "Q" * 64
        out = redact(f"{body}\\r{body}\\r-----END RSA PRIVATE KEY-----")
        self.assertNotIn(body, out)

    def test_headless_key_removed_in_a_diff(self):
        body = "Q" * 64
        out = redact(f"@@ -1,3 +0,0 @@\n-{body}\n-{body}\n------END RSA PRIVATE KEY-----\n")
        self.assertNotIn(body, out)
        self.assertIn("@@ -1,3 +0,0 @@", out)

    def test_full_block_output_is_unchanged_from_before(self):
        body = "Q" * 64
        out = redact(f"-----BEGIN RSA PRIVATE KEY-----\n{body}\n-----END RSA PRIVATE KEY-----")
        self.assertEqual(out, "[REDACTED PRIVATE KEY BLOCK]")

    def test_spaced_marker_is_not_cut_in_half(self):
        body = "Q" * 64
        out = redact(f"PRIVATE_KEY={body}\n{body}\n-----END RSA PRIVATE KEY-----")
        self.assertNotIn(body, out)
        self.assertNotIn("[REDACTED] PRIVATE", out)


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
