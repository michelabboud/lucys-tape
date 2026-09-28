"""Tests for the codex rollout source adapter (Lucy's Tape port, 2026-07-18).

All fixtures are SYNTHETIC — no real session content, no real secrets. The fake
key below is a deliberately fabricated shape that must be redacted.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import extract_conversations as ex  # noqa: E402

FAKE_KEY = "sk-" + "a1B2" * 6  # 24 chars after sk- → must trip openai_key


def _line(t, payload, ts="2026-07-18T03:00:00.000Z"):
    return json.dumps({"timestamp": ts, "type": t, "payload": payload})


def make_rollout(dirpath, name="rollout-2026-07-18T03-00-00-synthetic0001.jsonl",
                 cwd=str(Path.home() / "projects" / "webapp"), with_dialogue=True):
    lines = [
        _line("session_meta", {"id": "synthetic0001", "timestamp": "2026-07-18T03:00:00.000Z",
                               "cwd": cwd, "git": {"branch": "main"},
                               "model_provider": "openai", "cli_version": "0.144.5"}),
        _line("turn_context", {"model": "gpt-5.6-sol", "cwd": cwd}),
        _line("response_item", {"type": "message", "role": "developer",
                                "content": [{"type": "input_text", "text": "system prompt — never archived as dialogue"}]}),
        _line("response_item", {"type": "message", "role": "user",
                                "content": [{"type": "input_text",
                                             "text": "<environment_context>noise</environment_context>fix the dashboard bug"}]}),
        _line("response_item", {"type": "function_call", "name": "shell",
                                "arguments": json.dumps({"command": ["bash", "-lc", "grep -rn bug src/"]}),
                                "call_id": "c1"}),
        _line("response_item", {"type": "function_call_output", "call_id": "c1",
                                "output": "should never be archived"}),
        _line("response_item", {"type": "reasoning", "summary": ["private, never archived"]}),
        _line("event_msg", {"type": "agent_message", "message": "duplicate stream — skipped"}),
    ]
    if with_dialogue:
        lines.append(_line("response_item", {"type": "message", "role": "assistant",
                                             "content": [{"type": "output_text",
                                                          "text": f"fixed it; also here is a fake leak {FAKE_KEY}"}]}))
    p = Path(dirpath) / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


class CodexParseTest(unittest.TestCase):
    def parse(self, **kw):
        with tempfile.TemporaryDirectory() as d:
            return ex.parse_codex_session(make_rollout(d, **kw))

    def test_basic_shape(self):
        meta = self.parse()
        self.assertIsNotNone(meta)
        self.assertEqual(meta["sid"], "synthetic0001")
        self.assertEqual(meta["engine"], "codex")
        self.assertEqual(meta["project"], "webapp")
        self.assertEqual(meta["branch"], "main")
        self.assertEqual(meta["models"], "gpt-5.6-sol")
        self.assertEqual(meta["user_turns"], 1)
        self.assertEqual(meta["assistant_turns"], 1)
        self.assertEqual(meta["n_steps"], 1)

    def test_user_wrapper_stripped_and_developer_skipped(self):
        meta = self.parse()
        texts = [tx for r, k, _t, _m, tx in meta["turns"] if k == "dialogue"]
        self.assertTrue(any(tx == "fix the dashboard bug" for tx in texts))
        joined = "\n".join(tx for _r, _k, _t, _m, tx in meta["turns"])
        self.assertNotIn("environment_context", joined)
        self.assertNotIn("system prompt", joined)

    def test_secret_redacted_and_outputs_reasoning_absent(self):
        meta = self.parse()
        joined = "\n".join(tx for _r, _k, _t, _m, tx in meta["turns"])
        self.assertNotIn(FAKE_KEY, joined)
        self.assertIn("[REDACTED sk-key]", joined)
        self.assertNotIn("should never be archived", joined)
        self.assertNotIn("private, never archived", joined)
        self.assertNotIn("duplicate stream", joined)

    def test_step_label_is_bash_style(self):
        meta = self.parse()
        steps = [tx for r, k, _t, _m, tx in meta["turns"] if k == "step"]
        self.assertEqual(len(steps), 1)
        self.assertTrue(steps[0].startswith("Bash: "), steps[0])
        self.assertIn("grep -rn bug src/", steps[0])

    def test_no_dialogue_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            p = make_rollout(d, with_dialogue=True)
            # rewrite keeping only meta + telemetry: no dialogue at all
            keep = [line for line in p.read_text().splitlines()
                    if '"message"' not in line or '"developer"' in line]
            p.write_text("\n".join(keep) + "\n")
            self.assertIsNone(ex.parse_codex_session(p))

    def test_model_attribution_on_assistant_only(self):
        meta = self.parse()
        for role, kind, _ts, model, _tx in meta["turns"]:
            if kind == "dialogue" and role == "user":
                self.assertEqual(model, "")
            if kind == "dialogue" and role == "assistant":
                self.assertEqual(model, "gpt-5.6-sol")


class CodexLabelTest(unittest.TestCase):
    def test_projects_path(self):
        self.assertEqual(ex.codex_project_label(str(Path.home() / "projects" / "webapp")), "webapp")

    def test_worktree_path_keeps_own_name(self):
        self.assertEqual(ex.codex_project_label(str(Path.home() / "projects" / "webapp-wt-a")), "webapp-wt-a")

    def test_home(self):
        self.assertEqual(ex.codex_project_label(str(Path.home())), "home")

    def test_empty(self):
        self.assertEqual(ex.codex_project_label(None), "codex-misc")


class CodexEngineSentinelTest(unittest.TestCase):
    def test_engine_key_in_fab_sentinel(self):
        with tempfile.TemporaryDirectory() as d:
            meta = ex.parse_codex_session(make_rollout(d))
            meta["title"] = "synthetic"
            out = Path(d) / "out.md"
            ex.write_markdown(meta, "webapp", out)
            first = out.read_text().splitlines()[0]
            self.assertIn('"engine":"codex"', first.replace(" ", ""))


if __name__ == "__main__":
    unittest.main()


class CodexShellLabelTests(unittest.TestCase):
    """A shell step must carry its COMMAND, not just the tool's name.

    Measured on the real Temple 2026-08-06: 174,092 of 525,768 step turns (33% of
    the whole Architect layer) rendered as a bare label with no command, and every
    single one came from a codex model. Two independent causes:

      1. `exec` carries its payload in `input`, not `arguments`, and that payload
         is JAVASCRIPT — `const r = await tools.exec_command({"cmd": "..."})` —
         which json.loads cannot parse. 107,953 turns rendered as `exec`.
      2. codex names the key `cmd`; the labeller read `command`. So even the
         older calls whose arguments WERE valid JSON produced an empty
         `Bash: ` — 66,139 turns.

    The data was never missing from the source or filtered by the viewer. The
    extractor dropped it on the way in.
    """

    JS_WRAPPER = ('const r = await tools.exec_command('
                  '{"cmd":"rg -n \'fox\' /home/michel/projects","workdir":"/home/michel"});\n'
                  'console.log(r);')

    def test_exec_payload_in_input_as_javascript(self):
        label = ex.codex_step_label("exec", self.JS_WRAPPER)
        self.assertIn("rg -n 'fox'", label, f"command was dropped: {label!r}")
        self.assertNotEqual(label, "exec")

    def test_exec_command_uses_the_cmd_key_not_command(self):
        label = ex.codex_step_label("exec_command", json.dumps({"cmd": "cargo test -p vaelir"}))
        self.assertIn("cargo test -p vaelir", label, f"command was dropped: {label!r}")
        self.assertNotEqual(label.strip(), "Bash:")

    def test_plain_json_arguments_still_work(self):
        for name in ("shell", "local_shell", "exec_command", "exec"):
            with self.subTest(name=name):
                label = ex.codex_step_label(name, json.dumps({"command": ["ls", "-la"]}))
                self.assertIn("ls -la", label)

    def test_a_shell_step_never_renders_a_lying_empty_label(self):
        # If the command genuinely cannot be recovered, say the tool's name —
        # never "Bash: " with nothing after it, which reads as a real step that
        # ran nothing.
        for payload in (None, "", "{}", "not json at all", '{"workdir":"/tmp"}'):
            with self.subTest(payload=payload):
                label = ex.codex_step_label("exec", payload)
                self.assertNotEqual(label.strip(), "Bash:")
                self.assertFalse(label.strip().endswith(":"), f"empty label: {label!r}")

    def test_braces_inside_the_command_do_not_break_extraction(self):
        js = ('const r = await tools.exec_command('
              '{"cmd":"awk \'{print $1}\' file.txt | sort"});')
        label = ex.codex_step_label("exec", js)
        self.assertIn("awk", label)
        self.assertIn("print $1", label)

    def test_secrets_in_a_recovered_command_are_still_redacted(self):
        js = f'const r = await tools.exec_command({{"cmd":"export TOKEN={FAKE_KEY}"}});'
        label = ex.redact(ex.codex_step_label("exec", js))
        self.assertNotIn(FAKE_KEY, label)

    def test_non_shell_tools_are_unaffected(self):
        self.assertEqual(ex.codex_step_label("apply_patch", "{}"), "apply_patch (edit)")
        self.assertEqual(ex.codex_step_label("list_agents", "{}"), "list_agents")


class CodexPatchLabelTests(unittest.TestCase):
    """`exec` is a JS sandbox, not only a shell.

    On real rollouts roughly three quarters of `exec` calls are apply_patch
    envelopes rather than commands. Labelling those "Bash:" would swap one wrong
    label for another, so they are recognised and named for the file they touch.
    """

    def _envelope(self, *files):
        body = "*** Begin Patch\\n" + "".join(
            f"*** Update File: {f}\\n@@\\n-old\\n+new\\n" for f in files) + "*** End Patch"
        return f'const patch = "{body}";\nawait tools.apply_patch({{patch}});'

    def test_single_file_patch_names_the_file(self):
        label = ex.codex_step_label("exec", self._envelope("/home/u/projects/mai/VERSION"))
        self.assertIn("apply_patch", label)
        self.assertIn("mai/VERSION", label)
        self.assertNotIn("Bash", label)

    def test_multi_file_patch_names_the_first_and_counts_the_rest(self):
        label = ex.codex_step_label("exec", self._envelope(
            "/home/u/projects/mai/VERSION", "/home/u/projects/mai/CHANGELOG.md",
            "/home/u/projects/mai/README.md"))
        self.assertIn("VERSION", label)
        self.assertIn("+2 more", label)

    def test_add_and_delete_directives_are_recognised(self):
        for directive in ("Add", "Delete"):
            with self.subTest(directive=directive):
                payload = f'const patch = "*** Begin Patch\\n*** {directive} File: a/b.txt\\n";'
                self.assertIn("apply_patch", ex.codex_step_label("exec", payload))

    def test_a_shell_command_is_still_a_shell_command(self):
        # The patch branch must not swallow ordinary exec_command calls.
        js = 'const r = await tools.exec_command({"cmd":"git status"});'
        self.assertIn("Bash: git status", ex.codex_step_label("exec", js))

    def test_secrets_inside_a_patch_path_are_still_redacted(self):
        payload = f'const patch = "*** Begin Patch\\n*** Update File: /tmp/{FAKE_KEY}.txt\\n";'
        self.assertNotIn(FAKE_KEY, ex.redact(ex.codex_step_label("exec", payload)))


class CodexJsPayloadTests(unittest.TestCase):
    """The `exec` payload is JavaScript, and JS is not JSON."""

    def test_unquoted_object_keys_are_recovered(self):
        # `{cmd:"…"}` is legal JS and illegal JSON — the most common real shape.
        js = 'const r = await tools.exec_command({cmd:"git log --oneline -5",workdir:"/tmp"});'
        label = ex.codex_step_label("exec", js)
        self.assertIn("Bash: git log --oneline -5", label)

    def test_single_quoted_js_strings_do_not_break_the_scan(self):
        js = "const r = await tools.exec_command({cmd:\"echo 'hi there'\"});"
        self.assertIn("echo 'hi there'", ex.codex_step_label("exec", js))

    def test_inner_tool_is_named_when_there_is_no_command(self):
        js = 'const r = await tools.write_stdin({session_id:"3",chars:"y\\n"});'
        label = ex.codex_step_label("exec", js)
        self.assertIn("write_stdin", label)
        self.assertNotEqual(label, "exec")

    def test_the_sandbox_itself_is_never_reported_as_the_inner_tool(self):
        self.assertIsNone(ex.codex_inner_tool("await tools.exec({})"))

    def test_unrecoverable_payload_still_degrades_to_the_tool_name(self):
        for payload in (None, "", "// just a comment", "???"):
            with self.subTest(payload=payload):
                self.assertEqual(ex.codex_step_label("exec", payload), "exec")

    def test_a_secret_in_an_unquoted_key_payload_is_redacted(self):
        js = f'const r = await tools.exec_command({{cmd:"curl -H \'Authorization: Bearer {FAKE_KEY}\'"}});'
        self.assertNotIn(FAKE_KEY, ex.redact(ex.codex_step_label("exec", js)))
