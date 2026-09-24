"""Hook entry point: ``python -m cachekeeper.hook pre-model-switch|post-model-switch|user-prompt-submit|stop``.

Reads the event from stdin, answers on stdout, and appends one line per event to
``events.jsonl`` in the plugin's data directory (no prompt text, no file
contents: model ids, token counts and the decision). A PreModelSwitch hook that
fails or times out blocks the switch, so every error path here stays silent and
lets the switch through. ``stop`` is the keep-alive's background wait: its exit
code (2 wakes the model) is the answer.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

from . import keepalive
from .guard import Config, at_stake, basis_for, decide, delegation, offer_for

MAX_EVENT_BYTES = 1_000_000


def data_dir(env: dict[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    configured = env.get("CLAUDE_PLUGIN_DATA", "").strip()
    return Path(configured) if configured else Path.home() / ".cachekeeper"


def read_pending(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_pending(path: Path, pending: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        json.dump(pending, stream)
    os.replace(temporary, path)


def log_event(directory: Path, record: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / "events.jsonl", "a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")


def record_for(kind: str, event: dict, decision: str, basis: str = "api") -> dict:
    warm, tokens, usd = at_stake(event, basis)
    return {
        "at": round(time.time(), 3),
        "event": kind,
        "session_id": str(event.get("session_id", "")),
        "source": event.get("source"),
        "from_model": event.get("from_model"),
        "to_model": event.get("to_model"),
        "context_tokens": tokens,
        "prompt_cache_warm": warm,
        "cache_ttl": event.get("cache_ttl"),
        "estimated_cache_write_usd": None if usd is None else round(usd, 4),
        "basis": basis,
        "pricing": event.get("pricing"),
        "decision": decision,
    }


def handle(kind: str, raw: str, env: dict[str, str] | None = None, now: float | None = None) -> str:
    """Process one hook event and return what to print (possibly empty)."""
    env = dict(os.environ if env is None else env)
    now = time.time() if now is None else now
    event = json.loads(raw)
    if not isinstance(event, dict):
        return ""
    directory = data_dir(env)
    pending_path = directory / "pending.json"
    offers_path = directory / "offers.json"
    session = str(event.get("session_id", ""))
    config = Config.from_env(env)
    if kind == "pre-model-switch":
        output, pending = decide(event, read_pending(pending_path), now, config)
        write_pending(pending_path, pending)
        if output is None:
            decision = "silent"
        elif "systemMessage" in output:
            decision = "warn"
        else:
            decision = output["hookSpecificOutput"]["permissionDecision"]
        offers = read_pending(offers_path)
        offer = offer_for(event) if decision == "ask" else None
        if offer:
            offers[session] = {**offer, "at": now}
        elif decision == "allow":
            offers.pop(session, None)   # confirmed: the session itself switches
        write_pending(offers_path, offers)
        log_event(directory, record_for("pre", event, decision, basis_for(event, config)))
        return json.dumps(output, ensure_ascii=False) if output else ""
    if kind == "post-model-switch":
        # The switch the guard asked about happened (confirmed in a dialog): drop the pending ask
        # and the subagent offer. A different switch — a resume restoring the session's model, an
        # automatic fallback — leaves both in place, so the user's repeat still counts.
        for path in (pending_path, offers_path):
            entries = read_pending(path)
            entry = entries.get(session)
            if isinstance(entry, dict) and entry.get("to_model") == event.get("to_model"):
                entries.pop(session)
                write_pending(path, entries)
        if event.get("source") != "resume":
            keepalive.switched(directory, session)  # the next request rebuilds anyway: no ping for it
        log_event(directory, record_for("post", event, "switched", basis_for(event, config)))
        return ""
    if kind == "user-prompt-submit":
        # The first ordinary message after a refused switch is the request the user meant for the
        # other model: the main model asks whether a subagent on that model should take it. Nobody
        # answers in `claude -p` runs and SDK apps (an `sdk-` entrypoint), so there it goes to the
        # subagent at once. Slash commands (a `/model` confirming the switch, anything else) leave
        # the offer for the next message.
        prompt = str(event.get("prompt", ""))
        offers = read_pending(offers_path)
        offer = offers.get(session)
        if not isinstance(offer, dict) or prompt.lstrip().startswith("/"):
            return ""
        offers.pop(session)
        write_pending(offers_path, offers)
        if now - float(offer.get("at", 0)) > config.offer_seconds:
            return ""
        ask = not env.get("CLAUDE_CODE_ENTRYPOINT", "").startswith("sdk-")
        log_event(directory, {"at": round(now, 3), "event": "prompt", "session_id": session,
                              "from_model": offer.get("from_model"), "to_model": offer.get("to_model"),
                              "decision": "ask" if ask else "delegate"})
        return json.dumps(delegation(offer, config.lang, ask), ensure_ascii=False)
    return ""


def utf8_output() -> None:
    """Claude Code reads a hook's pipes as UTF-8. Python on Windows writes them in the ANSI code page (cp1252,
    cp949), which cannot encode the guard's "→" or "—": the hook would fail and the switch pass unasked."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure") and str(getattr(stream, "encoding", "")).lower().replace("-", "") != "utf8":
            stream.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        utf8_output()
        data = getattr(sys.stdin, "buffer", sys.stdin).read(MAX_EVENT_BYTES + 1)   # bytes: UTF-8 whatever the code page
        raw = data.decode("utf-8", "replace") if isinstance(data, bytes) else data
        if len(data) > MAX_EVENT_BYTES or len(argv) != 1:
            return 0
        if argv[0] == "stop":
            event = json.loads(raw)
            if not isinstance(event, dict):
                return 0
            directory = data_dir()
            return keepalive.wait(event, dict(os.environ), directory, log=lambda record: log_event(directory, record))
        output = handle(argv[0], raw)
        if output:
            sys.stdout.write(output)
    except Exception as error:  # never block a switch because of a bug here
        sys.stderr.write(f"cachekeeper: {type(error).__name__}: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
