"""``cachekeeper statusline``: how long the prompt cache stays warm, and when the keep-alive pings next.

Claude Code runs a status line command in the interactive terminal and hands it the session as JSON on stdin; the
``prompt_cache`` part (Claude Code 2.1.251 and later) says whether the cache is warm and when it expires. The desktop
app runs no status line command at all (measured 2026-09-24), so this is for the terminal only.

The next ping is the keep-alive's own plan (``keepalive.plan``) for this moment, from the transcript, the pings sent so
far and the policy in force. Auto mode's stored verdict is read, never recomputed: the status line runs after every
event and must stay fast. Nothing here writes anything.
"""

from __future__ import annotations

import time
from pathlib import Path

from . import keepalive

WORDS = {
    "ko": {"cache": "캐시 {size}", "left": "{time} 남음", "short": "(5분 캐시)",
           "cold": "캐시 식음", "rewrite": "다음 요청에 {size} 다시 씀",
           "next": "다음 핑 {time} 후 ({n}/{max})", "now": "곧 핑 ({n}/{max})",
           "cap": "핑 한도 ({max}/{max})", "small": "핑 안 함 ({min} 미만)", "off": "keep-alive 꺼짐",
           "minutes": "{m}분", "under": "1분 미만"},
    "en": {"cache": "cache {size}", "left": "{time} left", "short": "(5-min cache)",
           "cold": "cache cold", "rewrite": "next request rewrites {size}",
           "next": "next ping in {time} ({n}/{max})", "now": "ping due ({n}/{max})",
           "cap": "ping cap ({max}/{max})", "small": "no ping (under {min})", "off": "keep-alive off",
           "minutes": "{m}m", "under": "<1m"},
}


def tokens(count: int) -> str:
    return f"{count / 1_000_000:.1f}M" if count >= 1_000_000 else f"{round(count / 1000)}k"


def line(event: dict, env: dict[str, str], directory: Path, lang: str, now: float | None = None) -> str:
    """One status line, or "" when the session has no cache to speak of yet."""
    now = time.time() if now is None else now
    words = WORDS[lang]
    cache = event.get("prompt_cache")
    if not isinstance(cache, dict) or not cache.get("caching_observed"):
        return ""
    size = cache.get("recache_tokens_if_cold")
    size = tokens(int(size)) if isinstance(size, (int, float)) and size > 0 else ""
    expires = cache.get("expires_at")
    if not cache.get("warm") or not isinstance(expires, (int, float)) or expires <= now:
        return words["cold"] + (" · " + words["rewrite"].format(size=size) if size else "")

    def minutes(seconds: float) -> str:
        return words["minutes"].format(m=int(seconds // 60)) if seconds >= 60 else words["under"]

    parts = [words["cache"].format(size=size).strip(), words["left"].format(time=minutes(expires - now))]
    if cache.get("ttl") != "1h":
        return " · ".join(parts) + " " + words["short"]    # the keep-alive only waits on the one-hour cache
    ping = next_ping(event, env, directory, now, words, minutes)
    return " · ".join(parts + ([ping] if ping else []))


def next_ping(event: dict, env: dict[str, str], directory: Path, now: float, words: dict, minutes) -> str:
    policy = keepalive.policy_for(env, directory, now, recompute=False)
    if policy is None or policy.max_pings <= 0:
        return words["off"]
    session = str(event.get("session_id") or "")
    transcript = Path(str(event.get("transcript_path") or ""))
    if not session or not transcript.is_file():
        return ""
    view = keepalive.read_view(transcript)
    state = keepalive.read_state(keepalive.state_path(directory, session))
    pings = [float(at) for at in state.get("pings", []) if isinstance(at, (int, float))]
    # Planned as if the turn ended now: while the user types or the model works, that is what an idle moment brings.
    action, seconds, reason = keepalive.plan(view, pings, now, now, policy)
    count = sum(1 for at in pings if at > view.last_human)
    if action == "wait":
        return words["next"].format(time=minutes(seconds), n=count + 1, max=policy.max_pings)
    if action == "ping":
        return words["now"].format(n=count + 1, max=policy.max_pings)
    if reason == "cap":
        return words["cap"].format(max=policy.max_pings)
    if reason == "small":
        return words["small"].format(min=tokens(policy.min_context))
    return ""
