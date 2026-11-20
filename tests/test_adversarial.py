"""Try to make a trimmer drop the one line that matters: random noise with a unique marker line inserted at a random place."""

import json
import random

from whittle_mcp.trimmers import diffs, jsonmask, logs, tests

NOISE = [
    "INFO request ok {n}", "DEBUG cache hit key={n}", "tests/test_x.py::test_{n} PASSED", "....................  [ 50%]",
    "    at Object.<anonymous> (file.js:{n}:10)", "  File \"a.py\", line {n}, in f", "    call()", "", "WARNING slow {n} ms",
    "2026-11-20 10:00:{n} INFO heartbeat", "Collecting package-{n}", "   Downloading wheel-{n}.whl",
]


def noise(rng: random.Random, count: int) -> list[str]:
    return [rng.choice(NOISE).format(n=rng.randint(0, 99)) for _ in range(count)]


def test_log_never_drops_a_distinct_error_message():
    rng = random.Random(1234)
    for i in range(150):
        lines = noise(rng, rng.randint(40, 400))
        words = rng.sample(["gateway", "ledger", "queue", "cache", "mailer", "auth", "billing", "search"], rng.randint(1, 4))
        errors = [f"ERROR {w} failure: code {rng.randint(1000, 9999)}" for w in words]   # distinct messages, varying numbers
        for e in errors:
            lines.insert(rng.randint(0, len(lines)), e)
        text = logs.trim("\n".join(lines)).text
        for e in errors:
            assert e in text, (i, e)


def test_tests_never_drops_a_failed_test_id_or_the_summary():
    rng = random.Random(99)
    for i in range(150):
        lines = noise(rng, rng.randint(30, 300))
        failed = [f"FAILED tests/test_mod.py::test_case_{i}_{k} - assert {k} == {k + 1}" for k in range(rng.randint(1, 3))]
        for f in failed:
            lines.insert(rng.randint(0, len(lines)), f)
        lines.append(f"==== {len(failed)} failed, 80 passed in 1.2s ====")
        text = tests.trim("\n".join(lines)).text
        assert all(f in text for f in failed) and "failed, 80 passed" in text, i


def test_diff_never_drops_a_changed_line_in_a_normal_file():
    rng = random.Random(5)
    for i in range(100):
        body = [f" context {rng.randint(0, 9)}" for _ in range(rng.randint(5, 60))]
        changes = {rng.randint(0, len(body)): f"+added line number {i}-{k}" for k in range(rng.randint(1, 5))}
        for pos, line in sorted(changes.items(), reverse=True):
            body.insert(pos, line)
        diff = "diff --git a/src/mod.py b/src/mod.py\nindex 1..2 100644\n--- a/src/mod.py\n+++ b/src/mod.py\n@@ -1,50 +1,60 @@\n" + "\n".join(body) + "\n"
        text = diffs.trim(diff).text
        assert all(line in text for line in changes.values()), i


def test_json_keeps_every_top_level_key_and_masked_output_parses():
    rng = random.Random(3)
    for i in range(100):
        doc = {f"key{k}": ([{"v": rng.random(), "s": "z" * rng.randint(0, 400)} for _ in range(rng.randint(0, 40))]
                           if rng.random() < 0.5 else {"nested": {"deep": {"deeper": list(range(30))}}}) for k in range(rng.randint(1, 8))}
        out = jsonmask.trim(json.dumps(doc, indent=2)).text
        assert set(json.loads(out)) == set(doc), i


def test_garbage_and_huge_inputs_do_not_crash():
    rng = random.Random(8)
    for trimmer in (tests.trim, logs.trim, diffs.trim, jsonmask.trim):
        trimmer("")
        trimmer("\x00\xff�" * 500)
        trimmer("\n" * 5000)
        trimmer("".join(rng.choice("abc \n{}[]\":,") for _ in range(20000)))
        trimmer("x" * 2_000_000)


def test_log_errors_that_differ_only_in_numbers_are_treated_as_repeats_but_stay_recoverable():
    """The documented trade-off: after three errors of the same shape the rest are omitted, with a marker to get them back."""
    from whittle_mcp.engine import Whittle
    from whittle_mcp.store import Store
    from whittle_mcp.tokens import get_counter
    lines = [f"info {i}" for i in range(80)]
    lines[10:10] = [f"ERROR order {1000 + k} failed with timeout" for k in range(12)]
    w = Whittle(counter=get_counter("estimate"), store=Store())
    result = w.trim("log", chr(10).join(lines))
    shown = [ln for ln in result.text.splitlines() if ln.startswith("ERROR order")]
    assert 1 <= len(shown) <= 3 or "(x" in result.text
    assert "ERROR order 1011 failed" in w.expand(result.handle)        # nothing is lost: the full log is one expand away
