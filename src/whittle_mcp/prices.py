"""A price table you edit yourself, and the cost model that turns tokens saved into money saved.

The default numbers are EXAMPLES, not any provider's real prices. Provider prices change; put your own in a JSON file and pass it
with --prices. The tokens-saved figures never depend on this file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

EXAMPLE_PRICES = {
    "_note": "EXAMPLE VALUES ONLY. Replace with your provider's current prices (USD per million tokens) before trusting any dollar figure.",
    "example-small": {"input": 0.20, "cache_write": 0.25, "cache_read": 0.02},
    "example-mid": {"input": 2.00, "cache_write": 2.50, "cache_read": 0.20},
    "example-large": {"input": 5.00, "cache_write": 6.25, "cache_read": 0.50},
}


@dataclass(frozen=True)
class Price:
    name: str
    input: float        # USD per million input tokens
    cache_write: float  # USD per million tokens written to the cache
    cache_read: float   # USD per million tokens read from the cache


def load_prices(path: str | Path | None = None) -> dict[str, Price]:
    data = EXAMPLE_PRICES if path is None else json.loads(Path(path).read_text(encoding="utf-8"))
    prices: dict[str, Price] = {}
    for name, row in data.items():
        if name.startswith("_") or not isinstance(row, dict):
            continue
        base = float(row["input"])
        write = float(row["cache_write"]) if "cache_write" in row else base
        read = float(row["cache_read"]) if "cache_read" in row else base
        prices[name] = Price(name, base, write, read)
    return prices


def input_cost(tokens: int, price: Price, later_turns: int, cached: bool) -> float:
    """Cost of putting `tokens` into the context once and keeping them there for `later_turns` more turns.

    Cached: written once, then read from the cache on each later turn.  Not cached: paid in full on every turn.
    """
    if cached:
        return tokens * (price.cache_write + later_turns * price.cache_read) / 1_000_000
    return tokens * (1 + later_turns) * price.input / 1_000_000


def saved_cost(raw_tokens: int, kept_tokens: int, price: Price, later_turns: int = 10, cached: bool = True) -> float:
    return input_cost(raw_tokens, price, later_turns, cached) - input_cost(kept_tokens, price, later_turns, cached)
