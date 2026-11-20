"""Build a HELD-OUT set: samples the trimmers were never tuned on (different codebase, different endpoints, different log shapes).

The main corpus was in view while the trimmers were written, so a perfect score there is optimistic. This set is generated after the
fact from whittle-mcp's own test-suite (with injected faults), new API endpoints and new log scripts, and scored the same way.

    python bench/make_holdout.py        then        whittle bench --corpus bench/holdout
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("make_corpus", HERE / "make_corpus.py")
mc = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
spec.loader.exec_module(mc)  # type: ignore[union-attr]
mc.ROOT = HERE / "holdout"

REPO = HERE.parent
MUTATIONS = {
    "h1-max-same": ("src/whittle_mcp/trimmers/logs.py", "MAX_SAME = 3", "MAX_SAME = 0"),
    "h2-json-items": ("src/whittle_mcp/trimmers/jsonmask.py", "max_items: int = 3", "max_items: int = 1"),
    "h3-new-file-head": ("src/whittle_mcp/trimmers/diffs.py", "NEW_FILE_HEAD = 40", "NEW_FILE_HEAD = 0"),
    "h4-never-worse": ("src/whittle_mcp/engine.py", "if not trimmed.changed or out_tokens >= raw_tokens:", "if not trimmed.changed:"),
    "h5-min-run": ("src/whittle_mcp/compose.py", "MIN_RUN = 3", "MIN_RUN = 1"),
    "h6-cost-model": ("src/whittle_mcp/prices.py", "later_turns * price.cache_read", "price.cache_read"),
    "h7-no-generated": ("src/whittle_mcp/trimmers/diffs.py", 'return "generated or lock file"', "return None"),
}


def build_tests() -> None:
    for name, (rel, old, new) in MUTATIONS.items():
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "project"
            shutil.copytree(REPO, work, ignore=shutil.ignore_patterns(".venv", ".git", "__pycache__", ".pytest_cache", "*.egg-info", "bench", "space"))
            (work / "bench").mkdir()
            (work / "bench" / "corpus").mkdir()
            target = work / rel
            body = target.read_text(encoding="utf-8")
            if old not in body:
                print(f"  skip {name}: pattern not found")
                continue
            target.write_text(body.replace(old, new, 1), encoding="utf-8")
            env = {**mc.ENV, "PYTHONPATH": str(work / "src")}
            out = mc.scrub(mc.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "--color=no", "-q", "--ignore=tests/test_engine.py::test_retention_on_the_corpus_and_beats_naive_truncation"],
                                  cwd=work, env=env), [str(work)])
            if not re.search(r"\d+ failed", out):
                print(f"  skip {name}: nothing failed")
                continue
            mc.save("tests", f"pytest-{name}", out, f"pytest on a mutated copy of whittle-mcp ({name})", mc.pytest_facts(out))


def build_json() -> None:
    import json
    import shutil as sh
    gh = sh.which("gh")
    sources: dict[str, str] = {}
    if gh:
        for name, endpoint in {"gh-black-issues": "repos/psf/black/issues?per_page=15&state=all", "gh-numpy-pulls": "repos/numpy/numpy/pulls?per_page=10&state=all",
                               "gh-rich-releases": "repos/Textualize/rich/releases?per_page=6", "gh-ruff-repo": "repos/astral-sh/ruff"}.items():
            sources[name] = mc.run([gh, "api", endpoint], env=None)
    for name, url in {"pypi-flask": "https://pypi.org/pypi/flask/json", "npm-react-latest": "https://registry.npmjs.org/react/latest",
                      "npm-search-llm": "https://registry.npmjs.org/-/v1/search?text=llm&size=25"}.items():
        try:
            sources[name] = mc.fetch(url)
        except Exception as exc:  # noqa: BLE001
            print(f"  skip {name}: {exc}")
    for name, raw in sources.items():
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        text = json.dumps(data, indent=2, ensure_ascii=False)
        if 3000 < len(text) < 1_500_000:
            mc.save("json", name, text, "public API response (held out)", {"json_paths": sorted(mc.key_paths(data))})


HOLDOUT_LOGS = {
    "py-jsonlines": ("import json, random, sys\nrandom.seed(3)\nfor i in range(900):\n    lvl = 'ERROR' if i in (70, 400, 801) else ('WARN' if i % 97 == 0 else 'INFO')\n"
                     "    msg = {70: 'upstream 502 from billing', 400: 'schema mismatch in payload', 801: 'queue depth exceeded'}.get(i, 'handled request')\n"
                     "    print(json.dumps({'ts': 1700000000 + i, 'level': lvl, 'msg': msg, 'id': random.randint(1, 10**6)}))\n"),
    "py-asyncio": ("import asyncio\nasync def fetch(n):\n    await asyncio.sleep(0)\n    if n == 3:\n        raise ConnectionError('peer reset on shard 3')\n    return n\n"
                   "async def main():\n    return await asyncio.gather(*(fetch(n) for n in range(6)))\nasyncio.run(main())\n"),
    "node-promise": ("Error.stackTraceLimit = 100;\nconst chain = (n) => n === 0 ? Promise.reject(new RangeError('index 99 out of bounds')) : chain(n - 1).then(x => x);\n"
                     "chain(30).catch(e => { console.error(e.stack); console.error('ERROR retry budget exhausted'); process.exit(2); });\n"),
}


def build_logs() -> None:
    node = shutil.which("node")
    for name, script in HOLDOUT_LOGS.items():
        ext = "js" if name.startswith("node") else "py"
        if ext == "js" and not node:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"app.{ext}"
            path.write_text(script, encoding="utf-8")
            out = mc.scrub(mc.run([node if ext == "js" else sys.executable, str(path)], cwd=Path(tmp)), [tmp])
        if len(out.splitlines()) >= 12:
            mc.save("log", name, out, f"script run ({name}, held out)", mc.log_facts(out))


if __name__ == "__main__":
    import shutil as _sh
    if mc.ROOT.exists():
        _sh.rmtree(mc.ROOT)
    for label, step in (("tests", build_tests), ("json", build_json), ("logs", build_logs)):
        print(label)
        step()
    print(f"wrote {len(mc.written)} held-out samples to {mc.ROOT}")
