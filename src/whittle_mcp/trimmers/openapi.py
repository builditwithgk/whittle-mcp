"""OpenAPI documents (JSON; YAML too when PyYAML is installed): an index, or only the operations you ask for plus the schemas they use."""

from __future__ import annotations

import fnmatch
import json
from typing import Any

from whittle_mcp.trimmers.base import Trim

METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


def load(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
    except ValueError:
        try:
            import yaml  # type: ignore[import-untyped]
            data = yaml.safe_load(text)
        except Exception:  # noqa: BLE001
            return None
    return data if isinstance(data, dict) and "paths" in data else None


def trim(text: str, paths: list[str] | None = None, tags: list[str] | None = None, operation_ids: list[str] | None = None,
         methods: list[str] | None = None, index: bool = False, max_description: int = 200, handle: str | None = None,
         **_: object) -> Trim:
    spec = load(text)
    if spec is None:
        return Trim(text, changed=False, notes=["not an OpenAPI document with `paths`, returned as is"])
    ops = list(_operations(spec))
    if index or not (paths or tags or operation_ids or methods):
        title = spec.get("info", {}).get("title", "")
        version = spec.get("info", {}).get("version", "")
        head = f"{title} {version}: {len(ops)} operations. Ask for a slice with paths=, tags=, operation_ids= or methods=."
        rows = [f"{m.upper():6} {p}  {op.get('operationId', '')}  {str(op.get('summary', ''))[:80]}" for p, m, op in ops]
        return Trim("\n".join([head, *rows]), notes=["index"])
    wanted = [(p, m, op) for p, m, op in ops if _match(p, m, op, paths, tags, operation_ids, methods)]
    if not wanted:
        return Trim("No operations matched. Use the index (no filters) to see what exists.", notes=["no match"])
    out: dict[str, Any] = {k: spec[k] for k in ("openapi", "swagger") if k in spec}
    info = spec.get("info", {})
    out["info"] = {k: info[k] for k in ("title", "version") if k in info}
    if spec.get("servers"):
        out["servers"] = spec["servers"][:2]
    out["paths"] = {}
    for p, m, op in wanted:
        out["paths"].setdefault(p, {})[m] = _shorten(op, max_description)
    needed = _closure(spec, out)
    if needed:
        out["components"] = needed
    return Trim(json.dumps(out, separators=(",", ":"), ensure_ascii=False),
                notes=[f"{len(wanted)} of {len(ops)} operations"])


def _operations(spec: dict[str, Any]):
    for path, item in spec.get("paths", {}).items():
        if not isinstance(item, dict):
            continue
        for method in METHODS:
            op = item.get(method)
            if isinstance(op, dict):
                yield path, method, op


def _match(path: str, method: str, op: dict[str, Any], paths, tags, operation_ids, methods) -> bool:
    if paths and not any(fnmatch.fnmatch(path, pat) for pat in paths):
        return False
    if tags and not set(tags) & set(op.get("tags", [])):
        return False
    if operation_ids and op.get("operationId") not in operation_ids:
        return False
    if methods and method not in [m.lower() for m in methods]:
        return False
    return True


def _shorten(value: Any, limit: int) -> Any:
    if isinstance(value, dict):
        return {k: _shorten(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [_shorten(v, limit) for v in value]
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "..."
    return value


def _refs(node: Any):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str) and v.startswith("#/"):
                yield v
            else:
                yield from _refs(v)
    elif isinstance(node, list):
        for v in node:
            yield from _refs(v)


def _closure(spec: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
    """Every component the selected operations use, directly or through other components."""
    todo = list(_refs(out["paths"]))
    done: set[str] = set()
    result: dict[str, Any] = {}
    while todo:
        ref = todo.pop()
        if ref in done:
            continue
        done.add(ref)
        parts = ref.removeprefix("#/").split("/")
        node: Any = spec
        for part in parts:
            node = node.get(part) if isinstance(node, dict) else None
        if node is None or parts[0] != "components" or len(parts) < 3:
            continue
        result.setdefault(parts[1], {})[parts[2]] = _shorten(node, 200)
        todo.extend(_refs(node))
    return result
