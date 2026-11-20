"""Logs and stack traces: collapse repeats and the middle of tracebacks, always keep every distinct error line."""

from __future__ import annotations

import re

from whittle_mcp.compose import compose, keep_around
from whittle_mcp.trimmers.base import Trim

_TS = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b|\b\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\b")
_NUM = re.compile(r"\b0x[0-9a-fA-F]+\b|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b|\b\d+\b")
_LEVEL = re.compile(r"\b(ERROR|FATAL|CRITICAL|SEVERE|PANIC|panic|Exception|Traceback|FAILED|failed|Failed|WARN(?:ING)?|Error)\b")
_PY_TRACE = re.compile(r"^Traceback \(most recent call last\):")
_AT_FRAME = re.compile(r"^\s+at\s")
MAX_SAME = 3  # keep the first three occurrences of an identical message, count the rest


def normalise(line: str) -> str:
    return _NUM.sub("#", _TS.sub("<ts>", line)).strip()


def trim(text: str, head: int = 5, tail: int = 25, max_frames: int = 3, handle: str | None = None, **_: object) -> Trim:
    lines = text.splitlines()
    if len(lines) < head + tail + 10:
        return Trim(text, changed=False, notes=["short log, returned as is"])
    rows, spans = _collapse_repeats(lines)
    n = len(rows)
    keep = [False] * n
    seen: dict[str, int] = {}
    for i, row in enumerate(rows):
        base = re.sub(r" \(x\d+\)$", "", row)
        if _LEVEL.search(row):
            key = normalise(base)
            seen[key] = seen.get(key, 0) + 1
            if seen[key] <= MAX_SAME:
                keep_around(keep, i, 0, 1 if not row.startswith(" ") else 0)
                keep[i] = True
    for i in range(min(head, n)):
        keep[i] = True
    for i in range(max(0, n - tail), n):
        keep[i] = True
    _keep_traceback_edges(rows, keep, max_frames)
    out, omitted = compose(rows, keep, handle, spans)
    return Trim("\n".join(out), omitted_lines=omitted)


def _collapse_repeats(lines: list[str]) -> tuple[list[str], list[tuple[int, int]]]:
    """Merge consecutive lines that differ only in numbers and timestamps into one row with a repeat count."""
    rows: list[str] = []
    spans: list[tuple[int, int]] = []
    i = 0
    while i < len(lines):
        j = i
        key = normalise(lines[i])
        while j + 1 < len(lines) and key and normalise(lines[j + 1]) == key:
            j += 1
        count = j - i + 1
        rows.append(lines[i] if count == 1 else f"{lines[i]} (x{count})")
        spans.append((i + 1, j + 1))
        i = j + 1
    return rows, spans


def _keep_traceback_edges(rows: list[str], keep: list[bool], max_frames: int) -> None:
    """Python tracebacks: header and the exception line stay, plus the last frames. Java/JS `at` frames: the first few stay."""
    n = len(rows)
    i = 0
    while i < n:
        if _PY_TRACE.match(rows[i]):
            j = i + 1
            while j < n and rows[j].startswith((" ", "\t")):
                j += 1
            keep[i] = True
            frames = list(range(i + 1, j))
            for k in frames[-max_frames * 2:]:   # a frame is a File line plus a code line
                keep[k] = True
            if j < n:
                keep[j] = True                   # the exception line itself
            i = j
        elif _AT_FRAME.match(rows[i]):
            j = i
            while j < n and _AT_FRAME.match(rows[j]):
                j += 1
            for k in range(i, min(j, i + max_frames + 2)):
                keep[k] = True
            i = j
        else:
            i += 1
