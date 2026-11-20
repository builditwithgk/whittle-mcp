"""Regression tests for the bugs a fresh-agent walkthrough found in 0.1.0. Each test is one reported problem."""

import asyncio
import json
import os
import subprocess
import sys

import pytest
from whittle_mcp.cli import main
from whittle_mcp.engine import Whittle
from whittle_mcp.server import build_server
from whittle_mcp.store import Store
from whittle_mcp.tokens import get_counter
from whittle_mcp.trimmers import diffs, jsonmask, logs, openapi, tests


def make():
    return Whittle(counter=get_counter("estimate"), store=Store())


# ---------------------------------------------------------------- Windows: encoding and CRLF
def test_cli_survives_a_narrow_console_code_page_and_keeps_utf8():
    text = "ERROR " + chr(0x1F4A5) + " " + chr(0x5931) + chr(0x8D25) + " failed, caf" + chr(0xE9)
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"}
    done = subprocess.run([sys.executable, "-m", "whittle_mcp.cli", "log", "--quiet", "--no-store", "--counter", "estimate"],
                          input=text.encode("utf-8"), capture_output=True, env=env, check=False)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    assert done.stdout.decode("utf-8").strip() == text            # bytes in, the same UTF-8 bytes out


def test_crlf_input_is_normalised_and_expand_has_no_doubled_line_endings(tmp_path):
    crlf = chr(13) + chr(10)
    raw = crlf.join(f"line {i}" for i in range(120)) + crlf
    w = Whittle(counter=get_counter("estimate"), store=Store(tmp_path))
    result = w.trim("log", raw)
    expanded = w.expand(result.handle, lines="1-3")
    assert chr(13) not in result.text and chr(13) not in expanded
    stored = (tmp_path / f"{result.handle}.txt").read_bytes()
    assert b"\r" not in stored                                    # the store never writes \r\r\n


# ---------------------------------------------------------------- CLI errors
def test_cli_missing_file_and_bad_expand_give_clear_errors_and_exit_codes(capsys, tmp_path):
    assert main(["log", str(tmp_path / "nope.log"), "--store-dir", str(tmp_path)]) == 2
    assert "file not found" in capsys.readouterr().err
    assert main(["expand", "deadbeef", "--store-dir", str(tmp_path)]) == 1
    assert "No stored output" in capsys.readouterr().err
    handle = Store(tmp_path).put("a" + chr(10) + "b" + chr(10))
    assert main(["expand", handle, "--lines", "50-60", "--store-dir", str(tmp_path)]) == 1
    assert "past the end" in capsys.readouterr().err


def test_bench_without_a_corpus_is_an_error_that_explains_itself(capsys, tmp_path):
    assert main(["bench", "--corpus", str(tmp_path)]) == 2
    assert "git repository" in capsys.readouterr().err


# ---------------------------------------------------------------- logs
def test_java_caused_by_chain_keeps_every_cause_line():
    frames = chr(10).join("\tat com.example.Layer%d.run(Layer.java:%d)" % (i, i) for i in range(60))
    log = chr(10).join(["INFO start"] * 30 + ["java.lang.RuntimeException: wrapper", frames,
                                              "Caused by: java.sql.SQLException: deadlock detected", frames,
                                              "Caused by: java.io.IOException: socket closed", frames] + ["INFO after"] * 40)
    out = logs.trim(log).text
    assert "SQLException: deadlock detected" in out and "IOException: socket closed" in out and "RuntimeException: wrapper" in out


