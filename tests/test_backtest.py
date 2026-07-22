"""Point-in-time backtest tests (analysis/backtest.py).

Injects synthetic git vintages (no real git) to check the vintage parse, the
revision table (including coverage-change detection), and the nowcast backtest.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import backtest as bt  # noqa: E402

HEADER = "quarter,ratio,missing_origins,methodology_version\n"


def vintage(date, rows):
    text = HEADER + "".join(
        f"{q},{r},{cov},2.0.0\n" for q, r, cov in rows)
    return {"date": date, "text": text}


def test_parse_and_revision_with_coverage_change():
    vintages = [
        # early vintage: 2023Q1 reduced-coverage; 2023Q3 full
        vintage("2026-07-12", [("2023Q1", 0.167, "EU27+Taiwan"),
                               ("2023Q3", 0.115, "Taiwan")]),
        # later vintage: 2023Q1 now full-coverage (revised down); 2023Q3 stable
        vintage("2026-07-16", [("2023Q1", 0.146, "Taiwan"),
                               ("2023Q3", 0.115, "Taiwan")]),
    ]
    panel = bt.parse_ratio_vintages(vintages)
    rev = bt.revision_table(panel).set_index("quarter")
    assert rev.loc["2023Q1", "revision_pp"] == pytest.approx(-2.1, abs=0.05)
    assert bool(rev.loc["2023Q1", "coverage_changed"]) is True
    assert rev.loc["2023Q3", "revision_pp"] == pytest.approx(0.0, abs=1e-9)
    assert bool(rev.loc["2023Q3", "coverage_changed"]) is False


def test_methodology_break_excluded():
    v = {"date": "2026-07-09",
         "text": "quarter,ratio,missing_origins,methodology_version\n"
                 "2023Q3,0.30,Taiwan,1.0.0\n"}
    assert bt.parse_ratio_vintages([v]).empty


def test_nowcast_backtest():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE nowcasts (made_at TEXT, target_quarter TEXT, ratio_nowcast REAL)")
    conn.executemany(
        "INSERT INTO nowcasts VALUES (?,?,?)",
        [("2026-05-01", "2025Q4", 0.20), ("2026-06-01", "2025Q4", 0.21)])
    conn.commit()
    bt_df = bt.nowcast_backtest(conn, {"2025Q4": 0.22})
    row = bt_df.set_index("target_quarter").loc["2025Q4"]
    assert row["nowcast"] == pytest.approx(0.20)          # earliest used
    assert row["error_pp"] == pytest.approx(-2.0, abs=1e-6)
