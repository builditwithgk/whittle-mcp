from pathlib import Path

import pytest

from whittle_mcp.engine import Whittle
from whittle_mcp.store import Store
from whittle_mcp.tokens import get_counter

CORPUS = Path(__file__).resolve().parent.parent / "bench" / "corpus"


@pytest.fixture()
def whittle():
    return Whittle(counter=get_counter("estimate"), store=Store())


PYTEST_FAIL = """============================= test session starts =============================
platform linux -- Python 3.12.1, pytest-8.0.0
rootdir: /work/project
collected 40 items

tests/test_a.py ..........                                               [ 25%]
tests/test_b.py ..F.....                                                 [ 45%]
tests/test_c.py ..........                                               [ 70%]
tests/test_d.py ........F.                                               [100%]

=================================== FAILURES ===================================
____________________________ test_parse_dates_utc ______________________________

    def test_parse_dates_utc():
        value = parse("2026-01-01T00:00:00Z")
>       assert value.hour == 1
E       assert 0 == 1
E        +  where 0 = datetime.datetime(2026, 1, 1, 0, 0).hour

tests/test_b.py:21: AssertionError
----------------------------- Captured stdout call -----------------------------
parsing 2026-01-01T00:00:00Z
capture line 2
capture line 3
capture line 4
capture line 5
capture line 6
capture line 7
capture line 8
capture line 9
capture line 10
capture line 11
capture line 12
capture line 13
capture line 14
____________________________ test_total_with_tax ______________________________

    def test_total_with_tax():
        cart = Cart([Item(10), Item(20)])
>       assert cart.total(tax=0.1) == 33.5
E       assert 33.0 == 33.5

tests/test_d.py:88: AssertionError
=========================== short test summary info ============================
FAILED tests/test_b.py::test_parse_dates_utc - assert 0 == 1
FAILED tests/test_d.py::test_total_with_tax - assert 33.0 == 33.5
======================== 2 failed, 38 passed in 1.42s ==========================
"""
