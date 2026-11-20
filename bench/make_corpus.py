"""Build the benchmark corpus from real tool runs. Needs git, Python, Node and (for the JSON samples) the GitHub CLI `gh` and network.

    python bench/make_corpus.py --source-repo <path to a Python project with pytest tests and git history> [--other-repo <path>...]

Every sample is a text file plus a metadata file with the facts that must survive trimming. Facts are extracted from the raw text
(failing test ids, assertion lines, error lines, changed file paths, JSON key paths, operation ids), never from the trimmer's output.
Paths and user names are scrubbed so the corpus can be published.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "corpus"
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "NO_COLOR": "1", "PY_COLORS": "0", "COLUMNS": "120"}
SCRUB = [
    (re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"']+", re.I), r"C:\\Users\\dev"),
    (re.compile(r"/(?:c|C)/Users/[^/\s\"']+"), "/c/Users/dev"),
    (re.compile(r"aitha", re.I), "dev"),
]
written: list[str] = []


def scrub(text: str, extra: list[str] = ()) -> str:  # type: ignore[assignment]
    for needle in extra:
        text = text.replace(needle, "/work/project").replace(needle.replace("\\", "/"), "/work/project")
    for pattern, repl in SCRUB:
        text = pattern.sub(repl, text)
    return text


def save(kind: str, name: str, text: str, source: str, facts: dict, options: dict | None = None) -> None:
    folder = ROOT / kind
    folder.mkdir(parents=True, exist_ok=True)
    assert "aitha" not in text.lower(), f"{kind}/{name} still contains a user name"
    (folder / f"{name}.txt").write_text(text, encoding="utf-8", newline="\n")
    meta = {"kind": kind, "options": options or {}, "source": source, "facts": facts}
    (folder / f"{name}.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    written.append(f"{kind}/{name}")


def run(cmd: list[str], cwd: Path | None = None, env: dict | None = None, timeout: int = 300) -> str:
    done = subprocess.run(cmd, cwd=cwd, env=env or ENV, capture_output=True, timeout=timeout, check=False)
    return (done.stdout + done.stderr).decode("utf-8", "replace").replace("\r\n", "\n")


# ---------------------------------------------------------------- facts
def uniq(items: list[str], limit: int) -> list[str]:
    seen: list[str] = []
    for item in items:
        item = item.strip()
        if item and item not in seen:
            seen.append(item)
    return seen[:limit]


def pytest_facts(text: str) -> dict:
    ids = re.findall(r"^(?:FAILED|ERROR) (\S+?)(?: - .*)?$", text, re.M)
    lines = [m.strip() for m in re.findall(r"^E\s+(.+)$", text, re.M)]
    source = [m.strip() for m in re.findall(r"^>\s+(.+)$", text, re.M)]   # the failing source line
    where = re.findall(r"^(\S+\.py:\d+): \w", text, re.M)        # file:line of the failure
    summary = re.findall(r"^=+ (.+? in [\d.]+s.*?) =+$|^(\d+ (?:passed|failed).*)$", text, re.M)
    last = [a or b for a, b in summary][-1:]
    return {"contains": uniq(ids, 30) + uniq(lines, 12) + uniq(source, 10) + uniq(where, 10) + last}


def log_facts(text: str) -> dict:
    exc = re.findall(r"^(?:[\w.]+\.)?\w*(?:Error|Exception|Warning|Exit)\b[^\n]*$", text, re.M)
    err = [ln for ln in text.splitlines() if re.search(r"\b(ERROR|CRITICAL|FATAL)\b", ln)]
    first_by_message: dict[str, str] = {}
    for ln in err:
        key = re.sub(r"\d+", "#", re.sub(r"\d{4}-\d{2}-\d{2}[T ][\d:.,]+", "", ln)).strip()
        first_by_message.setdefault(key, ln.strip())
    return {"contains": uniq(exc, 12) + uniq(list(first_by_message.values()), 25)}


# ---------------------------------------------------------------- tests
MUTATIONS = {
    "m1-default-allow": ("src/agent_firebreak/policy.py", 'default_effect = "ask"', 'default_effect = "allow"'),
    "m2-no-invisible-strip": ("src/agent_firebreak/normalize.py", 'return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")', "return text"),
    "m3-sensitive-off": ("src/agent_firebreak/provenance.py", "if segment.sensitive:", "if False:"),
    "m4-no-lowercase": ("src/agent_firebreak/normalize.py", "return text.lower()", "return text"),
    "m5-no-undeclared": ("src/agent_firebreak/guard.py", "findings += self._check_undeclared(spec, call)", "pass"),
    "m6-genesis": ("src/agent_firebreak/audit.py", 'GENESIS = "0" * 64', 'GENESIS = "1" * 64'),
}


def copy_project(source: Path, dest: Path) -> None:
    shutil.copytree(source, dest, ignore=shutil.ignore_patterns(".venv", ".git", "__pycache__", ".pytest_cache", "*.egg-info", "space", "docs"))


def build_pytest(source: Path) -> None:
    py = sys.executable
    for variant, (rel, old, new) in [("pass", (None, None, None)), *MUTATIONS.items()]:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "project"
            copy_project(source, work)
            if rel:
                target = work / rel
                body = target.read_text(encoding="utf-8")
                if old not in body:
                    print(f"  skip {variant}: pattern not found")
                    continue
                target.write_text(body.replace(old, new, 1), encoding="utf-8")
            env = {**ENV, "PYTHONPATH": str(work / "src")}
            flag_sets = [["-q"], ["-v", "--tb=short"], ["-rA", "--tb=long"]] if variant in ("pass", "m1-default-allow", "m3-sensitive-off") else [["-q"]]
            for flags in flag_sets:
                out = run([py, "-m", "pytest", "-p", "no:cacheprovider", "--color=no", *flags], cwd=work, env=env)
                out = scrub(out, [str(work)])
                if variant != "pass" and not re.search(r"\d+ failed", out):
                    print(f"  skip {variant} {flags}: nothing failed")
                    continue
                tag = flags[0].lstrip("-") + ("-long" if "--tb=long" in flags else "")
                save("tests", f"pytest-{variant}-{tag}", out, f"pytest run on a copy of {source.name} ({variant})", pytest_facts(out))


UNITTEST_SRC = '''
def slug(s):
    return "-".join(s.lower().split())

def mean(xs):
    return sum(xs) / len(xs)

def parse_kv(s):
    return dict(part.split("=") for part in s.split(","))
'''


def unittest_case(variant: str) -> str:
    tests = {
        "pass": ["slug('A B') == 'a-b'", "mean([1,2,3]) == 2", "parse_kv('a=1,b=2') == {'a':'1','b':'2'}"],
        "fail": ["slug('A  B') == 'a_b'", "mean([1,2,4]) == 2", "parse_kv('a=1') == {'a':'1'}"],
        "error": ["mean([]) == 0", "parse_kv('a') == {}", "slug(None) == ''"],
    }[variant]
    body = "\n".join(f"    def test_{i}(self):\n        self.assertTrue({t})\n" for i, t in enumerate(tests))
    return f"import unittest\nfrom textkit import *\n\nclass T(unittest.TestCase):\n{body}\nif __name__ == '__main__':\n    unittest.main()\n"


def build_unittest() -> None:
    for variant in ("pass", "fail", "error"):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / "textkit.py").write_text(UNITTEST_SRC, encoding="utf-8")
            (work / "test_textkit.py").write_text(unittest_case(variant), encoding="utf-8")
            out = scrub(run([sys.executable, "-m", "unittest", "-v", "test_textkit"], cwd=work), [str(work)])
        fails = re.findall(r"^(?:FAIL|ERROR): (.+)$", out, re.M)
        lines = re.findall(r"^(\w*(?:Error|Exception)\b.*)$", out, re.M)
        summary = re.findall(r"^(OK|FAILED \(.*\))$", out, re.M)
        save("tests", f"unittest-{variant}", out, "python -m unittest -v on a tiny module", {"contains": uniq(fails, 10) + uniq(lines, 10) + summary[-1:]})


# ---------------------------------------------------------------- logs
CHAIN = ("def a():\n    raise KeyError('user_id')\n\ndef f0():\n    return a()\n"
         + "".join(f"\ndef f{i}():\n    return f{i - 1}()\n" for i in range(1, 40))
         + "\ntry:\n    f39()\nexcept KeyError as e:\n    raise RuntimeError('lookup failed') from e\n")

LOG_SCRIPTS = {
    "py-recursion": "import sys\nsys.setrecursionlimit(1500)\ndef f(n):\n    return f(n+1)\nf(0)\n",
    "py-chained": CHAIN,
    "py-logging-noisy": (
        "import logging, random\nrandom.seed(7)\nlogging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s %(name)s %(message)s')\n"
        "log = logging.getLogger('shop.orders')\nfor i in range(1800):\n    log.info('processed order %d for customer %d', 1000+i, random.randint(1, 90))\n"
        "    if i % 150 == 0:\n        log.warning('slow query on orders table (%d ms)', random.randint(800, 2000))\n"
        "    if i in (200, 900, 1500):\n        log.error('payment gateway timeout for order %d', 1000+i)\n"
        "    if i % 60 == 0:\n        log.error('cache miss storm on key product:%d', 5)\n"
        "try:\n    {}['missing']\nexcept KeyError:\n    log.exception('unhandled lookup in checkout')\n"),
    "py-threads": ("import concurrent.futures as cf\ndef work(n):\n    if n % 7 == 0:\n        raise ValueError(f'bad shard {n}')\n    return n\n"
                   "with cf.ThreadPoolExecutor(4) as ex:\n    futs = [ex.submit(work, n) for n in range(40)]\n    for f in futs:\n        f.result()\n"),
}


def build_logs(py: str) -> None:
    for name, script in LOG_SCRIPTS.items():
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "app.py"
            path.write_text(script, encoding="utf-8")
            out = scrub(run([py, str(path)], cwd=Path(tmp)), [tmp])
        if len(out.splitlines()) < 12:
            print(f"  skip {name}: too short")
            continue
        save("log", name, out, f"python script run ({name})", log_facts(out))
    node = shutil.which("node")
    if node:
        js = ("Error.stackTraceLimit = 200;\nfunction deep(n){ if(n===0) throw new TypeError('Cannot read properties of undefined (reading id)'); return deep(n-1); }\n"
              "function handler(){ return deep(60); }\ntry { handler(); } catch (e) { console.error(e.stack); }\n"
              "process.on('uncaughtException', e => { console.error('FATAL', e.message); process.exit(1); });\nsetTimeout(() => { throw new Error('timer failed'); }, 1);\n")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "app.js"
            path.write_text(js, encoding="utf-8")
            out = scrub(run([node, str(path)], cwd=Path(tmp)), [tmp])
        save("log", "node-deep-stack", out, "node script run", log_facts(out))
    out = scrub(run([py, "-m", "pip", "install", "--no-input", "--disable-pip-version-check", "nonexistent-package-zzz-9137==99.1"]))
    if "ERROR" in out:
        save("log", "pip-missing-package", out, "pip install of a package that does not exist", log_facts(out))


# ---------------------------------------------------------------- json
def key_paths(node: object, prefix: str = "$", depth: int = 0, out: set | None = None) -> set:
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


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "whittle-mcp-corpus"})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
        return resp.read().decode("utf-8")


def build_json() -> None:
    gh = shutil.which("gh")
    sources: dict[str, str] = {}
    if gh:
        for name, endpoint in {
            "gh-flask-issues": "repos/pallets/flask/issues?per_page=20&state=all",
            "gh-flask-pulls": "repos/pallets/flask/pulls?per_page=15&state=all",
            "gh-requests-releases": "repos/psf/requests/releases?per_page=8",
            "gh-flask-repo": "repos/pallets/flask",
            "gh-flask-contents": "repos/pallets/flask/contents",
            "gh-search-mcp": "search/repositories?q=topic:mcp&per_page=12",
            "gh-django-issues": "repos/django/django/issues?per_page=15&state=all",
        }.items():
            sources[name] = run([gh, "api", endpoint], env=os.environ.copy())
    for name, url in {
        "pypi-requests": "https://pypi.org/pypi/requests/json",
        "pypi-rich": "https://pypi.org/pypi/rich/json",
        "npm-express-latest": "https://registry.npmjs.org/express/latest",
        "npm-search-mcp": "https://registry.npmjs.org/-/v1/search?text=mcp&size=20",
    }.items():
        try:
            sources[name] = fetch(url)
        except Exception as exc:  # noqa: BLE001
            print(f"  skip {name}: {exc}")
    for name, raw in sources.items():
        try:
            data = json.loads(raw)
        except ValueError:
            print(f"  skip {name}: not JSON")
            continue
        text = json.dumps(data, indent=2, ensure_ascii=False)
        if len(text) > 1_500_000 or len(text) < 3000:
            print(f"  skip {name}: size {len(text)}")
            continue
        save("json", name, text, "public API response", {"json_paths": sorted(key_paths(data))})


# ---------------------------------------------------------------- diffs
def changed_lines(diff: str, limit: int = 12) -> list[str]:
    out: list[str] = []
    current = ""
    for ln in diff.splitlines():
        if ln.startswith("diff --git"):
            current = ln
        elif ln[:1] in "+-" and not ln.startswith(("+++", "---")) and not re.search(r"lock|\.min\.|\.map$", current):
            body = ln[1:].strip()
            if len(body) > 12:
                out.append(ln.rstrip())
    return uniq(out, limit)


def diff_facts(diff: str) -> dict:
    files = re.findall(r"^diff --git a/.+? b/(.+)$", diff, re.M)
    return {"contains": files + changed_lines(diff)}


def build_diffs(repos: list[Path]) -> None:
    count = 0
    for repo in repos:
        if not (repo / ".git").exists():
            continue
        commits = run(["git", "log", "--format=%h", "-n", "40", "--no-merges"], cwd=repo).split()
        lock_commits = run(["git", "log", "--format=%h", "-n", "4", "--", "package-lock.json", "uv.lock", "poetry.lock"], cwd=repo).split()
        for sha in dict.fromkeys(lock_commits + commits):
            diff = run(["git", "show", "--format=", "--no-color", sha], cwd=repo)
            diff = scrub(diff, [str(repo)])
            if not 1500 < len(diff) < 900_000 or "diff --git" not in diff:
                continue
            save("diff", f"{repo.name}-{sha}", diff, f"git show {sha} in {repo.name}", diff_facts(diff))
            count += 1
            if count >= 10:
                break
    # a whitespace-only change, made on a copy of a real file
    for repo in repos:
        files = run(["git", "ls-files", "*.py"], cwd=repo).split()
        if files and (repo / ".git").exists():
            target = max(files, key=lambda f: (repo / f).stat().st_size)
            with tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp) / "r"
                shutil.copytree(repo, work, ignore=shutil.ignore_patterns(".venv", "node_modules", "__pycache__", "space"))
                body = (work / target).read_text(encoding="utf-8")
                (work / target).write_text("\n".join(line + "  " if line.strip() else line for line in body.split("\n")), encoding="utf-8")
                diff = scrub(run(["git", "diff", "--no-color"], cwd=work), [str(work)])
            if "diff --git" in diff:
                save("diff", f"{repo.name}-whitespace-only", diff, "trailing spaces added to every line of one file", {"contains": re.findall(r"^diff --git a/.+? b/(.+)$", diff, re.M)})
            break


# ---------------------------------------------------------------- openapi
OPENAPI_SOURCES = {
    "petstore3": ("https://petstore3.swagger.io/api/v3/openapi.json", [{"paths": ["/pet/*"]}, {"tags": ["store"]}, {"operation_ids": ["getUserByName", "loginUser"]}]),
    "petstore-expanded": ("https://raw.githubusercontent.com/OAI/learn.openapis.org/main/examples/v3.0/petstore-expanded.json", [{"paths": ["/pets*"], "methods": ["get"]}, {"operation_ids": ["addPet"]}]),
    "api-with-examples": ("https://raw.githubusercontent.com/OAI/learn.openapis.org/main/examples/v3.0/api-with-examples.json", [{"paths": ["/*"], "methods": ["get"]}]),
    "link-example": ("https://raw.githubusercontent.com/OAI/learn.openapis.org/main/examples/v3.0/link-example.json", [{"paths": ["/2.0/users/*"]}]),
}


def expected_ops(spec: dict, query: dict) -> list[tuple[str, str, dict]]:
    import fnmatch
    found = []
    for path, item in spec["paths"].items():
        for method in ("get", "put", "post", "delete", "options", "head", "patch", "trace"):
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            if query.get("paths") and not any(fnmatch.fnmatch(path, p) for p in query["paths"]):
                continue
            if query.get("tags") and not set(query["tags"]) & set(op.get("tags", [])):
                continue
            if query.get("operation_ids") and op.get("operationId") not in query["operation_ids"]:
                continue
            if query.get("methods") and method not in query["methods"]:
                continue
            found.append((path, method, op))
    return found


def build_openapi() -> None:
    for name, (url, queries) in OPENAPI_SOURCES.items():
        try:
            raw = fetch(url)
            spec = json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            print(f"  skip {name}: {exc}")
            continue
        text = json.dumps(spec, indent=2, ensure_ascii=False)
        for i, query in enumerate(queries):
            ops = expected_ops(spec, query)
            if not ops:
                continue
            facts = [op["operationId"] for _, _, op in ops if "operationId" in op]
            facts += [p["name"] for _, _, op in ops for p in op.get("parameters", []) if isinstance(p, dict) and "name" in p]
            facts += [code for _, _, op in ops for code in op.get("responses", {})]
            facts += [p for p, _, _ in ops]
            save("openapi", f"{name}-q{i + 1}", text, f"{url} (query {json.dumps(query)})", {"contains": uniq(facts, 40)}, query)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-repo", required=True, type=Path)
    parser.add_argument("--other-repo", action="append", default=[], type=Path)
    args = parser.parse_args()
    if ROOT.exists():
        shutil.rmtree(ROOT)
    for label, step in [("pytest", lambda: build_pytest(args.source_repo)), ("unittest", build_unittest),
                        ("logs", lambda: build_logs(sys.executable)), ("json", build_json),
                        ("diffs", lambda: build_diffs([args.source_repo, *args.other_repo])), ("openapi", build_openapi)]:
        print(label)
        step()
    print(f"wrote {len(written)} samples to {ROOT}")


if __name__ == "__main__":
    main()
