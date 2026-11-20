#!/usr/bin/env bash
# Assemble the static Space into a folder: bash space/build.sh [OUT_DIR]   (default: space/_site)
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="${1:-space/_site}"
mkdir -p "$OUT/samples"
python - "$OUT" <<'PY'
import pathlib, shutil, sys, zipfile
out = pathlib.Path(sys.argv[1]); root = pathlib.Path("src")
with zipfile.ZipFile(out / "whittle_mcp.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for p in sorted((root / "whittle_mcp").rglob("*.py")):
        if p.name == "server.py" or "__pycache__" in p.parts:   # the MCP server needs the `mcp` package, the core does not
            continue
        z.write(p, p.relative_to(root).as_posix())
shutil.copy("space/index.html", out / "index.html")
shutil.copy("space/SPACE_README.md", out / "README.md")
samples = {
    "tests.txt": "bench/corpus/tests/pytest-m1-default-allow-v.txt",
    "log.txt": "bench/corpus/log/py-logging-noisy.txt",
    "json.txt": "bench/corpus/json/gh-flask-issues.txt",
    "diff.txt": "bench/corpus/diff/mcpreportcard-repo-c594da2.txt",
    "openapi.txt": "bench/corpus/openapi/petstore3-q1.txt",
}
for name, src in samples.items():
    shutil.copy(src, out / "samples" / name)
PY
echo "built $OUT"
