"""The hooks and the CLI the way Claude Code runs them: hooks.json's commands in each shell it uses, the event on stdin.

On Windows Claude Code runs a plugin's hook commands with Git Bash, or with PowerShell when there is no Git Bash, and
Python writes a pipe in the ANSI code page (cp1252, cp949) unless told otherwise, while Claude Code reads UTF-8.
Forcing those code pages here reproduces that on any system; on Windows CI the same tests also run Git Bash's `sh` on
a Windows path, and PowerShell 7 (pwsh) and Windows PowerShell 5.1, as Claude Code does.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from cachekeeper.keepalive import WAKE

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


# Claude Code 2.1.280 runs a shell-form hook with /bin/sh -c on macOS and Linux (dash on Ubuntu). On Windows it uses
# Git Bash, or PowerShell when there is no Git Bash: pwsh (7 and later) if it finds one, else Windows PowerShell 5.1,
# started with these flags. Every one of them found here is tested.
POWERSHELL_FLAGS = ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command"]


def hook_shells() -> dict:
    if os.name != "nt":
        return {"sh": ["/bin/sh", "-c"]}
    shells = {}
    if git_bash():
        shells["git-bash"] = [git_bash(), "-c"]
    for name in ("pwsh", "powershell"):
        if shutil.which(name):
            shells[name] = [shutil.which(name), *POWERSHELL_FLAGS]
    return shells


SHELLS = hook_shells()
POWERSHELLS = {name: argv for name, argv in SHELLS.items() if name in ("pwsh", "powershell")}


def as_claude_code_runs(shell: str, command: str, root: Path) -> str:
    """Claude Code puts the plugin's native path in place of ${CLAUDE_PLUGIN_ROOT} and exports it as well; in a
    PowerShell command it writes PowerShell's ${env:CLAUDE_PLUGIN_ROOT} there instead."""
    return command.replace("${CLAUDE_PLUGIN_ROOT}", "${env:CLAUDE_PLUGIN_ROOT}" if shell in POWERSHELLS else str(root))

