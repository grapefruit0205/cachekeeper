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


def gap(hours, context=300_000, rebuild=300_000, start=0.0, session="s"):
    # Opus 5 on subscription usage (the default here): a 300k rewrite counts $1.50, a ping under a cent.
    return Gap(hours * 3600, context, "claude-opus-5", rebuild, NOW - DAY + start, session)


def ping(minutes, number):
    text = (f"<task-notification><summary>cachekeeper keep-alive ping</summary></task-notification>\n"
            f"cachekeeper: keep-alive ping {number} of 3, not an error: reply with exactly (keep-alive)")
    return [{"type": "user", "timestamp": at(minutes), "origin": {"kind": "task-notification"},
             "message": {"role": "user", "content": text}}]


class DecideTests(unittest.TestCase):
    def test_breaks_the_pings_can_bridge_set_the_cap(self):
        decision = autopolicy.decide([gap(1.5, start=i * 3600) for i in range(12)], NOW, 1, 1)
        self.assertEqual(decision["source"], "history")
        # One ping bridges a 90-minute break: a one-hour cap saves as much as any longer one, with fewer pings;
        # every minimum up to 300k saves the same, and the largest leaves more small sessions alone.
        self.assertEqual((decision["cap_hours"], decision["min_context"]), (1.0, 300_000))
        self.assertEqual(decision["prevented"], 12)

    def test_a_near_tie_goes_to_fewer_pings(self):
        # A small session's break adds a few cents: not worth pinging every small session for.
        gaps = [gap(1.5, start=i * 3600) for i in range(12)] + [gap(1.5, context=50_000, rebuild=10_000, start=99_000)]
        decision = autopolicy.decide(gaps, NOW, 1, 1)
        self.assertEqual((decision["min_context"], decision["pings"]), (300_000, 12))
        exact = autopolicy.decide(gaps[:12] + [gap(1.5, context=50_000, rebuild=50_000, start=99_000)], NOW, 1, 1)
        self.assertEqual(exact["min_context"], 0)       # a real difference still wins

    def test_too_little_history_uses_the_defaults(self):
        decision = autopolicy.decide([gap(1.5, start=i) for i in range(9)], NOW, 1, 1)
        self.assertEqual((decision["source"], decision["min_context"], decision["cap_hours"]), ("default", 100_000, 3.0))

    def test_breaks_too_long_to_bridge_turn_it_off(self):
        decision = autopolicy.decide([gap(30, start=i) for i in range(12)], NOW, 1, 1)
        self.assertEqual(decision["source"], "off")

    def test_five_minute_cache_sessions_only_turn_it_off(self):
        self.assertEqual(autopolicy.decide([], NOW, 0, 5)["why"], "5-minute cache")

    def test_only_the_recent_window_counts(self):
        old = [Gap(5400, 300_000, "claude-opus-5", 300_000, NOW - 90 * DAY + i, "s") for i in range(12)]
        self.assertEqual(autopolicy.decide(old, NOW, 1, 1)["source"], "default")

    def test_sessions_never_returned_to_cost_pings_but_are_not_stretches(self):
        left = [Gap(30 * 3600, 300_000, "claude-opus-5", 0, NOW - 2 * DAY + i, "t", returned=False) for i in range(12)]
        self.assertEqual(autopolicy.decide(left, NOW, 1, 1)["source"], "default")    # nothing to learn from yet
        decision = autopolicy.decide([gap(1.5, start=i * 3600) for i in range(12)] + left, NOW, 1, 1)
        # Each costs as many pings as the cap allows: the one-hour cap still bridges every lunch, with fewest.
        self.assertEqual((decision["stretches"], decision["cap_hours"], decision["pings"]), (12, 1.0, 24))


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
        [stretch] = idle_gaps(sessions)
        self.assertEqual(stretch.seconds, 150 * 60)
        # The pings kept the cache, so nothing was rewritten; the stretch carries the rewrite they saved.
        self.assertEqual(stretch.rebuild_tokens, 300_000 + 3 + 100)
        report = analyze(sessions, 1).to_json()
        self.assertEqual(report["keepalive"]["pings_sent"], 2)
        self.assertEqual(report["keepalive"]["prevented_rebuilds"], 1)
        self.assertEqual(report["rebuilds"]["idle expiry"]["count"], 0)

    def test_a_rebuild_after_the_pings_is_not_theirs_to_claim(self):
        # The pings kept the cache, but the effort change on return rewrote it anyway: they saved nothing.
        entries = (response("m1", 0, "claude-opus-5", write_1h=300_000)
                   + ping(55, 1) + response("p1", 55.1, "claude-opus-5", read=300_000, write_1h=300, output=9)
                   + ping(110, 2) + response("p2", 110.1, "claude-opus-5", read=300_300, write_1h=300, output=9)
                   + response("m2", 150, "claude-opus-5", write_1h=302_600, effort="high"))
        write(self.projects / "p" / "s.jsonl", entries, T0.timestamp())
        [stretch] = idle_gaps(read_sessions(self.projects, T0 - dt.timedelta(days=1)))
        self.assertEqual(stretch.rebuild_tokens, 0)

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
        with mock.patch.object(autopolicy, "recompute", side_effect=lambda d, p, now, basis: {
                "computed_at": now, "source": "history", "basis": basis}) as run:
            env = {"CLAUDE_CONFIG_DIR": str(self.root)}
            first = autopolicy.current(self.data, env, NOW)
            self.assertEqual(run.call_args.args[1], self.projects)
            (self.data / "keepalive").mkdir(parents=True, exist_ok=True)
            (self.data / "keepalive" / "policy.json").write_text(json.dumps(first))
            autopolicy.current(self.data, env, NOW + DAY - 60)
            self.assertEqual(run.call_count, 1)
            autopolicy.current(self.data, env, NOW + DAY + 60)
            self.assertEqual(run.call_count, 2)

    def test_a_policy_computed_on_another_yardstick_is_redone(self):
        folder = self.data / "keepalive"
        folder.mkdir(parents=True)
        with mock.patch.object(autopolicy, "recompute", side_effect=lambda d, p, now, basis: {
                "computed_at": now, "source": "history", "basis": basis}) as run:
            # Written by 0.5, which priced everything at list prices.
            (folder / "policy.json").write_text(json.dumps({"computed_at": NOW, "source": "history"}))
            self.assertEqual(autopolicy.current(self.data, {}, NOW + 60)["basis"], "subscription")
            (folder / "policy.json").write_text(json.dumps({"computed_at": NOW, "source": "history",
                                                            "basis": "subscription"}))
            self.assertEqual(autopolicy.current(self.data, {}, NOW + 60)["computed_at"], NOW)
            self.assertEqual(autopolicy.current(self.data, {"CACHEKEEPER_BASIS": "api"}, NOW + 60)["basis"], "api")
            self.assertEqual(run.call_count, 2)

    def test_stretches_stored_by_earlier_versions_still_count(self):
        path = self.data / "keepalive" / "gaps.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"at": NOW - DAY, "session": "a", "seconds": 5400, "context": 300_103,
                                    "read_price": 0.5, "rebuild_cost": 3.0}) + "\n")
        [stretch] = autopolicy.load_gaps(path)
        # 0.4-0.5 kept the cache-read price and the rewrite in list-price dollars: Opus 5, 300k tokens written.
        self.assertEqual((stretch.model, stretch.rebuild_tokens, stretch.returned), ("opus-5", 300_000, True))

    def test_the_time_since_a_last_message_is_stored_once_no_cap_reaches_past_it(self):
        path = self.data / "keepalive" / "gaps.jsonl"
        early = Gap(5 * 3600, 300_000, "claude-opus-5", 0, NOW - 5 * 3600, "t", returned=False)
        self.assertEqual(autopolicy.remember(path, [], [early]), [])     # the user may still come back
        self.assertFalse(path.exists())
        late = Gap(30 * 3600, 300_000, "claude-opus-5", 0, NOW - 5 * 3600, "t", returned=False)
        autopolicy.remember(path, [], [late])
        [kept] = autopolicy.load_gaps(path)
        self.assertEqual((kept.seconds, kept.returned), (30 * 3600, False))

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
        decision = autopolicy.recompute(self.data, self.projects, T0.timestamp() + 13 * DAY, "api")
        self.assertEqual((decision["source"], decision["cap_hours"], decision["basis"]), ("history", 1.0, "api"))
        self.assertEqual(autopolicy.read_decision(self.data), decision)
        # At list prices a ping re-reads 300k tokens: bridging a 22.5-hour night takes 24 of them, more than the
        # rewrite. On subscription usage re-reading counts for nothing, and the nights are worth bridging too.
        overnight = autopolicy.recompute(self.data, self.projects, T0.timestamp() + 13 * DAY, "subscription")
        self.assertEqual((overnight["cap_hours"], overnight["prevented"]), (24.0, 23))


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
        (folder / "policy.json").write_text(json.dumps({"computed_at": NOW, "basis": "subscription", **decision}))

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
