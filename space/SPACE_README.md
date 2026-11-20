---
title: whittle-mcp
emoji: ✂️
colorFrom: blue
colorTo: green
sdk: static
pinned: false
license: mit
short_description: Trim test logs, JSON and diffs and see what was kept
tags:
  - mcp
  - llm
  - tokens
  - context
  - ai-agents
  - developer-tools
  - pyodide
---

# ✂️ whittle-mcp

**Trim what your agent reads, and measure what it kept.**

Paste a test log, a stack trace, a big JSON response, a git diff or an OpenAPI document and see what is kept, how many tokens that saves, and what was omitted (every omitted part can be expanded). It runs in your browser with Python (Pyodide); what you paste stays in the tab.

- **Source, CLI and MCP server:** https://github.com/builditwithgk/whittle-mcp
- `pip install whittle-mcp` or `uvx whittle-mcp`
- Token counts here are an estimate; the CLI uses tiktoken.

Built by [Gopi K Aitham (builditwithgk)](https://github.com/builditwithgk) at [Scaleup Solutions](https://scaleup-solutions.in/).
