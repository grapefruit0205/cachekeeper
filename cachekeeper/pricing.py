"""Token prices, and the two yardsticks cachekeeper weighs usage with.

``Price`` holds a model's list prices per million tokens: cache reads bill at a fraction of the input price,
cache writes at 1.25x input (5-minute TTL) or 2x input (1-hour TTL), output at 5x input. Values follow the
Claude API price table; Claude Fable 5.1 and Claude Opus 5.5 carry their own cache-read rates.

A yardstick (``basis``) turns token counts into one amount that can be compared and summed:

* ``api``: what the API bills, at those list prices.
* ``subscription``: what a Claude subscription's usage limits count. The formula is not published; measured
  from outside, cache reads count about nothing, cache writes (either TTL) and uncached input count at the
  input list price, and output at the output list price. Sources: she-llac.com/claude-limits (January 2026,
  recovered from unrounded usage values: reads fit at 0.18% of the input price, 80% interval 0-0.5%) and the
  alldonesites.com usage tracker (four Max 20x accounts, to 2026-09-21: Fable 5.1 counts 2.11x Opus 5, near
  its 2x list ratio). That one-hour writes count at 1x input and that Opus 5.5 follows its list price are
  assumptions; neither has been measured. An amount on this yardstick is list-price dollars of the tokens the
  limits count: a share of it is a share of plan usage, not a bill.

Claude Code (2.1.280) gives the main conversation the one-hour cache by default only on a subscription within
its plan usage; an API key, and a subscription in extra usage (billed at API rates), get five minutes. So
``choose`` picks the yardstick from the cache TTL unless CACHEKEEPER_BASIS names one — as it should when
ENABLE_PROMPT_CACHING_1H or a prompt-cache-TTL setting breaks that link.
"""

from __future__ import annotations

from dataclasses import dataclass

BASES = ("subscription", "api")
# A cache read on the subscription yardstick, as a fraction of the input price: the pooled fit (0.18%, 80%
# interval 0-0.5%). Next to nothing per request, but the longest sessions read hundreds of millions of tokens.
SUBSCRIPTION_READ = 0.0018


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


@dataclass(frozen=True)
class Rates:
    """What one million tokens of each kind count for on one yardstick."""
    cache_read: float
    write_5m: float
    write_1h: float
    input: float
    output: float


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


def rates(price: Price, basis: str) -> Rates:
    if basis == "subscription":
        return Rates(price.input * SUBSCRIPTION_READ, price.input, price.input, price.input, price.output)
    return Rates(price.cache_read, price.write_5m, price.write_1h, price.input, price.output)


def rates_for(model: str | None, basis: str) -> Rates | None:
    price = price_for(model)
    return None if price is None else rates(price, basis)


def model_for_read_price(read_price: float) -> str:
    """The first model in the table with this cache-read price (records from before models were stored)."""
    for key, price in _TABLE:
        if abs(price.cache_read - read_price) < 1e-9:
            return key
    return ""


def setting(env: dict[str, str]) -> str:
    """CACHEKEEPER_BASIS: ``subscription``, ``api``, or ``auto`` (the default) for anything else."""
    value = env.get("CACHEKEEPER_BASIS", "").strip().lower()
    return value if value in BASES else "auto"


def choose(configured: str, one_hour: bool) -> str:
    """The yardstick: the configured one, else subscription for the one-hour cache and api for five minutes."""
    if configured in BASES:
        return configured
    return "subscription" if one_hour else "api"


def alias_for(model: str | None) -> str:
    """The short name a user types for a model: fable, opus, sonnet or haiku."""
    lowered = (model or "").lower()
    for alias in ("fable", "mythos", "opus", "sonnet", "haiku"):
        if alias in lowered:
            return alias
    return model or "?"
