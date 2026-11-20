import asyncio
import io
import json
import sys

import pytest
from conftest import PYTEST_FAIL
from whittle_mcp.cli import main
from whittle_mcp.server import build_server


def run_cli(monkeypatch, capsys, args, stdin=""):
    monkeypatch.setattr(sys, "stdin", type("S", (), {"buffer": io.BytesIO(stdin.encode("utf-8"))})())
    code = main(args)
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli_filter_expand_and_report(monkeypatch, capsys, tmp_path):
    store = ["--store-dir", str(tmp_path), "--counter", "estimate"]
    code, out, err = run_cli(monkeypatch, capsys, ["tests", *store], PYTEST_FAIL * 3)
    assert code == 0 and "test_parse_dates_utc" in out and "[whittle tests]" in err
    handle = err.split("whittle expand ")[1].split()[0]
    code, out, _ = run_cli(monkeypatch, capsys, ["expand", handle, "--lines", "1-3", *store])
    assert "test session starts" in out
    code, out, _ = run_cli(monkeypatch, capsys, ["report", "--json", *store])
    data = json.loads(out)
    assert data["calls"] == 1 and data["expanded_tokens"] > 0 and data["counter"].startswith("estimate")


def test_cli_quiet_and_no_store(monkeypatch, capsys, tmp_path):
    _, out, err = run_cli(monkeypatch, capsys, ["tests", "--quiet", "--no-store", "--store-dir", str(tmp_path), "--counter", "estimate"],
                          PYTEST_FAIL * 3)
    assert err == "" and "whittle expand" not in out and not list(tmp_path.glob("*.txt"))


def test_cli_prices_and_bad_args(monkeypatch, capsys):
    _, out, _ = run_cli(monkeypatch, capsys, ["prices"])
    assert "EXAMPLE" in out
    with pytest.raises(SystemExit):
        main(["nonsense"])


def call(server, name, **args):
    return asyncio.run(server.call_tool(name, args))


def text_of(result):
    return result.content[0].text


def test_server_lists_the_seven_tools_with_read_only_hints(tmp_path):
    server = build_server(tmp_path)
    tools = asyncio.run(server.list_tools())
    assert {t.name for t in tools} == {"trim_tests", "trim_log", "mask_json", "trim_diff", "slice_openapi", "expand", "report"}
    assert all(t.annotations.read_only_hint for t in tools)          # nothing runs commands by default


def test_server_reads_files_inside_root_only_and_appends_a_receipt(tmp_path):
    (tmp_path / "out.txt").write_text(PYTEST_FAIL * 3, encoding="utf-8")
    server = build_server(tmp_path)
    result = text_of(call(server, "trim_tests", path="out.txt"))
    assert "test_total_with_tax" in result and "[whittle tests]" in result
    with pytest.raises(Exception):
        call(server, "trim_tests", path="../outside.txt")
    with pytest.raises(Exception):
        call(server, "trim_tests", path="out.txt", text="also text")     # exactly one source


def test_server_commands_are_off_unless_allowed(tmp_path):
    with pytest.raises(Exception):
        call(build_server(tmp_path), "trim_log", command=f"{sys.executable} --version")


@pytest.mark.skipif(" " in sys.executable, reason="the test builds a command line from the interpreter path")
def test_server_runs_a_command_when_allowed(tmp_path):
    server = build_server(tmp_path, allow_run=True)
    tools = asyncio.run(server.list_tools())
    assert all(t.annotations.destructive_hint for t in tools if t.name.startswith(("trim", "mask", "slice")))
    out = text_of(call(server, "trim_log", command=f"{sys.executable} --version"))
    assert "Python" in out and "exit code 0" in out


def test_server_expand_and_report_round_trip(tmp_path):
    (tmp_path / "o.txt").write_text(PYTEST_FAIL * 3, encoding="utf-8")
    server = build_server(tmp_path)
    receipt = text_of(call(server, "trim_tests", path="o.txt")).splitlines()[-1]
    handle = receipt.split("whittle expand ")[1].split()[0]
    assert "test session starts" in text_of(call(server, "expand", id=handle, lines="1-3"))
    assert "net_saved_tokens" in text_of(call(server, "report"))


def test_server_can_expose_a_subset_to_save_definition_tokens(tmp_path):
    server = build_server(tmp_path, tools=["tests", "log"])
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {"trim_tests", "trim_log", "expand"}           # expand always stays: the markers point at it
    with pytest.raises(ValueError):
        build_server(tmp_path, tools=["nonsense"])
