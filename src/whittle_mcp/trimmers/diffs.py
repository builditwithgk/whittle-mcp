"""Unified diffs: collapse lockfiles, generated and minified files and whitespace-only changes; trim context to one line."""

from __future__ import annotations

import re

from whittle_mcp.compose import marker
from whittle_mcp.trimmers.base import Trim

_GENERATED = re.compile(
    r"(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|uv\.lock|Pipfile\.lock|Cargo\.lock|go\.sum|composer\.lock|Gemfile\.lock)$"
    r"|\.min\.(js|css)$|\.map$|(^|/)(dist|build|vendor|node_modules|__pycache__)/|\.snap$|\.pb\.go$|_pb2\.py$")
# In these files a change of indentation changes the meaning, so only trailing whitespace counts as whitespace-only.
_INDENT_MATTERS = (".py", ".pyi", ".yml", ".yaml", ".md", ".rst", ".toml", ".mk", "Makefile", ".nim", ".hs", ".coffee", ".sass", ".pug")
_FILE = re.compile(r"^diff --git a/(.+?) b/(.+)$")
NEW_FILE_HEAD = 40


def trim(text: str, context: int = 1, handle: str | None = None, **_: object) -> Trim:
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if _FILE.match(ln)]
    if not starts:
        return Trim(text, changed=False, notes=["not a git unified diff, returned as is"])
    starts.append(len(lines))
    out: list[str] = []
    omitted_total = 0
    files = adds = dels = 0
    collapsed: dict[str, int] = {}
    for a, b in zip(starts, starts[1:], strict=False):
        section = lines[a:b]
        name = _FILE.match(section[0]).group(2)  # type: ignore[union-attr]
        plus = sum(1 for ln in section if ln.startswith("+") and not ln.startswith("+++"))
        minus = sum(1 for ln in section if ln.startswith("-") and not ln.startswith("---"))
        files, adds, dels = files + 1, adds + plus, dels + minus
        reason = _collapse_reason(name, section, plus, minus)
        if reason:
            collapsed[reason] = collapsed.get(reason, 0) + 1
            out.append(f"{section[0]}")
            out.append(f"[{reason}: +{plus} -{minus} collapsed" + (f"; whittle expand {handle} lines={a + 1}-{b}]" if handle else "]"))
            omitted_total += len(section) - 1
            continue
        body, omitted = _trim_section(section, context, handle, a)
        out.extend(body)
        omitted_total += omitted
    summary = f"whittle diff: {files} files, +{adds} -{dels}"
    if collapsed:
        summary += "; collapsed: " + ", ".join(f"{count} {reason}" for reason, count in collapsed.items())
    prefix = [lines[i] for i in range(0, starts[0])]  # anything before the first file (commit header)
    return Trim("\n".join([summary, *prefix, *out]), omitted_lines=omitted_total)


def _collapse_reason(name: str, section: list[str], plus: int, minus: int) -> str | None:
    if any(ln.startswith("Binary files") or ln.startswith("GIT binary patch") for ln in section):
        return None  # already one line
    if _GENERATED.search(name):
        return "generated, vendored or lock file"
    norm = (lambda s: s.rstrip()) if name.endswith(_INDENT_MATTERS) else (lambda s: s.strip())
    added = sorted(norm(ln[1:]) for ln in section if ln.startswith("+") and not ln.startswith("+++"))
    removed = sorted(norm(ln[1:]) for ln in section if ln.startswith("-") and not ln.startswith("---"))
    if (plus or minus) and added == removed:
        return "whitespace-only change"
    return None


def _trim_section(section: list[str], context: int, handle: str | None, base: int) -> tuple[list[str], int]:
    """Keep headers and every changed line, and `context` lines around changes; drop the rest of each hunk."""
    keep = [False] * len(section)
    in_hunk = False
    new_file = any(ln.startswith("new file mode") for ln in section)
    for i, ln in enumerate(section):
        if ln.startswith("@@"):
            in_hunk = True
            keep[i] = True
        elif not in_hunk:
            keep[i] = True   # file header lines
        elif ln.startswith(("+", "-")):
            for k in range(max(0, i - context), min(len(section), i + context + 1)):
                keep[k] = True
    if new_file:  # a brand new file: its head is enough to see what it is
        header_end = next((i for i, ln in enumerate(section) if ln.startswith("@@")), 0)
        for i in range(len(section)):
            keep[i] = i <= header_end + NEW_FILE_HEAD
    out: list[str] = []
    omitted = 0
    i = 0
    while i < len(section):
        if keep[i]:
            out.append(section[i])
            i += 1
            continue
        j = i
        while j < len(section) and not keep[j]:
            j += 1
        out.append(marker(j - i, handle, base + i + 1, base + j) if j - i >= 3 else "")
        if j - i < 3:
            out.pop()
            out.extend(section[i:j])
        else:
            omitted += j - i
        i = j
    return out, omitted