def test_errors_with_different_ids_are_not_merged_into_one_counted_line():
    def unique(i):   # lines that do not collapse into repeats
        return "step " + "".join(chr(97 + (i // 26 ** k) % 26) for k in range(3)) + " done"

    lines = [unique(i) for i in range(120)]
    lines[40:40] = ["ERROR user %d not found in tenant" % (4000 + k) for k in range(10)]
    w = make()
    result = w.trim("log", chr(10).join(lines))
    shown = [ln for ln in result.text.splitlines() if ln.startswith("ERROR user")]
    assert 1 <= len(shown) <= 3 and not any("(x" in ln for ln in shown)       # the README's "first three, rest recoverable"
    assert f"whittle expand {result.handle}" in result.text                   # and the marker says where the rest is
    assert "ERROR user 4009 not found" in w.expand(result.handle)


def test_collapsed_repeats_say_which_original_lines_they_cover():
    log = chr(10).join(["START"] * 1 + ["INFO heartbeat %d ok" % i for i in range(100)] + ["ERROR boom"] + ["INFO tail %d" % i for i in range(5)])
    out = logs.trim(log, head=1, tail=2).text
    assert "(x100; lines 2-101)" in out


# ---------------------------------------------------------------- tests (go, cargo)
def test_go_failure_message_before_the_fail_line_is_kept():
    body = chr(10).join("=== RUN   TestOK%d" % i + chr(10) + "--- PASS: TestOK%d (0.00s)" % i for i in range(40))
    go = body + chr(10) + "=== RUN   TestB" + chr(10) + "    b_test.go:12: got 3, want 4" + chr(10) + "--- FAIL: TestB (0.00s)" + chr(10) + "FAIL" + chr(10) + "FAIL\texample.com/pkg\t0.01s"
    out = tests.trim(go).text
    assert "b_test.go:12: got 3, want 4" in out and "--- FAIL: TestB" in out


def test_cargo_failed_lines_are_kept():
    lines = ["test mod::ok%d ... ok" % i for i in range(60)] + ["test mod::bad ... FAILED", "", "failures:", "", "---- mod::bad stdout ----",
                                                                  "thread 'mod::bad' panicked at src/lib.rs:9:5:", "assertion failed: x == 2", "",
                                                                  "test result: FAILED. 60 passed; 1 failed; 0 ignored"]
    out = tests.trim(chr(10).join(lines)).text
    assert "test mod::bad ... FAILED" in out and "assertion failed: x == 2" in out


# ---------------------------------------------------------------- JSON
def test_json_numbers_and_duplicate_keys_survive_exactly():
    doc = '{"big":123456789012345678901234567890.5,"huge":1e400,"p":1E+2,"tiny":0.1000000000000000055511151231257827,"x":1,"x":"SECOND","arr":[1,2,3,4,5,6]}'
    out = jsonmask.trim(doc).text
    for token in ("123456789012345678901234567890.5", "1e400", "1E+2", "0.1000000000000000055511151231257827", '"x":1', '"x":"SECOND"'):
        assert token in out, token


def test_json_nested_5000_deep_does_not_crash():
    deep = "[" * 5000 + "]" * 5000
    result = jsonmask.trim(deep)
    assert not result.changed and "too deeply" in result.notes[0]


# ---------------------------------------------------------------- OpenAPI
SWAGGER2 = {
    "swagger": "2.0", "info": {"title": "Old", "version": "1"}, "securityDefinitions": {"key": {"type": "apiKey", "name": "k", "in": "header"}},
    "paths": {"/things/{sid}": {"parameters": [{"name": "sid", "in": "path", "required": True, "type": "string"}, {"$ref": "#/parameters/PageSize"}],
                                "get": {"operationId": "getThing", "responses": {"200": {"schema": {"$ref": "#/definitions/Thing"}}}}}},
    "parameters": {"PageSize": {"name": "size", "in": "query", "type": "integer"}},
    "definitions": {"Thing": {"type": "object"}, "Unused": {"type": "string"}},
}


def test_openapi_slice_keeps_path_level_parameters_security_and_swagger2_definitions():
    out = json.loads(openapi.trim(json.dumps(SWAGGER2), paths=["/things/*"]).text)
    item = out["paths"]["/things/{sid}"]
    assert any(p.get("name") == "sid" for p in item["parameters"]) and "get" in item
    assert "PageSize" in out["parameters"] and set(out["definitions"]) == {"Thing"}
    assert "key" in out["securityDefinitions"]


def test_openapi_oas3_keeps_security_schemes_and_top_level_security():
    spec = {"openapi": "3.0.0", "info": {"title": "T", "version": "1"}, "security": [{"bearer": []}],
            "paths": {"/a": {"get": {"operationId": "a", "responses": {"200": {"description": "ok"}}}}},
            "components": {"securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}}}}
    out = json.loads(openapi.trim(json.dumps(spec), operation_ids=["a"]).text)
    assert out["security"] == [{"bearer": []}] and "bearer" in out["components"]["securitySchemes"]


def test_openapi_unreadable_input_says_why_in_the_receipt():
    w = make()
    result = w.trim("openapi", "just some text, not a spec")
    assert result.text == "just some text, not a spec" and "unchanged:" in result.receipt()


# ---------------------------------------------------------------- diffs
def py_diff(old, new, name="a.py"):
    return (f"diff --git a/{name} b/{name}" + chr(10) + "index 1..2 100644" + chr(10) + f"--- a/{name}" + chr(10) + f"+++ b/{name}" + chr(10)
            + "@@ -1,3 +1,3 @@" + chr(10) + " if x:" + chr(10) + f"-{old}" + chr(10) + f"+{new}" + chr(10) + " done()" + chr(10))


def test_diff_does_not_hide_an_indentation_change_in_python_or_yaml():
    for name in ("a.py", "ci.yml"):
        text = diffs.trim(py_diff("    do_b()", "        do_b()", name)).text
        assert "whitespace-only" not in text and "+        do_b()" in text, name


def test_diff_still_collapses_trailing_whitespace_and_brace_language_indentation():
    assert "whitespace-only" in diffs.trim(py_diff("x = 1", "x = 1   ")).text
    assert "whitespace-only" in diffs.trim(py_diff("    foo();", "        foo();", "a.js")).text


# ---------------------------------------------------------------- MCP errors
def test_mcp_refusals_tell_the_agent_why(tmp_path):
    server = build_server(tmp_path)
    cases = [({"path": "../outside.txt"}, "outside the root"), ({"path": "missing.txt"}, "not a file"),
             ({"command": "echo hi"}, "Running commands is off"), ({}, "exactly one of path, text or command")]
    for args, expected in cases:
        with pytest.raises(Exception) as caught:
            asyncio.run(server.call_tool("trim_log", args))
        assert expected in str(caught.value) or expected in str(caught.value.__cause__), (args, str(caught.value))
