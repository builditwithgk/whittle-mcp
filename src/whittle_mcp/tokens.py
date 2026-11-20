"""Token counting. Exact with tiktoken when it is installed and its data is available; otherwise a documented estimate."""

from __future__ import annotations

import math
from typing import Protocol


class TokenCounter(Protocol):
    name: str
    exact: bool

    def count(self, text: str) -> int: ...


class EstimateCounter:
    """About four characters per token. Good enough to compare before and after; labelled as an estimate everywhere."""

    name = "estimate:chars/4"
    exact = False

    def count(self, text: str) -> int:
        return math.ceil(len(text) / 4) if text else 0


class TiktokenCounter:
    exact = True

    def __init__(self, encoding: str = "o200k_base") -> None:
        import tiktoken  # may raise ImportError or fail to fetch its data offline

        self._enc = tiktoken.get_encoding(encoding)
        self.name = f"tiktoken:{encoding}"

    def count(self, text: str) -> int:
        return len(self._enc.encode(text, disallowed_special=())) if text else 0


def get_counter(prefer: str = "auto") -> TokenCounter:
    """`auto` tries tiktoken and falls back to the estimate; `estimate` forces the estimate (deterministic, no data download)."""
    if prefer != "estimate":
        try:
            return TiktokenCounter()
        except Exception:  # noqa: BLE001 - any failure (missing package, offline) falls back safely
            if prefer == "tiktoken":
                raise
    return EstimateCounter()
