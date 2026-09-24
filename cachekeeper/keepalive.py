"""Keep a long session's prompt cache warm while its user is away — only while it pays.

Claude Code keeps the main conversation's prompt cache for an hour after the
last request started (on a subscription within plan usage; five minutes
otherwise). Coming back later writes the whole conversation into the cache
again: for a 300k-token Opus conversation, a few dollars at list price. One
short request before the hour is up reads the cache instead, for about a
twentieth of that, and starts the hour again.

The keep-alive is a Stop hook with ``asyncRewake``: when a turn ends, Claude
Code runs ``wait`` in the background, and if the hook exits with code 2, wakes
the model with what it printed. ``wait``

* returns 0 at once unless the conversation is at least ``min_context`` tokens,
  its cache lives an hour, and fewer than ``max_pings`` pings have followed the
  user's last message;
* otherwise sleeps until ``interval`` (55 minutes) after the last request
  started and returns ``WAKE``, which the hook command turns into exit code 2:
  the model answers one word, which reads the cache and
  restarts the hour, and the Stop hook of that short turn starts the next wait;
* returns 0 as soon as something else happens first: the user writes, another
  turn ends, the model is switched, the session is gone, or the machine slept
  past the hour.

It is on by default in ``auto`` mode: the minimum size and ``max_pings`` come
from this machine's history (``autopolicy``), which leaves the keep-alive off
when no policy would have paid off. ``CACHEKEEPER_KEEPALIVE=1`` waits under the
fixed settings instead (3 pings in a row, about three hours) and ``0`` turns it
off. ``plan`` holds the decision and is pure; ``wait`` is the loop around it.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import autopolicy
from .transcripts import PING_MARK as MARK, PING_TEXT, parse_time

POLL_SECONDS = 30
# Immediate stand-downs, which happen at most turn ends: not logged.
QUIET = ("small", "5-minute cache", "unknown cache", "no request")
LATE_SECONDS = 60           # closer than this to the hour's end, a ping may land after the cache is gone
KEEP_PINGS_SECONDS = 86_400
REPLY = "(keep-alive)"
# The exit code for a ping. The hook command turns it, and nothing else, into exit code 2, the one code that wakes
# the model: a missing file, a missing or failing Python, or a shell's own error can never wake it in a loop.
WAKE = 75
# Who counts as the user coming back: someone typing, another session's message, a channel message.
# Background-task notifications (the pings among them), automatic continuations and plugin messages do not.
ARRIVALS = ("human", "peer", "channel", "person")


@dataclass(frozen=True)
class Policy:
    interval: int = 55 * 60
    max_pings: int = 3
    min_context: int = 100_000

    @staticmethod
    def from_env(env: dict[str, str] | None = None) -> "Policy":
        env = dict(os.environ if env is None else env)

        def number(key: str, default: float) -> float:
            try:
                value = float(env.get(key, "") or default)
            except ValueError:
                return default
            return value if value >= 0 else default

        minutes = number("CACHEKEEPER_KEEPALIVE_MINUTES", 55) or 55
        hours = number("CACHEKEEPER_KEEPALIVE_HOURS", 3)
        return Policy(
            interval=int(minutes * 60),
            max_pings=int(hours * 3600 // (minutes * 60)),
            min_context=int(number("CACHEKEEPER_KEEPALIVE_MIN_TOKENS", 100_000)),
        )


def mode(env: dict[str, str]) -> str:
    """``auto`` (the default: recomputed daily from history), ``fixed`` (the CACHEKEEPER_KEEPALIVE_* settings)
    or ``off``."""
    value = env.get("CACHEKEEPER_KEEPALIVE", "").strip().lower()
    if value in ("0", "off", "false", "no"):
        return "off"
    return "fixed" if value in ("1", "on", "true", "yes") else "auto"


def policy_for(env: dict[str, str], directory: Path, now: float, recompute: bool = True) -> Policy | None:
    """The policy to wait under, or None when the keep-alive is off (by setting or by auto mode's verdict).
    ``recompute=False`` reads auto mode's stored verdict and never replays the history, for the status line."""
    current = mode(env)
    if current == "off":
        return None
    policy = Policy.from_env(env)
    if current == "fixed":
        return policy
    if recompute:
        decision = autopolicy.current(directory, env, now)
    else:
        decision = autopolicy.read_decision(directory) or autopolicy.DEFAULT
    if decision.get("source") == "off":
        return None
    # The replay that chose the decision prices a ping every 55 minutes: auto mode pings at that interval, and
    # CACHEKEEPER_KEEPALIVE_MINUTES applies with CACHEKEEPER_KEEPALIVE=1 only.
    interval = Policy().interval
    return Policy(interval=interval,
                  max_pings=int(float(decision.get("cap_hours", 0)) * 3600 // interval),
                  min_context=int(decision.get("min_context", 0)))


@dataclass(frozen=True)
class View:
    """What the transcript says about the session's cache, as epoch seconds and tokens."""
    anchor: float | None = None      # when the last main-conversation request started
    last_human: float = 0.0          # the user's last message, or another session's (0 when none is in view)
    context: int = 0                 # tokens the next request re-sends; 0 right after a compaction
    ttl: int | None = None           # 3600 or 300 from the last cache write; None when none is in view, as with
                                     # a backend that reports no cache writes: then nothing says a ping would pay


def plan(view: View, pings: list[float], started_at: float, now: float, policy: Policy) -> tuple[str, float, str]:
    """``("ping", 0, "")``, ``("wait", seconds, "")`` or ``("stop", 0, reason)`` for one look at the session."""
    if view.anchor is None:
        return "stop", 0.0, "no request"
    if view.context < policy.min_context:
        return "stop", 0.0, "small"
    if view.ttl is None:
        return "stop", 0.0, "unknown cache"
    ttl = view.ttl
    if ttl < 3600:
        return "stop", 0.0, "5-minute cache"
    if view.last_human > started_at:
        return "stop", 0.0, "user back"     # the Stop hook of the user's turn takes over
    if sum(1 for at in pings if at > view.last_human) >= policy.max_pings:
        return "stop", 0.0, "cap"
    if now >= view.anchor + ttl - LATE_SECONDS:
        return "stop", 0.0, "late"          # the machine slept, or the hook started late: the cache is gone
    deadline = view.anchor + policy.interval
    if now >= deadline:
        return "ping", 0.0, ""
    return "wait", deadline - now, ""


def _epoch(value: object) -> float | None:
    parsed = parse_time(value)
    return parsed.timestamp() if parsed else None


def _is_arrival(entry: dict) -> bool:
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, list):
        if any(isinstance(block, dict) and block.get("type") == "tool_result" for block in content):
            return False
        content = " ".join(str(block.get("text", "")) for block in content if isinstance(block, dict))
    text = str(content or "").lstrip()
    if PING_TEXT.search(text):
        return False    # a ping's own words, whatever origin Claude Code delivers it with
    origin = entry.get("origin")
    if isinstance(origin, dict):
        return origin.get("kind") in ARRIVALS
    # Transcripts from before `origin` existed: plain text the user typed.
    if entry.get("isMeta") or entry.get("isCompactSummary"):
        return False
    return bool(text) and not text.startswith(("<", "["))


def view_of(lines: list[str]) -> tuple[View, bool]:
    """Read transcript lines; the flag says whether the last request's start, a user message and a cache write
    were in view."""
    times: dict[str, float] = {}
    first_block: dict[str, dict] = {}
    last_id: str | None = None
    last_usage: dict = {}
    last_human = 0.0
    ttl: int | None = None
    compacted = False
    for line in lines:
        if '"timestamp"' not in line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("isSidechain"):
            continue
        at = _epoch(entry.get("timestamp"))
        if at is None:
            continue
        if isinstance(entry.get("uuid"), str):
            times[entry["uuid"]] = at
        kind = entry.get("type")
        message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
        if kind == "assistant" and isinstance(message.get("usage"), dict):
            if str(message.get("model", "")).startswith("<"):
                continue            # synthetic messages (errors, interruptions) made no request
            message_id = str(message.get("id") or entry.get("requestId") or entry.get("uuid"))
            first_block.setdefault(message_id, entry)
            last_id, last_usage = message_id, message["usage"]
            split = last_usage.get("cache_creation")
            if isinstance(split, dict):
                if int(split.get("ephemeral_1h_input_tokens") or 0):
                    ttl = 3600
                elif int(split.get("ephemeral_5m_input_tokens") or 0):
                    ttl = 300
            compacted = False
        elif kind == "user" and _is_arrival(entry):
            last_human = at
        elif kind == "system" and entry.get("subtype") == "compact_boundary":
            compacted = True
    anchor = None
    if last_id is not None:
        first = first_block[last_id]
        anchor = times.get(str(first.get("parentUuid"))) or _epoch(first.get("timestamp"))
        if last_human > (anchor or 0):
            anchor = last_human     # a message sent after it: its request is the latest
    context = 0 if compacted else sum(int(last_usage.get(key) or 0) for key in (
        "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens"))
    return View(anchor, last_human, context, ttl), (anchor is not None and last_human > 0 and ttl is not None)


def read_view(transcript: Path, window: int = 2_000_000, limit: int = 64_000_000) -> View:
    """The transcript's view, reading back from the end until the last request, a user message and a cache write
    are in it."""
    try:
        with open(transcript, "rb") as stream:
            size = stream.seek(0, os.SEEK_END)
            while True:
                start = max(0, size - window)
                stream.seek(start)
                lines = stream.read(size - start).decode("utf-8", "replace").splitlines()
                if start:
                    lines = lines[1:]   # the first line is cut
                view, complete = view_of(lines)
                if complete or start == 0 or window >= limit:
                    return view
                window *= 8
    except OSError:
        return View()


def state_path(directory: Path, session: str) -> Path:
    safe = "".join(ch for ch in session if ch.isalnum() or ch in "-_") or "unknown"
    return directory / "keepalive" / f"{safe}.json"


def read_state(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}")
    temporary.write_text(json.dumps(state), encoding="utf-8")
    os.replace(temporary, path)


def _alive(pid: int) -> bool:
    if os.name == "nt":
        return _alive_on_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _alive_on_windows(pid: int) -> bool:
    """os.kill(pid, 0) would terminate the process on Windows: ask for its exit code instead."""
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel32.OpenProcess(0x1000, False, pid)      # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ctypes.get_last_error() != 87                # ERROR_INVALID_PARAMETER: no such process
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == 259                            # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def message(view: View, pings: int, now: float, policy: Policy) -> str:
    idle = max(0, round((now - (view.anchor or now)) / 60))
    return (f"{MARK} {pings} of {policy.max_pings}, not an error: this session has been idle for {idle} min and "
            f"its prompt cache ({view.context / 1000:,.0f}k tokens) expires an hour after the last request. This "
            f"turn only keeps it warm while the user is away (CACHEKEEPER_KEEPALIVE=0 in settings turns these "
            f"pings off). Reply with exactly {REPLY} and nothing else: no tools, no summary.")


def wait(event: dict, env: dict[str, str], directory: Path, *, now: Callable[[], float] = time.time,
         sleep: Callable[[float], None] = time.sleep, err=None,
         log: Callable[[dict], None] | None = None) -> int:
    """The Stop hook's background wait. Returns ``WAKE`` to wake the model for one ping, else 0.

    ``log`` receives one record per wait that ran: how it ended, and why (not the immediate
    stand-downs of small or five-minute-cache sessions, which happen at most turn ends).
    """
    err = err or sys.stderr
    if mode(env) == "off" or env.get("CLAUDE_CODE_ENTRYPOINT", "").startswith("sdk-"):
        return 0                        # `claude -p` runs asyncRewake hooks in the foreground; SDK apps are programs
    transcript = Path(str(event.get("transcript_path") or ""))
    session = str(event.get("session_id") or "")
    if not session or not transcript.is_file():
        return 0
    policy = policy_for(env, directory, now())
    if policy is None or policy.max_pings <= 0:
        return 0
    code, reason, view = _wait(transcript, session, directory, policy, env, now, sleep, err)
    if log is not None and reason not in QUIET:
        log({"at": round(now(), 3), "event": "keepalive", "session_id": session,
             "decision": "ping" if code == WAKE else "stop", "reason": reason,
             "context_tokens": view.context, "idle_seconds": round(now() - view.anchor) if view.anchor else None,
             "policy": {"interval": policy.interval, "max_pings": policy.max_pings, "min_context": policy.min_context}})
    return code


def _wait(transcript: Path, session: str, directory: Path, policy: Policy, env: dict[str, str],
          now: Callable[[], float], sleep: Callable[[float], None], err) -> tuple[int, str, View]:
    path = state_path(directory, session)
    started_at = now()
    generation = f"{os.getpid()}-{started_at}"
    state = read_state(path)
    state["generation"] = generation
    state["pings"] = [at for at in state.get("pings", []) if isinstance(at, (int, float))
                      and started_at - at < KEEP_PINGS_SECONDS]
    write_state(path, state)
    owner = int(env.get("CLAUDE_PID") or 0)
    seen: tuple[float, int] | None = None
    view = View()
    while True:
        state = read_state(path)
        if state.get("generation") != generation:
            return 0, "superseded", view    # a later turn ended or the model was switched
        if owner and not _alive(owner):
            return 0, "gone", view
        try:
            stat = transcript.stat()
        except OSError:
            return 0, "gone", view
        if seen != (stat.st_mtime, stat.st_size):
            seen, view = (stat.st_mtime, stat.st_size), read_view(transcript)
        current = now()
        pings = [float(at) for at in state.get("pings", [])]
        action, seconds, reason = plan(view, pings, started_at, current, policy)
        if action == "stop":
            return 0, reason, view
        if action == "ping":
            count = sum(1 for at in pings if at > view.last_human) + 1
            state["pings"] = pings + [current]
            state["generation"] = None
            write_state(path, state)
            err.write(message(view, count, current, policy) + "\n")
            return WAKE, f"{count}/{policy.max_pings}", view
        sleep(min(POLL_SECONDS, max(1.0, seconds)))


def switched(directory: Path, session: str) -> None:
    """A model switch happened: the next request rebuilds anyway, so a pending wait stands down."""
    path = state_path(directory, session)
    state = read_state(path)
    if state.get("generation"):
        state["generation"] = None
        write_state(path, state)
