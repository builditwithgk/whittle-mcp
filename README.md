# whittle-mcp

**Trim what your agent reads, and measure what it kept.**

Coding agents spend most of their tokens re-reading tool output: test runs, logs and stack traces, big JSON, diffs and API specs. Every result stays in the conversation and is re-sent on every later turn. whittle-mcp shrinks that output *without losing the facts*, and it proves what it kept.

- **Five trimmers:** test output, logs, JSON, git diffs, OpenAPI documents.
- **Nothing is lost.** What it removes is replaced by a short marker such as `[... 312 lines omitted: whittle expand a1b2c3d4 lines=45-356 ...]`, and `expand` returns exactly that part on request.
- **Two ways to use it:** an MCP server (`uvx whittle-mcp`) and a pipe for any shell (`pytest 2>&1 | whittle tests`).
- **Measured, not claimed:** every trimmer is scored on how many tokens it saves *and* how many must-keep facts survive, on a public corpus. See [docs/BENCHMARK.md](docs/BENCHMARK.md).

**Try it in your browser, nothing to install or send anywhere:** https://huggingface.co/spaces/builditwithgk/whittle-mcp (paste a test log, JSON or diff and see what is kept).

## Install and use

```bash
pip install whittle-mcp          # or: uvx whittle-mcp
pip install "whittle-mcp[tokens]"   # optional: exact token counts with tiktoken (otherwise an estimate, labelled)
pip install "whittle-mcp[yaml]"     # optional: read YAML OpenAPI documents
```

**As a filter in any agent's shell** (the simplest way, and it works with every agent):

```bash
pytest 2>&1 | whittle tests          # failures and the summary, not 4,000 dots and passes
npm test 2>&1 | whittle tests
git diff | whittle diff              # lockfiles and generated files collapse to one line each
curl -s https://api.example.com/items | whittle json
whittle log build.log                # repeats counted, long tracebacks shortened, every distinct error kept
whittle openapi spec.json --index    # one line per operation
whittle openapi spec.json --path '/pets*' --method get      # Git Bash on Windows rewrites a leading /: use MSYS_NO_PATHCONV=1 or --operation-id / --tag
whittle expand a1b2c3d4 lines=45-356       # get back what a marker omitted: paste the marker as printed (or use --lines 45-356)
whittle report                       # tokens saved so far, net of anything you expanded
```
The receipt (`[whittle tests] 12,431 -> 912 tokens (-92.7%) | full output: whittle expand a1b2c3d4 | counter: tiktoken:o200k_base`) goes to stderr, so pipes stay clean. Note that in a pipe the exit code is whittle's, not the test runner's: use `set -o pipefail` (bash) if a script needs the runner's status.

**As an MCP server:**

```bash
claude mcp add whittle -- uvx whittle-mcp --tools tests,log      # Claude Code, with just two trimmers
```
```json
{ "mcpServers": { "whittle": { "command": "uvx", "args": ["whittle-mcp"] } } }
```
The tools take a **file path** (or, if you start the server with `--allow-run`, a command). A `text` argument exists for small inputs, but sending a big text through a tool call costs the tokens you meant to save, so do not use it for large output. Refusals (a path outside the root, commands switched off) and command failures (not found, timed out) come back with their reason. A large input that is not in the format you asked for is not echoed back: you get its first lines and a hint. Typical use: the agent runs `pytest > out.log` and calls `trim_tests(path="out.log")`.

| Tool | What it does |
|---|---|
| `trim_tests` | pytest, unittest, jest, mocha, RSpec, TAP, go test, cargo test: failures with their assertions and locations, plus the summary. Any other format is returned unchanged |
| `trim_log` | adjacent repeats collapsed and counted, long tracebacks keep their last frames, the first three errors of each shape stay (and the rest are summarised as "N more like ...") |
| `mask_json` | object keys stay; arrays show their first three items plus up to three later ones that add a new key or a new kind of value; long strings are shortened; the result is still valid JSON |
| `trim_diff` | lockfiles, generated or vendored files and whitespace-only changes collapse; long runs of unchanged lines are cut |
| `slice_openapi` | an index of operations, or only the operations you ask for plus the schemas they use |
| `expand` | returns what a marker omitted, by line range or JSON path |
| `report` | tokens saved this session, net of anything re-expanded, and money saved at *your* prices |

## What it costs, honestly

