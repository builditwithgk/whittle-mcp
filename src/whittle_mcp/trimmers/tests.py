"""Test-runner output: keep the failures (names, assertions, locations) and the summary; collapse passes, dots and noise.

Recognised: pytest, unittest, jest, mocha, RSpec, TAP, go test, cargo test. Anything else is returned unchanged.
"""

from __future__ import annotations

import re

from whittle_mcp.compose import compose, keep_around
from whittle_mcp.trimmers.base import Trim

_SECTION = re.compile(r"^=+ (.+?) =+$")
_BLOCK = re.compile(r"^_{2,} (.+?) _{2,}$")
_CAPTURE = re.compile(r"^-+ Captured .+ -+$")
_LOCATION = re.compile(r"^\S+:\d+: ")
_SUMMARY = re.compile(
    r"\d+ (passed|failed|errors?|skipped|xfailed|xpassed|warnings?|deselected)|^Ran \d+ tests?|^(OK|FAILED)( \(|$)"
    r"|^Tests?:\s|^Test Suites:|^test result:|^(ok|FAIL)\s+\S+\s|^Snapshots:|^Time:|^=+ .+ in [\d.]+s"
    r"|^\s*\d+ (passing|failing|pending)|\d+ examples?, \d+ failures?|^# (tests|pass|fail|skip)\b|^1\.\.\d+")
# What makes the text a test run at all; anything else passes through unchanged.
_RECOGNISED = re.compile(
    r"test session starts|^Ran \d+ tests?|^=+ .* in [\d.]+s|^(ok|FAIL)\s+\S+\s+[\d.]+s|^\s*--- (FAIL|PASS)|^=== RUN|^test result:"
    r"|^Tests?:\s+\d|^Test Suites:|^(PASS|FAIL) \S|\.\.\. (ok|FAILED|ignored)$|^\s*\d+ (passing|failing)|\d+ examples?, \d+ failures?"
    r"|^(not )?ok \d+|^TAP version|^collected \d+ items|^Failures:$|\d+ (passed|failed)\b.* in [\d.]+s|^Finished in [\d.]+", re.M)
_FAIL_WORDS = re.compile(
    r"\b(FAILED|FAIL|ERROR|ERRORS|panicked)\b|^E\s|--- FAIL|● |\bfailures?:|AssertionError|^not ok|\bfailing\b|Failure/Error")
# (pattern, lines kept before, lines kept after): the part of a failure that carries its meaning
_WINDOWS = [
    (re.compile(r"^(FAIL|ERROR)(ED)?[: ]|^\s*(FAILED|ERROR) "), 0, 6),
    (re.compile(r"^\s*--- FAIL"), 3, 8),
    (re.compile(r"_test\.go:\d+:"), 0, 0),
    (re.compile(r"\.\.\. FAILED$"), 0, 0),
    (re.compile(r"^\s*● "), 0, 14),
    (re.compile(r"^---- .+ stdout ----$"), 0, 8),
    (re.compile(r"panicked at"), 0, 4),
    (re.compile(r"^E\s|^>\s"), 1, 1),
    (re.compile(r"(AssertionError|Error|Exception)\b.*:"), 1, 1),
    (re.compile(r"^\s*\d+\) "), 0, 10),                 # mocha and RSpec numbered failures
    (re.compile(r"Failure/Error:|^\s*expected[: ]|^\s*got:"), 1, 6),
    (re.compile(r"^not ok"), 0, 8),                      # TAP
    (re.compile(r"^(Failures|Failed examples):$"), 0, 3),
]
_TRACE = re.compile(r"^Traceback \(most recent call last\):")


def trim(text: str, max_failure_lines: int = 60, handle: str | None = None, **_: object) -> Trim:
    lines = text.splitlines()
    n = len(lines)
    if n < 12:
        return Trim(text, changed=False, notes=["short output, returned as is"])
    if not _RECOGNISED.search(text):
        return Trim(text, changed=False, notes=["not a recognised test-runner output (see the README for the supported runners)"])
    keep = [False] * n
    for i, line in enumerate(lines):
        if _SUMMARY.search(line):
            keep[i] = True
    for k in range(max(0, n - 3), n):
        keep[k] = True
    failed = any(_FAIL_WORDS.search(line) for line in lines)
    if failed:
        _pytest_blocks(lines, keep, max_failure_lines)
        for i, line in enumerate(lines):
            for pattern, before, after in _WINDOWS:
                if pattern.search(line):
                    keep_around(keep, i, before, after)
        _keep_python_traces(lines, keep)
    else:
        keep[0] = True  # all green: the summary lines are enough
    out, omitted = compose(lines, keep, handle)
    return Trim("\n".join(out), omitted_lines=omitted, notes=[] if failed else ["no failures found"])


def _pytest_blocks(lines: list[str], keep: list[bool], cap: int) -> None:
    n = len(lines)
    sections = [(i, m.group(1)) for i, line in enumerate(lines) if (m := _SECTION.match(line))]
    for idx, (start, name) in enumerate(sections):
        end = sections[idx + 1][0] if idx + 1 < len(sections) else n
        upper = name.upper()
        if "SHORT TEST SUMMARY" in upper:
            for k in range(start, end):
                keep[k] = True
        elif "FAILURES" in upper or "ERRORS" in upper:
            keep[start] = True
            _failure_blocks(lines, keep, start + 1, end, cap)


def _failure_blocks(lines: list[str], keep: list[bool], start: int, end: int, cap: int) -> None:
    heads = [i for i in range(start, end) if _BLOCK.match(lines[i])] + [end]
    for a, b in zip(heads, heads[1:], strict=False):
        kept = 0
        keep[a] = True
        capture_at = None
        for k in range(a + 1, b):
            line = lines[k]
            if _CAPTURE.match(line):
                keep[k] = True
                capture_at = k
                continue
            if capture_at is not None:
                if k - capture_at <= 3:
                    keep[k] = True
                if b - k <= 3:
                    keep[k] = True
                continue
            if line.startswith("E ") or _LOCATION.match(line) or line.startswith(">"):
                if kept < cap:
                    keep[k] = True
                    kept += 1
                if line.startswith(">"):
                    keep_around(keep, k, 2, 0)


def _keep_python_traces(lines: list[str], keep: list[bool]) -> None:
    n = len(lines)
    i = 0
    while i < n:
        if _TRACE.match(lines[i]):
            j = i + 1
            while j < n and lines[j].startswith((" ", "\t")):
                j += 1
            keep[i] = True
            for k in range(max(i + 1, j - 6), j):   # the last three frames
                keep[k] = True
            if j < n:
                keep[j] = True
            i = j
        else:
            i += 1
