"""Where the main conversation's cache spend goes, and what each remedy would reach.

A request "rebuilt" its cache when it wrote at least ``REBUILD_MIN_TOKENS`` and
at least half of what it sent. Each rebuild is attributed to the first cause
that explains it, in this order:

1. ``session start``   no earlier request in this transcript (a new or resumed session)
2. ``model switch``    the model differs from the previous request's; ``/model``
                       in between makes it manual, otherwise automatic (fallback, resume)
3. ``effort change``   both requests record an effort level and they differ
4. ``compaction``      a compaction boundary lies between the two requests
5. ``idle expiry``     the gap reached the session's cache TTL
6. ``other``           tool definitions, system prompt, images, upgrades — not visible here

Two replays read the same history:

* the guard: every net manual switch with a warm cache whose rebuild would cost
  at least ``min_usd`` is a switch the guard would have asked about;
* a keep-alive ping every 55 minutes of idleness (one-hour TTL sessions only,
  capped at ``cap_hours``): what the pings cost against the idle rebuilds they
  would have prevented.
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from .pricing import price_for
from .transcripts import Request, Session, read_sessions

REBUILD_MIN_TOKENS = 50_000
PING_SECONDS = 55 * 60
CAPS_HOURS = (1, 2, 3, 4, 6, 8, 12, 24)
MIN_CONTEXTS = (0, 100_000, 200_000, 300_000, 500_000)
CAUSES = ("session start", "model switch (manual)", "model switch (automatic)", "effort change",
          "compaction", "idle expiry", "other")


def write_cost(request: Request) -> float:
    price = price_for(request.model)
    if price is None:
        return 0.0
    return (request.write_5m * price.write_5m + request.write_1h * price.write_1h) / 1_000_000


def request_cost(request: Request) -> dict[str, float]:
    price = price_for(request.model)
    if price is None:
        return {}
    return {
        "cache read": request.cache_read * price.cache_read / 1_000_000,
        "cache write": write_cost(request),
        "output": request.output * price.output / 1_000_000,
        "uncached input": request.input * price.input / 1_000_000,
    }


def is_rebuild(request: Request) -> bool:
    return request.writes >= REBUILD_MIN_TOKENS and request.writes >= 0.5 * request.context


@dataclass
class Report:
    days: int
    sessions: int = 0
    requests: int = 0
    cost_by_class: dict[str, float] = field(default_factory=dict)
    rebuilds: dict[str, list[tuple[int, float]]] = field(default_factory=lambda: {c: [] for c in CAUSES})
    guard_switches: int = 0
    guard_asks: int = 0
    guard_asks_rebuilt: int = 0
    guard_usd: float = 0.0
    cold_switches: int = 0
    automatic_switches: int = 0
    keepalive_pings: int = 0
    keepalive_cost: float = 0.0
    keepalive_saved: float = 0.0
    keepalive_saved_count: int = 0
    first_at: dt.datetime | None = None
    last_at: dt.datetime | None = None
    pings_sent: int = 0          # keep-alive pings that actually ran
    pings_cost: float = 0.0

    @property
    def history_days(self) -> float:
        """How many days the history actually spans (it can be shorter than the window asked for)."""
        if self.first_at is None or self.last_at is None:
            return 0.0
        return (self.last_at - self.first_at).total_seconds() / 86_400

    @property
    def total(self) -> float:
        return sum(self.cost_by_class.values())

    def to_json(self) -> dict:
        causes = {
            cause: {
                "count": len(items),
                "tokens_median": int(statistics.median([t for t, _ in items])) if items else 0,
                "cost_share": (sum(c for _, c in items) / self.total) if self.total else 0.0,
            }
            for cause, items in self.rebuilds.items()
        }
        return {
            "days": self.days,
            "history_days": round(self.history_days, 1),
            "first": self.first_at.date().isoformat() if self.first_at else None,
            "sessions": self.sessions,
            "requests": self.requests,
            "cost_share_by_class": {k: (v / self.total if self.total else 0.0) for k, v in self.cost_by_class.items()},
            "rebuilds": causes,
            "guard": {
                "net_manual_switches": self.guard_switches,
                "would_ask": self.guard_asks,
                "asked_and_rebuilt": self.guard_asks_rebuilt,
                "at_stake_share": self.guard_usd / self.total if self.total else 0.0,
                "cold_manual_switches": self.cold_switches,
                "automatic_switches": self.automatic_switches,
            },
            "keepalive": {
                "pings": self.keepalive_pings,
                "cost_share": self.keepalive_cost / self.total if self.total else 0.0,
                "prevented_rebuilds": self.keepalive_saved_count,
                "saved_share": self.keepalive_saved / self.total if self.total else 0.0,
                "net_share": (self.keepalive_saved - self.keepalive_cost) / self.total if self.total else 0.0,
                "pings_sent": self.pings_sent,
                "pings_sent_share": self.pings_cost / self.total if self.total else 0.0,
            },
        }


def classify(previous: Request | None, request: Request, session: Session) -> str:
    if previous is None:
        return "session start"
    between = [m for m in session.markers if previous.at < m.at <= request.at]
    if request.model != previous.model:
        manual = any(m.kind == "model_command" for m in between)
        return "model switch (manual)" if manual else "model switch (automatic)"
    if request.effort and previous.effort and request.effort != previous.effort:
        return "effort change"
    if any(m.kind == "compact" for m in between):
        return "compaction"
    if (request.at - previous.at).total_seconds() >= session.ttl_seconds:
        return "idle expiry"
    return "other"


def analyze(sessions: list[Session], days: int, min_usd: float = 1.0, cap_hours: float = 8.0) -> Report:
    report = Report(days=days, sessions=len(sessions))
    for session in sessions:
        ttl = session.ttl_seconds
        previous: Request | None = None
        pinged = False
        for request in session.requests:
            if price_for(request.model) is None:
                continue
            report.requests += 1
            report.first_at = min(report.first_at or request.at, request.at)
            report.last_at = max(report.last_at or request.at, request.at)
            for key, value in request_cost(request).items():
                report.cost_by_class[key] = report.cost_by_class.get(key, 0.0) + value
            if request.ping:
                # Usage like any other, but not the user: the replays measure the user's breaks around it.
                report.pings_sent += 1
                report.pings_cost += sum(request_cost(request).values())
                pinged = True
                continue
            rebuilt = is_rebuild(request)
            cause = classify(previous, request, session)
            if rebuilt:
                report.rebuilds[cause].append((request.writes, write_cost(request)))
            if previous is not None:
                _replay_guard(report, previous, request, session, ttl, rebuilt, min_usd)
                _replay_keepalive(report, previous, request, ttl, idle_rebuild_cost(previous, request, session, pinged),
                                  cap_hours)
            previous, pinged = request, False
    return report


def idle_rebuild_cost(previous: Request, request: Request, session: Session, pinged: bool) -> float:
    """What the break before ``request`` cost in cache writes.

    The idle rebuild the request actually made; or, when keep-alive pings kept the cache through a break
    longer than its TTL, the rebuild they prevented, estimated as the whole conversation written at the
    one-hour rate, as an idle rebuild does; else nothing.
    """
    if is_rebuild(request) and classify(previous, request, session) == "idle expiry":
        return write_cost(request)
    price = price_for(previous.model)
    seconds = (request.at - previous.at).total_seconds()
    if pinged and price is not None and seconds >= session.ttl_seconds and request.model == previous.model:
        return previous.next_context * price.write_1h / 1_000_000
    return 0.0


def _replay_guard(report: Report, previous: Request, request: Request, session: Session,
                  ttl: int, rebuilt: bool, min_usd: float) -> None:
    if request.model == previous.model:
        return
    commands = [m for m in session.markers if m.kind == "model_command" and previous.at < m.at <= request.at]
    if not commands:
        report.automatic_switches += 1
        return
    report.guard_switches += 1
    warm = (commands[0].at - previous.at).total_seconds() < ttl
    if not warm:
        report.cold_switches += 1
        return
    price = price_for(request.model)
    rate = (price.write_1h if ttl >= 3600 else price.write_5m) if price else 0.0
    estimate = previous.next_context * rate / 1_000_000
    if estimate >= min_usd:
        report.guard_asks += 1
        if rebuilt:
            report.guard_asks_rebuilt += 1
            report.guard_usd += write_cost(request)


def _replay_keepalive(report: Report, previous: Request, request: Request, ttl: int,
                      rebuild_cost: float, cap_hours: float) -> None:
    if ttl < 3600:
        return
    gap = (request.at - previous.at).total_seconds()
    if gap < PING_SECONDS:
        return
    cap = cap_hours * 3600
    pings = int(min(gap, cap) // PING_SECONDS)
    price = price_for(previous.model)
    if price is None or pings == 0:
        return
    report.keepalive_pings += pings
    report.keepalive_cost += pings * previous.next_context * price.cache_read / 1_000_000
    # The last ping keeps the cache for one more TTL; past that the rebuild happens anyway.
    if rebuild_cost and gap < pings * PING_SECONDS + ttl:
        report.keepalive_saved += rebuild_cost
        report.keepalive_saved_count += 1


@dataclass
class Gap:
    """An idle stretch of at least one ping interval in a one-hour-TTL session."""
    seconds: float
    context: int          # what the next request re-sends
    read_price: float     # $/MTok to re-read it once
    rebuild_cost: float   # what the next request wrote because of the gap (0 when it did not rebuild)
    at: float = 0.0       # when it began (epoch seconds)
    session: str = ""     # the transcript it is in


GAP_BUCKETS = ((55 * 60, 3600, "55-60 min"), (3600, 2 * 3600, "1-2 h"), (2 * 3600, 4 * 3600, "2-4 h"),
               (4 * 3600, 8 * 3600, "4-8 h"), (8 * 3600, 24 * 3600, "8-24 h"), (24 * 3600, float("inf"), "24 h+"))


def idle_gaps(sessions: list[Session]) -> tuple[list[Gap], float]:
    """Every idle stretch a keep-alive could have covered, and the total usage cost for shares.

    Keep-alive pings are skipped: a stretch runs from one request of the user's to the next, and when pings
    kept the cache through it, ``idle_rebuild_cost`` supplies the rebuild they prevented. Otherwise a policy
    replayed on a history its own pings shaped would see only short breaks that never rebuilt, and turn off.
    """
    gaps: list[Gap] = []
    total = 0.0
    for session in sessions:
        previous: Request | None = None
        pinged = False
        for request in session.requests:
            if price_for(request.model) is None:
                continue
            total += sum(request_cost(request).values())
            if request.ping:
                pinged = True
                continue
            if previous is not None and session.ttl_seconds >= 3600:
                seconds = (request.at - previous.at).total_seconds()
                price = price_for(previous.model)
                if seconds >= PING_SECONDS and price is not None:
                    gaps.append(Gap(seconds, previous.next_context, price.cache_read,
                                    idle_rebuild_cost(previous, request, session, pinged),
                                    previous.at.timestamp(), session.path.stem))
            previous, pinged = request, False
    return gaps, total


def keepalive_policy(gaps: list[Gap], cap_hours: float, min_context: int) -> dict[str, float]:
    """Ping every 55 idle minutes up to ``cap_hours``, only when the context is at least ``min_context``."""
    cost = saved = 0.0
    pings = prevented = 0
    for gap in gaps:
        if gap.context < min_context:
            continue
        count = int(min(gap.seconds, cap_hours * 3600) // PING_SECONDS)
        pings += count
        cost += count * gap.context * gap.read_price / 1_000_000
        if gap.rebuild_cost and gap.seconds < count * PING_SECONDS + 3600:
            saved += gap.rebuild_cost
            prevented += 1
    return {"cap_hours": cap_hours, "min_context": min_context, "pings": pings, "cost": cost,
            "saved": saved, "prevented": prevented, "net": saved - cost}


def best_policy(gaps: list[Gap], tolerance: float = 0.01) -> dict[str, float]:
    """The combination of minimum context and cap to use.

    The largest net saving, except that among the combinations within ``tolerance`` of it the one with the
    fewest pings wins, then the larger minimum context: a few weeks of history cannot tell such near-ties
    apart, and every ping is a turn the user sees.
    """
    policies = [keepalive_policy(gaps, cap, minimum) for minimum in MIN_CONTEXTS for cap in CAPS_HOURS]
    top = max(policy["net"] for policy in policies)
    near = [policy for policy in policies if policy["net"] >= top - abs(top) * tolerance]
    return min(near, key=lambda policy: (policy["pings"], -policy["min_context"], -policy["net"]))


def run(projects: Path, days: int, min_usd: float = 1.0, cap_hours: float = 8.0,
        now: dt.datetime | None = None) -> Report:
    now = now or dt.datetime.now(dt.timezone.utc)
    sessions = read_sessions(projects, now - dt.timedelta(days=days))
    return analyze(sessions, days, min_usd=min_usd, cap_hours=cap_hours)
