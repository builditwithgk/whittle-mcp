# Corpus provenance

Every sample is `name.txt` (the raw text) plus `name.json` (kind, options, source, and the must-keep facts). Built by `bench/make_corpus.py`; user names and local paths are scrubbed.

| Kind | Source | Licence / terms |
|---|---|---|
| tests | `pytest` runs on copies of the author's MIT-licensed project `agent-firebreak` with injected faults; `unittest` runs on a tiny module written for this corpus | MIT |
| log | Output of small Python and Node scripts written for this corpus; `pip install` of a package that does not exist | MIT |
| json | Public API responses: GitHub REST API (public repositories, no email addresses), PyPI JSON API, npm registry | Public metadata; provenance in each `.json` |
| diff | `git show` output from the author's own MIT-licensed repositories (`agent-firebreak`, `mcp-reportcard`, `repo-cartographer`), plus one synthetic whitespace-only change | MIT |
| openapi | Swagger Petstore (Apache-2.0) and the OpenAPI Initiative's example documents (Apache-2.0) | Apache-2.0 |

To add a sample, see CONTRIBUTING.md. Please do not submit text containing secrets, personal data or anything you do not have the right to share.
