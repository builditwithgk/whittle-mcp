"""JSON: keep the shape and every key path, shorten long arrays and long strings. Numbers and duplicate keys are kept exactly as written."""

from __future__ import annotations

import json
from typing import Any

from whittle_mcp.trimmers.base import Trim


class Raw:
    """A number (or Infinity/NaN) kept exactly as it was written, so 1e400 or a 30-digit integer is never rewritten."""

    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text


class Obj(list):
    """A JSON object as a list of (key, value) pairs: keeps the order and any duplicate keys."""


def _loads(text: str) -> Any:
    return json.loads(text, parse_float=Raw, parse_int=Raw, parse_constant=Raw, object_pairs_hook=Obj)


def _dump(value: Any) -> str:
    if isinstance(value, Obj):
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + _dump(v) for k, v in value) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_dump(v) for v in value) + "]"
    if isinstance(value, Raw):
        return value.text
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    return json.dumps(value, ensure_ascii=False)


def trim(text: str, max_items: int = 3, max_string: int = 120, max_depth: int = 6, handle: str | None = None, **_: object) -> Trim:
    try:
        parsed = _parse(text)
    except RecursionError:
        return Trim(text, changed=False, notes=["JSON is nested too deeply to process, returned as is"])
    if parsed is None:
        return Trim(text, changed=False, notes=["not valid JSON or JSON Lines, returned as is"])
    docs, is_lines = parsed
    ref = f" (whittle expand {handle} path=" if handle else None

    def mask(value: Any, depth: int, path: str) -> Any:
        if isinstance(value, Obj):
            if depth >= max_depth:
                return f"{{... {len(value)} keys}}"
            return Obj((k, mask(v, depth + 1, f"{path}.{k}")) for k, v in value)
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

    masked = [mask(d, 0, "$") for d in docs]
    if is_lines:   # JSON Lines: keep a few lines
        parts = [_dump(m) for m in masked[:max_items]]
        if len(masked) > max_items:
            parts.append(f"... +{len(masked) - max_items} more lines")
        return Trim("\n".join(parts))
    return Trim(_dump(masked[0]))


def _shape(node: Any) -> set[str]:
    """What an item adds to the picture: its own kind, plus the key paths inside it."""
    kind = "obj" if isinstance(node, Obj) else "arr" if isinstance(node, list) else "num" if isinstance(node, Raw) else type(node).__name__
    return {"<" + kind + ">"} | _paths(node)


def _paths(node: Any, prefix: str = "", depth: int = 0, out: set[str] | None = None) -> set[str]:
    out = set() if out is None else out
    if depth < 3 and isinstance(node, Obj):
        for k, v in node:
            out.add(f"{prefix}.{k}")
            _paths(v, f"{prefix}.{k}", depth + 1, out)
    elif depth < 3 and isinstance(node, list):
        for v in node:
            _paths(v, f"{prefix}[]", depth + 1, out)
    return out


def _pick(items: list[Any], limit: int, extras: int = 3) -> list[int]:
    """The first `limit` items, plus up to `extras` later items that show a kind of value or a key the kept ones lack."""
    picked = list(range(min(limit, len(items))))
    if len(items) <= limit:
        return picked
    seen: set[str] = set()
    for i in picked:
        seen |= _shape(items[i])
    # Items that reveal new key paths matter most; items that only add a new kind of value (a null, a number) come second.
    for wanted_keys in (True, False):
        for i in range(limit, len(items)):
            if len(picked) >= limit + extras:
                break
            if i in picked:
                continue
            new = _shape(items[i]) - seen
            if wanted_keys:
                new = {s for s in new if not s.startswith("<")}
            if new:
                picked.append(i)
                seen |= _shape(items[i])
    return sorted(picked)


def _parse(text: str) -> tuple[list[Any], bool] | None:
    try:
        return [_loads(text)], False
    except ValueError:
        pass
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    try:
        return [_loads(ln) for ln in lines], True
    except ValueError:
        return None


def subtree(text: str, path: str) -> str | None:
    """Return the part of a stored JSON document at a simple path such as $.items[3].user (used by `expand`)."""
    try:
        node: Any = _loads(text)
    except (ValueError, RecursionError):
        return None
    tokens = path.removeprefix("$").replace("[", ".[").split(".")
    for token in (t for t in tokens if t):
        try:
            if token.startswith("["):
                node = node[int(token.strip("[]"))]
            elif isinstance(node, Obj):
                node = next(v for k, v in node if k == token)
            else:
                return None
        except (StopIteration, IndexError, TypeError, ValueError):
            return None
    return _dump(node)
