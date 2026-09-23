import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path

from cachekeeper.audit import analyze, run
from cachekeeper.transcripts import read_sessions

T0 = dt.datetime(2026, 9, 20, 9, 0, tzinfo=dt.timezone.utc)


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


if __name__ == "__main__":
    unittest.main()
