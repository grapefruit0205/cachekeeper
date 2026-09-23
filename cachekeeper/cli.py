"""``cachekeeper audit``, ``keepalive``, ``compaction`` and ``events``."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .audit import CAUSES, run
from .guard import language
from .hook import data_dir

LABELS = {
    "ko": {
        "title": "cachekeeper 감사 — 최근 {days}일, 메인 세션 {sessions}개, 요청 {requests:,}개",
        "classes": "사용량 구성 (API 정가로 환산한 비중)",
        "cache read": "캐시 읽기", "cache write": "캐시 쓰기", "output": "출력", "uncached input": "캐시 안 된 입력",
        "rebuilds": "캐시 재구축 원인 (사용량 대비 비중)",
        "cause": "원인", "count": "횟수", "median": "중간 크기", "share": "비중",
        "session start": "세션 시작·재개", "model switch (manual)": "모델 전환 (직접)",
        "model switch (automatic)": "모델 전환 (자동)", "effort change": "effort 변경",
        "compaction": "압축", "idle expiry": "1시간 이상 쉼 (만료)", "other": "기타",
        "guard": "모델 전환 경고를 켰다면",
        "guard_line": "직접 한 전환 {switches}번 중 캐시가 살아 있고 재구축이 ${min_usd:g} 이상인 {asks}번에 물었을 것이고, "
                      "그중 {rebuilt}번은 실제로 재구축됐습니다 — 사용량의 {share:.1%}가 그 결정에 걸려 있었습니다.",
        "guard_other": "캐시가 이미 식은 뒤의 전환 {cold}번, 자동 전환 {auto}번은 대상이 아닙니다.",
        "keepalive": "55분 keep-alive를 켰다면 (1시간 TTL 세션, {cap:g}시간 한도)",
        "keepalive_line": "핑 {pings}번에 사용량의 {cost:.1%}를 쓰고, 만료 재구축 {saved_count}번(사용량의 {saved:.1%})을 막아 "
                          "순효과는 {net:+.1%}입니다.",
        "note": "비중은 API 정가로 환산한 값입니다. 구독 요금제의 사용량 계산 방식은 공개되어 있지 않습니다.",
        "span": "(이 컴퓨터의 기록은 {first}부터라서 실제로는 {history_days:g}일치입니다)",
        "pings_sent": "실제로 나간 keep-alive 핑: {pings}번, 사용량의 {share:.1%}",
    },
    "en": {
        "title": "cachekeeper audit — last {days} days, {sessions} main sessions, {requests:,} requests",
        "classes": "What the usage is made of (share, at list prices)",
        "cache read": "cache read", "cache write": "cache write", "output": "output", "uncached input": "uncached input",
        "rebuilds": "Why the cache was rebuilt (share of all usage)",
        "cause": "cause", "count": "count", "median": "median size", "share": "share",
        "session start": "session start/resume", "model switch (manual)": "model switch (manual)",
        "model switch (automatic)": "model switch (automatic)", "effort change": "effort change",
        "compaction": "compaction", "idle expiry": "idle past the TTL", "other": "other",
        "guard": "With the model-switch guard on",
        "guard_line": "Of {switches} manual switches, {asks} had a warm cache and a rebuild of at least ${min_usd:g}: "
                      "the guard would have asked; {rebuilt} of them did rebuild — {share:.1%} of all usage rode on those answers.",
        "guard_other": "Out of scope: {cold} switches after the cache had already expired, {auto} automatic switches.",
        "keepalive": "With a 55-minute keep-alive (one-hour TTL sessions, {cap:g}-hour cap)",
        "keepalive_line": "{pings} pings would cost {cost:.1%} of usage and prevent {saved_count} idle rebuilds "
                          "({saved:.1%}): net {net:+.1%}.",
        "note": "Shares are weighted at list prices; how a subscription counts usage is not published.",
        "span": "(history on this machine starts {first}: {history_days:g} days)",
        "pings_sent": "Keep-alive pings actually sent: {pings}, {share:.1%} of usage",
    },
}


def render(report_json: dict, lang: str, min_usd: float, cap_hours: float) -> str:
    t = LABELS[lang]
    lines = [t["title"].format(**report_json)]
    if report_json.get("first") and report_json["history_days"] < report_json["days"] - 1:
        lines.append(t["span"].format(**report_json))
    lines += ["", t["classes"]]
    for key, share in sorted(report_json["cost_share_by_class"].items(), key=lambda kv: -kv[1]):
        lines.append(f"  {t[key]:<18}{share:>7.1%}")
    lines += ["", t["rebuilds"], f"  {t['cause']:<24}{t['count']:>6}{t['median']:>14}{t['share']:>8}"]
    for cause in CAUSES:
        row = report_json["rebuilds"][cause]
        if row["count"]:
            lines.append(f"  {t[cause]:<24}{row['count']:>6}{row['tokens_median']:>14,}{row['cost_share']:>8.1%}")
    guard = report_json["guard"]
    lines += ["", t["guard"], "  " + t["guard_line"].format(
        switches=guard["net_manual_switches"], asks=guard["would_ask"], rebuilt=guard["asked_and_rebuilt"],
        share=guard["at_stake_share"], min_usd=min_usd),
        "  " + t["guard_other"].format(cold=guard["cold_manual_switches"], auto=guard["automatic_switches"])]
    keep = report_json["keepalive"]
    lines += ["", t["keepalive"].format(cap=cap_hours), "  " + t["keepalive_line"].format(
        pings=keep["pings"], cost=keep["cost_share"], saved_count=keep["prevented_rebuilds"],
        saved=keep["saved_share"], net=keep["net_share"])]
    if keep.get("pings_sent"):
        lines.append("  " + t["pings_sent"].format(pings=keep["pings_sent"], share=keep["pings_sent_share"]))
    lines += ["", t["note"]]
    return "\n".join(lines)


def events_summary(directory: Path, limit: int) -> str:
    path = directory / "events.jsonl"
    if not path.exists():
        return f"no events yet ({path})"
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    pre = [r for r in records if r.get("event") == "pre"]
    waits = [r for r in records if r.get("event") == "keepalive"]
    pings = [r for r in waits if r.get("decision") == "ping"]
    reasons: dict[str, int] = {}
    for r in waits:
        if r.get("decision") != "ping":
            reasons[str(r.get("reason"))] = reasons.get(str(r.get("reason")), 0) + 1
    post = [r for r in records if r.get("event") == "post" and r.get("source") != "resume"]
    asks = [r for r in pre if r.get("decision") == "ask"]
    lines = [
        f"events: {len(records)} ({path})",
        f"switch requests seen: {len(pre)}; asked: {len(asks)}; allowed on repeat: "
        f"{sum(r.get('decision') == 'allow' for r in pre)}; switches that happened: {len(post)} "
        f"(automatic: {sum(r.get('source') == 'auto' for r in post)}; resume restores not counted)",
        f"estimated rewrite behind the asks: ${sum(r.get('estimated_cache_write_usd') or 0 for r in asks):,.2f}",
        f"keep-alive: {len(pings)} pings in {len({r.get('session_id') for r in pings})} sessions; waits that stood down: "
        + (", ".join(f"{reason} {count}" for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1])) or "none"),
        "",
    ]
    for r in records[-limit:]:
        if r.get("event") == "keepalive":
            idle = r.get("idle_seconds")
            lines.append(f"keep {r.get('decision'):8} {r.get('reason') or '-':12} {r.get('context_tokens') or 0:>9,} tok  "
                         f"idle {'-' if idle is None else f'{idle / 60:.0f} min'}")
            continue
        lines.append(f"{r.get('event'):4} {r.get('decision'):8} {r.get('source') or '-':7} "
                     f"{r.get('from_model')} -> {r.get('to_model')}  {r.get('context_tokens', 0):>9,} tok  "
                     f"warm={r.get('prompt_cache_warm')}  ${r.get('estimated_cache_write_usd') or 0:,.2f}")
    return "\n".join(lines)


def keepalive_report(projects: Path, days: int, lang: str, directory: Path | None = None) -> str:
    """How idle stretches are distributed, which keep-alive policy would have paid off, and what auto mode uses."""
    import datetime as dt
    from .audit import CAPS_HOURS, GAP_BUCKETS, MIN_CONTEXTS, best_policy, idle_gaps, keepalive_policy
    from .autopolicy import MIN_STRETCHES, read_decision
    from .transcripts import read_sessions

    now = dt.datetime.now(dt.timezone.utc)
    sessions = read_sessions(projects, now - dt.timedelta(days=days))
    gaps, total = idle_gaps(sessions)
    if not total:
        return "no usage found"
    ko = lang == "ko"
    first = min(request.at for session in sessions for request in session.requests)
    span = (now - first).total_seconds() / 86_400
    lines = [(f"기록: {first.date().isoformat()}부터 {span:.0f}일치, 1시간 캐시 세션에서 55분 이상 쉰 구간 {len(gaps)}개"
              if ko else
              f"History: {span:.0f} days since {first.date().isoformat()}, {len(gaps)} idle stretches of 55 min or more "
              f"in one-hour-cache sessions"), "",
             ("쉬는 구간 분포" if ko else "Idle stretches"),
             f"  {'구간' if ko else 'length':<11}{'횟수' if ko else 'count':>7}{'재구축' if ko else 'rebuilt':>8}{'재구축 비중' if ko else 'rebuild share':>14}"]
    for low, high, label in GAP_BUCKETS:
        inside = [g for g in gaps if low <= g.seconds < high]
        rebuilt = [g for g in inside if g.rebuild_cost]
        lines.append(f"  {label:<11}{len(inside):>7}{len(rebuilt):>8}{sum(g.rebuild_cost for g in rebuilt) / total:>14.1%}")
    lines += ["", ("정책별 순효과 (핑 비용 − 막은 재구축, 사용량 대비)" if ko else "Net effect by policy (prevented rebuilds − ping cost, share of usage)"),
              f"  {'최소 맥락' if ko else 'min context':<12}" + "".join(f"{f'{c:g}h':>8}" for c in CAPS_HOURS)]
    for minimum in MIN_CONTEXTS:
        row = [keepalive_policy(gaps, cap, minimum)["net"] / total for cap in CAPS_HOURS]
        lines.append(f"  {f'{minimum // 1000}k':<12}" + "".join(f"{v:>+8.1%}" for v in row))
    best = best_policy(gaps)
    lines += ["", (f"가장 좋은 조합: 맥락 {best['min_context'] // 1000}k 이상인 세션만, 최대 {best['cap_hours']:g}시간 — "
                   f"핑 {best['pings']}번(사용량의 {best['cost'] / total:.1%})으로 재구축 {best['prevented']}번"
                   f"(사용량의 {best['saved'] / total:.1%})을 막아 순효과 {best['net'] / total:+.1%}"
                   if ko else
                   f"Best: sessions of at least {best['min_context'] // 1000}k tokens, up to {best['cap_hours']:g} h — "
                   f"{best['pings']} pings ({best['cost'] / total:.1%} of usage) prevent {best['prevented']} rebuilds "
                   f"({best['saved'] / total:.1%}): net {best['net'] / total:+.1%}")]
    if len(gaps) < MIN_STRETCHES:
        lines.append(f"쉬는 구간이 {MIN_STRETCHES}개보다 적어 이 추천은 우연에 좌우됩니다. auto 모드는 그동안 기본값(100k, 3시간)을 씁니다."
                     if ko else
                     f"Fewer than {MIN_STRETCHES} idle stretches: this pick rests on chance. Auto mode uses the defaults "
                     f"(100k, 3 h) until there are more.")
    elif best["net"] <= 0:
        lines.append("이 기록에서는 keep-alive가 이득이 아니었습니다. 끈 채로 두세요." if ko else
                     "On this history a keep-alive would not have paid off: leave it off.")
        return "\n".join(lines)
    lines += ["", ("켜는 법 (~/.claude/settings.json의 \"env\"):" if ko else "To turn it on (\"env\" in ~/.claude/settings.json):"),
              ('  "CACHEKEEPER_KEEPALIVE": "auto"   — 하루 한 번 최근 기록으로 이 계산을 다시 해서 적용' if ko else
               '  "CACHEKEEPER_KEEPALIVE": "auto"   — redo this every day on recent history and apply the best'),
              ('  또는 고정: ' if ko else '  or fixed: ') +
              f'"CACHEKEEPER_KEEPALIVE": "1", "CACHEKEEPER_KEEPALIVE_MIN_TOKENS": "{best["min_context"]}", '
              f'"CACHEKEEPER_KEEPALIVE_HOURS": "{best["cap_hours"]:g}"']
    decision = read_decision(directory) if directory is not None else None
    if decision:
        when = dt.datetime.fromtimestamp(float(decision.get("computed_at", 0))).strftime("%Y-%m-%d %H:%M")
        if decision.get("source") == "off":
            state = "꺼 둠" if ko else "off"
        else:
            state = (f"{int(decision.get('min_context', 0)) // 1000}k 이상, 최대 {float(decision.get('cap_hours', 0)):g}시간"
                     if ko else
                     f"at least {int(decision.get('min_context', 0)) // 1000}k tokens, up to {float(decision.get('cap_hours', 0)):g} h")
        lines += ["", (f"auto 모드가 지금 쓰는 정책: {state} ({decision.get('source')}: {decision.get('why')}, {when} 계산)"
                       if ko else
                       f"Auto mode currently uses: {state} ({decision.get('source')}: {decision.get('why')}, computed {when})")]
    return "\n".join(lines)


def events_dir() -> Path:
    """The hook's data directory: CLAUDE_PLUGIN_DATA when set (inside hooks), else the
    plugin data directory Claude Code gave this plugin, else ~/.cachekeeper."""
    if os.environ.get("CLAUDE_PLUGIN_DATA", "").strip():
        return data_dir()
    candidates = [p for p in (Path.home() / ".claude" / "plugins" / "data").glob("cachekeeper*") if (p / "events.jsonl").exists()]
    if candidates:
        return max(candidates, key=lambda p: (p / "events.jsonl").stat().st_mtime)
    return data_dir()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cachekeeper", description=__doc__)
    parser.add_argument("--version", action="version", version=f"cachekeeper {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    audit = commands.add_parser("audit", help="attribute cache rebuilds in your transcripts to their causes")
    audit.add_argument("--days", type=int, default=30)
    audit.add_argument("--projects", type=Path, default=Path.home() / ".claude" / "projects")
    audit.add_argument("--min-usd", type=float, default=float(os.environ.get("CACHEKEEPER_MIN_USD", 1.0)))
    audit.add_argument("--cap-hours", type=float, default=8.0)
    audit.add_argument("--lang", choices=("ko", "en"))
    audit.add_argument("--json", action="store_true")
    events = commands.add_parser("events", help="what the guard saw and answered")
    events.add_argument("--limit", type=int, default=20)
    compact = commands.add_parser("compaction", help="what an earlier auto-compaction would have saved and cost")
    compact.add_argument("--days", type=int, default=30)
    compact.add_argument("--projects", type=Path, default=Path.home() / ".claude" / "projects")
    compact.add_argument("--lang", choices=("ko", "en"))
    keep = commands.add_parser("keepalive", help="which keep-alive policy would have paid off on your history")
    keep.add_argument("--days", type=int, default=30)
    keep.add_argument("--projects", type=Path, default=Path.home() / ".claude" / "projects")
    keep.add_argument("--lang", choices=("ko", "en"))
    args = parser.parse_args(argv)

    if args.command == "compaction":
        from .compaction import run as compaction_run
        print(compaction_run(args.projects, args.days, args.lang or language(dict(os.environ))))
        return 0

    if args.command == "keepalive":
        print(keepalive_report(args.projects, args.days, args.lang or language(dict(os.environ)), events_dir()))
        return 0

    if args.command == "audit":
        report = run(args.projects, args.days, min_usd=args.min_usd, cap_hours=args.cap_hours).to_json()
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(render(report, args.lang or language(dict(os.environ)), args.min_usd, args.cap_hours))
        return 0
    if args.command == "events":
        print(events_summary(events_dir(), args.limit))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
