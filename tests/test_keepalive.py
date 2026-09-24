from __future__ import annotations

import datetime as dt
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cachekeeper import hook, keepalive
from cachekeeper.keepalive import MARK, Policy, View, plan, read_view, view_of

T0 = dt.datetime(2026, 9, 23, 10, 0, tzinfo=dt.timezone.utc)
ON = {"CACHEKEEPER_KEEPALIVE": "1", "CLAUDE_CODE_ENTRYPOINT": "claude-desktop"}


def stamp(seconds: float) -> str:
    return (T0 + dt.timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def at(seconds: float) -> float:
    return (T0 + dt.timedelta(seconds=seconds)).timestamp()


def prompt(uuid, seconds, text="fix the parser", origin="human", parent=None):
    entry = {"type": "user", "uuid": uuid, "parentUuid": parent, "timestamp": stamp(seconds),
             "message": {"role": "user", "content": text}}
    if origin:
        entry["origin"] = {"kind": origin}
    return entry


def attachment(uuid, seconds, parent):
    return {"type": "attachment", "uuid": uuid, "parentUuid": parent, "timestamp": stamp(seconds),
            "attachment": {"type": "total_tokens_reminder"}}


def reply(uuid, seconds, parent, message_id, read=150_000, write=2_000, output=300, ttl="1h", model="claude-opus-5-5"):
    split = {"ephemeral_1h_input_tokens": write if ttl == "1h" else 0,
             "ephemeral_5m_input_tokens": write if ttl == "5m" else 0}
    return {"type": "assistant", "uuid": uuid, "parentUuid": parent, "timestamp": stamp(seconds),
            "message": {"id": message_id, "model": model, "role": "assistant", "content": [{"type": "text", "text": "ok"}],
                        "usage": {"input_tokens": 2, "cache_read_input_tokens": read, "cache_creation_input_tokens": write,
                                  "output_tokens": output, "cache_creation": split}}}


def tool_result(uuid, seconds, parent):
    return {"type": "user", "uuid": uuid, "parentUuid": parent, "timestamp": stamp(seconds),
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "done"}]}}


def turn() -> list[dict]:
    """A user message, a tool call, and the final answer that started 7.1 s later."""
    return [
        prompt("u1", 0),
        attachment("a1", 0.1, "u1"),
        reply("r1", 5, "a1", "msg_1"),
        tool_result("t1", 6, "r1"),
        attachment("a2", 7.1, "t1"),
        reply("r2", 40, "a2", "msg_2"),       # a long answer: its first block lands 33 s after the request
        reply("r3", 41, "r2", "msg_2"),
    ]


def uncached(entries) -> list[dict]:
    """The same turn from a backend that reports no cache writes: plain input and output tokens only."""
    return [{**entry, "message": {**entry["message"], "usage": {"input_tokens": 152_000, "output_tokens": 300}}}
            if entry["type"] == "assistant" else entry for entry in entries]


def lines(entries) -> list[str]:
    return [json.dumps(entry) for entry in entries]


