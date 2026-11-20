"""OpenAPI and Swagger documents (JSON; YAML with PyYAML): an index, or only the operations you ask for plus what they use."""

from __future__ import annotations

import fnmatch
import json
from typing import Any

from whittle_mcp.trimmers.base import Trim

METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
PATH_ITEM_KEYS = ("summary", "description", "parameters", "servers")   # shared by every operation under a path


def load(text: str) -> tuple[dict[str, Any] | None, str]:
    """Return (document, reason it could not be read)."""
    try:
        data = json.loads(text)
    except ValueError:
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError:
            return None, "not JSON (for YAML install whittle-mcp[yaml])"
        try:
            data = yaml.safe_load(text)
        except Exception:  # noqa: BLE001
            return None, "not valid JSON or YAML"
    if isinstance(data, dict) and "paths" in data:
        return data, ""
    return None, "not an OpenAPI or Swagger document (no `paths`)"


def trim(text: str, paths: list[str] | None = None, tags: list[str] | None = None, operation_ids: list[str] | None = None,
         methods: list[str] | None = None, index: bool = False, max_description: int = 200, handle: str | None = None,
         **_: object) -> Trim:
    spec, reason = load(text)
    if spec is None:
        return Trim(text, changed=False, notes=[reason + ", returned as is"])
    ops = list(_operations(spec))
    if index or not (paths or tags or operation_ids or methods):
        title = spec.get("info", {}).get("title", "")
        version = spec.get("info", {}).get("version", "")
        head = f"{title} {version}: {len(ops)} operations. Ask for a slice with paths=, tags=, operation_ids= or methods=."
        rows = [f"{m.upper():6} {p}  {op.get('operationId', '')}  {str(op.get('summary', ''))[:80]}" for p, m, op in ops]
        return Trim("\n".join([head, *rows]), notes=["index"])
    wanted = [(p, m, op) for p, m, op in ops if _match(p, m, op, paths, tags, operation_ids, methods)]
    if not wanted:
        given = {k: v for k, v in (("paths", paths), ("tags", tags), ("operation_ids", operation_ids), ("methods", methods)) if v}
        hint = ""
        if any(":/" in p for p in paths or []):
            hint = " A leading / in a path was rewritten by Git Bash on Windows: set MSYS_NO_PATHCONV=1 or use operation ids."
        return Trim(f"No operations matched {given}. Ask for the index (no filters) to see what exists.{hint}", notes=["no match"])
    out: dict[str, Any] = {k: spec[k] for k in ("openapi", "swagger", "basePath", "host", "schemes") if k in spec}
    info = spec.get("info", {})
    out["info"] = {k: info[k] for k in ("title", "version") if k in info}
    if spec.get("servers"):
        out["servers"] = spec["servers"][:2]
    if "security" in spec:
        out["security"] = spec["security"]
    out["paths"] = {}
    for p, m, op in wanted:
        shared = {k: _shorten(spec["paths"][p][k], max_description) for k in PATH_ITEM_KEYS if k in spec["paths"][p]}
        item = out["paths"].setdefault(p, shared)
        item[m] = _shorten(op, max_description)
    _add_references(spec, out, max_description)
    for where in (("components", "securitySchemes"), ("securityDefinitions",)):   # how the API is authenticated stays visible
        node: Any = spec
        for part in where:
            node = node.get(part) if isinstance(node, dict) else None
        if node:
            cur = out
            for part in where[:-1]:
                cur = cur.setdefault(part, {})
            cur[where[-1]] = node
    return Trim(json.dumps(out, separators=(",", ":"), ensure_ascii=False), notes=[f"{len(wanted)} of {len(ops)} operations"])


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


def _add_references(spec: dict[str, Any], out: dict[str, Any], limit: int) -> None:
    """Copy every shared definition the selected operations use, directly or through other definitions, to the same place in the output.

    Works for OpenAPI 3 (#/components/schemas/X, #/components/parameters/Y, ...) and Swagger 2 (#/definitions/X, #/parameters/Y).
    """
    todo = list(_refs(out["paths"]))
    done: set[str] = set()
    while todo:
        ref = todo.pop()
        if ref in done:
            continue
        done.add(ref)
        parts = [p.replace("~1", "/").replace("~0", "~") for p in ref.removeprefix("#/").split("/")]
        node: Any = spec
        for part in parts:
            node = node.get(part) if isinstance(node, dict) else None
        if node is None:
            continue
        cur = out
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = _shorten(node, limit)
        todo.extend(_refs(node))