The tool definitions themselves are sent every turn. Measured with [mcp-reportcard](https://github.com/builditwithgk/mcp-reportcard): all seven tools cost about **1,570 tokens** per turn; `--tools tests,log` (plus `expand`) costs about **610**. Expose only the trimmers you will use. On the benchmark corpus an average call saved several thousand tokens, so it pays for itself when the agent trims a long output every few turns; if your agent rarely produces long output, it will not.

## Results (public corpus, [methodology and caveats](docs/BENCHMARK.md))

Token counter: tiktoken `o200k_base`. "Naive" is head-and-tail truncation to the *same* token budget as whittle.

| Corpus | Samples | Tokens saved (whittle) | Facts kept: whittle | Facts kept: naive truncation |
|---|---:|---:|---:|---:|
| Development corpus (tests, logs, JSON, diffs, OpenAPI) | 48 | 53.3% | 100% | 84.4% |
| Held-out set (written after the trimmers) | 16 | 61.3% | 100% | 85.8% |

Savings depend on the input and are token-weighted, so large outputs dominate: logs shrank about 96%, OpenAPI slices 84%, diffs 60%, test output 47%. **Short outputs save little**: half the diffs and most short `pytest -q` runs in the corpus saved under 15%, and on the held-out set's short test runs the saving was 7%. **Honest limits of these numbers:** the corpus is small and was built by the author; the "must-keep facts" were chosen by the author (failing test ids and assertion lines, error lines, changed files, JSON key paths, operation ids); the development corpus was in view while the trimmers were written, which is why the held-out set exists; and **end-to-end agent success with and without trimming has not been measured yet**. Treat the numbers as a regression suite and a starting point. Samples that break it are the most useful contribution you can make.

## Cost, in dollars, with your prices

Provider prices change, so the tool never bakes one in. `whittle report` and the benchmark use an editable price table (`whittle prices` prints the format) and a stated model: a token you keep out of the context is saved on the turn it would have arrived and on every later turn it would have been re-sent, at the cache-read rate if you use prompt caching. **The default table holds clearly labelled example numbers, not any provider's real prices.**

## Limits

- It uses **rules, not a model**: common formats are handled well, and a format it does not recognise (a test runner it does not know, text that is not JSON) is returned unchanged, never mangled.
- Errors that differ **only in numbers** (order ids, codes) count as the same shape after the third occurrence; the rest are summarised (`N more like ...`) and are one `expand` away. Only *adjacent* repeats are collapsed and counted inline, and a failure with no recognisable keyword (no `ERROR`, no exception name, none of the common phrases such as `No space left on device` or `exited with code 137`) can fall into an omitted range.
- Terminal colour codes are removed, and a line longer than 1,000 characters keeps its first 700 and last 300.
- `trim_diff` output is for reading, not for applying. Lockfile bodies are collapsed, so a newly added dependency is not visible until you `expand` it: expand lockfiles when you review dependency changes. Files under `dist/`, `build/` or `vendor/` are treated as generated even if you wrote them. An indentation-only change is collapsed only for languages where it cannot change meaning; in Python and YAML it is shown.
- JSON: numbers and duplicate keys are kept exactly as written; arrays show the first three items (plus any that reveal other keys) and a string marker such as `... +497 more items`, and long strings are cut at 120 characters. Input nested more than about a thousand levels is returned unchanged.
- **Windows:** files written by PowerShell 5.1's `>` (UTF-16) and UTF-8 files with a BOM are read correctly, and output is always UTF-8. Text you *pipe* from PowerShell 5.1 is re-encoded by PowerShell itself (its `$OutputEncoding` is ASCII); set `$OutputEncoding = [Text.Encoding]::UTF8` or pass a file name instead.
- Installing pulls in the MCP SDK and its dependencies, even if you only use the command line.
- Small inputs are returned unchanged: there is nothing to gain from a short log (under about 40 lines) or a short test run (under 12 lines). CRLF line endings and carriage-return progress output are turned into plain lines first.
- Token counts differ between providers; `tiktoken` is used when installed, otherwise an estimate (`chars/4`, labelled).
- An agent only benefits if it calls the tool. The shell filter and a one-line instruction in your agent settings (below) help.
- The CLI keeps the full text you trim in one shared temp folder (`$WHITTLE_DIR`, default `whittle-store` in your temp directory) so `expand` works for 24 hours; the MCP server keeps it in memory unless you pass `--store-dir`, so ids from one do not work in the other. `whittle report` adds up everything in that folder, including earlier projects. Logs can contain secrets: use `--no-store` to keep nothing, or point `WHITTLE_DIR` at a folder per project.
- The MCP tools read files only inside `--root` (default: the current folder) and run commands only with `--allow-run`.

## How other tools relate

Command-output compressors such as RTK, sqz, szr and ContextZip, and MCP servers such as TokenDiet MCP, solve a neighbouring problem; Claude Code and the Anthropic API also clear old tool results. They report large savings (their own figures). whittle-mcp has **not** been benchmarked against them yet; `whittle bench --tool NAME=COMMAND` runs any stdin-to-stdout trimmer through the same corpus and fact check, and a fair, reproducible comparison is a good first contribution.

## Tell your agent to use it

Add to `CLAUDE.md`, `AGENTS.md` or your agent's rules:
```
For long command output, pipe it through whittle first: `pytest 2>&1 | whittle tests`, `git diff | whittle diff`,
`whittle log build.log`. Markers like "[... N lines omitted: whittle expand ID ...]" can be expanded with `whittle expand ID`.
```

## Benchmark and contribute

```bash
pip install -e ".[dev]"
pytest -q
whittle bench                              # the development corpus (needs a git clone: the corpus is not in the pip package)
whittle bench --corpus bench/holdout       # the held-out set
python bench/make_corpus.py --source-repo <a Python repo with tests and git history>   # rebuild the corpus
```
Add a sample by putting `name.txt` and `name.json` (kind, options, must-keep facts) in `bench/corpus/<kind>/`. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. Built by [Gopi K Aitham](https://github.com/builditwithgk) at [Scaleup Solutions](https://scaleup-solutions.in/).
