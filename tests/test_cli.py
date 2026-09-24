import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from cachekeeper import cli
from cachekeeper.audit import analyze
from cachekeeper.transcripts import read_sessions
from test_audit import T0, response, write

DAY = 86_400
NOW = T0 + dt.timedelta(days=13)


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.projects = self.root / "projects"
        entries = []
        for day in range(12):   # a 90-minute lunch every day, and the rewrite it cost
            base = day * 24 * 60
            entries += response(f"a{day}", base, "claude-opus-5", write_1h=300_000)
            entries += response(f"b{day}", base + 90, "claude-opus-5", read=100, write_1h=300_500)
        write(self.projects / "p" / "s.jsonl", entries, T0.timestamp() + 12 * DAY)

    def test_the_audit_says_which_yardstick_it_used(self):
        sessions = read_sessions(self.projects, T0 - dt.timedelta(days=1))
        for basis, note in (("subscription", "cache reads count 0.18% of the input price"), ("api", "weighted at list prices")):
            report = analyze(sessions, 30, basis=basis, now=T0.timestamp() + 13 * DAY).to_json()
            text = cli.render(report, "en", 1.0, 8.0, auto=True)
            self.assertIn(note, text)
            self.assertIn("100% of requests ran on the one-hour cache", text)
            self.assertIn("구독 사용량" if basis == "subscription" else "API 정가", cli.render(report, "ko", 1.0, 8.0))

    def test_the_keepalive_report_counts_sessions_never_returned_to(self):
        text = cli.keepalive_report(self.projects, 30, "en", None, "subscription", NOW)
        # 12 lunches and 11 nights; after the last message the session sat for a day and a half.
        self.assertIn("23 idle stretches of 55 min or more, and 1 session left idle", text)
        self.assertIn("on subscription usage", text)
        self.assertIn("up to 24 h", text)
        self.assertIn("only run while the computer is awake", text)
        self.assertIn("up to 1 h", cli.keepalive_report(self.projects, 30, "en", None, "api", NOW))
        korean = cli.keepalive_report(self.projects, 30, "ko", None, "subscription", NOW)
        self.assertIn("핑은 컴퓨터가 깨어 있고", korean)

    def test_the_keepalive_report_flags_a_policy_on_another_yardstick(self):
        folder = self.root / "data" / "keepalive"
        folder.mkdir(parents=True)
        (folder / "policy.json").write_text(json.dumps({"computed_at": T0.timestamp(), "source": "history",
                                                        "why": "net $1.00", "min_context": 100_000, "cap_hours": 3.0}))
        text = cli.keepalive_report(self.projects, 30, "en", self.root / "data", "subscription", NOW)
        self.assertIn("at list prices", text)
        self.assertIn("computed on another yardstick", text)

    def test_the_events_summary_keeps_the_yardsticks_apart(self):
        folder = self.root / "data"
        folder.mkdir()
        records = [{"event": "pre", "decision": "ask", "estimated_cache_write_usd": 9.0},     # before 0.6
                   {"event": "pre", "decision": "ask", "estimated_cache_write_usd": 4.5, "basis": "subscription"}]
        (folder / "events.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
        text = cli.events_summary(folder, 5)
        self.assertIn("$9.00 at list prices, $4.50 on subscription usage", text)


if __name__ == "__main__":
    unittest.main()
