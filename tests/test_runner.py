"""The hooks and the CLI the way Claude Code runs them: `sh <plugin root>/hooks/run <event>`, the event on stdin.

On Windows Claude Code runs a plugin's hook commands with Git Bash, and Python writes a pipe in the ANSI code page
(cp1252, cp949) unless told otherwise, while Claude Code reads UTF-8. Forcing those code pages here reproduces that
on any system; on Windows CI the same tests also run Git Bash's `sh` on a Windows path, as Claude Code does.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SH = shutil.which("sh")
HOOKS = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]


def git_bash() -> str | None:
    """The bash Claude Code runs hooks with on Windows (Git for Windows), never WSL's System32 launcher."""
    for candidate in (os.environ.get("CLAUDE_CODE_GIT_BASH_PATH"), r"C:\Program Files\Git\bin\bash.exe",
                      shutil.which("bash")):
        if candidate and os.path.isfile(candidate) and "system32" not in candidate.lower():
            return candidate
    return None


# Claude Code runs a shell-form hook with /bin/sh -c on macOS and Linux (dash on Ubuntu) and with Git Bash on Windows.
SHELL = [git_bash(), "-c"] if os.name == "nt" else ["/bin/sh", "-c"]
CODE_PAGES = ("utf-8", "cp1252", "cp949")
EVENT = {
    "session_id": "s1", "hook_event_name": "PreModelSwitch", "from_model": "claude-opus-5-5",
    "to_model": "claude-fable-5-1", "requested_model": "fable", "source": "sdk", "context_tokens": 338_385,
    "prompt_cache_warm": True, "cache_ttl": "1h", "estimated_cache_write_usd": 6.77, "pricing": "catalog",
}


@unittest.skipIf(SH is None, "no sh on PATH (on Windows it comes with Git for Windows)")
class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        # Nothing from the developer's own settings: no CACHEKEEPER_* or Claude Code variables.
        self.base = {key: value for key, value in os.environ.items()
                     if not key.startswith(("CACHEKEEPER_", "CLAUDE_", "PYTHONIOENCODING", "PYTHONUTF8"))}

    def run_script(self, script, args, code_page, stdin=b"", data="data"):
        env = {**self.base, "PYTHONIOENCODING": code_page, "CACHEKEEPER_LANG": "ko", "CLAUDE_CODE_ENTRYPOINT": "cli",
               "CLAUDE_PLUGIN_DATA": str(Path(self.directory.name) / code_page / data)}
        # Claude Code substitutes a native path for ${CLAUDE_PLUGIN_ROOT}: backslashes on Windows, then "/hooks/run".
        result = subprocess.run([SH, f"{ROOT}/{script}", *args], input=stdin, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        self.assertEqual(result.stderr.decode("utf-8", "replace"), "")
        return result.returncode, result.stdout.decode("utf-8")

    def test_the_guard_and_the_offer_speak_utf8_whatever_the_code_page(self):
        for code_page in CODE_PAGES:
            with self.subTest(code_page=code_page):
                code, out = self.run_script("hooks/run", ["pre-model-switch"], code_page,
                                            json.dumps(EVENT).encode("utf-8"))
                specific = json.loads(out)["hookSpecificOutput"]
                self.assertEqual((code, specific["permissionDecision"]), (0, "ask"))
                self.assertIn("opus-5-5 → fable-5-1", specific["permissionDecisionReason"])
                prompt = {"session_id": "s1", "prompt": "이 버그 원인을 찾아줘 — 한글 프롬프트"}
                code, out = self.run_script("hooks/run", ["user-prompt-submit"], code_page,
                                            json.dumps(prompt, ensure_ascii=False).encode("utf-8"))
                offer = json.loads(out)
                self.assertIn("fable-5-1 서브에이전트에 맡길지 먼저 묻습니다", offer["systemMessage"])
                self.assertIn("이 요청을 fable-5-1 서브에이전트로 실행할까요?",
                              offer["hookSpecificOutput"]["additionalContext"])

    def test_the_cli_prints_a_korean_report_whatever_the_code_page(self):
        empty = Path(self.directory.name) / "projects"
        empty.mkdir()
        for code_page in CODE_PAGES:
            with self.subTest(code_page=code_page):
                code, out = self.run_script("bin/cachekeeper", ["audit", "--lang", "ko", "--projects", str(empty)],
                                            code_page)
                self.assertEqual(code, 0)
                self.assertIn("cachekeeper 감사 — 최근 30일", out)


def stamp(seconds_ago: float) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=seconds_ago)).isoformat().replace("+00:00", "Z")


