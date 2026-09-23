"""``cachekeeper audit`` and ``cachekeeper events``."""

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
    },
}


def render(report_json: dict, lang: str, min_usd: float, cap_hours: float) -> str:
    t = LABELS[lang]
    lines = [t["title"].format(**report_json), "", t["classes"]]
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
        saved=keep["saved_share"], net=keep["net_share"]), "", t["note"]]
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
    post = [r for r in records if r.get("event") == "post" and r.get("source") != "resume"]
    asks = [r for r in pre if r.get("decision") == "ask"]
    lines = [
        f"events: {len(records)} ({path})",
        f"switch requests seen: {len(pre)}; asked: {len(asks)}; allowed on repeat: "
        f"{sum(r.get('decision') == 'allow' for r in pre)}; switches that happened: {len(post)} "
        f"(automatic: {sum(r.get('source') == 'auto' for r in post)}; resume restores not counted)",
        f"estimated rewrite behind the asks: ${sum(r.get('estimated_cache_write_usd') or 0 for r in asks):,.2f}",
        "",
    ]
    for r in records[-limit:]:
        lines.append(f"{r.get('event'):4} {r.get('decision'):8} {r.get('source') or '-':7} "
                     f"{r.get('from_model')} -> {r.get('to_model')}  {r.get('context_tokens', 0):>9,} tok  "
                     f"warm={r.get('prompt_cache_warm')}  ${r.get('estimated_cache_write_usd') or 0:,.2f}")
    return "\n".join(lines)


def keepalive_report(projects: Path, days: int, lang: str) -> str:
    """How idle stretches are distributed, and which keep-alive policy would have paid off."""
    import datetime as dt
    from .audit import GAP_BUCKETS, idle_gaps, keepalive_policy
    from .transcripts import read_sessions

    now = dt.datetime.now(dt.timezone.utc)
    gaps, total = idle_gaps(read_sessions(projects, now - dt.timedelta(days=days)))
    if not total:
        return "no usage found"
    ko = lang == "ko"
    lines = [("쉬는 구간 분포 (1시간 TTL 세션, 55분 이상)" if ko else "Idle stretches (one-hour TTL sessions, 55 min or more)"),
             f"  {'구간' if ko else 'length':<11}{'횟수' if ko else 'count':>7}{'재구축' if ko else 'rebuilt':>8}{'재구축 비중' if ko else 'rebuild share':>14}"]
    for low, high, label in GAP_BUCKETS:
        inside = [g for g in gaps if low <= g.seconds < high]
        rebuilt = [g for g in inside if g.rebuild_cost]
        lines.append(f"  {label:<11}{len(inside):>7}{len(rebuilt):>8}{sum(g.rebuild_cost for g in rebuilt) / total:>14.1%}")
    lines += ["", ("정책별 순효과 (핑 비용 − 막은 재구축, 사용량 대비)" if ko else "Net effect by policy (prevented rebuilds − ping cost, share of usage)"),
              f"  {'최소 맥락' if ko else 'min context':<12}" + "".join(f"{f'{c:g}h':>8}" for c in (1, 2, 3, 4, 6, 8, 12, 24))]
    best = None
    for minimum in (0, 100_000, 200_000, 300_000, 500_000):
        row = []
        for cap in (1, 2, 3, 4, 6, 8, 12, 24):
            policy = keepalive_policy(gaps, cap, minimum)
            row.append(policy["net"] / total)
            if best is None or policy["net"] > best["net"]:
                best = policy
        lines.append(f"  {f'{minimum // 1000}k':<12}" + "".join(f"{v:>+8.1%}" for v in row))
    assert best is not None
    lines += ["", (f"가장 좋은 조합: 맥락 {best['min_context'] // 1000}k 이상인 세션만, 최대 {best['cap_hours']:g}시간 — "
                   f"핑 {best['pings']}번(사용량의 {best['cost'] / total:.1%})으로 재구축 {best['prevented']}번"
                   f"(사용량의 {best['saved'] / total:.1%})을 막아 순효과 {best['net'] / total:+.1%}"
                   if ko else
                   f"Best: sessions of at least {best['min_context'] // 1000}k tokens, up to {best['cap_hours']:g} h — "
                   f"{best['pings']} pings ({best['cost'] / total:.1%} of usage) prevent {best['prevented']} rebuilds "
                   f"({best['saved'] / total:.1%}): net {best['net'] / total:+.1%}")]
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
    keep = commands.add_parser("keepalive", help="which keep-alive policy would have paid off on your history")
    keep.add_argument("--days", type=int, default=30)
    keep.add_argument("--projects", type=Path, default=Path.home() / ".claude" / "projects")
    keep.add_argument("--lang", choices=("ko", "en"))
    args = parser.parse_args(argv)

    if args.command == "keepalive":
        print(keepalive_report(args.projects, args.days, args.lang or language(dict(os.environ))))
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
