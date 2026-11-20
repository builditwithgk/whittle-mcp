"""Command line: a filter for any agent's shell (`pytest 2>&1 | whittle tests`), plus expand, report and bench."""

from __future__ import annotations

import argparse
import codecs
import json
import os
import sys
from pathlib import Path

from whittle_mcp import __version__
from whittle_mcp.engine import Whittle
from whittle_mcp.prices import EXAMPLE_PRICES, load_prices
from whittle_mcp.store import Store, default_directory
from whittle_mcp.tokens import get_counter


class CliError(Exception):
    """A problem the user can fix; printed without a traceback."""


def _decode(data: bytes) -> str:
    """UTF-8 (with or without a BOM) and UTF-16 (what Windows PowerShell 5.1 writes for `>`); anything else is read as cp1252."""
    if data.startswith(codecs.BOM_UTF8):
        return data[len(codecs.BOM_UTF8):].decode("utf-8", "replace")
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16", "replace")
    if len(data) > 3 and data[1:2] == bytes(1) and data[3:4] == bytes(1):   # UTF-16 LE without a BOM, ASCII text
        return data.decode("utf-16-le", "replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", "replace")


def _read(source: str) -> str:
    return _decode(sys.stdin.buffer.read() if source == "-" else Path(source).read_bytes())


def _write(text: str) -> None:
    """Write UTF-8 bytes, so a Windows console code page can never crash the filter or garble the text."""
    data = (text if text.endswith(chr(10)) else text + chr(10)).encode("utf-8", "replace")
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(data)
        buffer.flush()
    else:
        sys.stdout.write(data.decode("utf-8"))


def _engine(args: argparse.Namespace) -> Whittle:
    directory = None if getattr(args, "no_store", False) else Path(args.store_dir) if args.store_dir else default_directory()
    try:
        counter = get_counter(args.counter)
    except Exception as exc:  # noqa: BLE001 - tiktoken missing, or it could not download its data
        raise CliError(f"the {args.counter} token counter is not available ({type(exc).__name__}); try --counter estimate") from exc
    try:
        return Whittle(counter=counter, store=Store(directory))
    except OSError as exc:
        raise CliError(f"cannot use the store folder {directory}: {exc.strerror or exc}") from exc


def _log_event(engine: Whittle, event: dict) -> None:
    directory = engine.store.directory
    if directory:
        with (directory / "stats.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--store-dir", help="where omitted text is kept (default: a temp folder, or $WHITTLE_DIR)")
    p.add_argument("--counter", choices=["auto", "estimate", "tiktoken"], default="auto", help="token counter (default: auto)")
    p.add_argument("--quiet", action="store_true", help="do not print the receipt on stderr")