def transcript(read: int) -> list[dict]:
    """A turn whose last request started 56 minutes ago on the one-hour cache: the keep-alive pings at once."""
    return [
        {"type": "user", "uuid": "u1", "parentUuid": None, "timestamp": stamp(3370), "origin": {"kind": "human"},
         "message": {"role": "user", "content": "fix the parser"}},
        {"type": "attachment", "uuid": "a1", "parentUuid": "u1", "timestamp": stamp(3360),
         "attachment": {"type": "total_tokens_reminder"}},
        {"type": "assistant", "uuid": "r1", "parentUuid": "a1", "timestamp": stamp(3340),
         "message": {"id": "msg_1", "model": "claude-opus-5-5", "role": "assistant",
                     "content": [{"type": "text", "text": "ok"}],
                     "usage": {"input_tokens": 2, "cache_read_input_tokens": read, "cache_creation_input_tokens": 2000,
                               "output_tokens": 300, "cache_creation": {"ephemeral_1h_input_tokens": 2000,
                                                                        "ephemeral_5m_input_tokens": 0}}}},
    ]


@unittest.skipIf(SHELL[0] is None, "no Git Bash (Claude Code on Windows runs plugin hooks with it)")
class HookCommandTests(unittest.TestCase):
    """hooks/hooks.json's own commands, run by the shell Claude Code runs them with."""

    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.directory, True)
        self.base = {key: value for key, value in os.environ.items()
                     if not key.startswith(("CACHEKEEPER_", "CLAUDE_", "PYTHONIOENCODING", "PYTHONUTF8"))}

    def run_hook(self, event_name, event, root=ROOT, **env):
        command = HOOKS[event_name][0]["hooks"][0]["command"]
        # Claude Code puts the plugin's native path in place of ${CLAUDE_PLUGIN_ROOT} and exports it as well.
        command = command.replace("${CLAUDE_PLUGIN_ROOT}", str(root))
        env = {**self.base, "CLAUDE_PLUGIN_ROOT": str(root), "CLAUDE_PLUGIN_DATA": str(self.directory / "data"),
               "CACHEKEEPER_LANG": "ko", "CLAUDE_CODE_ENTRYPOINT": "cli", "PYTHONIOENCODING": "cp949", **env}
        started = time.monotonic()
        result = subprocess.run([*SHELL, command], input=json.dumps(event, ensure_ascii=False).encode("utf-8"),
                                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        self.assertLess(time.monotonic() - started, 60)
        return result.returncode, result.stdout.decode("utf-8"), result.stderr.decode("utf-8")

    def stop_event(self, read):
        path = self.directory / "session.jsonl"
        path.write_text("".join(json.dumps(entry) + "\n" for entry in transcript(read)), encoding="utf-8")
        return {"session_id": "s1", "transcript_path": str(path), "hook_event_name": "Stop", "stop_hook_active": False}

    def test_the_keep_alive_wakes_the_model_with_exit_2_and_a_utf8_message(self):
        # asyncRewake wakes the model only on exit code 2, with the hook's stderr (Claude Code 2.1.280).
        code, out, err = self.run_hook("Stop", self.stop_event(read=150_000), CACHEKEEPER_KEEPALIVE="1")
        self.assertEqual(code, 2, err)
        self.assertIn("keep-alive ping 1 of 3", err)
        self.assertIn("not an error", err)

    def test_a_small_session_is_left_alone(self):
        code, out, err = self.run_hook("Stop", self.stop_event(read=1_000), CACHEKEEPER_KEEPALIVE="1")
        self.assertEqual((code, out, err), (0, "", ""))

    def test_no_hook_exits_2_when_the_plugin_files_are_gone(self):
        # Exit 2 blocks a switch, erases a prompt and wakes the model; an asyncRewake Stop hook that exits 2 on
        # every turn end loops without end (anthropics/claude-code#96087, #96148). Ubuntu's sh (dash) exits 2 when
        # it cannot open a script, as after an update removed the directory a running session still points at.
        gone = self.directory / "removed-plugin-version"
        events = {"PreModelSwitch": {"session_id": "s1", "to_model": "claude-fable-5-1"},
                  "PostModelSwitch": {"session_id": "s1", "to_model": "claude-fable-5-1"},
                  "UserPromptSubmit": {"session_id": "s1", "prompt": "안녕"},
                  "Stop": self.stop_event(read=150_000)}
        for event_name, event in events.items():
            with self.subTest(event=event_name):
                code, out, err = self.run_hook(event_name, event, root=gone, CACHEKEEPER_KEEPALIVE="1")
                self.assertNotEqual(code, 2, err)
                self.assertEqual((code, out), (0, ""))


if __name__ == "__main__":
    unittest.main()
