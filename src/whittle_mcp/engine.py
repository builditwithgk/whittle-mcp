"""The engine: run a trimmer, store the full input, count tokens before and after, and keep honest books."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from whittle_mcp.prices import Price, load_prices, saved_cost
from whittle_mcp.store import Store
from whittle_mcp.tokens import TokenCounter, get_counter
from whittle_mcp.trimmers import diffs, jsonmask, logs, openapi, tests
from whittle_mcp.trimmers.base import Trim

TRIMMERS: dict[str, Callable[..., Trim]] = {
    "tests": tests.trim, "log": logs.trim, "json": jsonmask.trim, "diff": diffs.trim, "openapi": openapi.trim,
}


@dataclass
class Result:
    kind: str
    text: str                 # what the agent should read
    raw_tokens: int
    out_tokens: int
    handle: str | None
    omitted_lines: int
    notes: list[str] = field(default_factory=list)
    counter: str = ""

    @property
    def saved(self) -> int:
        return self.raw_tokens - self.out_tokens

    @property
    def percent(self) -> float:
        return 100.0 * self.saved / self.raw_tokens if self.raw_tokens else 0.0

    def receipt(self) -> str:
        line = f"[whittle {self.kind}] {self.raw_tokens:,} -> {self.out_tokens:,} tokens ({-self.percent:.1f}%)"
        if self.handle and self.omitted_lines:
            line += f" | full output: whittle expand {self.handle}"
        return line + f" | counter: {self.counter}"

    def render(self, receipt: bool = True) -> str:
        return f"{self.text}\n{self.receipt()}" if receipt else self.text


class Whittle:
    def __init__(self, counter: TokenCounter | None = None, store: Store | None = None) -> None:
        self.counter = counter or get_counter()
        self.store = store or Store()
        self.events: list[dict[str, Any]] = []

    def trim(self, kind: str, text: str, keep_original: bool = True, **options: Any) -> Result:
        if kind not in TRIMMERS:
            raise ValueError(f"unknown kind {kind!r}; choose one of {', '.join(TRIMMERS)}")
        raw_tokens = self.counter.count(text)
        handle = self.store.put(text) if keep_original and text else None
        trimmed = TRIMMERS[kind](text, handle=handle, **options)
        out_tokens = self.counter.count(trimmed.text)
        # Never make things worse: if trimming did not shrink the text, hand the original back.
        if not trimmed.changed or out_tokens >= raw_tokens:
            result = Result(kind, text, raw_tokens, raw_tokens, None, 0, trimmed.notes + ["unchanged"], self.counter.name)
        else:
            result = Result(kind, trimmed.text, raw_tokens, out_tokens, handle, trimmed.omitted_lines, trimmed.notes,
                            self.counter.name)
        self.events.append({"event": "trim", "kind": kind, "raw": result.raw_tokens, "out": result.out_tokens,
                            "handle": result.handle})
        return result

    def expand(self, handle: str, lines: str | None = None, path: str | None = None) -> str:
        """Give back what was omitted: a line range (`45-356`), a JSON path (`$.items`), or everything."""
        text = self.store.get(handle)
        if text is None:
            return f"No stored output for id {handle!r}. It may have expired, or was created with storage turned off."
        out = text
        if lines:
            try:
                start, _, end = lines.partition("-")
                out = self.store.lines(handle, int(start), int(end or start)) or ""
            except ValueError:
                return f"Bad lines value {lines!r}; use START-END, for example 45-356."
        elif path:
            sub = jsonmask.subtree(text, path)
            out = sub if sub is not None else f"Path {path!r} not found in the stored JSON."
        self.events.append({"event": "expand", "handle": handle, "tokens": self.counter.count(out)})
        return out

    def report(self, prices: dict[str, Price] | None = None, later_turns: int = 10, cached: bool = True) -> dict[str, Any]:
        trims = [e for e in self.events if e["event"] == "trim"]
        raw = sum(e["raw"] for e in trims)
        out = sum(e["out"] for e in trims)
        expanded = sum(e["tokens"] for e in self.events if e["event"] == "expand")
        net = raw - out - expanded
        prices = prices if prices is not None else load_prices()
        cost = {name: round(saved_cost(raw, out + expanded, price, later_turns, cached), 6) for name, price in prices.items()}
        return {"calls": len(trims), "raw_tokens": raw, "returned_tokens": out, "expanded_tokens": expanded,
                "gross_saved_tokens": raw - out, "net_saved_tokens": net,
                "net_saved_percent": round(100.0 * net / raw, 1) if raw else 0.0,
                "later_turns_assumed": later_turns, "cached_assumed": cached, "counter": self.counter.name,
                "saved_usd_at_example_prices": cost}
