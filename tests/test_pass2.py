"""Regression tests for the second fresh-agent walkthrough. Each test is one reported problem."""

import asyncio
import codecs
import json
import sys
import time

import pytest
from whittle_mcp.cli import main
from whittle_mcp.engine import Whittle
from whittle_mcp.server import build_server
from whittle_mcp.store import Store
from whittle_mcp.tokens import get_counter
from whittle_mcp.trimmers import diffs, jsonmask, logs, tests

NL = chr(10)


def make():
    return Whittle(counter=get_counter("estimate"), store=Store())


def padded(line, before=50, after=50):
    return NL.join(["INFO line %d" % i for i in range(before)] + [line] + ["INFO tail %d" % i for i in range(after)])


# ---------------------------------------------------------------- the hang and very long lines
@pytest.mark.parametrize("line", ["x" * 160_000, "abcdefghij" * 16_000 + " ERROR in the middle " + "z" * 100, "A" * 160_000 + "Error"])
def test_one_very_long_line_cannot_make_the_log_trimmer_slow(line):
    started = time.perf_counter()
    logs.trim(padded(line))
    assert time.perf_counter() - started < 3.0


def test_a_very_long_kept_line_keeps_its_head_and_tail():
    line = "ERROR start " + "q" * 5000 + " the real cause at the end"
    out = logs.trim(padded(line)).text
    assert "ERROR start" in out and "the real cause at the end" in out and "chars" in out and len(out) < 3000


