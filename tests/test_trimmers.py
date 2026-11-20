import json

from conftest import PYTEST_FAIL
from whittle_mcp.trimmers import diffs, jsonmask, logs, openapi, tests


def test_tests_keeps_failures_and_summary_drops_noise():
    result = tests.trim(PYTEST_FAIL)
    text = result.text
    for fact in ("test_parse_dates_utc", "test_total_with_tax", "assert 0 == 1", "assert 33.0 == 33.5",
                 "tests/test_b.py:21", "2 failed, 38 passed"):
        assert fact in text
    assert "capture line 8" not in text                  # the middle of a capture is collapsed
    assert "tests/test_a.py .........." not in text      # progress lines are noise
    assert result.omitted_lines > 0


def test_tests_all_green_collapses_to_the_summary():
    green = "\n".join(["platform linux"] + [f"tests/test_x.py::test_{i} PASSED" for i in range(60)] + ["===== 60 passed in 0.5s ====="])
    text = tests.trim(green).text
    assert "60 passed" in text and "test_30 PASSED" not in text


def test_tests_short_output_is_returned_as_is():
    out = tests.trim("1 passed in 0.01s")
    assert out.text == "1 passed in 0.01s" and not out.changed


def test_log_collapses_repeats_and_keeps_every_distinct_error():
    lines = [f"2026-11-20 10:00:{i % 60:02d} INFO processed order {i}" for i in range(300)]
    lines.insert(50, "2026-11-20 10:00:50 ERROR payment gateway timeout order 51")
    lines.insert(200, "2026-11-20 10:03:20 ERROR disk full on /var/data")
    text = logs.trim("\n".join(lines)).text
    assert "payment gateway timeout" in text and "disk full" in text
    assert "(x" in text                                   # repeats are counted, not repeated
    assert len(text.splitlines()) < 60


def test_log_traceback_keeps_last_frames_and_the_exception():
    frames = "".join(f'  File "a.py", line {i}, in f{i}\n    call()\n' for i in range(40))
    log = ("\n".join(f"info line {i}" for i in range(40)) + "\nTraceback (most recent call last):\n" + frames
           + "ValueError: boom\n" + "\n".join(f"after {i}" for i in range(60)))
    text = logs.trim(log).text
    assert "ValueError: boom" in text and "Traceback (most recent call last):" in text
    assert 'line 39, in f39' in text and 'line 10, in f10' not in text


def test_log_short_is_unchanged():
    assert not logs.trim("a\nb\nc").changed


def test_json_keeps_shape_and_stays_valid():
    doc = {"items": [{"id": i, "name": "x" * 300, "tags": list(range(20))} for i in range(50)], "total": 50}
    out = jsonmask.trim(json.dumps(doc, indent=2), handle="abc12345")
    data = json.loads(out.text)
    assert set(data) == {"items", "total"} and len(data["items"]) == 4   # 3 items plus the marker
    assert "chars)" in data["items"][0]["name"] and "whittle expand abc12345 path=$.items)" in data["items"][-1]


def test_json_array_sampling_shows_keys_that_only_later_items_have():
    items = [{"id": i} for i in range(10)] + [{"id": 10, "draft": True}] + [{"id": i} for i in range(11, 20)]
    data = json.loads(jsonmask.trim(json.dumps(items)).text)
    assert any(isinstance(x, dict) and "draft" in x for x in data)


def test_json_lines_and_invalid_input():
    jl = "\n".join(json.dumps({"n": i, "text": "y" * 50}) for i in range(10))
    assert jsonmask.trim(jl).text.count("\n") < 6
    assert not jsonmask.trim("not json at all").changed


def test_json_subtree_path():
    text = json.dumps({"a": {"b": [10, 20, {"c": 7}]}})
    assert jsonmask.subtree(text, "$.a.b[2].c") == "7"
    assert jsonmask.subtree(text, "$.missing") is None


DIFF = """diff --git a/src/app.py b/src/app.py
index 1..2 100644
--- a/src/app.py
+++ b/src/app.py
@@ -10,9 +10,9 @@ def f():
 a
 b
 c
 d
-old_value = 1
+new_value = 2
 e
 f
 g
 h
diff --git a/package-lock.json b/package-lock.json
index 3..4 100644
--- a/package-lock.json
+++ b/package-lock.json
@@ -1,5 +1,5 @@
""" + "\n".join(f"-    \"dep{i}\": \"1.0.0\"\n+    \"dep{i}\": \"1.0.1\"" for i in range(60)) + """
diff --git a/pad.py b/pad.py
index 5..6 100644
--- a/pad.py
+++ b/pad.py
@@ -1,3 +1,3 @@
-x = 1
+x = 1  
 y = 2
 z = 3
"""


def test_diff_collapses_lockfiles_and_whitespace_only_and_keeps_changes():
    text = diffs.trim(DIFF).text
    assert "-old_value = 1" in text and "+new_value = 2" in text
    assert "generated, vendored or lock file" in text and "whitespace-only change" in text
    assert '"dep30"' not in text
    assert text.splitlines()[0].startswith("whittle diff: 3 files")


def test_diff_not_a_diff_is_unchanged():
    assert not diffs.trim("hello\nworld").changed


SPEC = {
    "openapi": "3.0.0", "info": {"title": "Pets", "version": "1"},
    "paths": {
        "/pets": {"get": {"operationId": "listPets", "tags": ["pets"], "responses": {"200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Pet"}}}}}}},
        "/owners": {"get": {"operationId": "listOwners", "tags": ["owners"], "responses": {"200": {"description": "ok"}}}},
    },
    "components": {"schemas": {"Pet": {"type": "object", "properties": {"owner": {"$ref": "#/components/schemas/Owner"}}},
                               "Owner": {"type": "object"}, "Unused": {"type": "string"}}},
}


def test_openapi_index_then_slice_with_schema_closure():
    index = openapi.trim(json.dumps(SPEC)).text
    assert "listPets" in index and "listOwners" in index and "components" not in index
    sliced = json.loads(openapi.trim(json.dumps(SPEC), tags=["pets"]).text)
    assert list(sliced["paths"]) == ["/pets"]
    assert set(sliced["components"]["schemas"]) == {"Pet", "Owner"}    # follows $ref, drops the unused schema


def test_openapi_no_match_and_not_a_spec():
    assert "No operations matched" in openapi.trim(json.dumps(SPEC), paths=["/nothing"]).text
    assert not openapi.trim("{}").changed
