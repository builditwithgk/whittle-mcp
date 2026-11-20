"""The engine: run a trimmer, store the full input, count tokens before and after, and keep honest books."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from whittle_mcp.prices import Price, load_prices, saved_cost
from whittle_mcp.store import Store
from whittle_mcp.tokens import TokenCounter, get_counter
from whittle_mcp.trimmers import diffs, jsonmask, logs, openapi, tests
from whittle_mcp.trimmers.base import Trim

CR, LF, CRLF = chr(13), chr(10), chr(13) + chr(10)
_ANSI = re.compile(chr(27) + r"\[[0-9;?]*[ -/]*[@-~]")   # terminal colour and cursor codes cost tokens and carry no meaning
LINES = re.compile(r"^\d+(?:-\d+)?$")

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
        reasons = [n for n in self.notes if n != "unchanged"]
        if "unchanged" in self.notes and reasons:
            line += f" | unchanged: {reasons[0]}"
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
        text = _ANSI.sub("", text.replace(CRLF, LF).replace(CR, LF))   # CRLF, progress output and colour codes become plain text
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
                            "handle": result.handle, "counter": self.counter.name})
        return result

    def expand(self, handle: str, lines: str | None = None, path: str | None = None) -> str:
        """Give back what was omitted: a line range (`45-356`), a JSON path (`$.items`), or everything."""
        return self.expand_checked(handle, lines, path)[0]

    def expand_checked(self, handle: str, lines: str | None = None, path: str | None = None) -> tuple[str, bool]:
        """Like expand, but also says whether it worked (the CLI turns a failure into a non-zero exit code)."""
        text = self.store.get(handle)
        if text is None:
            return (f"No stored output for id {handle!r}. Stored text expires after 24 hours, the command-line tool and the MCP server "
                    "keep separate stores, and nothing is stored when it was trimmed with storage turned off."), False
        if lines and path:
            return "Give either lines or path, not both.", False
        out = text
        if lines:
            if not LINES.match(lines):
                return f"Bad lines value {lines!r}; use START-END, for example 45-356.", False
            start, _, end = lines.partition("-")
            first, last = int(start), int(end or start)
            if first < 1 or last < first:
                return f"Bad lines value {lines!r}; the range must start at 1 or more and not run backwards.", False
            total = len(text.splitlines())
            if first > total:
                return f"Lines {lines} are past the end: the stored output has {total} lines.", False
            out = self.store.lines(handle, first, last) or ""
        elif path:
            sub = jsonmask.subtree(text, path)
            if sub is None:
                return f"Path {path!r} not found in the stored JSON.", False
            out = sub
        self.events.append({"event": "expand", "handle": handle, "tokens": self.counter.count(out)})
        return out, True

    def report(self, prices: dict[str, Price] | None = None, later_turns: int = 10, cached: bool = True) -> dict[str, Any]:
        trims = [e for e in self.events if e["event"] == "trim"]
        raw = sum(e["raw"] for e in trims)
        out = sum(e["out"] for e in trims)
        expanded = sum(e["tokens"] for e in self.events if e["event"] == "expand")
        net = raw - out - expanded
        prices = prices if prices is not None else load_prices()
        cost = {name: round(saved_cost(raw, out + expanded, price, later_turns, cached), 6) for name, price in prices.items()}
        counters = sorted({e.get("counter", self.counter.name) for e in self.events})
        counter_name = counters[0] if len(counters) == 1 else "mixed (" + ", ".join(counters) + ")"
        return {"calls": len(trims), "raw_tokens": raw, "returned_tokens": out, "expanded_tokens": expanded,
                "gross_saved_tokens": raw - out, "net_saved_tokens": net,
                "net_saved_percent": round(100.0 * net / raw, 1) if raw else 0.0,
                "later_turns_assumed": later_turns, "cached_assumed": cached, "counter": counter_name,
                "saved_usd_at_example_prices": cost}
