"""Vendor-alpha tests (analysis/vendor_alpha.py).

Synthetic in-memory DB: two vendors with china_revenue_pct series (mixed
monthly/quarterly period labels) + exposure-ladder rows. Checks the period→
quarter mapping, peak→latest erosion, driver classification, and ordering.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import vendor_alpha as va  # noqa: E402


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript((ROOT / "db" / "schema.sql").read_text())
    c.execute("INSERT INTO sources (name,url,type,language) VALUES ('t','u','filing','en')")
    c.execute("INSERT INTO documents (source_id,url,retrieved_at,raw_path,sha256,title,language)"
              " VALUES (1,'u','t','p','s1','t','en')")
    for name, tkr in [("Applied Materials", "AMAT"), ("KLA", "KLAC")]:
        c.execute("INSERT INTO entities (name_en,ticker,entity_type,supply_chain_layer)"
                  " VALUES (?,?, 'company','equipment_foreign')", (name, tkr))
        eid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        # AMAT peaks 35 then latest 27 (-8); KLA peaks 40 then latest 24 (-16)
        series = {"AMAT": [("2025-07", 35.0), ("2026-04", 27.0)],
                  "KLAC": [("2025-09", 40.0), ("2026Q1", 24.0)]}[tkr]
        for period, val in series:
            c.execute("INSERT INTO metrics (entity_id,metric_name,period,value,unit,document_id)"
                      " VALUES (?, 'china_revenue_pct', ?, ?, 'pct', 1)", (eid, period, val))
        c.execute("INSERT INTO instrument_exposure (instrument,venue,instrument_type,"
                  "exposure_sign,confidence,mechanism,human_reviewed)"
                  " VALUES (?, 'NASDAQ','equity', ?, ?, 'm', 1)",
                  (tkr, "harm" if tkr == "AMAT" else "mixed",
                   "high" if tkr == "AMAT" else "medium"))
    c.commit()
    return c


def test_period_maps_to_quarter(conn):
    v = va.load_vendor_china(conn)
    assert set(v.quarter) == {"2025Q3", "2026Q2", "2026Q1"}


def test_erosion_and_driver(conn):
    df = va.build(conn).set_index("ticker")
    assert df.loc["AMAT", "erosion_pp"] == pytest.approx(8.0)
    assert df.loc["AMAT", "driver"] == "structural substitution"
    assert df.loc["KLAC", "erosion_pp"] == pytest.approx(16.0)
    assert df.loc["KLAC", "driver"] == "control-denial (not clean)"


def test_structural_sorted_first(conn):
    df = va.build(conn)
    assert df.iloc[0]["driver"] == "structural substitution"
