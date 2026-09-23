"""What an earlier auto-compaction would have cost and saved, replayed on the local history.

Every request re-reads the whole conversation from the cache, so a long session pays for its length on every
turn. Claude Code compacts automatically when the context approaches the auto-compact window (the
``autoCompactWindow`` setting or ``CLAUDE_CODE_AUTO_COMPACT_WINDOW``, 100k-1M tokens; by default close to the
model's whole window, 1M for the current models). ``replay`` asks, for a smaller window: how much less would
the requests have re-read, and what would the extra compactions have cost?

Each session is replayed request by request. The simulated context grows by what the real one grew by; when
it would pass the window, a compaction happens first:

* the compaction request reads the context and writes a summary (``SUMMARY_TOKENS`` of output);
* the conversation continues from ``after`` tokens — by default the median size right after the real
  compactions in this history — plus ``REREAD_TOKENS`` the model reads again (files, errors) because the
  summary lost them, all written to the cache anew;
* every later request reads the smaller context, and a rebuild (after a break or a model switch) rewrites
  the smaller context.

What the replay cannot see is quality: a summary loses details, and whether that costs more than a long
context does is a question about the work, not the bill. ``REREAD_TOKENS`` prices only the obvious part.
"""

from __future__ import annotations

import datetime as dt
import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from .audit import is_rebuild, request_cost
from .pricing import price_for
from .transcripts import Session

WINDOWS = (200_000, 300_000, 400_000, 500_000, 600_000, 800_000)
SUMMARY_TOKENS = 8_000       # output of one compaction: the summary and the thinking around it
REREAD_TOKENS = 20_000       # what the model reads again after a compaction because the summary dropped it
CAUTIOUS_REREAD = 60_000     # the same, for a summary that dropped a lot: the second net column
DEFAULT_AFTER = 70_000       # context right after a compaction when the history has none to measure


@dataclass
class Outcome:
    window: int
    compactions: int = 0
    read_saved: float = 0.0       # $ the requests would not have re-read
    rebuild_saved: float = 0.0    # $ smaller rebuilds after breaks and switches
    compaction_cost: float = 0.0  # $ the compactions themselves
    sessions: set = field(default_factory=set)

    @property
    def net(self) -> float:
        return self.read_saved + self.rebuild_saved - self.compaction_cost