class ViewTests(unittest.TestCase):
    def test_the_hour_counts_from_when_the_last_request_started(self):
        view, complete = view_of(lines(turn()))
        self.assertTrue(complete)
        self.assertEqual(view.anchor, at(7.1))       # the entry the request was sent after, not the answer
        self.assertEqual(view.last_human, at(0))
        self.assertEqual(view.context, 2 + 150_000 + 2_000 + 300)
        self.assertEqual(view.ttl, 3600)

    def test_only_the_user_counts_as_the_user(self):
        entries = turn() + [
            prompt("n1", 100, "<task-notification>done</task-notification>", origin="task-notification", parent="r3"),
            # A ping counts as nobody, whatever origin it arrives with.
            prompt("p1", 200, f"cachekeeper: {MARK} 1 of 3, not an error: reply", origin="human", parent="n1"),
            prompt("l1", 300, "<command-name>/cost</command-name>", origin=None, parent="p1"),
            prompt("l2", 400, "[Request interrupted by user]", origin=None, parent="l1"),
        ]
        self.assertEqual(view_of(lines(entries))[0].last_human, at(0))
        legacy = turn() + [prompt("u2", 500, "and the tests", origin=None, parent="r3")]
        self.assertEqual(view_of(lines(legacy))[0].last_human, at(500))
        peer = turn() + [prompt("m1", 600, "From another session: status?", origin="peer", parent="r3")]
        self.assertEqual(view_of(lines(peer))[0].last_human, at(600))
        automatic = turn() + [prompt("c1", 700, "continue", origin="auto-continuation", parent="r3")]
        self.assertEqual(view_of(lines(automatic))[0].last_human, at(0))
        asking = turn() + [prompt("h1", 800, f"why did a {MARK} run at 3 am?", origin="human", parent="r3")]
        self.assertEqual(view_of(lines(asking))[0].last_human, at(800))

    def test_a_message_after_the_last_answer_is_the_latest_request(self):
        view, _ = view_of(lines(turn() + [prompt("u2", 90, "next", parent="r3")]))
        self.assertEqual(view.anchor, at(90))

    def test_a_compaction_after_the_last_request_leaves_nothing_to_keep(self):
        entries = turn() + [{"type": "system", "subtype": "compact_boundary", "uuid": "c1", "timestamp": stamp(60)}]
        self.assertEqual(view_of(lines(entries))[0].context, 0)

    def test_five_minute_cache_and_synthetic_messages(self):
        entries = turn()[:4] + [attachment("a2", 7.1, "t1"), reply("r2", 9, "a2", "msg_2", ttl="5m")]
        self.assertEqual(view_of(lines(entries))[0].ttl, 300)
        synthetic = turn() + [reply("s1", 99, "r3", "msg_s", model="<synthetic>")]
        self.assertEqual(view_of(lines(synthetic))[0].anchor, at(7.1))

    def test_reads_further_back_until_the_user_message_is_in_view(self):
        entries = [prompt("u1", 0)] + [
            {**tool_result(f"f{i}", 1 + i, "u1"), "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t", "content": "x" * 2_000}]}} for i in range(200)
        ] + [attachment("a9", 300, "f199"), reply("r9", 301, "a9", "msg_9")]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "s.jsonl"
            path.write_text("\n".join(lines(entries)) + "\n", encoding="utf-8")
            view = read_view(path, window=10_000)
        self.assertEqual(view.last_human, at(0))
        self.assertEqual(view.anchor, at(300))

    def test_reads_further_back_until_a_cache_write_is_in_view(self):
        entries = [prompt("u1", 0), attachment("a1", 0.1, "u1"), reply("r1", 5, "a1", "msg_1")] + [
            {**tool_result(f"f{i}", 6 + i, "r1"), "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t", "content": "x" * 2_000}]}} for i in range(200)
        ] + [prompt("u2", 290), attachment("a9", 300, "u2"), reply("r9", 301, "a9", "msg_9", write=0)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "s.jsonl"
            path.write_text("\n".join(lines(entries)) + "\n", encoding="utf-8")
            view = read_view(path, window=10_000)
        self.assertEqual((view.anchor, view.ttl), (at(300), 3600))

    def test_a_backend_that_reports_no_cache_writes_leaves_the_ttl_unknown(self):
        # Claude Code pointed at another provider's model (DeepSeek, on the author's machine) records usage
        # without cache writes: nothing tells the cache's lifetime.
        self.assertIsNone(view_of(lines(uncached(turn())))[0].ttl)


class PlanTests(unittest.TestCase):
    VIEW = View(anchor=1000.0, last_human=900.0, context=300_000, ttl=3600)
    POLICY = Policy()

    def test_waits_until_55_minutes_after_the_last_request_then_pings(self):
        self.assertEqual(plan(self.VIEW, [], 1001.0, 1060.0, self.POLICY), ("wait", 3300 - 60, ""))
        self.assertEqual(plan(self.VIEW, [], 1001.0, 1000.0 + 3300, self.POLICY), ("ping", 0.0, ""))

    def test_stands_down_when_a_ping_does_not_pay_or_cannot_land(self):
        cases = {
            "small": View(1000.0, 900.0, 99_999, 3600),
            "5-minute cache": View(1000.0, 900.0, 300_000, 300),
            "unknown cache": View(1000.0, 900.0, 300_000, None),
            "no request": View(None, 900.0, 300_000, 3600),
        }
        for reason, view in cases.items():
            with self.subTest(reason):
                self.assertEqual(plan(view, [], 1001.0, 4300.0, self.POLICY), ("stop", 0.0, reason))
        # The machine slept past the hour: the cache is gone, a ping would only rebuild it.
        self.assertEqual(plan(self.VIEW, [], 1001.0, 1000.0 + 3600 - 30, self.POLICY), ("stop", 0.0, "late"))

    def test_three_pings_in_a_row_then_the_cache_may_expire(self):
        pings = [4300.0, 7600.0, 10900.0]
        self.assertEqual(plan(self.VIEW, pings[:2], 1001.0, 1000.0 + 3300, self.POLICY)[0], "ping")
        self.assertEqual(plan(self.VIEW, pings, 1001.0, 1000.0 + 3300, self.POLICY), ("stop", 0.0, "cap"))
        back = View(20000.0, 20000.0, 300_000, 3600)        # the user wrote again: the count starts over
        self.assertEqual(plan(back, pings, 20001.0, 20000.0 + 3300, self.POLICY)[0], "ping")

    def test_the_user_coming_back_ends_the_wait(self):
        view = View(5000.0, 5000.0, 300_000, 3600)
        self.assertEqual(plan(view, [], 1001.0, 5010.0, self.POLICY), ("stop", 0.0, "user back"))

    def test_policy_from_settings(self):
        self.assertEqual(Policy.from_env({}), Policy(3300, 3, 100_000))
        custom = Policy.from_env({"CACHEKEEPER_KEEPALIVE_MINUTES": "50", "CACHEKEEPER_KEEPALIVE_HOURS": "2",
                                  "CACHEKEEPER_KEEPALIVE_MIN_TOKENS": "200000"})
        self.assertEqual(custom, Policy(3000, 2, 200_000))
        self.assertEqual(Policy.from_env({"CACHEKEEPER_KEEPALIVE_MINUTES": "junk"}).interval, 3300)

    def test_auto_mode_pings_every_55_minutes_the_interval_its_replay_prices(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "keepalive"
            folder.mkdir()
            (folder / "policy.json").write_text(json.dumps({"source": "history", "min_context": 100_000,
                                                            "cap_hours": 3.0}))
            env = {"CACHEKEEPER_KEEPALIVE_MINUTES": "30"}
            auto = keepalive.policy_for(env, Path(directory), 0.0, recompute=False)
            fixed = keepalive.policy_for({**env, "CACHEKEEPER_KEEPALIVE": "1"}, Path(directory), 0.0)
        self.assertEqual(auto, Policy(3300, 3, 100_000))
        self.assertEqual(fixed.interval, 1800)


class Clock:
    def __init__(self, start: float):
        self.value = start
        self.slept: list[float] = []
        self.on_sleep = None

    def now(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.value += seconds
        if self.on_sleep:
            self.on_sleep()


class WaitTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.transcript = self.directory / "s1.jsonl"
        self.transcript.write_text("\n".join(lines(turn())) + "\n", encoding="utf-8")
        self.event = {"session_id": "s1", "transcript_path": str(self.transcript), "hook_event_name": "Stop"}

    def tearDown(self):
        self.temporary.cleanup()

    def run_wait(self, clock, env=ON):
        err = io.StringIO()
        self.records = []
        code = keepalive.wait(self.event, dict(env), self.directory, now=clock.now, sleep=clock.sleep, err=err,
                              log=self.records.append)
        return code, err.getvalue()

    def test_pings_once_55_minutes_after_the_last_request(self):
        clock = Clock(at(45))
        code, text = self.run_wait(clock)
        self.assertEqual(code, keepalive.WAKE)
        self.assertAlmostEqual(clock.value, at(7.1) + 3300, delta=0.01)
        self.assertLessEqual(max(clock.slept), keepalive.POLL_SECONDS)
        self.assertIn(f"{MARK} 1 of 3", text)
        self.assertIn("Reply with exactly (keep-alive)", text)
        state = keepalive.read_state(keepalive.state_path(self.directory, "s1"))
        self.assertEqual(state["pings"], [clock.value])
        self.assertIsNone(state["generation"])
        [record] = self.records
        self.assertEqual((record["decision"], record["reason"], record["idle_seconds"]), ("ping", "1/3", 3300))

    def test_no_ping_when_the_transcript_never_shows_the_cache(self):
        self.transcript.write_text("\n".join(lines(uncached(turn()))) + "\n", encoding="utf-8")
        code, text = self.run_wait(Clock(at(45)))
        self.assertEqual((code, text, self.records), (0, "", []))     # stands down at once, and quietly

    def test_on_by_default_in_auto_mode_and_off_only_when_asked(self):
        for value, expected in (("", "auto"), ("auto", "auto"), ("Auto ", "auto"), ("1", "fixed"), ("on", "fixed"),
                                ("0", "off"), ("off", "off"), ("false", "off"), ("no", "off")):
            with self.subTest(value=value):
                self.assertEqual(keepalive.mode({"CACHEKEEPER_KEEPALIVE": value}), expected)
        self.assertEqual(keepalive.mode({}), "auto")

    def test_off_when_asked_and_never_in_single_shot_print_mode(self):
        for env in ({**ON, "CACHEKEEPER_KEEPALIVE": "0"}, {**ON, "CLAUDE_CODE_ENTRYPOINT": "sdk-cli"},
                    {"CLAUDE_CODE_ENTRYPOINT": "sdk-cli"}, {"CLAUDE_CODE_ENTRYPOINT": "sdk-py"}):
            with self.subTest(env=env):
                clock = Clock(at(45))
                self.assertEqual(self.run_wait(clock, env), (0, ""))
                self.assertEqual(clock.slept, [])
                self.assertEqual(self.records, [])

    def test_a_later_turn_or_a_model_switch_takes_over(self):
        clock = Clock(at(45))
        clock.on_sleep = lambda: keepalive.switched(self.directory, "s1") if len(clock.slept) == 3 else None
        self.assertEqual(self.run_wait(clock), (0, ""))
        self.assertEqual(len(clock.slept), 3)
        self.assertEqual(self.records[0]["reason"], "superseded")

    def test_after_three_pings_without_the_user_it_stays_quiet(self):
        path = keepalive.state_path(self.directory, "s1")
        keepalive.write_state(path, {"pings": [at(3000), at(6000), at(9000)]})
        clock = Clock(at(45))
        self.assertEqual(self.run_wait(clock), (0, ""))
        self.assertEqual(self.records[0]["reason"], "cap")

    def test_stands_down_when_claude_code_is_gone(self):
        clock = Clock(at(45))
        with mock.patch.object(keepalive, "_alive", return_value=False) as alive:
            self.assertEqual(self.run_wait(clock, {**ON, "CLAUDE_PID": "4242"}), (0, ""))
        alive.assert_called_with(4242)
        self.assertEqual(self.records[0]["reason"], "gone")

    def test_the_hook_entry_returns_the_exit_code(self):
        with mock.patch.object(keepalive, "wait", return_value=keepalive.WAKE) as wait, \
                mock.patch.object(hook.sys, "stdin", io.StringIO(json.dumps(self.event))):
            self.assertEqual(hook.main(["stop"]), keepalive.WAKE)
        self.assertEqual(wait.call_args.args[0], self.event)
        with mock.patch.object(hook.sys, "stdin", io.StringIO("not json")), \
                mock.patch.object(hook.sys, "stderr", io.StringIO()):
            self.assertEqual(hook.main(["stop"]), 0)

    def test_a_switch_through_the_hook_stands_the_wait_down_but_a_resume_does_not(self):
        path = keepalive.state_path(self.directory, "s1")
        env = {"CLAUDE_PLUGIN_DATA": str(self.directory)}
        post = {"session_id": "s1", "from_model": "claude-opus-5-5", "to_model": "claude-fable-5-1"}
        keepalive.write_state(path, {"generation": "g", "pings": []})
        hook.handle("post-model-switch", json.dumps({**post, "source": "resume"}), env)
        self.assertEqual(keepalive.read_state(path)["generation"], "g")
        hook.handle("post-model-switch", json.dumps({**post, "source": "sdk"}), env)
        self.assertIsNone(keepalive.read_state(path)["generation"])


class AliveTests(unittest.TestCase):
    """The wait's check that Claude Code (CLAUDE_PID) still runs. On Windows it must not use os.kill, which would
    terminate the process it asks about."""

    def test_a_process_is_alive_until_it_ends_and_asking_leaves_it_running(self):
        self.assertTrue(keepalive._alive(os.getpid()))
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            self.assertTrue(keepalive._alive(child.pid))
            self.assertTrue(keepalive._alive(child.pid))
            self.assertIsNone(child.poll())
        finally:
            child.kill()
            child.wait()
        self.assertFalse(keepalive._alive(child.pid))


if __name__ == "__main__":
    unittest.main()
