"""Hook entry point: ``python -m cachekeeper.hook pre-model-switch|post-model-switch``.

Reads the event from stdin, answers on stdout, and appends one line per event to
``events.jsonl`` in the plugin's data directory (no prompt text, no file
contents: model ids, token counts and the decision). A PreModelSwitch hook that
fails or times out blocks the switch, so every error path here stays silent and
lets the switch through.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

from .guard import Config, at_stake, decide

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


def record_for(kind: str, event: dict, decision: str) -> dict:
    warm, tokens, usd = at_stake(event)
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
    if kind == "pre-model-switch":
        config = Config.from_env(env)
        output, pending = decide(event, read_pending(pending_path), now, config)
        write_pending(pending_path, pending)
        if output is None:
            decision = "silent"
        elif "systemMessage" in output:
            decision = "warn"
        else:
            decision = output["hookSpecificOutput"]["permissionDecision"]
        log_event(directory, record_for("pre", event, decision))
        return json.dumps(output, ensure_ascii=False) if output else ""
    if kind == "post-model-switch":
        # The switch the guard asked about happened (confirmed in a dialog): drop the pending ask.
        # A different switch — a resume restoring the session's model, an automatic fallback —
        # leaves it in place, so the user's repeat still counts as the confirmation.
        pending = read_pending(pending_path)
        session = str(event.get("session_id", ""))
        entry = pending.get(session)
        if isinstance(entry, dict) and entry.get("to_model") == event.get("to_model"):
            pending.pop(session)
            write_pending(pending_path, pending)
        log_event(directory, record_for("post", event, "switched"))
        return ""
    return ""


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        raw = sys.stdin.read(MAX_EVENT_BYTES + 1)
        if len(raw) > MAX_EVENT_BYTES or len(argv) != 1:
            return 0
        output = handle(argv[0], raw)
        if output:
            sys.stdout.write(output)
    except Exception as error:  # never block a switch because of a bug here
        sys.stderr.write(f"cachekeeper: {type(error).__name__}: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
