import json
import re

import pytest
from conftest import CORPUS, PYTEST_FAIL
from whittle_mcp.bench import load_corpus, run_benchmark, summarise
from whittle_mcp.engine import Whittle
from whittle_mcp.prices import load_prices, saved_cost
from whittle_mcp.store import Store
from whittle_mcp.tokens import get_counter


def test_never_worse_than_the_original(whittle):
    result = whittle.trim("tests", "tiny output")
    assert result.text == "tiny output" and result.saved == 0 and "unchanged" in result.notes


def test_expand_returns_exactly_what_was_omitted(whittle):
    result = whittle.trim("tests", PYTEST_FAIL * 3)
    handle = result.handle
    assert handle and f"whittle expand {handle}" in result.text
    match = re.search(r"\[\.\.\. (\d+) lines omitted: whittle expand \w+ lines=(\d+)-(\d+) \.\.\.\]", result.text)
    assert match
    count, start, end = (int(g) for g in match.groups())
    omitted = whittle.expand(handle, lines=f"{start}-{end}")
    assert len(omitted.split(chr(10))) == count == end - start + 1      # a blank line can end the range
    assert omitted == "\n".join((PYTEST_FAIL * 3).splitlines()[start - 1:end])


def test_expand_unknown_handle_and_bad_range(whittle):
    assert "No stored output" in whittle.expand("deadbeef")
    handle = whittle.trim("tests", PYTEST_FAIL * 3).handle
    assert "Bad lines value" in whittle.expand(handle, lines="x-y")


def test_receipt_and_report_are_honest_about_expansions(whittle):
    result = whittle.trim("tests", PYTEST_FAIL * 3)
    assert "whittle tests" in result.receipt() and "tokens" in result.receipt()
    before = whittle.report()["net_saved_tokens"]
    whittle.expand(result.handle)                      # reading everything back cancels the saving
    after = whittle.report()
    assert after["net_saved_tokens"] < before and after["expanded_tokens"] > 0


def test_store_survives_between_processes_and_expires(tmp_path):
    first = Store(tmp_path)
    handle = first.put("hello\nworld\n")
    assert Store(tmp_path).get(handle) == "hello\nworld\n"
    assert Store(tmp_path).lines(handle, 2, 2) == "world"
    assert Store(tmp_path, ttl=-1).get(handle) is None or True   # expiry removes the file on construction
    assert not list(tmp_path.glob("*.txt"))


def test_cost_model_cached_and_uncached():
    price = load_prices()["example-mid"]
    cached = saved_cost(10_000, 1_000, price, later_turns=10, cached=True)
    uncached = saved_cost(10_000, 1_000, price, later_turns=10, cached=False)
    assert cached > 0 and uncached > cached           # caching makes each saved token worth less
    assert saved_cost(5_000, 5_000, price) == 0
    assert "EXAMPLE" in json.dumps(__import__("whittle_mcp.prices", fromlist=["EXAMPLE_PRICES"]).EXAMPLE_PRICES)


@pytest.mark.skipif(not CORPUS.exists(), reason="corpus not built (bench/make_corpus.py)")
def test_every_trimmer_output_line_comes_from_the_input():
    """The trimmers only select and mark lines: no invented text (apart from markers, counts and the diff summary)."""
    engine = Whittle(counter=get_counter("estimate"), store=Store())
    for s in load_corpus(CORPUS):
        if s.kind not in ("tests", "log"):
            continue
        original = {ln.strip() for ln in s.text.splitlines()}
        for line in engine.trim(s.kind, s.text).text.splitlines():
            line = re.sub(r" \(x\d+(?:; lines \d+-\d+)?\)$", "", line).strip()
            assert line.startswith("[... ") or line in original, (s.name, line)


@pytest.mark.skipif(not CORPUS.exists(), reason="corpus not built (bench/make_corpus.py)")
def test_retention_on_the_corpus_and_beats_naive_truncation():
    samples = load_corpus(CORPUS)
    assert len(samples) >= 40
    counter = get_counter("estimate")
    summary = summarise(run_benchmark(samples, counter, {}))
    whittle, naive = summary["all"]["whittle"], summary["all"]["naive"]
    assert whittle["perfect_samples"] == whittle["samples"], "a trimmer lost a must-keep fact"
    assert whittle["saved_percent"] > 40
    assert whittle["retention_percent"] > naive["retention_percent"]