def measured_after(paths: list[Path]) -> int | None:
    """Median context of the first request after each real compaction in these transcripts."""
    sizes: dict[str, int] = {}
    for path in paths:
        waiting: str | None = None
        try:
            stream = open(path, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with stream:
            for line in stream:
                if "compact_boundary" in line:
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        continue
                    if entry.get("subtype") == "compact_boundary" and not entry.get("isSidechain"):
                        waiting = str(entry.get("uuid") or entry.get("timestamp"))
                elif waiting and '"usage"' in line and '"assistant"' in line:
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        continue
                    usage = (entry.get("message") or {}).get("usage")
                    if entry.get("type") == "assistant" and not entry.get("isSidechain") and isinstance(usage, dict):
                        size = sum(int(usage.get(key) or 0) for key in
                                   ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
                        if size:
                            sizes[waiting] = size     # a resumed copy of the same boundary counts once
                        waiting = None
    return int(statistics.median(sizes.values())) if sizes else None


def replay(sessions: list[Session], window: int, after: int, reread: int = REREAD_TOKENS) -> Outcome:
    outcome = Outcome(window)
    restart = after + reread
    for session in sessions:
        simulated: int | None = None
        previous_context = 0
        for request in session.requests:
            price = price_for(request.model)
            if price is None:
                continue
            context = request.context
            if simulated is None:
                simulated = context
            elif context < previous_context:
                simulated = min(simulated, context)     # the real conversation shrank: a real compaction
            else:
                grown = simulated + context - previous_context
                if grown > window:
                    # Compact first: read the conversation, write the summary, go on from `restart`.
                    outcome.compactions += 1
                    outcome.sessions.add(session.path.stem)
                    write = price.write_1h if session.ttl_seconds >= 3600 else price.write_5m
                    outcome.compaction_cost += (simulated * price.cache_read + SUMMARY_TOKENS * price.output
                                                + restart * write) / 1_000_000
                    grown = restart + context - previous_context
                simulated = grown
            previous_context = context
            if simulated >= context:
                continue
            shorter = context - simulated
            if is_rebuild(request):
                outcome.rebuild_saved += request_cost(request)["cache write"] * shorter / context
            else:
                outcome.read_saved += min(request.cache_read, shorter) * price.cache_read / 1_000_000
    return outcome


def report(sessions: list[Session], paths: list[Path], lang: str, total: float, days: float) -> str:
    after = measured_after(paths)
    measured = after is not None
    after = after or DEFAULT_AFTER
    ko = lang == "ko"
    rows = [(replay(sessions, window, after), replay(sessions, window, after, CAUTIOUS_REREAD)) for window in WINDOWS]
    lines = [(f"자동 압축 재현 — 기록 {days:.0f}일치, 메인 세션 {len(sessions)}개. 압축 뒤 맥락 {after / 1000:.0f}k 토큰"
              f"({'실제 압축들의 중간값' if measured else '기본값'}) + 다시 읽기 {REREAD_TOKENS // 1000}k, 요약 출력 "
              f"{SUMMARY_TOKENS // 1000}k로 가정. 마지막 열은 다시 읽기를 {CAUTIOUS_REREAD // 1000}k로 잡았을 때"
              if ko else
              f"Auto-compaction replay — {days:.0f} days of history, {len(sessions)} main sessions. Context after a "
              f"compaction: {after / 1000:.0f}k tokens ({'median of the real ones' if measured else 'default'}) + "
              f"{REREAD_TOKENS // 1000}k read again; {SUMMARY_TOKENS // 1000}k of summary output. The last column "
              f"assumes {CAUTIOUS_REREAD // 1000}k read again"), "",
             (f"  {'창':<6}{'압축(하루)':>12}{'읽기 절감':>10}{'재구축 절감':>11}{'압축 비용':>10}{'순효과':>8}{'신중히':>9}"
              if ko else
              f"  {'window':<8}{'compactions (a day)':>21}{'reads':>8}{'rebuilds':>10}{'compacting':>12}{'net':>8}"
              f"{'cautious':>10}")]
    for plain, cautious in rows:
        per_day = plain.compactions / days if days else 0.0
        cells = [plain.read_saved / total, plain.rebuild_saved / total, -plain.compaction_cost / total,
                 plain.net / total, cautious.net / total]
        widths = (10, 11, 10, 8, 9) if ko else (8, 10, 12, 8, 10)
        lines.append(f"  {f'{plain.window // 1000}k':<{6 if ko else 8}}"
                     f"{f'{plain.compactions} ({per_day:.1f})':>{12 if ko else 21}}"
                     + "".join(f"{value:>{width}.1%}" for value, width in zip(cells, widths)))
    # The pick has to survive a summary that loses more than assumed.
    best, best_cautious = max(rows, key=lambda row: row[1].net)
    weekly = best.net / days * 7 if days else 0.0
    if best_cautious.net <= 0:
        lines += ["", "어떤 창 크기에서도 압축 비용이 절감보다 컸습니다." if ko else
                  "At every window the compactions would have cost more than they saved."]
    else:
        lines += ["", (f"신중한 가정에서도 가장 나은 창: {best.window // 1000}k — 하루 압축 약 {best.compactions / days:.0f}번, "
                       f"순효과 {best_cautious.net / total:+.0%}~{best.net / total:+.0%} (주당 약 ${weekly:,.0f}, API 정가)"
                       if ko else
                       f"Best window that holds up under the cautious assumption: {best.window // 1000}k — about "
                       f"{best.compactions / days:.0f} compactions a day, net {best_cautious.net / total:+.0%} to "
                       f"{best.net / total:+.0%} (about ${weekly:,.0f} a week at list price)")]
    lines += [("비용만 잰 값입니다. 압축은 요약에서 빠진 세부를 잃게 하고, 창이 작을수록 자주 일어납니다. 작업 단위가 끝날 때 "
               "직접 /compact 하고, 창은 그걸 놓쳤을 때의 안전망으로 두는 편이 품질에 낫습니다. 설정: "
               "~/.claude/settings.json의 \"autoCompactWindow\" (100k~1M 토큰) 또는 CLAUDE_CODE_AUTO_COMPACT_WINDOW."
               if ko else
               "Cost only. A compaction loses what the summary leaves out, and a smaller window compacts more often. "
               "/compact at the end of a piece of work, with the window as the safety net for when you don't, keeps "
               "more. Setting: \"autoCompactWindow\" in ~/.claude/settings.json (100k-1M tokens) or "
               "CLAUDE_CODE_AUTO_COMPACT_WINDOW.")]
    return "\n".join(lines)


def run(projects: Path, days: int, lang: str) -> str:
    from .audit import analyze
    from .transcripts import main_session_files, read_sessions

    now = dt.datetime.now(dt.timezone.utc)
    since = now - dt.timedelta(days=days)
    sessions = read_sessions(projects, since)
    total_report = analyze(sessions, days)
    if not total_report.total:
        return "no usage found"
    paths = [path for path in main_session_files(projects) if path.stat().st_mtime >= since.timestamp()]
    return report(sessions, paths, lang, total_report.total, total_report.history_days or days)
