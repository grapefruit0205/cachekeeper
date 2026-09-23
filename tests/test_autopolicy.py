import datetime as dt
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cachekeeper import autopolicy, keepalive
from cachekeeper.audit import Gap, analyze, idle_gaps
from cachekeeper.transcripts import read_sessions
from test_audit import T0, at, response, write

DAY = 86_400
NOW = T0.timestamp() + 2 * DAY


def gap(hours, context=300_000, rebuild=3.0, start=0.0, session="s"):
    # Opus 5 list prices: a cache read of 300k tokens costs $0.15, the one-hour rewrite $3.
    return Gap(hours * 3600, context, 0.5, rebuild, NOW - DAY + start, session)


def ping(minutes, number):
    text = (f"<task-notification><summary>cachekeeper keep-alive ping</summary></task-notification>\n"
            f"cachekeeper: keep-alive ping {number} of 3, not an error: reply with exactly (keep-alive)")
    return [{"type": "user", "timestamp": at(minutes), "origin": {"kind": "task-notification"},
             "message": {"role": "user", "content": text}}]


class DecideTests(unittest.TestCase):
    def test_breaks_the_pings_can_bridge_set_the_cap(self):
        decision = autopolicy.decide([gap(1.5, start=i * 3600) for i in range(12)], NOW, 1, 1)
        self.assertEqual(decision["source"], "history")
        # One ping bridges a 90-minute break: a one-hour cap saves as much as any longer one, with fewer pings.
        self.assertEqual((decision["cap_hours"], decision["min_context"]), (1.0, 0))
        self.assertEqual(decision["prevented"], 12)

    def test_too_little_history_uses_the_defaults(self):
        decision = autopolicy.decide([gap(1.5, start=i) for i in range(9)], NOW, 1, 1)
        self.assertEqual((decision["source"], decision["min_context"], decision["cap_hours"]), ("default", 100_000, 3.0))

    def test_breaks_too_long_to_bridge_turn_it_off(self):
        decision = autopolicy.decide([gap(30, start=i) for i in range(12)], NOW, 1, 1)
        self.assertEqual(decision["source"], "off")

    def test_five_minute_cache_sessions_only_turn_it_off(self):
        self.assertEqual(autopolicy.decide([], NOW, 0, 5)["why"], "5-minute cache")

    def test_only_the_recent_window_counts(self):
        old = [Gap(5400, 300_000, 0.5, 3.0, NOW - 90 * DAY + i, "s") for i in range(12)]
        self.assertEqual(autopolicy.decide(old, NOW, 1, 1)["source"], "default")


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.projects = self.root / "projects"
        self.data = self.root / "data"

    def test_a_break_kept_warm_by_pings_still_counts_as_the_break_it_was(self):
        entries = (response("m1", 0, "claude-opus-5", write_1h=300_000)
                   + ping(55, 1) + response("p1", 55.1, "claude-opus-5", read=300_000, write_1h=300, output=9)
                   + ping(110, 2) + response("p2", 110.1, "claude-opus-5", read=300_300, write_1h=300, output=9)
                   + response("m2", 150, "claude-opus-5", read=300_600, write_1h=2_000))
        write(self.projects / "p" / "s.jsonl", entries, T0.timestamp())
        sessions = read_sessions(self.projects, T0 - dt.timedelta(days=1))
        self.assertEqual([r.ping for r in sessions[0].requests], [False, True, True, False])
        [stretch], _ = idle_gaps(sessions)
        self.assertEqual(stretch.seconds, 150 * 60)
        # The pings kept the cache, so nothing was rewritten; the stretch carries the rewrite they saved.
        self.assertAlmostEqual(stretch.rebuild_cost, (300_000 + 3 + 100) * 10.0 / 1_000_000)
        report = analyze(sessions, 1).to_json()
        self.assertEqual(report["keepalive"]["pings_sent"], 2)
        self.assertEqual(report["keepalive"]["prevented_rebuilds"], 1)
        self.assertEqual(report["rebuilds"]["idle expiry"]["count"], 0)

    def test_idle_stretches_outlive_the_transcripts(self):
        path = self.data / "keepalive" / "gaps.jsonl"
        first = [gap(1.5, start=i * 3600, session="a") for i in range(6)]
        known = autopolicy.remember(path, autopolicy.load_gaps(path), first)
        # The next day the same stretches are read again with new ones; the day after, the transcript is gone.
        second = first[3:] + [gap(2, start=40_000 + i * 3600, session="b") for i in range(6)]
        known = autopolicy.remember(path, autopolicy.load_gaps(path), second)
        self.assertEqual(len(known), 12)
        self.assertEqual(len(autopolicy.load_gaps(path)), 12)
        self.assertEqual(len(path.read_text().splitlines()), 12)

    def test_the_policy_is_recomputed_once_a_day(self):
        with mock.patch.object(autopolicy, "recompute", side_effect=lambda d, p, now: {"computed_at": now,
                                                                                       "source": "history"}) as run:
            env = {"CLAUDE_CONFIG_DIR": str(self.root)}
            first = autopolicy.current(self.data, env, NOW)
            self.assertEqual(run.call_args.args[1], self.projects)
            (self.data / "keepalive").mkdir(parents=True, exist_ok=True)
            (self.data / "keepalive" / "policy.json").write_text(json.dumps(first))
            autopolicy.current(self.data, env, NOW + DAY - 60)
            self.assertEqual(run.call_count, 1)
            autopolicy.current(self.data, env, NOW + DAY + 60)
            self.assertEqual(run.call_count, 2)

    def test_one_recomputation_at_a_time(self):
        lock = self.data / "keepalive" / "policy.lock"
        lock.parent.mkdir(parents=True)
        lock.write_text("")
        with mock.patch.object(autopolicy, "recompute") as run:
            decision = autopolicy.current(self.data, {}, lock.stat().st_mtime + 5)
        run.assert_not_called()
        self.assertEqual(decision["source"], "default")

    def test_recompute_writes_what_the_hook_reads(self):
        entries = []
        for day in range(12):   # a 90-minute lunch every day, and the rewrite it cost
            base = day * 24 * 60
            entries += response(f"a{day}", base, "claude-opus-5", write_1h=300_000)
            entries += response(f"b{day}", base + 90, "claude-opus-5", write_1h=300_500)
        write(self.projects / "p" / "s.jsonl", entries, T0.timestamp() + 12 * DAY)
        decision = autopolicy.recompute(self.data, self.projects, T0.timestamp() + 13 * DAY)
        self.assertEqual((decision["source"], decision["cap_hours"]), ("history", 1.0))
        self.assertEqual(autopolicy.read_decision(self.data), decision)


class AutoWaitTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data = Path(self.temporary.name)
        self.transcript = self.data / "s1.jsonl"
        self.transcript.write_text("{}\n")
        self.event = {"session_id": "s1", "transcript_path": str(self.transcript)}
        self.env = {"CACHEKEEPER_KEEPALIVE": "auto", "CLAUDE_CODE_ENTRYPOINT": "claude-desktop"}

    def decided(self, decision):
        folder = self.data / "keepalive"
        folder.mkdir(exist_ok=True)
        (folder / "policy.json").write_text(json.dumps({"computed_at": NOW, **decision}))

    def test_auto_mode_waits_under_todays_policy(self):
        self.decided({"source": "history", "min_context": 200_000, "cap_hours": 2.0})
        self.assertEqual(keepalive.policy_for(self.env, self.data, NOW), keepalive.Policy(3300, 2, 200_000))
        fixed = {**self.env, "CACHEKEEPER_KEEPALIVE": "1", "CACHEKEEPER_KEEPALIVE_HOURS": "1"}
        self.assertEqual(keepalive.policy_for(fixed, self.data, NOW), keepalive.Policy(3300, 1, 100_000))

    def test_an_off_verdict_ends_the_wait_before_it_starts(self):
        self.decided({"source": "off", "min_context": 0, "cap_hours": 0.0})
        records = []
        with mock.patch.object(keepalive, "_wait") as inner:
            code = keepalive.wait(self.event, self.env, self.data, now=lambda: NOW, sleep=lambda s: None,
                                  err=io.StringIO(), log=records.append)
        self.assertEqual((code, records), (0, []))
        inner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