# ---------------------------------------------------------------- logs: failures without a level word, and repeat counts
def test_common_failure_phrases_without_a_level_keyword_are_kept():
    unique = ["step %s done" % "".join(chr(97 + (i // 26 ** k) % 26) for k in range(3)) for i in range(200)]
    unique[90:90] = ["write failed: No space left on device", "Container was OOMKilled", "process exited with code 137", "Permission denied (publickey)"]
    out = logs.trim(NL.join(unique)).text
    for phrase in ("No space left on device", "OOMKilled", "exited with code 137", "Permission denied"):
        assert phrase in out, phrase


def test_errors_of_a_shape_already_shown_are_counted_not_just_dropped():
    lines = []
    for i in range(60):
        lines.append("2026-11-20 10:00:%02d WARN slow query on orders (%d ms)" % (i % 60, 800 + i))
        lines.append("2026-11-20 10:00:%02d INFO processed order %s" % (i % 60, "".join(chr(97 + (i // 26 ** k) % 26) for k in range(3))))
    out = logs.trim(NL.join(lines)).text
    assert "more like:" in out and "WARN slow query" in out


# ---------------------------------------------------------------- test runners
def pad(lines, n=30):
    return NL.join(["setup line %d" % i for i in range(n)] + lines)


def test_rspec_failures_section_is_kept():
    rspec = pad(["Failures:", "", "  1) Calculator adds numbers", "     Failure/Error: expect(calc.add(2, 2)).to eq(5)", "       expected: 5", "            got: 4",
                 "     # ./spec/calc_spec.rb:12:in `block (2 levels)'", "", "Finished in 0.01 seconds", "9 examples, 1 failure"])
    out = tests.trim(rspec).text
    assert "Failure/Error" in out and "expected: 5" in out and "got: 4" in out and "9 examples, 1 failure" in out


def test_mocha_failures_and_summary_are_kept():
    mocha = pad(["  60 passing (1s)", "  1 failing", "", "  1) Array #indexOf should return -1:", "     AssertionError: expected 0 to equal -1", "      at Context.<anonymous> (test/a.js:9:14)"])
    out = tests.trim(mocha).text
    assert "60 passing" in out and "1 failing" in out and "expected 0 to equal -1" in out


def test_tap_failures_are_kept():
    tap = NL.join(["TAP version 13"] + ["ok %d - fine %d" % (i, i) for i in range(1, 40)] + ["not ok 40 - bad thing", "  ---", "  message: boom", "  ...", "1..40", "# tests 40", "# fail 1"])
    out = tests.trim(tap).text
    assert "not ok 40 - bad thing" in out and "message: boom" in out and "# fail 1" in out


def test_unrecognised_output_is_returned_unchanged():
    csv = NL.join("row%d,%d,value" % (i, i) for i in range(500))
    result = tests.trim(csv)
    assert not result.changed and result.text == csv and "not a recognised" in result.notes[0]


# ---------------------------------------------------------------- JSON
def test_json_arrays_of_mixed_kinds_still_show_later_key_paths():
    doc = json.dumps({"mixed": [1, "two", {"three": 3}, [4], None, True, 1.0, {"k": "v"}] + [0] * 50,
                      "a.b": list(range(50)) + [{"x": 1}, {"y": 2}], "arr": [[], [[]], {}, {"z": [1, 2, 3, 4, 5, 6]}]})
    out = jsonmask.trim(doc).text
    for key in ('"k"', '"x"', '"y"', '"z"'):
        assert key in out, key


# ---------------------------------------------------------------- diffs
def test_a_rename_with_a_quoted_non_ascii_name_is_visible_and_counted():
    d = ('diff --git "a/old name.txt" "b/n\\303\\253w name.txt"' + NL + "similarity index 100%" + NL + "rename from old name.txt" + NL
         + 'rename to "n\\303\\253w name.txt"' + NL + "diff --git a/b.py b/b.py" + NL + "index 1..2 100644" + NL + "--- a/b.py" + NL + "+++ b/b.py" + NL
         + "@@ -1 +1 @@" + NL + "-x = 1" + NL + "+x = 2" + NL)
    out = diffs.trim(d).text
    assert "rename to" in out and out.startswith("whittle diff: 2 files")


def test_removed_sql_comments_are_counted_and_not_called_whitespace_only():
    d = ("diff --git a/q.sql b/q.sql" + NL + "index 1..2 100644" + NL + "--- a/q.sql" + NL + "+++ b/q.sql" + NL + "@@ -1,2 +1,2 @@" + NL
         + "--- a comment" + NL + "+++ b comment" + NL + " keep" + NL)
    out = diffs.trim(d).text
    assert "+1 -1" in out.splitlines()[0] and "whitespace-only" not in out and "--- a comment" in out


# ---------------------------------------------------------------- engine
def test_terminal_colour_codes_are_stripped():
    w = make()
    red = chr(27) + "[31m"
    reset = chr(27) + "[0m"
    out = w.trim("log", padded(red + "ERROR red text" + reset)).text
    assert "ERROR red text" in out and chr(27) not in out


def test_report_says_when_counters_are_mixed():
    w = make()
    w.events = [{"event": "trim", "kind": "log", "raw": 100, "out": 10, "handle": None, "counter": "estimate:chars/4"},
                {"event": "trim", "kind": "log", "raw": 100, "out": 10, "handle": None, "counter": "tiktoken:o200k_base"}]
    assert w.report()["counter"].startswith("mixed")


def test_expand_rejects_backwards_ranges_and_both_lines_and_path():
    w = make()
    handle = w.store.put(NL.join("line %d" % i for i in range(20)))
    for bad in ("9-2", "5-", "0-5", "abc"):
        assert w.expand_checked(handle, lines=bad)[1] is False, bad
    assert w.expand_checked(handle, lines="1-2", path="$.a")[1] is False
    assert w.expand_checked(handle, lines="3")[1] is True


# ---------------------------------------------------------------- CLI
def run_cli(monkeypatch, capsys, args, stdin=b""):
    import io
    monkeypatch.setattr(sys, "stdin", type("S", (), {"buffer": io.BytesIO(stdin)})())
    code = main(args)
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli_reads_utf16_utf8_bom_and_cp1252_input(monkeypatch, capsys, tmp_path):
    text = "ERROR caf" + chr(0xE9) + " failed"
    for data in (codecs.BOM_UTF16_LE + text.encode("utf-16-le"), codecs.BOM_UTF8 + text.encode("utf-8"), text.encode("cp1252")):
        code, out, _ = run_cli(monkeypatch, capsys, ["log", "--quiet", "--no-store"], data)
        assert code == 0 and out.strip() == text, data[:6]
    code, out, _ = run_cli(monkeypatch, capsys, ["json", "--quiet", "--no-store"], codecs.BOM_UTF8 + b'{"a": 1}')
    assert code == 0 and "not valid JSON" not in out


def test_cli_marker_text_can_be_pasted_as_printed(monkeypatch, capsys, tmp_path):
    store = ["--store-dir", str(tmp_path), "--counter", "estimate"]
    handle = Store(tmp_path).put(NL.join("line %d" % i for i in range(10)))
    code, out, _ = run_cli(monkeypatch, capsys, ["expand", handle, "lines=2-3", *store])
    assert code == 0 and out.splitlines() == ["line 1", "line 2"]
    code, _, err = run_cli(monkeypatch, capsys, ["expand", handle, "nonsense", *store])
    assert code == 2 and "lines=START-END" in err


def test_cli_folder_argument_and_missing_counter_give_clear_errors(monkeypatch, capsys, tmp_path):
    code, _, err = run_cli(monkeypatch, capsys, ["log", str(tmp_path), "--store-dir", str(tmp_path / "s")])
    assert code == 2 and "folder" in err and "Traceback" not in err


# ---------------------------------------------------------------- MCP
def call(server, name, **args):
    return asyncio.run(server.call_tool(name, args))


def reason_of(excinfo):
    return str(excinfo.value) + " " + str(excinfo.value.__cause__)


def test_mcp_command_runner_honours_quotes_and_reports_failures(tmp_path):
    if " " in sys.executable:
        pytest.skip("interpreter path has spaces")
    server = build_server(tmp_path, allow_run=True)
    ok = call(server, "trim_log", command=f'{sys.executable} -c "print(\'a b\'); print(1 + 1)"').content[0].text
    assert "exit code 0" in ok and "a b" in ok
    for command, expected in ((f"{sys.executable}-nope --x", "not found"), ("", "exactly one")):
        with pytest.raises(Exception) as caught:
            call(server, "trim_log", command=command)
        assert expected.lower() in reason_of(caught).lower(), command


def test_mcp_rejects_out_of_range_arguments_and_does_not_echo_unrecognised_big_input(tmp_path):
    server = build_server(tmp_path)
    with pytest.raises(Exception):
        call(server, "report", later_turns=-5)
    big = NL.join("plain prose line number %d with some words in it to make it long enough" % i for i in range(1500))
    (tmp_path / "big.txt").write_text(big, encoding="utf-8")
    reply = call(server, "mask_json", path="big.txt").content[0].text
    assert "not trimmed" in reply and len(reply) < 3000
