import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path

from cachekeeper.audit import Gap, analyze, basis_of, idle_gaps, ping_cost, rebuild_cost, run
from cachekeeper.pricing import SUBSCRIPTION_READ, choose, rates_for, setting
from cachekeeper.transcripts import read_sessions

T0 = dt.datetime(2026, 9, 20, 9, 0, tzinfo=dt.timezone.utc)
DAY_SECONDS = 86_400


def at(minutes: float) -> str:
    return (T0 + dt.timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def response(mid, minutes, model, read=0, write_1h=0, output=100, effort="max", block_lines=2):
    """One API response written as several transcript lines, the way Claude Code does."""
    usage = {"input_tokens": 3, "cache_read_input_tokens": read, "cache_creation_input_tokens": write_1h,
             "cache_creation": {"ephemeral_1h_input_tokens": write_1h, "ephemeral_5m_input_tokens": 0},
             "output_tokens": output}
    lines = []
    for index in range(block_lines):
        partial = dict(usage, output_tokens=output if index == block_lines - 1 else 1)
        lines.append({"type": "assistant", "timestamp": at(minutes + index * 0.1), "effort": effort,
                      "message": {"id": mid, "model": model, "usage": partial, "content": []}})
    return lines


def model_command(minutes, target):
    content = (f"<command-name>/model</command-name>\n<command-message>model</command-message>\n"
               f"<command-args>{target}</command-args>")
    return [{"type": "user", "timestamp": at(minutes), "message": {"role": "user", "content": content}}]


def compaction(minutes):
    return [{"type": "system", "subtype": "compact_boundary", "timestamp": at(minutes),
             "content": "Conversation compacted", "compactMetadata": {"trigger": "manual"}}]


def write(path: Path, entries, mtime):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    os.utime(path, (mtime, mtime))


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.projects = Path(self.directory.name)
        base = T0.timestamp()
        entries = (
            response("m1", 0, "claude-opus-5", write_1h=400_000)                       # session start
            + response("m2", 5, "claude-opus-5", read=400_000, write_1h=5_000)          # warm, normal turn
            + model_command(9, "claude-fable-5-1")
            + response("m3", 10, "claude-fable-5-1", write_1h=405_000)                 # manual switch, warm
            + response("m4", 100, "claude-fable-5-1", write_1h=410_000)                # 90 min idle: expired
            + response("m5", 105, "claude-fable-5-1", write_1h=411_000, effort="high")  # effort change
            + compaction(106)
            + response("m6", 107, "claude-fable-5-1", read=10_000, write_1h=60_000, effort="high")  # compaction
            + response("m7", 110, "claude-opus-5", write_1h=70_000, effort="high")     # automatic switch
        )
        write(self.projects / "project" / "session-a.jsonl", entries, base)
        # A resumed copy of the same history must not be counted twice.
        write(self.projects / "project" / "session-b.jsonl", response("m1", 0, "claude-opus-5", write_1h=400_000), base + 60)
        # Subagent transcripts are not the main conversation.
        write(self.projects / "project" / "session-a" / "subagents" / "agent.jsonl",
              response("s1", 1, "claude-haiku-4-5", write_1h=90_000), base + 120)

    def report(self, **options):
        sessions = read_sessions(self.projects, T0 - dt.timedelta(days=1))
        return sessions, analyze(sessions, 1, **options).to_json()

    def test_every_rebuild_is_attributed_to_its_cause(self):
        sessions, report = self.report()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(report["requests"], 7)
        counts = {cause: row["count"] for cause, row in report["rebuilds"].items() if row["count"]}
        self.assertEqual(counts, {
            "session start": 1, "model switch (manual)": 1, "idle expiry": 1,
            "effort change": 1, "compaction": 1, "model switch (automatic)": 1,
        })

    def test_the_guard_replay_asks_about_the_warm_manual_switch_only(self):
        _, report = self.report()
        guard = report["guard"]
        self.assertEqual((guard["net_manual_switches"], guard["would_ask"], guard["asked_and_rebuilt"]), (1, 1, 1))
        self.assertEqual(guard["automatic_switches"], 1)
        self.assertGreater(guard["at_stake_share"], 0)
        _, strict = self.report(min_usd=1000.0)
        self.assertEqual(strict["guard"]["would_ask"], 0)

    def test_the_keepalive_replay_prices_pings_against_the_rebuild_they_prevent(self):
        _, report = self.report()
        keep = report["keepalive"]
        self.assertEqual((keep["pings"], keep["prevented_rebuilds"]), (1, 1))
        self.assertGreater(keep["saved_share"], keep["cost_share"])
        _, capped = self.report(cap_hours=0.5)
        self.assertEqual(capped["keepalive"]["pings"], 0)

    def test_shares_add_up(self):
        _, report = self.report()
        self.assertAlmostEqual(sum(report["cost_share_by_class"].values()), 1.0)

    def test_run_reads_from_a_projects_directory(self):
        report = run(self.projects, 1, now=T0 + dt.timedelta(hours=3)).to_json()
        self.assertEqual(report["sessions"], 1)
        # On the one-hour cache, so on subscription usage unless told otherwise.
        self.assertEqual((report["basis"], report["one_hour_share"]), ("subscription", 1.0))
        self.assertEqual(run(self.projects, 1, now=T0 + dt.timedelta(hours=3), basis="api").to_json()["basis"], "api")

    def test_on_subscription_usage_cache_reads_count_next_to_nothing(self):
        sessions, listed = self.report()
        _, usage = self.report(basis="subscription")
        self.assertEqual(listed["basis"], "api")
        self.assertLess(usage["cost_share_by_class"]["cache read"], listed["cost_share_by_class"]["cache read"] / 20)
        self.assertEqual(basis_of(sessions, "auto"), "subscription")

    def test_pings_follow_a_last_message_until_the_cap(self):
        sessions, _ = self.report()
        [left] = [gap for gap in idle_gaps(sessions, T0.timestamp() + 5 * 3600) if not gap.returned]
        self.assertEqual((left.seconds, left.rebuild_tokens), (5 * 3600 - 110 * 60, 0))
        report = analyze(sessions, 1, now=T0.timestamp() + 5 * 3600).to_json()
        # One ping bridges the 90-minute break; three more follow the last message and prevent nothing.
        self.assertEqual((report["keepalive"]["pings"], report["keepalive"]["prevented_rebuilds"]), (4, 1))


class TranscriptTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.projects = Path(self.directory.name)

    def sessions(self):
        return read_sessions(self.projects, T0 - dt.timedelta(days=1))

    def test_a_message_about_pings_is_not_a_ping(self):
        def user(minutes, text, **fields):
            return [{"type": "user", "timestamp": at(minutes), "message": {"role": "user", "content": text}, **fields}]
        ping = ("<task-notification><summary>cachekeeper keep-alive ping</summary></task-notification>\n"
                "cachekeeper: keep-alive ping 1 of 3, not an error: reply with exactly (keep-alive)")
        entries = (response("m1", 0, "claude-opus-5", write_1h=300_000)
                   + user(1, "This session is being continued from a previous conversation. The keep-alive ping "
                             "replied (keep-alive).", isCompactSummary=True)
                   + response("m2", 2, "claude-opus-5", read=300_000, write_1h=100)
                   + user(3, "why did a keep-alive ping run at 3 am?", origin={"kind": "human"})
                   + response("m3", 4, "claude-opus-5", read=300_100, write_1h=100)
                   + user(60, ping, origin={"kind": "task-notification"})
                   + response("m4", 60.1, "claude-opus-5", read=300_200, write_1h=300))
        write(self.projects / "p" / "s.jsonl", entries, T0.timestamp())
        self.assertEqual([request.ping for request in self.sessions()[0].requests], [False, False, False, True])

    def test_claude_p_runs_are_not_waited_in(self):
        lines = response("h1", 0, "claude-opus-5", write_1h=300_000) + response("h2", 120, "claude-opus-5",
                                                                                write_1h=300_000)
        write(self.projects / "p" / "h.jsonl", [dict(line, entrypoint="sdk-cli") for line in lines], T0.timestamp())
        [session] = self.sessions()
        self.assertEqual(session.entrypoint, "sdk-cli")
        self.assertEqual(idle_gaps([session], T0.timestamp() + DAY_SECONDS), [])


class YardstickTests(unittest.TestCase):
    def test_subscription_usage_counts_reads_as_nothing_and_writes_at_the_input_price(self):
        usage = rates_for("claude-opus-5-5", "subscription")
        self.assertEqual((usage.write_5m, usage.write_1h, usage.input, usage.output), (4.0, 4.0, 4.0, 20.0))
        self.assertAlmostEqual(usage.cache_read, 4.0 * 0.0018)     # about a 28th of the list-price read
        listed = rates_for("claude-opus-5-5", "api")
        self.assertEqual((listed.cache_read, listed.write_5m, listed.write_1h), (0.20, 5.0, 8.0))

    def test_the_yardstick_follows_the_cache_unless_it_is_set(self):
        self.assertEqual((choose(setting({}), True), choose(setting({}), False)), ("subscription", "api"))
        self.assertEqual(choose(setting({"CACHEKEEPER_BASIS": " API "}), True), "api")
        self.assertEqual(setting({"CACHEKEEPER_BASIS": "bogus"}), "auto")

    def test_a_ping_on_subscription_usage_costs_mostly_its_own_messages(self):
        stretch = Gap(2 * 3600, 400_000, "claude-opus-5-5", 400_000)
        self.assertAlmostEqual(ping_cost(stretch, "subscription"),                                      # $0.008
                               (400_000 * 4 * SUBSCRIPTION_READ + 500 * 4 + 150 * 20) / 1e6)
        self.assertAlmostEqual(ping_cost(stretch, "api"), (400_000 * 0.2 + 500 * 8 + 150 * 20) / 1e6)  # $0.087
        self.assertAlmostEqual(rebuild_cost(stretch, "subscription"), 1.6)
        self.assertAlmostEqual(rebuild_cost(stretch, "api"), 3.2)


if __name__ == "__main__":
    unittest.main()
