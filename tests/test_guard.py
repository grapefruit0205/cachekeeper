import json
import tempfile
import unittest
from pathlib import Path

from cachekeeper.guard import Config, at_stake, decide, language
from cachekeeper.hook import handle

EVENT = {
    "session_id": "s1",
    "hook_event_name": "PreModelSwitch",
    "from_model": "claude-opus-5",
    "to_model": "claude-fable-5-1",
    "requested_model": "fable",
    "source": "picker",
    "context_tokens": 450_000,
    "prompt_cache_warm": True,
    "cache_ttl": "1h",
    "estimated_cache_write_usd": 9.0,
    "pricing": "catalog",
}


class DecideTests(unittest.TestCase):
    def test_warm_and_costly_asks_with_the_loss_and_the_alternative(self):
        output, pending = decide(EVENT, {}, 1000.0, Config())
        specific = output["hookSpecificOutput"]
        self.assertEqual(specific["permissionDecision"], "ask")
        self.assertIn("450k tokens", specific["permissionDecisionReason"])
        # On the one-hour cache the cost is counted as subscription usage: a write at the input price.
        self.assertIn("$4.50 of subscription usage", specific["permissionDecisionReason"])
        self.assertIn("fable-5-1 subagent", specific["permissionDecisionReason"])
        # The confirmation is a typed command with the resolved id: an alias can resolve to another
        # version, and a second pick in the desktop app's picker does not always reach Claude Code.
        self.assertIn("type `/model claude-fable-5-1` within 120s", specific["permissionDecisionReason"])
        self.assertIn("If a model picker still shows fable-5-1, this session is still on opus-5.",
                      specific["permissionDecisionReason"])
        self.assertEqual(pending, {"s1": {"to_model": "claude-fable-5-1", "at": 1000.0}})

    def test_list_prices_on_request_or_on_the_five_minute_cache(self):
        listed, _ = decide(EVENT, {}, 1000.0, Config(basis="api"))
        self.assertIn("$9.00 at list price", listed["hookSpecificOutput"]["permissionDecisionReason"])
        short = {**EVENT, "cache_ttl": "5m", "estimated_cache_write_usd": 5.625}
        output, _ = decide(short, {}, 1000.0, Config())
        self.assertIn("$5.62", output["hookSpecificOutput"]["permissionDecisionReason"])
        korean, _ = decide(EVENT, {}, 1000.0, Config(lang="ko"))
        self.assertIn("구독 사용량 기준", korean["hookSpecificOutput"]["permissionDecisionReason"])

    def test_the_same_switch_again_inside_the_window_is_the_confirmation(self):
        _, pending = decide(EVENT, {}, 1000.0, Config())
        output, pending = decide(EVENT, pending, 1060.0, Config())
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "allow")
        self.assertEqual(pending, {})

    def test_a_repeat_after_the_window_asks_again(self):
        _, pending = decide(EVENT, {}, 1000.0, Config(confirm_seconds=120))
        output, _ = decide(EVENT, pending, 1200.0, Config(confirm_seconds=120))
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "ask")

    def test_a_different_target_is_a_new_question(self):
        _, pending = decide(EVENT, {}, 1000.0, Config())
        other = {**EVENT, "to_model": "claude-opus-5-5", "requested_model": "opus"}
        output, pending = decide(other, pending, 1010.0, Config())
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "ask")
        self.assertEqual(pending["s1"]["to_model"], "claude-opus-5-5")

    def test_nothing_to_lose_stays_silent(self):
        for event in ({**EVENT, "prompt_cache_warm": False}, {**EVENT, "estimated_cache_write_usd": 0.4}):
            with self.subTest(event=event):
                output, _ = decide(event, {}, 1000.0, Config())
                self.assertIsNone(output)

    def test_unknown_price_falls_back_to_the_token_threshold(self):
        event = {**EVENT, "to_model": "some-other-model", "estimated_cache_write_usd": None}
        self.assertIsNone(decide({**event, "context_tokens": 50_000}, {}, 0.0, Config())[0])
        output, _ = decide(event, {}, 0.0, Config())
        self.assertIn("cost unknown", output["hookSpecificOutput"]["permissionDecisionReason"])

    def test_missing_estimate_uses_list_price_of_the_new_model(self):
        warm, tokens, usd = at_stake({**EVENT, "estimated_cache_write_usd": None})
        self.assertTrue(warm)
        self.assertEqual(tokens, 450_000)
        self.assertAlmostEqual(usd, 450_000 * 20.0 / 1_000_000)  # Fable 5.1 one-hour write: 2 x $10
        self.assertAlmostEqual(at_stake({**EVENT, "estimated_cache_write_usd": None}, "subscription")[2],
                               450_000 * 10.0 / 1_000_000)
        self.assertAlmostEqual(at_stake(EVENT, "subscription")[2], 4.5)

    def test_warn_mode_never_blocks_and_off_mode_is_silent(self):
        output, pending = decide(EVENT, {}, 0.0, Config(mode="warn"))
        self.assertIn("systemMessage", output)
        self.assertNotIn("hookSpecificOutput", output)
        self.assertEqual(pending, {})
        self.assertIsNone(decide(EVENT, {}, 0.0, Config(mode="off"))[0])

    def test_korean_message(self):
        output, _ = decide(EVENT, {}, 0.0, Config(lang="ko"))
        reason = output["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("서브에이전트", reason)
        self.assertIn("120초 안에 `/model claude-fable-5-1`를 입력하세요. 모델 선택기에 fable-5-1 표시가 남아 있어도 "
                      "세션은 opus-5 그대로입니다.", reason)

    def test_config_from_env(self):
        config = Config.from_env({"CACHEKEEPER_MODE": "WARN", "CACHEKEEPER_MIN_USD": "2.5", "LANG": "ko_KR.UTF-8"})
        self.assertEqual((config.mode, config.min_usd, config.lang, config.basis), ("warn", 2.5, "ko", "auto"))
        self.assertEqual(Config.from_env({"CACHEKEEPER_BASIS": "api"}).basis, "api")
        self.assertEqual(Config.from_env({"CACHEKEEPER_MODE": "bogus"}).mode, "ask")
        self.assertEqual(language({"CACHEKEEPER_LANG": "en", "LANG": "ko_KR.UTF-8"}), "en")


class HookTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env = {"CLAUDE_PLUGIN_DATA": self.directory.name, "LANG": "en_US.UTF-8"}

    def events(self):
        path = Path(self.directory.name) / "events.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]

    def test_ask_then_repeat_then_switch_is_logged_without_prompt_text(self):
        first = json.loads(handle("pre-model-switch", json.dumps(EVENT), self.env, now=100.0))
        self.assertEqual(first["hookSpecificOutput"]["permissionDecision"], "ask")
        second = json.loads(handle("pre-model-switch", json.dumps(EVENT), self.env, now=130.0))
        self.assertEqual(second["hookSpecificOutput"]["permissionDecision"], "allow")
        self.assertEqual(handle("post-model-switch", json.dumps({**EVENT, "source": "picker"}), self.env, now=131.0), "")
        records = self.events()
        self.assertEqual([r["decision"] for r in records], ["ask", "allow", "switched"])
        self.assertEqual(set(records[0]) - {"at"}, {
            "event", "session_id", "source", "from_model", "to_model", "context_tokens",
            "prompt_cache_warm", "cache_ttl", "estimated_cache_write_usd", "basis", "pricing", "decision"})
        self.assertEqual((records[0]["basis"], records[0]["estimated_cache_write_usd"]), ("subscription", 4.5))

    def test_a_resume_restoring_the_model_keeps_the_pending_ask(self):
        # Found live: `claude -p --resume` fires PostModelSwitch(source=resume) before the repeat.
        handle("pre-model-switch", json.dumps(EVENT), self.env, now=100.0)
        restore = {**EVENT, "source": "resume", "from_model": "claude-opus-5-5", "to_model": "claude-opus-5"}
        handle("post-model-switch", json.dumps(restore), self.env, now=110.0)
        again = json.loads(handle("pre-model-switch", json.dumps(EVENT), self.env, now=120.0))
        self.assertEqual(again["hookSpecificOutput"]["permissionDecision"], "allow")

    def test_a_confirmed_dialog_clears_the_pending_ask(self):
        handle("pre-model-switch", json.dumps(EVENT), self.env, now=100.0)
        handle("post-model-switch", json.dumps(EVENT), self.env, now=105.0)
        again = json.loads(handle("pre-model-switch", json.dumps(EVENT), self.env, now=110.0))
        self.assertEqual(again["hookSpecificOutput"]["permissionDecision"], "ask")

    def test_bad_input_prints_nothing(self):
        self.assertEqual(handle("pre-model-switch", "[]", self.env), "")
        self.assertEqual(handle("unknown-event", json.dumps(EVENT), self.env), "")


class OfferTests(unittest.TestCase):
    """A refused switch offers to run the next request in a subagent on that model."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env = {"CLAUDE_PLUGIN_DATA": self.directory.name, "LANG": "ko_KR.UTF-8"}

    def prompt(self, text, now, session="s1"):
        output = handle("user-prompt-submit", json.dumps({"session_id": session, "prompt": text}), self.env, now=now)
        return json.loads(output) if output else None

    def decisions(self):
        path = Path(self.directory.name) / "events.jsonl"
        return [r["decision"] for r in map(json.loads, path.read_text().splitlines()) if r["event"] == "prompt"]

    def test_the_refusal_offers_a_subagent_and_the_next_request_asks_first(self):
        self.env["CLAUDE_CODE_ENTRYPOINT"] = "claude-desktop"
        asked = json.loads(handle("pre-model-switch", json.dumps(EVENT), self.env, now=100.0))
        reason = asked["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("이 작업만 fable-5-1로 하려면 하려던 요청을 그대로 보내세요", reason)
        self.assertIn("서브에이전트에 맡길지 먼저 묻고, 끝나면 지금 모델(opus-5)로 이어집니다", reason)
        offered = self.prompt("이 버그 원인을 찾아줘", 160.0)
        context = offered["hookSpecificOutput"]["additionalContext"]
        # The main model asks first, in the user's language; the answer picks a subagent or the session's model.
        self.assertIn("Before working on it, ask the user with the AskUserQuestion tool", context)
        self.assertIn('the question "이 요청을 fable-5-1 서브에이전트로 실행할까요?"', context)
        self.assertIn('options "fable-5-1 서브에이전트"', context)
        self.assertIn('"opus-5로 계속"', context)
        self.assertIn('(Agent, or Task in some Claude Code versions) with model "claude-fable-5-1" '
                      '(if that model id is not accepted, "fable")', context)
        self.assertIn("self-contained brief", context)
        # When the subagent returns, the conversation carries on here, on the session's own model.
        self.assertIn("continue here on opus-5, saying in one line that fable-5-1 did this in a subagent and "
                      "this session is still on opus-5", context)
        self.assertIn("If they choose opus-5, handle the message yourself", context)
        self.assertIn("fable-5-1 서브에이전트에 맡길지 먼저 묻습니다", offered["systemMessage"])
        self.assertIsNone(self.prompt("다음 질문", 170.0))  # one request only
        self.assertEqual(self.decisions(), ["ask"])

    def test_without_anyone_to_answer_the_request_goes_to_the_subagent_at_once(self):
        # `claude -p` runs as sdk-cli, SDK apps as sdk-py or sdk-ts: no question can be answered there.
        for entrypoint in ("sdk-cli", "sdk-py"):
            with self.subTest(entrypoint=entrypoint):
                self.env["CLAUDE_CODE_ENTRYPOINT"] = entrypoint
                handle("pre-model-switch", json.dumps({**EVENT, "session_id": entrypoint}), self.env, now=100.0)
                delegated = self.prompt("이 버그 원인을 찾아줘", 130.0, session=entrypoint)
                context = delegated["hookSpecificOutput"]["additionalContext"]
                self.assertIn('Delegate it now: call the subagent tool', context)
                self.assertNotIn("AskUserQuestion", context)
                self.assertIn("fable-5-1 서브에이전트에게 맡깁니다", delegated["systemMessage"])
        self.assertEqual(self.decisions(), ["delegate", "delegate"])

    def test_from_fable_the_subagent_runs_on_the_exact_opus_asked_for(self):
        # `opus` would resolve to Opus 5.5 here; the user asked for Opus 5.
        back = {**EVENT, "from_model": "claude-fable-5-1", "to_model": "claude-opus-5", "requested_model": "claude-opus-5",
                "estimated_cache_write_usd": 4.5}
        asked = json.loads(handle("pre-model-switch", json.dumps(back), self.env, now=100.0))
        self.assertIn("이 작업만 opus-5로 하려면", asked["hookSpecificOutput"]["permissionDecisionReason"])
        context = self.prompt("이 설계를 검토해줘", 130.0)["hookSpecificOutput"]["additionalContext"]
        self.assertIn('with model "claude-opus-5" (if that model id is not accepted, "opus")', context)
        self.assertIn("continue here on fable-5-1", context)

    def test_a_slash_command_keeps_the_offer_for_the_next_message(self):
        handle("pre-model-switch", json.dumps(EVENT), self.env, now=100.0)
        self.assertIsNone(self.prompt("/cost", 110.0))
        self.assertIsNotNone(self.prompt("이제 해줘", 120.0))

    def test_confirming_the_switch_withdraws_the_offer(self):
        handle("pre-model-switch", json.dumps(EVENT), self.env, now=100.0)
        handle("pre-model-switch", json.dumps(EVENT), self.env, now=110.0)   # repeat: allow
        handle("post-model-switch", json.dumps(EVENT), self.env, now=111.0)
        self.assertIsNone(self.prompt("이 버그 원인을 찾아줘", 120.0))

    def test_an_old_offer_is_dropped(self):
        handle("pre-model-switch", json.dumps(EVENT), self.env, now=100.0)
        self.assertIsNone(self.prompt("이 버그 원인을 찾아줘", 100.0 + 901))

    def test_no_offer_for_a_model_a_subagent_cannot_run(self):
        other = {**EVENT, "to_model": "deepseek-v4.1-flash", "requested_model": "deepseek-v4.1-flash"}
        asked = json.loads(handle("pre-model-switch", json.dumps(other), self.env, now=100.0))
        self.assertNotIn("서브에이전트", asked["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIsNone(self.prompt("이 버그 원인을 찾아줘", 110.0))


if __name__ == "__main__":
    unittest.main()
