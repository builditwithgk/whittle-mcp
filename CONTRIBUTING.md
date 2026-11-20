# Contributing

The most useful contribution is **a sample that breaks a trimmer**: output where whittle shrank the text and something you needed went missing.

1. Put the raw text in `bench/corpus/<kind>/<name>.txt` (kinds: `tests`, `log`, `json`, `diff`, `openapi`). Remove secrets and personal data first.
2. Add `<name>.json` next to it:
   ```json
   {"kind": "log", "options": {}, "source": "where it came from",
    "facts": {"contains": ["the exact lines that must survive"], "json_paths": []}}
   ```
   Facts must be text that is in the raw file. For JSON samples use `json_paths` (for example `$[].draft`).
3. `whittle bench` should now show a loss. Open a pull request with the sample; the fix can come with it or after.

## Development

```bash
pip install -e ".[dev]"
pytest -q && ruff check . && mypy src
whittle bench --fail-under-retention 100
```
- The trimming core (everything except `server.py`) stays **pure standard library**: it also runs in the browser through Pyodide.
- Every behaviour change needs a test. Trimmers only select and mark lines; they must never invent text (a test checks this).
- Be honest about limits: if a change does not fully fix a case, say what remains in the README.
