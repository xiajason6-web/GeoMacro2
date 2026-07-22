"""Calls-ledger grader tests (analysis/calls.py).

Builds a synthetic quarter-indexed context (no repo files) and checks each
criteria type resolves YES/NO correctly, stays OPEN when the quarter is not yet
present, and that grade()/Brier scoring behave.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import calls  # noqa: E402


@pytest.fixture
def ctx():
    return {
        "ratio_full": pd.DataFrame(
            {"ratio": [0.22]}, index=pd.Index(["2026Q2"], name="quarter")),
        "ratio_all": pd.DataFrame(
            {"domestic_semicap_usd": [3.0e9, 2.0e9]},
            index=pd.Index(["2026Q2", "2025Q2"], name="quarter")),
        "cf": pd.DataFrame(
            {"us_actual_usd": [0.4e9]}, index=pd.Index(["2026Q4"], name="quarter")),
        "chips": pd.DataFrame(
            {"chip_domestic_share": [0.12]},
            index=pd.Index(["2026Q4"], name="quarter")),
    }


def call(ctype, **crit):
    return {"criteria": {"type": ctype, **crit}}


def test_prior_year_quarter():
    assert calls.prior_year_quarter("2026Q2") == "2025Q2"


def test_ratio_gte_and_lte(ctx):
    assert calls.GRADERS["ratio_gte"](
        call("ratio_gte", quarter="2026Q2", threshold=0.20), ctx)[0] == "YES"
    assert calls.GRADERS["ratio_gte"](
        call("ratio_gte", quarter="2026Q2", threshold=0.25), ctx)[0] == "NO"
    assert calls.GRADERS["ratio_lte"](
        call("ratio_lte", quarter="2026Q2", threshold=0.25), ctx)[0] == "YES"


def test_open_when_quarter_absent(ctx):
    # 2027Q1 is not in the context yet -> unresolved (open)
    assert calls.GRADERS["ratio_gte"](
        call("ratio_gte", quarter="2027Q1", threshold=0.20), ctx) is None


def test_us_equip_and_chip_and_yoy(ctx):
    assert calls.GRADERS["us_equip_lte"](
        call("us_equip_lte", quarter="2026Q4", threshold_bn=0.5), ctx)[0] == "YES"
    assert calls.GRADERS["us_equip_lte"](
        call("us_equip_lte", quarter="2026Q4", threshold_bn=0.3), ctx)[0] == "NO"
    assert calls.GRADERS["chip_share_lte"](
        call("chip_share_lte", quarter="2026Q4", threshold=0.15), ctx)[0] == "YES"
    assert calls.GRADERS["domestic_yoy_up"](
        call("domestic_yoy_up", quarter="2026Q2"), ctx)[0] == "YES"


def test_grade_and_brier(ctx):
    doc = {"calls": [
        {"id": "a", "made": "2026-07-21", "p": 0.8, "status": "open",
         "criteria": {"type": "ratio_gte", "quarter": "2026Q2", "threshold": 0.20}},
        {"id": "b", "made": "2026-07-21", "p": 0.9, "status": "open",
         "criteria": {"type": "ratio_gte", "quarter": "2026Q2", "threshold": 0.25}},
        {"id": "c", "made": "2026-07-21", "p": 0.5, "status": "open",
         "criteria": {"type": "ratio_gte", "quarter": "2099Q1", "threshold": 0.2}},
    ]}
    graded = calls.grade(doc=doc, ctx=ctx, write=False, today="2026-07-21")
    by = {c["id"]: c for c in graded["calls"]}
    assert by["a"]["outcome"] == "YES"   # 0.22 >= 0.20
    assert by["b"]["outcome"] == "NO"    # 0.22 < 0.25
    assert by["c"]["status"] == "open"   # future quarter, unresolved
    s = calls.summary(graded)
    assert s["n_resolved"] == 2 and s["n_open"] == 1
    # Brier = mean[(0.8-1)^2, (0.9-0)^2] = mean[0.04, 0.81] = 0.425
    assert s["brier"] == pytest.approx((0.04 + 0.81) / 2)
