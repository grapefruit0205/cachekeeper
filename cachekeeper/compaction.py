"""What an earlier auto-compaction would have cost and saved, replayed on the local history.

Every request re-reads the whole conversation from the cache, so a long session pays for its length on every
turn. Claude Code compacts automatically when the context approaches the auto-compact window (the
``autoCompactWindow`` setting or ``CLAUDE_CODE_AUTO_COMPACT_WINDOW``, 100k-1M tokens; by default close to the
model's whole window, 1M for the current models). ``replay`` asks, for a smaller window: how much less would
the requests have re-read, and what would the extra compactions have cost?

Each session is replayed request by request. The simulated context grows by what the real one grew by; when
it would pass the window, a compaction happens first:

* the compaction request reads the context from the cache and writes a summary (``SUMMARY_TOKENS`` of output;
  Claude Code 2.1.280 runs it on the conversation's own cache and writes nothing to it);
* the conversation continues from ``after`` tokens — by default the median size right after the real
  compactions in this history — of which the first request writes ``written`` (the system prompt and tools
  stay cached), plus ``REREAD_TOKENS`` the model reads again (files, errors) because the summary lost them;
* every later request reads the smaller context, and a rebuild (after a break or a model switch) rewrites
  the smaller context.

On the subscription yardstick cache reads count next to nothing, so a smaller window saves mostly through smaller
rebuilds, and the compaction costs its summary and what it writes; on API list prices the reads saved dominate.

What the replay cannot see is quality: a summary loses details, and whether that costs more than a long
context does is a question about the work, not the bill. ``REREAD_TOKENS`` prices only the obvious part.
"""

from __future__ import annotations

import datetime as dt
import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from .audit import analyze, basis_of, is_rebuild, request_cost
from .pricing import price_for, rates
from .transcripts import Session

WINDOWS = (200_000, 300_000, 400_000, 500_000, 600_000, 800_000)
# Measured on the author's 15 real compactions (at 900k+, 2026-09-23), against stretches without one:
SUMMARY_TOKENS = 5_300       # output of one compaction: the summary and the thinking around it
REREAD_TOKENS = 14_000       # files read again after it that had been read before it (medians, next 50 requests)
CAUTIOUS_REREAD = 45_000     # all the extra context growth after it: an upper bound, for the second net column
CAUTIOUS_SUMMARY = 15_000    # assumed: a summary three times the measured one
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


def measured_restart(paths: list[Path]) -> tuple[int, int] | None:
    """Medians over the real compactions in these transcripts: the context of the first request after each,
    and what that request wrote to the cache (with its uncached input)."""
    sizes: dict[str, tuple[int, int]] = {}
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
                        written = sum(int(usage.get(key) or 0) for key in ("input_tokens", "cache_creation_input_tokens"))
                        size = written + int(usage.get("cache_read_input_tokens") or 0)
                        if size:
                            sizes[waiting] = (size, written)     # a resumed copy of the same boundary counts once
                        waiting = None
    if not sizes:
        return None
    return (int(statistics.median(size for size, _ in sizes.values())),
            int(statistics.median(written for _, written in sizes.values())))


def measured_after(paths: list[Path]) -> int | None:
    """Median context of the first request after each real compaction in these transcripts."""
    restart = measured_restart(paths)
    return restart[0] if restart else None


def replay(sessions: list[Session], window: int, after: int, reread: int = REREAD_TOKENS, basis: str = "api",
           written: int | None = None, summary: int = SUMMARY_TOKENS) -> Outcome:
    outcome = Outcome(window)
    restart = after + reread
    fresh = (after if written is None else written) + reread
    for session in sessions:
        simulated: int | None = None
        previous_context = 0
        for request in session.requests:
            price = price_for(request.model)
            if price is None:
                continue
            rate = rates(price, basis)
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
                    write = rate.write_1h if session.ttl_seconds >= 3600 else rate.write_5m
                    outcome.compaction_cost += (simulated * rate.cache_read + summary * rate.output
                                                + fresh * write) / 1_000_000
                    grown = restart + context - previous_context
                simulated = grown
            previous_context = context
            if simulated >= context:
                continue
            shorter = context - simulated
            if is_rebuild(request):
                outcome.rebuild_saved += request_cost(request, basis)["cache write"] * shorter / context
            else:
                outcome.read_saved += min(request.cache_read, shorter) * rate.cache_read / 1_000_000
    return outcome


