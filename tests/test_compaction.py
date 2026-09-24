from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from cachekeeper import compaction
from cachekeeper.pricing import SUBSCRIPTION_READ, price_for
from cachekeeper.transcripts import read_sessions
from test_audit import T0, at, response, write

OPUS = price_for("claude-opus-5")


def turns(contexts, start=0):
    """One request per context size, each re-reading the one before and adding the difference."""
    entries, previous = [], 0
    for index, size in enumerate(contexts):
        added = size - previous if size >= previous else size
        entries += response(f"m{start + index}", start + index * 5, "claude-opus-5",
                            read=size - added, write_1h=added)
        previous = size
    return entries


def compact_boundary(minutes, uuid):
    return [{"type": "system", "subtype": "compact_boundary", "uuid": uuid, "timestamp": at(minutes),
             "compactMetadata": {"trigger": "auto"}}]


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.projects = Path(self.temporary.name)

    def sessions(self, entries, name="s"):
        write(self.projects / "p" / f"{name}.jsonl", entries, T0.timestamp())
        return read_sessions(self.projects, T0 - dt.timedelta(days=1))

    def test_a_window_the_session_never_reaches_changes_nothing(self):
        outcome = compaction.replay(self.sessions(turns([100_000, 300_000, 500_000, 700_000])), 1_000_000, 70_000)
        self.assertEqual((outcome.compactions, outcome.net), (0, 0.0))

    def test_a_smaller_window_compacts_and_rereads_less(self):
        sessions = self.sessions(turns([100_000, 300_000, 500_000, 700_000]))
        outcome = compaction.replay(sessions, 400_000, 70_000, reread=20_000)
        # 500k would pass 400k: compact at 300k and go on from 90k + the 200k this turn adds; the same at 700k.
        self.assertEqual(outcome.compactions, 2)
        self.assertAlmostEqual(outcome.read_saved, ((300_000 - 90_000) + (500_000 - 90_000)) * OPUS.cache_read / 1e6,
                               places=4)
        one = lambda read: (read * OPUS.cache_read + compaction.SUMMARY_TOKENS * OPUS.output
                            + 90_000 * OPUS.write_1h) / 1e6
        self.assertAlmostEqual(outcome.compaction_cost, one(300_000) + one(290_000), places=4)

    def test_on_subscription_usage_only_rebuilds_and_the_compaction_itself_count(self):
        sessions = self.sessions(turns([100_000, 300_000, 500_000, 700_000]))
        # The system prompt and tools stay cached: of the 70k after a compaction, 40k are written.
        outcome = compaction.replay(sessions, 400_000, 70_000, reread=20_000, basis="subscription", written=40_000)
        listed = compaction.replay(sessions, 400_000, 70_000, reread=20_000, written=40_000)
        self.assertEqual(outcome.compactions, 2)
        read = OPUS.input * SUBSCRIPTION_READ       # next to nothing: the reads saved are a 55th of the listed ones
        self.assertAlmostEqual(outcome.read_saved, listed.read_saved * read / OPUS.cache_read, places=6)
        one = lambda context: (context * read + compaction.SUMMARY_TOKENS * OPUS.output + 60_000 * OPUS.input) / 1e6
        self.assertAlmostEqual(outcome.compaction_cost, one(300_000) + one(290_000), places=6)

    def test_a_real_compaction_is_followed_not_counted(self):
        entries = turns([300_000, 900_000]) + compact_boundary(12, "c1") + turns([80_000, 150_000], start=20)
        outcome = compaction.replay(self.sessions(entries), 1_000_000, 70_000)
        self.assertEqual((outcome.compactions, outcome.net), (0, 0.0))

    def test_a_rebuild_after_a_break_rewrites_the_smaller_context(self):
        entries = turns([100_000, 300_000, 500_000]) + response("late", 200, "claude-opus-5", write_1h=520_000)
        outcome = compaction.replay(self.sessions(entries), 400_000, 70_000, reread=20_000)
        # After the compaction the conversation is 290k; the 520k rebuild would have written 310k.
        rebuilt = 520_000 * OPUS.write_1h / 1e6
        self.assertAlmostEqual(outcome.rebuild_saved, rebuilt * (520_000 - 310_000) / 520_003, places=4)

    def test_the_size_after_a_compaction_is_measured_once_per_boundary(self):
        body = turns([900_000]) + compact_boundary(6, "c1") + turns([64_000], start=10)
        write(self.projects / "p" / "a.jsonl", body, T0.timestamp())
        write(self.projects / "p" / "b.jsonl", body, T0.timestamp() + 60)     # a resumed copy
        paths = sorted((self.projects / "p").glob("*.jsonl"))
        self.assertEqual(compaction.measured_after(paths), 64_003)

    def test_what_the_first_request_after_a_compaction_writes_is_measured(self):
        body = (turns([900_000]) + compact_boundary(6, "c1")
                + response("m10", 10, "claude-opus-5", read=20_000, write_1h=44_000))
        write(self.projects / "p" / "a.jsonl", body, T0.timestamp())
        self.assertEqual(compaction.measured_restart([self.projects / "p" / "a.jsonl"]), (64_003, 44_003))

    def test_a_long_stretch_at_a_large_context_pays_for_the_compaction(self):
        grow = [100_000, 200_000, 300_000, 400_000] + [400_000 + 2_000 * step for step in range(1, 41)]
        text = compaction.report(self.sessions(turns(grow)), [], "en", total=100.0, days=1.0)
        self.assertIn("Best window that holds up under the cautious assumption", text)
        self.assertIn("default", text)          # no real compaction to measure: 70k assumed

    def test_the_report_names_its_yardstick(self):
        grow = [100_000, 200_000, 300_000, 400_000] + [400_000 + 2_000 * step for step in range(1, 41)]
        text = compaction.report(self.sessions(turns(grow)), [], "en", 100.0, 1.0, "subscription")
        self.assertIn("on subscription usage", text)
        self.assertIn("구독 사용량", compaction.report(self.sessions(turns(grow)), [], "ko", 100.0, 1.0, "subscription"))

    def test_a_session_too_short_to_repay_a_compaction_says_so(self):
        sessions = self.sessions(turns([100_000 * step for step in range(1, 10)]))
        text = compaction.report(sessions, [], "en", total=100.0, days=1.0)
        self.assertIn("At every window the compactions would have cost more than they saved.", text)


if __name__ == "__main__":
    unittest.main()
