import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cachekeeper import cli, keepalive
from cachekeeper.statusline import line
from test_keepalive import ON, at, lines, prompt, turn

ANCHOR = at(7.1)            # turn()'s last request started 7.1 s in; the cache expires an hour after it
NOW = ANCHOR + 20 * 60


def warm(ttl="1h", size=152_302):
    return {"warm": True, "caching_observed": True, "ttl": ttl, "expires_at": ANCHOR + (3600 if ttl == "1h" else 300),
            "recache_tokens_if_cold": size}


class StatusLineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.transcript = self.directory / "s1.jsonl"
        self.transcript.write_text("\n".join(lines(turn())) + "\n", encoding="utf-8")
        self.event = {"session_id": "s1", "transcript_path": str(self.transcript), "prompt_cache": warm()}

    def line(self, env=ON, lang="en", now=NOW, **changes):
        return line({**self.event, **changes}, dict(env), self.directory, lang, now)

    def pinged(self, *seconds):
        keepalive.write_state(keepalive.state_path(self.directory, "s1"), {"generation": None, "pings": list(seconds)})

    def test_time_left_and_the_next_ping(self):
        self.assertEqual(self.line(), "cache 152k · 40m left · next ping in 35m (1/3)")
        self.assertEqual(self.line(lang="ko"), "캐시 152k · 40분 남음 · 다음 핑 35분 후 (1/3)")
        self.assertEqual(self.line(now=ANCHOR + 55 * 60 + 10), "cache 152k · 4m left · ping due (1/3)")

    def test_counts_the_pings_since_the_user_last_wrote(self):
        self.pinged(at(-600), ANCHOR)       # one before the user's message, one after it
        self.assertEqual(self.line(), "cache 152k · 40m left · next ping in 35m (2/3)")
        self.pinged(ANCHOR - 2, ANCHOR - 1, ANCHOR)
        self.assertEqual(self.line(), "cache 152k · 40m left · ping cap (3/3)")

    def test_says_why_no_ping_comes(self):
        self.assertEqual(self.line({**ON, "CACHEKEEPER_KEEPALIVE_MIN_TOKENS": "200000"}),
                         "cache 152k · 40m left · no ping (under 200k)")
        self.assertEqual(self.line({"CACHEKEEPER_KEEPALIVE": "0"}, "ko"), "캐시 152k · 40분 남음 · keep-alive 꺼짐")
        self.assertEqual(self.line(prompt_cache=warm("5m"), now=ANCHOR + 250), "cache 152k · <1m left (5-min cache)")

    def test_auto_mode_reads_the_stored_policy_and_never_replays_history(self):
        with mock.patch("cachekeeper.autopolicy.current", side_effect=AssertionError("recomputed")):
            self.assertEqual(self.line({}), "cache 152k · 40m left · next ping in 35m (1/3)")    # the defaults
            policy = self.directory / "keepalive" / "policy.json"
            policy.parent.mkdir(exist_ok=True)
            policy.write_text(json.dumps({"source": "history", "min_context": 100_000, "cap_hours": 24.0}))
            self.assertEqual(self.line({}), "cache 152k · 40m left · next ping in 35m (1/26)")
            policy.write_text(json.dumps({"source": "off"}))
            self.assertEqual(self.line({}), "cache 152k · 40m left · keep-alive off")

    def test_a_cold_cache_and_a_session_without_one(self):
        cold = {"warm": False, "caching_observed": True, "ttl": "1h", "expires_at": None, "recache_tokens_if_cold": 1_234_567}
        self.assertEqual(self.line(prompt_cache=cold), "cache cold · next request rewrites 1.2M")
        self.assertEqual(self.line(lang="ko", now=ANCHOR + 3601), "캐시 식음 · 다음 요청에 152k 다시 씀")
        self.assertEqual(self.line(prompt_cache=None), "")
        self.assertEqual(self.line(prompt_cache={"caching_observed": False}), "")

    def test_the_user_writing_now_plans_from_their_message(self):
        entries = turn() + [prompt("u2", 30 * 60)]
        self.transcript.write_text("\n".join(lines(entries)) + "\n", encoding="utf-8")
        self.pinged(ANCHOR)
        self.assertEqual(self.line(now=at(31 * 60)), "cache 152k · 29m left · next ping in 54m (1/3)")

    def test_the_command_never_fails_the_status_bar(self):
        for stdin in (b"not json", b"[]", b""):
            out, err = io.StringIO(), io.StringIO()
            with mock.patch("sys.stdin", io.TextIOWrapper(io.BytesIO(stdin))), mock.patch("sys.stdout", out), \
                    mock.patch("sys.stderr", err):
                self.assertEqual(cli.main(["statusline"]), 0)
            self.assertEqual(out.getvalue().strip(), "")


if __name__ == "__main__":
    unittest.main()
