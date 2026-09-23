"""List prices per million tokens, used only to weigh token classes against each other.

Cache reads bill at a fraction of the input price, cache writes at 1.25x input
(5-minute TTL) or 2x input (1-hour TTL), output at 5x input. Values follow the
Claude API price table; Claude Fable 5.1 and Claude Opus 5.5 carry their own
cache-read rates. A subscription does not bill these amounts: they are a common
yardstick for "which part of my usage is this", not a bill.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_read: float

    @property
    def write_5m(self) -> float:
        return self.input * 1.25

    @property
    def write_1h(self) -> float:
        return self.input * 2.0


# Ordered: the first substring that matches a model id wins, so the more
# specific ids come first.
_TABLE: tuple[tuple[str, Price], ...] = (
    ("fable-5-1", Price(10.0, 50.0, 0.25)),
    ("mythos-5-1", Price(10.0, 50.0, 0.25)),
    ("fable-5", Price(10.0, 50.0, 1.0)),
    ("mythos-5", Price(10.0, 50.0, 1.0)),
    ("opus-5-5", Price(4.0, 20.0, 0.20)),
    ("opus-5", Price(5.0, 25.0, 0.50)),
    ("opus-4-8", Price(5.0, 25.0, 0.50)),
    ("opus-4-7", Price(5.0, 25.0, 0.50)),
    ("opus-4-6", Price(5.0, 25.0, 0.50)),
    ("sonnet-5", Price(2.0, 10.0, 0.20)),
    ("sonnet-4-6", Price(3.0, 15.0, 0.30)),
    ("haiku-4-5", Price(1.0, 5.0, 0.10)),
)


def price_for(model: str | None) -> Price | None:
    """The list price of a Claude model id, or None for anything else."""
    if not model:
        return None
    lowered = model.lower()
    for key, price in _TABLE:
        if key in lowered:
            return price
    return None


def alias_for(model: str | None) -> str:
    """The short name a user types for a model: fable, opus, sonnet or haiku."""
    lowered = (model or "").lower()
    for alias in ("fable", "mythos", "opus", "sonnet", "haiku"):
        if alias in lowered:
            return alias
    return model or "?"
