"""The keep-alive policy for ``CACHEKEEPER_KEEPALIVE=auto``: recomputed from this machine's history once a day.

``cachekeeper keepalive`` replays the idle stretches in the local transcripts against every combination of
minimum context size and cap and prints the best one; auto mode applies it, and keeps applying the current best
as habits change. Three guards:

* too little history (fewer than ``MIN_STRETCHES`` idle stretches of 55 minutes or more in one-hour-cache
  sessions): the defaults, 100k tokens and 3 hours, until there is enough to go on;
* no combination saves anything, or no session uses the one-hour cache: off, until that changes;
* Claude Code deletes terminal transcripts 30 days after their last activity (``cleanupPeriodDays``), so every
  idle stretch seen is also kept, as numbers only (when, how long, how big, what the rebuild cost), in
  ``keepalive/gaps.jsonl``; the policy reads the last ``WINDOW_DAYS`` of them.

The recomputation reads the transcripts (about two seconds for a few hundred sessions) inside the background
Stop hook, at most once a day, never on the user's turn.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import time
from pathlib import Path

from .audit import Gap, best_policy, idle_gaps
from .transcripts import read_sessions

MAX_AGE_SECONDS = 86_400
LOCK_SECONDS = 600
WINDOW_DAYS = 60
MIN_STRETCHES = 10
DEFAULT = {"min_context": 100_000, "cap_hours": 3.0}


def projects_dir(env: dict[str, str]) -> Path:
    base = env.get("CLAUDE_CONFIG_DIR", "").strip()
    return (Path(base) if base else Path.home() / ".claude") / "projects"


def _paths(directory: Path) -> tuple[Path, Path, Path]:
    folder = directory / "keepalive"
    return folder / "policy.json", folder / "gaps.jsonl", folder / "policy.lock"


def load_gaps(path: Path) -> list[Gap]:
    gaps = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return gaps
    for line in lines:
        try:
            record = json.loads(line)
            gaps.append(Gap(float(record["seconds"]), int(record["context"]), float(record["read_price"]),
                            float(record["rebuild_cost"]), float(record["at"]), str(record["session"])))
        except (ValueError, KeyError, TypeError):
            continue
    return gaps


def remember(path: Path, known: list[Gap], seen: list[Gap]) -> list[Gap]:
    """Append the stretches not stored yet; return everything known."""
    keys = {(gap.session, round(gap.at)) for gap in known}
    new = [gap for gap in seen if (gap.session, round(gap.at)) not in keys]
    if new:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as stream:
            for gap in new:
                stream.write(json.dumps({"at": round(gap.at, 3), "session": gap.session, "seconds": round(gap.seconds),
                                         "context": gap.context, "read_price": gap.read_price,
                                         "rebuild_cost": round(gap.rebuild_cost, 6)}) + "\n")
    return known + new


def decide(gaps: list[Gap], now: float, one_hour_sessions: int, sessions: int) -> dict:
    """The policy for these idle stretches: ``source`` is history, default or off."""
    window = [gap for gap in gaps if now - gap.at <= WINDOW_DAYS * 86_400]
    base = {"computed_at": round(now, 3), "stretches": len(window),
            "first_at": round(min(gap.at for gap in window), 3) if window else None}
    if sessions and not one_hour_sessions:
        return {**base, "source": "off", "why": "5-minute cache", "min_context": 0, "cap_hours": 0.0}
    if len(window) < MIN_STRETCHES:
        return {**base, "source": "default", "why": f"fewer than {MIN_STRETCHES} idle stretches", **DEFAULT}
    best = best_policy(window)
    if best["net"] <= 0:
        return {**base, "source": "off", "why": "no cap would have saved anything", "min_context": 0, "cap_hours": 0.0}
    return {**base, "source": "history", "why": f"net ${best['net']:.2f} over {len(window)} idle stretches",
            "min_context": int(best["min_context"]), "cap_hours": float(best["cap_hours"]),
            "pings": int(best["pings"]), "prevented": int(best["prevented"]), "net_usd": round(best["net"], 4)}


def recompute(directory: Path, projects: Path, now: float) -> dict:
    policy_path, gaps_path, _ = _paths(directory)
    sessions = read_sessions(projects, dt.datetime.fromtimestamp(now - WINDOW_DAYS * 86_400, dt.timezone.utc))
    seen, _ = idle_gaps(sessions)
    known = remember(gaps_path, load_gaps(gaps_path), seen)
    one_hour = sum(1 for session in sessions if session.ttl_seconds >= 3600)
    decision = decide(known, now, one_hour, len(sessions))
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = policy_path.with_name(f".{policy_path.name}.{os.getpid()}")
    temporary.write_text(json.dumps(decision), encoding="utf-8")
    os.replace(temporary, policy_path)
    return decision


def read_decision(directory: Path) -> dict | None:
    try:
        value = json.loads(_paths(directory)[0].read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def current(directory: Path, env: dict[str, str], now: float | None = None) -> dict:
    """Today's decision: the stored one while it is fresh, else a new one (one process at a time recomputes)."""
    now = time.time() if now is None else now
    stored = read_decision(directory)
    if stored and now - float(stored.get("computed_at", 0)) < MAX_AGE_SECONDS:
        return stored
    _, _, lock = _paths(directory)
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        if now - lock.stat().st_mtime < LOCK_SECONDS:
            return stored or {"source": "default", "why": "first computation in progress", **DEFAULT}
        lock.unlink()
    except OSError:
        pass
    try:
        handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        return stored or {"source": "default", "why": "first computation in progress", **DEFAULT}
    try:
        os.close(handle)
        return recompute(directory, projects_dir(env), now)
    finally:
        try:
            lock.unlink()
        except OSError:
            pass
