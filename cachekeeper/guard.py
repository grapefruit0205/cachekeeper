"""The model-switch guard: decide what to answer a PreModelSwitch hook.

Claude Code hands the hook everything the decision needs: whether the current
model's cache is still warm (``prompt_cache_warm``), how many tokens the next
request re-sends (``context_tokens``) and what re-caching them on the new model
costs at list price (``estimated_cache_write_usd``). The guard adds three things
Claude Code does not: the size of the loss in the question itself, with the
alternative that keeps the cache (a subagent on the other model); the loss on
the yardstick that counts for this session — subscription usage, where a write
counts at the input price, when the cache lives an hour (see ``pricing``); and a
way to confirm in a session that cannot show a confirmation dialog — asking for
the same switch again within ``confirm_seconds``.

``decide`` is pure: it takes the hook input, the pending confirmations and the
clock, and returns the hook output plus the new pending state.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .pricing import alias_for, choose, price_for, setting

MODES = ("ask", "warn", "off")


@dataclass(frozen=True)
class Config:
    mode: str = "ask"
    min_usd: float = 1.0
    min_tokens: int = 100_000
    confirm_seconds: int = 120
    offer_seconds: int = 900
    lang: str = "en"
    basis: str = "auto"

    @staticmethod
    def from_env(env: dict[str, str] | None = None) -> "Config":
        env = dict(os.environ if env is None else env)
        mode = env.get("CACHEKEEPER_MODE", "ask").strip().lower()
        return Config(
            mode=mode if mode in MODES else "ask",
            min_usd=_number(env.get("CACHEKEEPER_MIN_USD"), 1.0),
            min_tokens=int(_number(env.get("CACHEKEEPER_MIN_TOKENS"), 100_000)),
            confirm_seconds=int(_number(env.get("CACHEKEEPER_CONFIRM_SECONDS"), 120)),
            offer_seconds=int(_number(env.get("CACHEKEEPER_OFFER_SECONDS"), 900)),
            lang=language(env),
            basis=setting(env),
        )


def _number(value: str | None, default: float) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except ValueError:
        return default


def language(env: dict[str, str]) -> str:
    explicit = env.get("CACHEKEEPER_LANG", "").strip().lower()
    if explicit in ("ko", "en"):
        return explicit
    for key in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = env.get(key, "")
        if value:
            return "ko" if value.lower().startswith("ko") else "en"
    return "en"


def basis_for(event: dict, config: Config) -> str:
    """The configured yardstick, else subscription usage when the cache lives an hour."""
    return choose(config.basis, event.get("cache_ttl") == "1h")


def at_stake(event: dict, basis: str = "api") -> tuple[bool, int, float | None]:
    """Is a warm cache about to be forfeited, and how big is it?

    Returns (warm, context_tokens, usd). On list prices ``usd`` is Claude Code's own estimate when present,
    else the list price of a 1-hour (or 5-minute) write on the new model. On subscription usage a write counts
    at the input price: Claude Code's estimate without the write premium (2x for 1 hour, 1.25x for 5 minutes).
    """
    warm = event.get("prompt_cache_warm") is True
    tokens = int(event.get("context_tokens") or 0)
    one_hour = event.get("cache_ttl") == "1h"
    usd = event.get("estimated_cache_write_usd")
    if not isinstance(usd, (int, float)) or isinstance(usd, bool):
        price = price_for(event.get("to_model"))
        if price is None:
            usd = None
        else:
            rate = price.write_1h if one_hour else price.write_5m
            usd = tokens * rate / 1_000_000
    if usd is not None and basis == "subscription":
        usd = usd / (2.0 if one_hour else 1.25)
    return warm, tokens, (float(usd) if usd is not None else None)


def decide(event: dict, pending: dict, now: float, config: Config) -> tuple[dict | None, dict]:
    """Answer one PreModelSwitch event.

    ``pending`` maps session ids to ``{"to_model": ..., "at": epoch}`` for the
    switches the guard asked about. Returns (hook output or None to stay silent,
    updated pending).
    """
    pending = {
        sid: entry for sid, entry in pending.items()
        if isinstance(entry, dict) and now - float(entry.get("at", 0)) <= config.confirm_seconds
    }
    if config.mode == "off":
        return None, pending
    basis = basis_for(event, config)
    warm, tokens, usd = at_stake(event, basis)
    big = (usd is not None and usd >= config.min_usd) or (usd is None and tokens >= config.min_tokens)
    if not warm or not big:
        return None, pending

    session = str(event.get("session_id", ""))
    to_model = str(event.get("to_model", ""))
    reason = message(event, tokens, usd, config, basis)
    if config.mode == "warn":
        return {"systemMessage": reason}, pending

    previous = pending.get(session)
    if previous and previous.get("to_model") == to_model:
        # The same switch asked for again inside the window: that is the confirmation.
        pending.pop(session, None)
        return {"hookSpecificOutput": {"hookEventName": "PreModelSwitch", "permissionDecision": "allow"}}, pending
    pending[session] = {"to_model": to_model, "at": now}
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreModelSwitch",
            "permissionDecision": "ask",
            "permissionDecisionReason": reason,
        }
    }, pending


# Aliases the Agent tool accepts as a subagent's model.
SUBAGENT_ALIASES = ("fable", "opus", "sonnet", "haiku")


def offer_for(event: dict) -> dict | None:
    """The run-it-in-a-subagent offer for a refused switch, when the target can be a subagent model."""
    alias = alias_for(event.get("requested_model") or event.get("to_model"))
    if alias not in SUBAGENT_ALIASES:
        return None
    return {"alias": alias, "from_model": str(event.get("from_model", "")), "to_model": str(event.get("to_model", ""))}


def message(event: dict, tokens: int, usd: float | None, config: Config, basis: str = "api") -> str:
    source = _display(event.get("from_model"))
    target = _display(event.get("to_model"))
    offer = offer_for(event)
    ttl = event.get("cache_ttl") or "?"
    size = f"{tokens / 1000:,.0f}k"
    pricing = event.get("pricing")
    # The confirmation names the resolved id: an alias such as `opus` can resolve to another
    # version than the one asked about, and picking the same model again in the desktop app's
    # picker sends nothing (verified 2026-09-23), while a typed `/model` always reaches the hook.
    command = f"/model {event.get('to_model') or target}"
    if config.lang == "ko":
        label = (" (구독 사용량 기준: 캐시 쓰기를 입력 단가로 셈)" if basis == "subscription" else
                 {"configured": " (설정된 단가 기준)", "default": " (기본 단가로 추정)"}.get(pricing, " (API 정가 기준)"))
        cost = f"약 ${usd:,.2f}{label}" if usd is not None else "비용 추정 불가"
        text = (f"cachekeeper: {source} → {target}로 바꾸면 지금 살아 있는 캐시({ttl})를 버리고 "
                f"대화 {size} 토큰을 {target}에 다시 씁니다 — {cost}. ")
        if offer:
            text += (f"이 작업만 {target}로 하시겠습니까? 하려던 요청을 그대로 보내면 {target} 서브에이전트가 "
                     f"처리하고, 끝나면 지금 모델({source})로 이어집니다. 세션 모델 자체를 바꾸려면 ")
        else:
            text += "그래도 바꾸려면 "
        return text + (f"{config.confirm_seconds}초 안에 `{command}`를 입력하세요 "
                       f"(모델 선택기에서 같은 모델을 다시 누르면 전달되지 않을 수 있습니다).")
    label = (" of subscription usage (a cache write counts at the input price)" if basis == "subscription" else
             {"configured": " (your configured pricing)", "default": " (default tier, model unknown)"}.get(pricing, " at list price"))
    cost = f"about ${usd:,.2f}{label}" if usd is not None else "cost unknown"
    text = (f"cachekeeper: switching {source} → {target} forfeits the warm {ttl} cache and re-caches "
            f"{size} tokens on {target} — {cost}. ")
    if offer:
        text += (f"Run just this task on {target} instead? Send the request as you meant to and a {target} "
                 f"subagent handles it; this session then continues on {source}. To switch the session itself, ")
    else:
        text += "To switch anyway, "
    return text + (f"type `{command}` within {config.confirm_seconds}s (picking the same model again in a "
                   f"model picker may not reach Claude Code).")


def delegation(offer: dict, lang: str) -> dict:
    """UserPromptSubmit output that hands the next request to a subagent on the offered model.

    The subagent gets the exact model the user asked for (``claude-opus-5``, not ``opus``, which may resolve
    to another version); Claude Code 2.1.280 accepts full model ids there, and the alias is the fallback.
    """
    alias = offer["alias"]
    requested = str(offer.get("to_model") or "")
    exact = requested if requested.startswith("claude-") else alias
    target = _display(requested) if requested else alias
    source = _display(offer.get("from_model"))
    # Measured live with Haiku 4.5 as the main model: a conditional "if this is the task, delegate"
    # let it answer a short request itself, so the instruction is firm and only an explicit decline
    # is exempt. The subagent tool is `Agent` in the desktop app and `Task` in the headless CLI
    # (2.1.280); naming only `Agent` left the CLI with no tool to call.
    context = (
        f"cachekeeper: the user asked for this message to run on {target} without switching this session, "
        f"which stays on {source} so its prompt cache stays warm. Do not answer it yourself. Delegate it now: "
        f"call the subagent tool (Agent, or Task in some Claude Code versions) with model \"{exact}\""
        + (f" (if that model id is not accepted, \"{alias}\")" if exact != alias else "") +
        f" and a self-contained brief — the subagent does not see this "
        f"conversation, so include the request, the goal, the relevant files and paths, the decisions made so "
        f"far and the constraints. When it returns, relay or apply its result and continue here on {source}, "
        f"saying in one line that {target} did this in a subagent. Only if this message explicitly declines the "
        f"offer or only asks about the model switch itself, answer it directly instead."
    )
    notice = (f"cachekeeper: 이 요청을 {target} 서브에이전트에게 맡깁니다. 메인 세션은 {source}로 유지됩니다."
              if lang == "ko" else
              f"cachekeeper: handing this request to a {target} subagent; this session stays on {source}.")
    return {
        "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context},
        "systemMessage": notice,
    }


def _display(model: object) -> str:
    text = str(model or "?")
    return text[len("claude-"):] if text.startswith("claude-") else text
