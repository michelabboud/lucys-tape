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
            keep = [l for l in p.read_text().splitlines()
                    if '"message"' not in l or '"developer"' in l]
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
