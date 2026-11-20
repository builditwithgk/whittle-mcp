# Security

whittle-mcp reads files and, only if you start it with `--allow-run`, runs commands you give it. It keeps the text it trims in a temporary folder so that `expand` works.

- **Found a way for the MCP tools to read outside `--root`, or to run a command without `--allow-run`?** Please use GitHub's private vulnerability reporting on this repository's Security tab.
- **Trimmed output hid something important?** That is not a security issue; open a "A trimmer lost something I needed" issue.
- **Secrets:** logs can contain secrets. Use `--no-store` to keep nothing on disk, and delete the temp store folder (`$WHITTLE_DIR`, or `whittle-store` in your temp directory) when you are done.
