"""The MCP server. Tools take a file path (or, if you allow it, a command), so the big text never has to pass through the model."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from whittle_mcp import __version__
from whittle_mcp.engine import Whittle
from whittle_mcp.prices import load_prices
from whittle_mcp.store import Store
from whittle_mcp.tokens import get_counter

MAX_BYTES = 20 * 1024 * 1024
INSTRUCTIONS = (
    "Use these tools when a command or file would produce long output (test runs, logs, JSON, diffs, API specs). "
    "Pass a file path, not the text itself: sending the text through a tool call costs the tokens you want to save. "
    "Every result ends with a receipt line. Omitted parts are marked and can be fetched back with `expand`."
)
PATH = Annotated[str | None, Field(description="File to read, inside the server's root folder. Preferred way to pass input.")]
TEXT = Annotated[str | None, Field(description="The text itself. Only for small inputs: large text costs tokens to send.")]
COMMAND = Annotated[str | None, Field(description="A command to run and trim (no shell). Only works if started with --allow-run.")]


TOOL_NAMES = {"tests": "trim_tests", "log": "trim_log", "json": "mask_json", "diff": "trim_diff", "openapi": "slice_openapi",
              "expand": "expand", "report": "report"}


def build_server(root: Path, allow_run: bool = False, store_dir: Path | None = None, tools: list[str] | None = None) -> MCPServer:
    root = root.resolve()
    engine = Whittle(counter=get_counter(), store=Store(store_dir))
    hint = ToolAnnotations(read_only_hint=not allow_run, destructive_hint=allow_run, idempotent_hint=False, open_world_hint=False)
    server = MCPServer("whittle-mcp", instructions=INSTRUCTIONS, version=__version__)

    def source(path: str | None, text: str | None, command: str | None) -> str:
        given = [x for x in (path, text, command) if x]
        if len(given) != 1:
            raise ValueError("Give exactly one of path, text or command.")
        if text is not None:
            return text
        if path:
            target = (root / path).resolve()
            if not target.is_relative_to(root):
                raise ValueError(f"{path!r} is outside the root folder {root}.")
            if not target.is_file():
                raise ValueError(f"{path!r} is not a file.")
            if target.stat().st_size > MAX_BYTES:
                raise ValueError(f"{path!r} is larger than {MAX_BYTES // (1024 * 1024)} MB.")
            return target.read_text(encoding="utf-8", errors="replace")
        if not allow_run:
            raise ValueError("Running commands is off. Start the server with --allow-run, or pass a file path.")
        argv = shlex.split(command or "", posix=os.name != "nt")
        done = subprocess.run(argv, cwd=root, capture_output=True, timeout=120, check=False)  # noqa: S603 - opt-in, no shell
        out = (done.stdout + (b"\n" + done.stderr if done.stderr else b""))[:MAX_BYTES].decode("utf-8", "replace")
        return f"[exit code {done.returncode}]\n{out}"

    @server.tool(annotations=hint)
    def trim_tests(path: PATH = None, text: TEXT = None, command: COMMAND = None,
                   max_failure_lines: Annotated[int, Field(description="Most lines kept per failure.")] = 60) -> str:
        """Shrink test-runner output (pytest, unittest, jest, go test, cargo test) to the failures and the summary.
        Use it instead of reading a whole test log. Omitted parts can be fetched with expand."""
        return engine.trim("tests", source(path, text, command), max_failure_lines=max_failure_lines).render()

    @server.tool(annotations=hint)
    def trim_log(path: PATH = None, text: TEXT = None, command: COMMAND = None,
                 head: Annotated[int, Field(description="First lines always kept.")] = 5,
                 tail: Annotated[int, Field(description="Last lines always kept.")] = 25) -> str:
        """Shrink a log or stack trace: repeated lines collapse, long tracebacks keep their last frames, every distinct
        error line stays. Use it instead of reading a whole log."""
        return engine.trim("log", source(path, text, command), head=head, tail=tail).render()

    @server.tool(annotations=hint)
    def mask_json(path: PATH = None, text: TEXT = None, command: COMMAND = None,
                  max_items: Annotated[int, Field(description="Array items kept.")] = 3,
                  max_string: Annotated[int, Field(description="Characters kept per long string.")] = 120,
                  max_depth: Annotated[int, Field(description="Nesting levels shown before summarising.")] = 6) -> str:
        """Show the shape of a large JSON document: every key path stays, long arrays and strings are shortened.
        Use it to see what a big API response contains; fetch details with expand and a path such as $.items[3]."""
        return engine.trim("json", source(path, text, command), max_items=max_items, max_string=max_string,
                           max_depth=max_depth).render()

    @server.tool(annotations=hint)
    def trim_diff(path: PATH = None, text: TEXT = None, command: COMMAND = None,
                  context: Annotated[int, Field(description="Unchanged lines kept around each change.")] = 1) -> str:
        """Shrink a git unified diff: lockfiles, generated files and whitespace-only changes collapse to one line each,
        and context around changes is cut. The result is for reading, not for applying."""
        return engine.trim("diff", source(path, text, command), context=context).render()

    @server.tool(annotations=hint)
    def slice_openapi(path: PATH = None, text: TEXT = None, command: COMMAND = None,
                      paths: Annotated[list[str] | None, Field(description="Path patterns such as /repos/*/issues*.")] = None,
                      tags: Annotated[list[str] | None, Field(description="Only operations with one of these tags.")] = None,
                      operation_ids: Annotated[list[str] | None, Field(description="Only these operation ids.")] = None,
                      methods: Annotated[list[str] | None, Field(description="Only these HTTP methods.")] = None,
                      index: Annotated[bool, Field(description="List operations only, no details.")] = False) -> str:
        """Read a large OpenAPI document cheaply: with no filters you get an index of operations; with filters you get
        only the matching operations and the schemas they use."""
        return engine.trim("openapi", source(path, text, command), paths=paths, tags=tags, operation_ids=operation_ids,
                           methods=methods, index=index).render()

    @server.tool(annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False))
    def expand(id: Annotated[str, Field(description="The id printed in an omitted-lines marker or receipt.")],
               lines: Annotated[str | None, Field(description="START-END, as printed in the marker.")] = None,
               path: Annotated[str | None, Field(description="For JSON inputs: a path such as $.items[3].")] = None) -> str:
        """Get back text that a trim omitted. Give the id and, ideally, the line range or JSON path from the marker."""
        return engine.expand(id, lines=lines, path=path)

    @server.tool(annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False))
    def report(later_turns: Annotated[int, Field(description="How many more turns each output stays in context.")] = 10,
               cached: Annotated[bool, Field(description="Assume prompt caching.")] = True) -> str:
        """Tokens saved in this session, net of anything re-expanded, and the money saved at EXAMPLE prices."""
        data = engine.report(load_prices(), later_turns, cached)
        return "\n".join(f"{k}: {v}" for k, v in data.items())

    if tools:
        unknown = [name for name in tools if name not in TOOL_NAMES]
        if unknown:
            raise ValueError(f"unknown tool(s) {unknown}; choose from {', '.join(TOOL_NAMES)}")
        keep = {TOOL_NAMES[name] for name in tools} | {"expand"}      # expand always stays: markers point at it
        for full in set(TOOL_NAMES.values()) - keep:
            server.remove_tool(full)
    return server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="whittle-mcp", description="whittle-mcp MCP server (stdio)")
    parser.add_argument("--root", default=".", help="folder the tools may read from (default: current folder)")
    parser.add_argument("--allow-run", action="store_true", help="let the tools run a command and trim its output")
    parser.add_argument("--store-dir", help="keep omitted text on disk here (default: memory only)")
    parser.add_argument("--tools", help="comma-separated subset to expose, fewer tools cost fewer tokens per turn "
                                        f"({', '.join(TOOL_NAMES)}); default: all")
    args = parser.parse_args(argv)
    chosen = [name.strip() for name in args.tools.split(",")] if args.tools else None
    build_server(Path(args.root), args.allow_run, Path(args.store_dir) if args.store_dir else None, chosen).run()


if __name__ == "__main__":
    main()
