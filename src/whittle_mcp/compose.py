"""Shared helper: keep some rows, replace each skipped run with one marker that says how to get it back."""

from __future__ import annotations

MIN_RUN = 3  # a marker costs tokens too, so shorter runs are simply kept


def marker(count: int, handle: str | None, start: int, end: int) -> str:
    if handle:
        return f"[... {count} lines omitted: whittle expand {handle} lines={start}-{end} ...]"
    return f"[... {count} lines omitted ...]"


def compose(rows: list[str], keep: list[bool], handle: str | None, spans: list[tuple[int, int]] | None = None,
            min_run: int = MIN_RUN) -> tuple[list[str], int]:
    """Return (output rows, number of original lines omitted).

    `spans[i]` is the (first, last) original line number (1-based) that row i stands for; by default row i is line i+1.
    Rows that stand for several original lines (collapsed repeats) let the marker point at the right original range.
    """
    spans = spans or [(i + 1, i + 1) for i in range(len(rows))]
    out: list[str] = []
    omitted = 0
    i, n = 0, len(rows)
    while i < n:
        if keep[i]:
            out.append(rows[i])
            i += 1
            continue
        j = i
        while j < n and not keep[j]:
            j += 1
        if j - i < min_run:
            out.extend(rows[i:j])
        else:
            first, last = spans[i][0], spans[j - 1][1]
            out.append(marker(last - first + 1, handle, first, last))
            omitted += last - first + 1
        i = j
    return out, omitted


def keep_around(keep: list[bool], index: int, before: int = 0, after: int = 0) -> None:
    for k in range(max(0, index - before), min(len(keep), index + after + 1)):
        keep[k] = True
