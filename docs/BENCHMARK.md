# Benchmark: tokens saved, and what survived

Goal: when a tool shrinks output, show how many tokens it saved **and** whether the facts a reader needs are still there. Vendors usually report only the first number.

## Method

1. **Corpus.** Real tool output: pytest and unittest runs (with faults injected into a copy of a real project), Python and Node error logs and stack traces, real API responses (GitHub, PyPI, npm), real `git show` output from the author's repositories (including lockfile updates and a whitespace-only change), and OpenAPI examples. Paths and user names are scrubbed. Provenance: [bench/corpus/README.md](../bench/corpus/README.md).
2. **Must-keep facts.** For each sample, facts are extracted from the **raw** text by code (`bench/make_corpus.py`), never from a trimmer's output: failing test ids, assertion lines, the failing source line and its file:line, distinct error lines and exception messages, changed file paths and changed lines, JSON key paths (to depth 3), and for OpenAPI the operation ids, parameter names, status codes and paths of the operations a query selects.
3. **Scoring.** A tool's output is scored by the share of those facts it still contains (whitespace-insensitive substring match; for JSON key paths the output is parsed and its key paths compared). **Tokens saved** is token-weighted, so large samples dominate.
4. **Baselines.** `none` (the original) and `naive`: head-and-tail line truncation to **the same token budget** as whittle on that sample. Any tool can be added: `whittle bench --tool NAME=COMMAND` (the command reads the sample on stdin and writes the result on stdout).

## Results

### Development corpus (48 samples)
Token counter: `tiktoken:o200k_base`. Savings are token-weighted; retention is the average share of must-keep facts present.

| Input kind | Tool | Samples | Tokens saved | Facts retained | Samples with every fact |
|---|---|---:|---:|---:|---:|
| tests | none | 12 | 0.0% | 100.0% | 12/12 |
| tests | naive | 12 | 47.6% | 95.6% | 8/12 |
| tests | whittle | 12 | 46.9% | 100.0% | 12/12 |
| log | none | 6 | 0.0% | 100.0% | 6/6 |
| log | naive | 6 | 95.8% | 95.8% | 5/6 |
| log | whittle | 6 | 95.7% | 100.0% | 6/6 |
| json | none | 11 | 0.0% | 100.0% | 11/11 |
| json | naive | 11 | 44.5% | 95.4% | 4/11 |
| json | whittle | 11 | 44.5% | 100.0% | 11/11 |
| diff | none | 12 | 0.0% | 100.0% | 12/12 |
| diff | naive | 12 | 60.1% | 86.0% | 5/12 |
| diff | whittle | 12 | 60.0% | 100.0% | 12/12 |
| openapi | none | 7 | 0.0% | 100.0% | 7/7 |
| openapi | naive | 7 | 83.9% | 35.3% | 0/7 |
| openapi | whittle | 7 | 83.3% | 100.0% | 7/7 |
| all | none | 48 | 0.0% | 100.0% | 48/48 |
| all | naive | 48 | 53.3% | 84.4% | 22/48 |
| all | whittle | 48 | 53.3% | 100.0% | 48/48 |

### Held-out set (16 samples)
Built **after** the trimmers were written, from a different codebase (whittle-mcp's own test suite with injected faults), different API endpoints and different log shapes: `bench/make_holdout.py`.
Token counter: `tiktoken:o200k_base`. Savings are token-weighted; retention is the average share of must-keep facts present.

| Input kind | Tool | Samples | Tokens saved | Facts retained | Samples with every fact |
|---|---|---:|---:|---:|---:|
| tests | none | 7 | 0.0% | 100.0% | 7/7 |
| tests | naive | 7 | 8.1% | 87.9% | 2/7 |
| tests | whittle | 7 | 7.2% | 100.0% | 7/7 |
| log | none | 3 | 0.0% | 100.0% | 3/3 |
| log | naive | 3 | 94.9% | 66.7% | 2/3 |
| log | whittle | 3 | 94.9% | 100.0% | 3/3 |
| json | none | 6 | 0.0% | 100.0% | 6/6 |
| json | naive | 6 | 55.9% | 93.0% | 3/6 |
| json | whittle | 6 | 55.9% | 100.0% | 6/6 |
| all | none | 16 | 0.0% | 100.0% | 16/16 |
| all | naive | 16 | 61.3% | 85.8% | 7/16 |
| all | whittle | 16 | 61.3% | 100.0% | 16/16 |

## Reading these results honestly

- **The development corpus was in view while the trimmers were written** (for example, JSON array sampling was changed after a loss showed up). A perfect score there is optimistic. The held-out set exists for that reason, and it is small; it covers tests, logs and JSON, not diffs or OpenAPI.
- **The key-path check stops at depth 3 and the samples have fairly uniform arrays.** A trimmer that keeps every key path in these samples can still drop one in an array of mixed values; whittle reports that case honestly in the README rather than claiming completeness.
- **The facts are the author's choice.** They are objective in the sense that code extracts them from the raw text, but a different reader might care about other lines. If you find output a trimmer shrank and something you needed went missing, that is a bug report, and a new sample.
- **Naive truncation is an easy baseline.** It shows why trimming by structure matters, not that whittle beats every other tool.
- **Short inputs save little.** On the held-out test output (short `pytest -q` runs) whittle saved about 7%: there was little to remove.
- **No other tool has been benchmarked yet.** RTK, sqz, szr, ContextZip and TokenDiet MCP report large savings; they are not in these tables. Most are single-purpose binaries (Rust or Go) or MCP servers that do not read stdin, so a fair comparison needs wrappers and reproducible settings. Contributions are welcome.
- **Task success is not measured.** The tables show that the facts are present, not that an agent solves tasks as well with trimmed output. A small real-agent A/B is planned as a separate, clearly labelled experiment.
- **Token counts use `tiktoken` `o200k_base`.** Other providers tokenise differently; use `--counter estimate` for a deterministic count with no data download.

## Reproduce

```bash
pip install -e ".[dev]"
whittle bench --fail-under-retention 100
whittle bench --corpus bench/holdout --fail-under-retention 100
```
