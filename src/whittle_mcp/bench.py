"""Retention-checked benchmark: how many tokens does a trimmer save, and how many of the facts that matter survive?

Each corpus sample has the raw text plus a metadata file listing "facts" extracted from the RAW text (failing test ids, error lines,
changed file paths, JSON key paths, operation ids). A tool's output is scored by the share of those facts it still contains.
A tool is any command that reads the sample on stdin and writes the trimmed text on stdout (the sample's kind is in $WHITTLE_KIND
and its options in $WHITTLE_OPTIONS), so other trimmers can be measured with the same yardstick.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from whittle_mcp.engine import Whittle
from whittle_mcp.prices import load_prices, saved_cost
from whittle_mcp.store import Store
from whittle_mcp.tokens import TokenCounter, get_counter

KIND_ORDER = ["tests", "log", "json", "diff", "openapi"]


@dataclass
class Sample:
    kind: str
    name: str
    text: str
    options: dict[str, Any]
    facts: dict[str, list[str]]


@dataclass
class Score:
    tool: str
    sample: str
    kind: str
    raw_tokens: int
    out_tokens: int
    found: int
    total: int
    missing: list[str] = field(default_factory=list)

    @property
    def retention(self) -> float:
        return self.found / self.total if self.total else 1.0


def load_corpus(path: Path) -> list[Sample]:
    samples = []
    for meta_path in sorted(path.glob("*/*.json")):
        text_path = meta_path.with_suffix(".txt")
        if not text_path.is_file():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        samples.append(Sample(meta["kind"], meta_path.stem, text_path.read_text(encoding="utf-8"), meta.get("options", {}),
                              meta.get("facts", {})))
    return samples


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def key_paths(node: object, prefix: str = "$", depth: int = 0, out: set[str] | None = None) -> set[str]:
    out = set() if out is None else out
    if depth > 3:
        return out
    if isinstance(node, dict):
        for k, v in node.items():
            out.add(f"{prefix}.{k}")
            key_paths(v, f"{prefix}.{k}", depth + 1, out)
    elif isinstance(node, list):
        for v in node:
            key_paths(v, f"{prefix}[]", depth + 1, out)
    return out


def check_facts(output: str, facts: dict[str, list[str]]) -> tuple[int, int, list[str]]:
    squashed = _squash(output)
    found = total = 0
    missing: list[str] = []
    for fact in facts.get("contains", []):
        total += 1
        if _squash(fact) in squashed:
            found += 1
        else:
            missing.append(fact)
    wanted = facts.get("json_paths", [])
    if wanted:
        try:
            have: set[str] | None = key_paths(json.loads(output))
        except ValueError:
            have = None
        for path in wanted:
            total += 1
            # a tool whose output is not JSON is checked leniently: the last key name must appear quoted
            ok = path in have if have is not None else f'"{path.rsplit(".", 1)[-1]}"' in output
            if ok:
                found += 1
            else:
                missing.append(path)
    return found, total, missing


def naive_truncate(text: str, budget: int, counter: TokenCounter) -> str:
    """Head and tail lines, alternating, until the token budget is used. The baseline everyone can write in a minute."""
    lines = text.splitlines()
    head: list[str] = []
    tail: list[str] = []
    used = 0
    lo, hi = 0, len(lines) - 1
    while lo <= hi:
        for side in ("head", "tail"):
            if lo > hi:
                break
            line = lines[lo] if side == "head" else lines[hi]
            cost = counter.count(line + chr(10))
            if used + cost > budget:
                lo = hi + 1
                break
            used += cost
            if side == "head":
                head.append(line)
                lo += 1
            else:
                tail.append(line)
                hi -= 1
    omitted = len(lines) - len(head) - len(tail)
    middle = [f"[... {omitted} lines truncated ...]"] if omitted > 0 else []
    return "\n".join(head + middle + list(reversed(tail)))


def external(command: str) -> Callable[[Sample], str]:
    def run(sample: Sample) -> str:
        env = {**os.environ, "WHITTLE_KIND": sample.kind, "WHITTLE_OPTIONS": json.dumps(sample.options)}
        done = subprocess.run(shlex.split(command, posix=os.name != "nt"), input=sample.text.encode("utf-8"), capture_output=True,
                              env=env, timeout=120, check=False)
        return done.stdout.decode("utf-8", "replace")
    return run


def run_benchmark(samples: list[Sample], counter: TokenCounter, tools: dict[str, Callable[[Sample], str]]) -> list[Score]:
    engine = Whittle(counter=counter, store=Store())
    scores: list[Score] = []
    for s in samples:
        raw = counter.count(s.text)
        whittle_out = engine.trim(s.kind, s.text, **s.options).text
        outputs = {"none": s.text, "naive": naive_truncate(s.text, counter.count(whittle_out), counter), "whittle": whittle_out}
        for name, tool in tools.items():
            try:
                outputs[name] = tool(s)
            except Exception as exc:  # noqa: BLE001 - one broken tool must not stop the benchmark
                outputs[name] = f"[tool failed: {exc}]"
        for name, out in outputs.items():
            found, total, missing = check_facts(out, s.facts)
            scores.append(Score(name, f"{s.kind}/{s.name}", s.kind, raw, counter.count(out), found, total, missing))
    return scores


def summarise(scores: list[Score]) -> dict[str, dict[str, dict[str, Any]]]:
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for kind in [*KIND_ORDER, "all"]:
        for tool in dict.fromkeys(s.tool for s in scores):
            rows = [s for s in scores if s.tool == tool and (kind == "all" or s.kind == kind)]
            if not rows:
                continue
            raw = sum(r.raw_tokens for r in rows)
            kept = sum(r.out_tokens for r in rows)
            out.setdefault(kind, {})[tool] = {
                "samples": len(rows), "raw_tokens": raw, "out_tokens": kept,
                "saved_percent": round(100 * (raw - kept) / raw, 1) if raw else 0.0,
                "retention_percent": round(100 * sum(r.retention for r in rows) / len(rows), 1),
                "perfect_samples": sum(1 for r in rows if r.found == r.total),
            }
    return out


def to_markdown(summary: dict[str, dict[str, dict[str, Any]]], counter_name: str, scores: list[Score]) -> str:
    lines = [f"Token counter: `{counter_name}`. Savings are token-weighted; retention is the average share of must-keep facts present.", ""]
    lines += ["| Input kind | Tool | Samples | Tokens saved | Facts retained | Samples with every fact |", "|---|---|---:|---:|---:|---:|"]
    for kind, tools in summary.items():
        for tool, m in tools.items():
            lines.append(f"| {kind} | {tool} | {m['samples']} | {m['saved_percent']}% | {m['retention_percent']}% | "
                         f"{m['perfect_samples']}/{m['samples']} |")
    losses = [s for s in scores if s.tool == "whittle" and s.found < s.total]
    if losses:
        lines += ["", "Samples where whittle lost at least one fact:", ""]
        for s in losses:
            lines.append(f"- `{s.sample}`: {s.total - s.found} of {s.total} missing, e.g. `{s.missing[0][:90]}`")
    return "\n".join(lines)


def run_cli(args: argparse.Namespace) -> int:
    corpus = Path(args.corpus)
    samples = load_corpus(corpus)
    if not samples:
        print(f"No samples found in {corpus}. The corpus lives in the git repository, not in the pip package: clone "
              "https://github.com/builditwithgk/whittle-mcp and run `whittle bench` there.", file=sys.stderr)
        return 2
    counter = get_counter(args.counter)
    tools: dict[str, Callable[[Sample], str]] = {}
    for spec in args.tool:
        name, _, command = spec.partition("=")
        if not command:
            print(f"--tool needs NAME=COMMAND, got {spec!r}", file=sys.stderr)
            return 2
        tools[name] = external(command)
    scores = run_benchmark(samples, counter, tools)
    summary = summarise(scores)
    status = 0
    floor = getattr(args, "fail_under_retention", None)
    if floor is not None and summary["all"]["whittle"]["retention_percent"] < floor:
        print(f"whittle retention {summary['all']['whittle']['retention_percent']}% is below the required {floor}%", file=sys.stderr)
        status = 1
    if args.json:
        print(json.dumps({"counter": counter.name, "summary": summary,
                          "samples": [vars(s) | {"retention": s.retention} for s in scores]}, indent=1))
        return status
    if args.markdown:
        print(to_markdown(summary, counter.name, scores))
        return status
    print(f"corpus: {len(samples)} samples   counter: {counter.name}")
    price = load_prices()["example-mid"]
    for kind, per_tool in summary.items():
        print(f"\n{kind}")
        for tool, m in per_tool.items():
            print(f"  {tool:10} saved {m['saved_percent']:5.1f}%   retained {m['retention_percent']:5.1f}%   "
                  f"perfect {m['perfect_samples']}/{m['samples']}")
    total = summary["all"]["whittle"]
    usd = saved_cost(total["raw_tokens"], total["out_tokens"], price)
    print(f"\nwhittle on the whole corpus: {total['raw_tokens']:,} -> {total['out_tokens']:,} tokens; "
          f"about ${usd:.2f} saved at EXAMPLE prices (kept 10 turns, cached). Edit prices with `whittle prices`.")
    losses = [s for s in scores if s.tool == "whittle" and s.found < s.total]
    for s in losses:
        print(f"  LOSS {s.sample}: {s.total - s.found}/{s.total} facts missing, e.g. {s.missing[0][:80]!r}")
    return status