def report(sessions: list[Session], paths: list[Path], lang: str, total: float, days: float,
           basis: str = "api") -> str:
    restart = measured_restart(paths)
    measured = restart is not None
    after, written = restart or (DEFAULT_AFTER, DEFAULT_AFTER)
    ko = lang == "ko"
    subscription = basis == "subscription"
    rows = [(replay(sessions, window, after, REREAD_TOKENS, basis, written, SUMMARY_TOKENS),
             replay(sessions, window, after, CAUTIOUS_REREAD, basis, written, CAUTIOUS_SUMMARY)) for window in WINDOWS]
    lines = [(f"자동 압축 재현 — 기록 {days:.0f}일치, 메인 세션 {len(sessions)}개, "
              f"{'구독 사용량' if subscription else 'API 정가'} 기준. 압축 뒤 맥락 {after / 1000:.0f}k 토큰 중 "
              f"{written / 1000:.0f}k를 새로 씀({'실제 압축들의 중간값' if measured else '기본값'}) + 다시 읽기 "
              f"{REREAD_TOKENS // 1000}k, 요약 출력 {SUMMARY_TOKENS / 1000:.1f}k로 가정. 마지막 열은 다시 읽기 "
              f"{CAUTIOUS_REREAD // 1000}k, 요약 {CAUTIOUS_SUMMARY // 1000}k로 잡았을 때"
              if ko else
              f"Auto-compaction replay — {days:.0f} days of history, {len(sessions)} main sessions, on "
              f"{'subscription usage' if subscription else 'API list prices'}. Context after a compaction: "
              f"{after / 1000:.0f}k tokens, {written / 1000:.0f}k of them written anew "
              f"({'medians of the real ones' if measured else 'default'}) + {REREAD_TOKENS // 1000}k read again; "
              f"{SUMMARY_TOKENS / 1000:.1f}k of summary output. The last column assumes "
              f"{CAUTIOUS_REREAD // 1000}k read again and a {CAUTIOUS_SUMMARY // 1000}k summary"), "",
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
        unit = (("구독 사용량" if subscription else "API 정가") if ko else
                ("of subscription usage" if subscription else "at list price"))
        lines += ["", (f"신중한 가정에서도 가장 나은 창: {best.window // 1000}k — 하루 압축 약 {best.compactions / days:.0f}번, "
                       f"순효과 {best_cautious.net / total:+.0%}~{best.net / total:+.0%} (주당 약 ${weekly:,.0f}, {unit})"
                       if ko else
                       f"Best window that holds up under the cautious assumption: {best.window // 1000}k — about "
                       f"{best.compactions / days:.0f} compactions a day, net {best_cautious.net / total:+.0%} to "
                       f"{best.net / total:+.0%} (about ${weekly:,.0f} a week {unit})")]
    lines += [("비용만 잰 값입니다. 압축은 요약에서 빠진 세부를 잃게 하고, 창이 작을수록 자주 일어납니다. 작업 단위가 끝날 때 "
               "직접 /compact 하고, 창은 그걸 놓쳤을 때의 안전망으로 두는 편이 품질에 낫습니다. 설정: "
               "~/.claude/settings.json의 \"autoCompactWindow\" (100k~1M 토큰) 또는 CLAUDE_CODE_AUTO_COMPACT_WINDOW."
               if ko else
               "Cost only. A compaction loses what the summary leaves out, and a smaller window compacts more often. "
               "/compact at the end of a piece of work, with the window as the safety net for when you don't, keeps "
               "more. Setting: \"autoCompactWindow\" in ~/.claude/settings.json (100k-1M tokens) or "
               "CLAUDE_CODE_AUTO_COMPACT_WINDOW.")]
    return "\n".join(lines)


def run(projects: Path, days: int, lang: str, basis: str = "auto") -> str:
    from .transcripts import main_session_files, read_sessions

    now = dt.datetime.now(dt.timezone.utc)
    since = now - dt.timedelta(days=days)
    sessions = read_sessions(projects, since)
    chosen = basis_of(sessions, basis)
    summary = analyze(sessions, days, basis=chosen)
    if not summary.total:
        return "no usage found"
    paths = [path for path in main_session_files(projects) if path.stat().st_mtime >= since.timestamp()]
    return report(sessions, paths, lang, summary.total, summary.history_days or days, chosen)
