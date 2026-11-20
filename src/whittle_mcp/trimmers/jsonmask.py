"""JSON: keep the shape and every key path, shorten long arrays and long strings. The result is still valid JSON."""

from __future__ import annotations

import json
from typing import Any

from whittle_mcp.trimmers.base import Trim


def trim(text: str, max_items: int = 3, max_string: int = 120, max_depth: int = 6, handle: str | None = None, **_: object) -> Trim:
    docs = _parse(text)
    if docs is None:
        return Trim(text, changed=False, notes=["not valid JSON or JSON Lines, returned as is"])
    ref = f" (whittle expand {handle} path=" if handle else None

    def mask(value: Any, depth: int, path: str) -> Any:
        if isinstance(value, dict):
            if depth >= max_depth:
                return f"{{... {len(value)} keys}}"
            return {k: mask(v, depth + 1, f"{path}.{k}") for k, v in value.items()}
        if isinstance(value, list):
            if depth >= max_depth:
                return f"[... {len(value)} items]"
            picked = _pick(value, max_items)
            kept = [mask(value[i], depth + 1, f"{path}[{i}]") for i in picked]
            if len(value) > len(picked):
                more = f"... +{len(value) - len(picked)} more items"
                kept.append(more + (f"{ref}{path})" if ref else ""))
            return kept
        if isinstance(value, str) and len(value) > max_string:
            return value[:max_string] + f"... (+{len(value) - max_string} chars)"
        return value

    masked = [mask(d, 0, "$") for d in docs[0]]
    if docs[1]:   # JSON Lines: keep a few lines
        shown = masked[:max_items]
        parts = [json.dumps(m, separators=(",", ":"), ensure_ascii=False) for m in shown]
        if len(masked) > max_items:
            parts.append(f"... +{len(masked) - max_items} more lines")
        return Trim("\n".join(parts), omitted_lines=0)
    return Trim(json.dumps(masked[0], separators=(",", ":"), ensure_ascii=False))


def _paths(node: Any, prefix: str = "", depth: int = 0, out: set[str] | None = None) -> set[str]:
    out = set() if out is None else out
    if depth < 3 and isinstance(node, dict):
        for k, v in node.items():
            out.add(f"{prefix}.{k}")
            _paths(v, f"{prefix}.{k}", depth + 1, out)
    elif depth < 3 and isinstance(node, list):
        for v in node:
            _paths(v, f"{prefix}[]", depth + 1, out)
    return out


def _pick(items: list[Any], limit: int, extras: int = 3) -> list[int]:
    """The first `limit` items, plus up to `extras` later items that show keys the kept ones lack (so the shape stays complete)."""
    picked = list(range(min(limit, len(items))))
    if len(items) <= limit or not isinstance(items[0], dict):
        return picked
    seen: set[str] = set()
    for i in picked:
        _paths(items[i], "", 0, seen)
    for i in range(limit, len(items)):
        if len(picked) >= limit + extras:
            break
        if isinstance(items[i], dict):
            new = _paths(items[i], "", 0) - seen
            if new:
                picked.append(i)
                seen |= new
    return picked


def _parse(text: str) -> tuple[list[Any], bool] | None:
    try:
        return [json.loads(text)], False
    except ValueError:
        pass
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    try:
        return [json.loads(ln) for ln in lines], True
    except ValueError:
        return None


def subtree(text: str, path: str) -> str | None:
    """Return the part of a stored JSON document at a simple path such as $.items[3].user (used by `expand`)."""
    try:
        node: Any = json.loads(text)
    except ValueError:
        return None
    tokens = path.removeprefix("$").replace("[", ".[").split(".")
    for token in (t for t in tokens if t):
        try:
            if token.startswith("["):
                node = node[int(token.strip("[]"))]
            else:
                node = node[token]
        except (KeyError, IndexError, TypeError, ValueError):
            return None
    return json.dumps(node, separators=(",", ":"), ensure_ascii=False)
