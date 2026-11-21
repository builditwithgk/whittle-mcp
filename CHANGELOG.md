# Changelog

## 0.1.1
- Listing metadata for the official MCP Registry (`server.json`, an `mcp-name` marker in the README) and Glama (`glama.json`). No code changes.

## 0.1.0
First version. Fixes made after a fresh-agent walkthrough of the first build, before any release:
- Windows: the CLI reads and writes UTF-8 bytes, so a narrow console code page can no longer crash it or garble text; CRLF and carriage-return output is normalised, and the store no longer writes `\r\r\n`.
- CLI: a missing file or an unknown id gives a clear message and a non-zero exit code; closing a pipe early (`| head`) is quiet.
- MCP server: refusals (path outside the root, commands off, wrong arguments) now reach the agent with their reason.
- Logs: errors that differ in ids or codes are no longer merged into one counted line; collapsed repeats say which original lines they cover; Java `Caused by:` lines and `SomeException` names are kept.
- Test runners: Go failure messages that come before `--- FAIL`, and Cargo `... FAILED` lines, are kept.
- JSON: numbers (`1e400`, 30-digit integers) and duplicate keys are kept exactly; deeply nested input is returned unchanged instead of crashing.
- OpenAPI: path-level parameters, top-level `security`, `securitySchemes`, and Swagger 2 `definitions` / `parameters` / `securityDefinitions` are kept; unreadable input says why in the receipt.
- Diff: an indentation change in Python or YAML is no longer collapsed as whitespace-only.
- Second walkthrough: a very long single line no longer makes the log trimmer quadratic (a 160 KB line took about a minute, now milliseconds); very long lines keep their head and tail; terminal colour codes are removed; common failure phrases without a level keyword are kept and errors beyond the third of a shape are counted (`N more like ...`); RSpec, Mocha and TAP output is understood and unrecognised test output is returned unchanged; JSON arrays of mixed kinds show later items that add a key or a kind of value; a rename with a quoted non-ASCII name is no longer hidden, and diff +/- totals count every changed line; UTF-16 and BOM files are read; a pasted marker (`lines=45-356`) works as printed; the MCP command runner honours Windows quoting and reports failures with their reason; invalid arguments are rejected; the report says when token counters were mixed.
- Docs: how to get exact token counts, where the store lives, what is and is not collapsed, and that the benchmark needs a git clone.
