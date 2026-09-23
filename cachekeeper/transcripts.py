"""Read Claude Code transcripts into requests and the markers between them.

A main-session transcript is ``~/.claude/projects/<project>/<session>.jsonl``;
subagent transcripts live in subdirectories and are left out, because the cache
this tool is about is the main conversation's. Each API response can span
several transcript lines (one per content block) carrying the same message id;
it is counted once. A resumed session can copy earlier history into a new
file, so message ids are also counted once across files.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

MODEL_COMMAND = re.compile(r"<command-name>/model</command-name>.*?<command-args>(.*?)</command-args>", re.S)


@dataclass
class Request:
    at: dt.datetime
    model: str
    effort: str | None
    input: int = 0
    cache_read: int = 0
    write_5m: int = 0
    write_1h: int = 0
    output: int = 0

    @property
    def context(self) -> int:
        """Prompt tokens this request sent."""
        return self.input + self.cache_read + self.write_5m + self.write_1h

    @property
    def writes(self) -> int:
        return self.write_5m + self.write_1h

    @property
    def next_context(self) -> int:
        """What the following request re-sends: this prompt plus this response (Claude Code's context_tokens)."""
        return self.context + self.output


@dataclass
class Marker:
    at: dt.datetime
    kind: str  # "model_command" or "compact"
    detail: str = ""


@dataclass
class Session:
    path: Path
    requests: list[Request] = field(default_factory=list)
    markers: list[Marker] = field(default_factory=list)

    @property
    def ttl_seconds(self) -> int:
        """1 hour when the session wrote one-hour cache entries, else 5 minutes."""
        return 3600 if any(r.write_1h for r in self.requests) else 300


def parse_time(value: object) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(block.get("text", "")) for block in content if isinstance(block, dict))
    return ""


def _usage(request: Request, usage: dict) -> None:
    request.input = int(usage.get("input_tokens") or 0)
    request.cache_read = int(usage.get("cache_read_input_tokens") or 0)
    request.output = int(usage.get("output_tokens") or 0)
    created = int(usage.get("cache_creation_input_tokens") or 0)
    split = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else {}
    one_hour = int(split.get("ephemeral_1h_input_tokens") or 0)
    five_minutes = split.get("ephemeral_5m_input_tokens")
    request.write_1h = one_hour
    request.write_5m = int(five_minutes) if five_minutes is not None else max(0, created - one_hour)


def read_session(path: Path, since: dt.datetime, seen: set[str]) -> Session:
    """Parse one transcript; ``seen`` collects message ids across files."""
    session = Session(path)
    by_id: dict[str, tuple[Request, int]] = {}
    with open(path, encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if not ('"assistant"' in line or "/model" in line or "compact_boundary" in line):
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict) or entry.get("isSidechain"):
                continue
            at = parse_time(entry.get("timestamp"))
            if at is None or at < since:
                continue
            kind = entry.get("type")
            message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
            if kind == "assistant":
                usage = message.get("usage")
                message_id = message.get("id") or entry.get("requestId")
                model = message.get("model") or ""
                if not isinstance(usage, dict) or not message_id or model.startswith("<"):
                    continue
                if message_id in seen and message_id not in by_id:
                    continue
                output = int(usage.get("output_tokens") or 0)
                current = by_id.get(message_id)
                if current is None:
                    request = Request(at=at, model=model, effort=entry.get("effort"))
                    _usage(request, usage)
                    by_id[message_id] = (request, output)
                    seen.add(message_id)
                else:
                    request, best = current
                    request.at = min(request.at, at)
                    request.effort = request.effort or entry.get("effort")
                    if output >= best:
                        _usage(request, usage)
                        by_id[message_id] = (request, output)
            elif kind == "user":
                match = MODEL_COMMAND.search(_text(message.get("content")))
                if match:
                    session.markers.append(Marker(at, "model_command", match.group(1).strip()))
            elif kind == "system" and entry.get("subtype") == "compact_boundary":
                metadata = entry.get("compactMetadata") if isinstance(entry.get("compactMetadata"), dict) else {}
                session.markers.append(Marker(at, "compact", str(metadata.get("trigger", ""))))
    session.requests = sorted((pair[0] for pair in by_id.values()), key=lambda r: r.at)
    session.markers.sort(key=lambda m: m.at)
    return session


def main_session_files(projects: Path) -> Iterator[Path]:
    """Top-level transcripts only: ``<projects>/<project>/<session>.jsonl``."""
    if not projects.is_dir():
        return
    for project in sorted(projects.iterdir()):
        if project.is_dir():
            yield from sorted(project.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)


def read_sessions(projects: Path, since: dt.datetime) -> list[Session]:
    seen: set[str] = set()
    sessions = []
    files: Iterable[Path] = sorted(
        (path for path in main_session_files(projects) if path.stat().st_mtime >= since.timestamp()),
        key=lambda p: p.stat().st_mtime,
    )
    for path in files:
        session = read_session(path, since, seen)
        if session.requests:
            sessions.append(session)
    return sessions