CODE_PAGES = ("utf-8", "cp1252", "cp949")
COLD = {"session_id": "s1", "prompt_cache": {"warm": False, "caching_observed": True, "ttl": "1h", "expires_at": None,
                                             "recache_tokens_if_cold": 312_000}}
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
        # It runs hooks in the session's folder, never the plugin's: the package must come from the launcher.
        result = subprocess.run([SH, f"{ROOT}/{script}", *args], input=stdin, env=env, cwd=self.directory.name,
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

    def test_the_status_line_prints_korean_whatever_the_code_page(self):
        for code_page in CODE_PAGES:
            with self.subTest(code_page=code_page):
                code, out = self.run_script("bin/cachekeeper", ["statusline"], code_page, json.dumps(COLD).encode())
                self.assertEqual((code, out.strip()), (0, "캐시 식음 · 다음 요청에 312k 다시 씀"))


@unittest.skipIf(not POWERSHELLS, "no PowerShell (Claude Code on Windows without Git Bash runs commands in it)")
class PowerShellCliTests(unittest.TestCase):
    """bin/cachekeeper.ps1, which the audit skill runs by its path where the only shell tool is PowerShell."""

    def test_the_cli_prints_a_korean_report_whatever_the_code_page(self):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, True)
        empty = directory / "no projects"      # a space: the argument must reach Python as one
        empty.mkdir()
        base = {key: value for key, value in os.environ.items()
                if not key.startswith(("CACHEKEEPER_", "CLAUDE_", "PYTHONIOENCODING", "PYTHONUTF8"))}
        command = f"& '{ROOT / 'bin' / 'cachekeeper.ps1'}' audit --lang ko --projects '{empty}'"
        for shell, argv in POWERSHELLS.items():
            for code_page in CODE_PAGES:
                with self.subTest(shell=shell, code_page=code_page):
                    result = subprocess.run([*argv, command], env={**base, "PYTHONIOENCODING": code_page},
                                            cwd=directory, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
                    self.assertEqual((result.returncode, result.stderr.decode("utf-8", "replace")), (0, ""))
                    self.assertIn("cachekeeper 감사 — 최근 30일", result.stdout.decode("utf-8"))

    def test_the_status_line_reads_its_stdin_through_the_readmes_command(self):
        # The README's command for Windows without Git Bash: `powershell -NoProfile -ExecutionPolicy Bypass -File
        # C:/Users/<you>/.claude/plugins/marketplaces/cachekeeper/bin/cachekeeper.ps1 statusline`.
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, True)
        base = {key: value for key, value in os.environ.items()
                if not key.startswith(("CACHEKEEPER_", "CLAUDE_", "PYTHONIOENCODING", "PYTHONUTF8"))}
        for shell, argv in POWERSHELLS.items():
            for code_page in CODE_PAGES:
                with self.subTest(shell=shell, code_page=code_page):
                    result = subprocess.run(
                        [argv[0], "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                         (ROOT / "bin" / "cachekeeper.ps1").as_posix(), "statusline"],
                        input=json.dumps(COLD).encode(), cwd=directory, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        env={**base, "PYTHONIOENCODING": code_page, "CACHEKEEPER_LANG": "ko"}, timeout=120)
                    self.assertEqual((result.returncode, result.stderr.decode("utf-8", "replace")), (0, ""))
                    self.assertEqual(result.stdout.decode("utf-8").strip(), "캐시 식음 · 다음 요청에 312k 다시 씀")


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


@unittest.skipIf(not SHELLS, "no Git Bash or PowerShell (Claude Code on Windows runs plugin hooks with one of them)")
class HookCommandTests(unittest.TestCase):
    """hooks/hooks.json's own commands, run by each shell Claude Code runs them with."""

    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.directory, True)
        self.base = {key: value for key, value in os.environ.items()
                     if not key.startswith(("CACHEKEEPER_", "CLAUDE_", "PYTHONIOENCODING", "PYTHONUTF8"))}

    def run_hook(self, shell, event_name, event, root=ROOT, **env):
        command = as_claude_code_runs(shell, HOOKS[event_name][0]["hooks"][0]["command"], root)
        env = {**self.base, "CLAUDE_PLUGIN_ROOT": str(root), "CLAUDE_PLUGIN_DATA": str(self.directory / shell / "data"),
               "CACHEKEEPER_LANG": "ko", "CLAUDE_CODE_ENTRYPOINT": "cli", "PYTHONIOENCODING": "cp949", **env}
        started = time.monotonic()
        # Claude Code writes the event and a newline to the hook's stdin and runs it in the session's folder.
        result = subprocess.run([*SHELLS[shell], command], input=json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n",
                                env=env, cwd=self.directory, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        self.seconds = time.monotonic() - started
        self.assertLess(self.seconds, HOOKS[event_name][0]["hooks"][0]["timeout"])   # past it, Claude Code gives up
        return result.returncode, result.stdout.decode("utf-8"), result.stderr.decode("utf-8")

    def stop_event(self, read):
        path = self.directory / "session.jsonl"
        path.write_text("".join(json.dumps(entry) + "\n" for entry in transcript(read)), encoding="utf-8")
        return {"session_id": "s1", "transcript_path": str(path), "hook_event_name": "Stop", "stop_hook_active": False}

    def test_the_keep_alive_wakes_the_model_with_exit_2_and_a_utf8_message(self):
        # asyncRewake wakes the model only on exit code 2, with the hook's stderr (Claude Code 2.1.280).
        for shell in SHELLS:
            with self.subTest(shell=shell):
                code, out, err = self.run_hook(shell, "Stop", self.stop_event(read=150_000), CACHEKEEPER_KEEPALIVE="1")
                self.assertEqual((code, out), (2, ""), err)
                self.assertTrue(err.startswith("keep-alive ping 1 of 3, not an error"), err)   # nothing around it

    def test_a_small_session_is_left_alone(self):
        for shell in SHELLS:
            with self.subTest(shell=shell):
                self.assertEqual(self.run_hook(shell, "Stop", self.stop_event(read=1_000), CACHEKEEPER_KEEPALIVE="1"),
                                 (0, "", ""))

    def test_the_guard_and_the_offer_reach_claude_code_in_utf8(self):
        for shell in SHELLS:
            with self.subTest(shell=shell):
                code, out, err = self.run_hook(shell, "PreModelSwitch", EVENT)
                specific = json.loads(out)["hookSpecificOutput"]
                self.assertEqual((code, specific["permissionDecision"], err), (0, "ask", ""))
                self.assertIn("opus-5-5 → fable-5-1", specific["permissionDecisionReason"])
                code, out, err = self.run_hook(shell, "UserPromptSubmit",
                                               {"session_id": "s1", "prompt": "이 버그 원인을 찾아줘 — 한글 프롬프트"})
                self.assertEqual((code, err), (0, ""))
                self.assertIn("이 요청을 fable-5-1 서브에이전트로 실행할까요?",
                              json.loads(out)["hookSpecificOutput"]["additionalContext"])

    def test_no_hook_exits_2_when_the_plugin_files_are_gone(self):
        # Exit 2 blocks a switch, erases a prompt and wakes the model; an asyncRewake Stop hook that exits 2 on
        # every turn end loops without end (anthropics/claude-code#96087, #96148). Ubuntu's sh (dash) exits 2 when
        # it cannot open a script, as after an update removed the directory a running session still points at.
        gone = self.directory / "removed-plugin-version"
        events = {"PreModelSwitch": {"session_id": "s1", "to_model": "claude-fable-5-1"},
                  "PostModelSwitch": {"session_id": "s1", "to_model": "claude-fable-5-1"},
                  "UserPromptSubmit": {"session_id": "s1", "prompt": "안녕"},
                  "Stop": self.stop_event(read=150_000)}
        for shell in SHELLS:
            for event_name, event in events.items():
                with self.subTest(shell=shell, event=event_name):
                    code, out, err = self.run_hook(shell, event_name, event, root=gone, CACHEKEEPER_KEEPALIVE="1")
                    self.assertEqual((code, out), (0, ""), err)

    def test_only_the_keep_alives_own_code_becomes_exit_2(self):
        # A hook command exits 2 only when the keep-alive asks for a ping with its own code (WAKE). Whatever else a
        # launcher can end with, 2 from a Python that cannot open a file among it, ends the hook with 0.
        fake = self.directory / "fake-plugin"
        (fake / "hooks").mkdir(parents=True)
        (fake / "hooks" / "run").write_text('cat >/dev/null\nexit "$FAKE_CODE"\n', encoding="utf-8")
        (fake / "hooks" / "run.ps1").write_text(
            "[Console]::OpenStandardInput().CopyTo([IO.Stream]::Null)\nexit [int]$env:FAKE_CODE\n", encoding="utf-8")
        for shell in SHELLS:
            for event_name in HOOKS:
                for exit_code in (0, 1, 2, WAKE):
                    with self.subTest(shell=shell, event=event_name, exit_code=exit_code):
                        code, out, err = self.run_hook(shell, event_name, {"session_id": "s1"}, root=fake,
                                                       FAKE_CODE=str(exit_code))
                        self.assertEqual(code, 2 if event_name == "Stop" and exit_code == WAKE else 0, err)

    @unittest.skipUnless(os.name == "nt" and os.environ.get("GITHUB_ACTIONS"), "only GitHub's Windows runners")
    def test_githubs_windows_runners_test_every_shell_and_log_how_long_a_hook_takes(self):
        # They have Git Bash, pwsh and Windows PowerShell 5.1: none may drop out of these tests unnoticed.
        self.assertEqual(sorted(SHELLS), ["git-bash", "powershell", "pwsh"])
        times = {}
        for shell in SHELLS:
            runs = []
            for _ in range(3):
                self.assertEqual(self.run_hook(shell, "UserPromptSubmit", {"session_id": "s1", "prompt": "hi"}),
                                 (0, "", ""))
                runs.append(self.seconds)
            times[shell] = statistics.median(runs)
        sys.stderr.write("UserPromptSubmit, median of 3: "
                         + ", ".join(f"{shell} {seconds:.2f} s" for shell, seconds in times.items()) + "\n")

    def test_the_stop_command_turns_the_keep_alives_own_code_into_2_in_both_shells(self):
        command = HOOKS["Stop"][0]["hooks"][0]["command"]
        self.assertIn(f"[ $? -eq {WAKE} ] && exit 2", command)
        self.assertIn(f"if ($LASTEXITCODE -eq {WAKE}) {{ exit 2 }}", command)


if __name__ == "__main__":
    unittest.main()