def _trimmer(sub: argparse._SubParsersAction, name: str, help_text: str) -> argparse.ArgumentParser:
    p = sub.add_parser(name, help=help_text)
    p.add_argument("file", nargs="?", default="-", help="a file, or - for standard input (default)")
    p.add_argument("--no-store", action="store_true", help="do not keep the full input (markers then cannot be expanded)")
    _add_common(p)
    return p


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="whittle", description="Trim what your agent reads, and measure what it kept.")
    parser.add_argument("--version", action="version", version=f"whittle-mcp {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = _trimmer(sub, "tests", "test-runner output: keep failures and the summary")
    p.add_argument("--max-failure-lines", type=int, default=60)
    p = _trimmer(sub, "log", "logs and stack traces: collapse repeats, keep distinct errors")
    p.add_argument("--head", type=int, default=5)
    p.add_argument("--tail", type=int, default=25)
    p = _trimmer(sub, "json", "JSON: keep the shape, shorten long arrays and strings")
    p.add_argument("--max-items", type=int, default=3)
    p.add_argument("--max-string", type=int, default=120)
    p.add_argument("--max-depth", type=int, default=6)
    p = _trimmer(sub, "diff", "git unified diff: collapse lockfiles, generated files and whitespace-only changes")
    p.add_argument("--context", type=int, default=1)
    p = _trimmer(sub, "openapi", "OpenAPI document: an index, or only the operations you ask for")
    p.add_argument("--path", action="append", dest="paths", help="path pattern, e.g. '/repos/*/issues*' (repeatable)")
    p.add_argument("--tag", action="append", dest="tags")
    p.add_argument("--operation-id", action="append", dest="operation_ids")
    p.add_argument("--method", action="append", dest="methods")
    p.add_argument("--index", action="store_true", help="list operations only")
    p = sub.add_parser("expand", help="print what a marker omitted")
    p.add_argument("id")
    p.add_argument("marker_args", nargs="*", help="the rest of a marker, pasted as printed: lines=45-356 or path=$.items")
    p.add_argument("--lines", help="START-END, as printed in the marker")
    p.add_argument("--path", help="for JSON: a path such as $.items[3]")
    _add_common(p)
    p = sub.add_parser("report", help="tokens and money saved by the trims recorded in the store folder")
    p.add_argument("--prices", help="JSON price table (default: clearly labelled examples)")
    p.add_argument("--later-turns", type=int, default=10, help="how many more turns the output stays in context")
    p.add_argument("--no-cache", action="store_true", help="assume no prompt caching")
    p.add_argument("--json", action="store_true")
    _add_common(p)
    sub.add_parser("prices", help="print the example price table you can copy and edit")
    p = sub.add_parser("bench", help="retention-checked benchmark of a trimmer against a corpus")
    p.add_argument("--corpus", default="bench/corpus")
    p.add_argument("--tool", action="append", default=[], help="NAME=COMMAND to benchmark another trimmer (stdin to stdout)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--markdown", action="store_true")
    p.add_argument("--counter", choices=["auto", "estimate", "tiktoken"], default="auto")
    p.add_argument("--fail-under-retention", type=float, help="exit with an error if whittle keeps fewer facts than this percent (for CI)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(errors="backslashreplace")
    try:
        return _run(args)
    except CliError as exc:
        print(f"whittle: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"whittle: cannot read {exc.filename}: file not found", file=sys.stderr)
        return 2
    except (IsADirectoryError, PermissionError) as exc:
        what = "a folder, not a file" if os.path.isdir(exc.filename or "") else "not readable (permission denied)"
        print(f"whittle: {exc.filename} is {what}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"whittle: cannot read {exc.filename or 'input'}: {exc.strerror or exc}", file=sys.stderr)
        return 2
    except BrokenPipeError:   # for example `whittle expand ID | head`
        try:
            sys.stdout = open(os.devnull, "w")  # noqa: SIM115 - stop the interpreter complaining again at exit
        except OSError:
            pass
        return 0


def _run(args: argparse.Namespace) -> int:
    if args.cmd == "prices":
        print(json.dumps(EXAMPLE_PRICES, indent=2))
        return 0
    if args.cmd == "bench":
        from whittle_mcp.bench import run_cli
        return run_cli(args)
    engine = _engine(args)
    if args.cmd == "expand":
        lines, path = args.lines, args.path
        for token in args.marker_args:
            key, _, value = token.partition("=")
            if key == "lines" and value:
                lines = value
            elif key == "path" and value:
                path = value
            else:
                raise CliError(f"unexpected argument {token!r}; use lines=START-END or path=$.json.path as printed in the marker")
        out, ok = engine.expand_checked(args.id, lines=lines, path=path)
        if not ok:
            print(f"whittle: {out}", file=sys.stderr)
            return 1
        _write(out)
        _log_event(engine, engine.events[-1])
        return 0
    if args.cmd == "report":
        return _report(engine, args)
    options = {k: v for k, v in vars(args).items()
               if k in ("max_failure_lines", "head", "tail", "max_items", "max_string", "max_depth", "context", "paths",
                        "tags", "operation_ids", "methods", "index") and v is not None}
    result = engine.trim(args.cmd, _read(args.file), keep_original=not args.no_store, **options)
    _write(result.text)
    if not args.quiet:
        print(result.receipt(), file=sys.stderr)
    _log_event(engine, engine.events[-1])
    return 0


def _report(engine: Whittle, args: argparse.Namespace) -> int:
    directory = engine.store.directory
    stats = directory / "stats.jsonl" if directory else None
    if not stats or not stats.is_file():
        print("Nothing recorded yet. Trim something first (stats are kept in the store folder).", file=sys.stderr)
        return 1
    engine.events = [json.loads(line) for line in stats.read_text(encoding="utf-8").splitlines() if line.strip()]
    data = engine.report(load_prices(args.prices), args.later_turns, cached=not args.no_cache)
    if args.json:
        print(json.dumps(data, indent=2))
        return 0
    print(f"trims: {data['calls']}   raw: {data['raw_tokens']:,}   returned: {data['returned_tokens']:,}   "
          f"re-expanded: {data['expanded_tokens']:,}")
    print(f"net tokens saved: {data['net_saved_tokens']:,} ({data['net_saved_percent']}%)   counter: {data['counter']}")
    print(f"(adds up every trim recorded in {directory}, including earlier projects; set WHITTLE_DIR per project to separate them)")
    print(f"assumes each output stays in context for {data['later_turns_assumed']} more turns, "
          f"{'with' if data['cached_assumed'] else 'without'} prompt caching")
    note = "EXAMPLE prices" if not args.prices else f"prices from {args.prices}"
    for name, usd in data["saved_usd_at_example_prices"].items():
        print(f"  {name}: ${usd:.4f} saved ({note})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
