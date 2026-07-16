"""Tests for the two analytical-extension modules."""

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import chip_vs_equipment as cve  # noqa: E402
import vendor_lead as vl  # noqa: E402


# ---- vendor_lead helpers -------------------------------------------------------

def test_pearson_known_values():
    assert vl.pearson([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)
    assert vl.pearson([1, 2, 3], [6, 4, 2]) == pytest.approx(-1.0)
    assert vl.pearson([1], [1]) is None


def test_month_to_quarter():
    assert vl.month_to_quarter("2025-01") == "2025Q1"
    assert vl.month_to_quarter("2025-04") == "2025Q2"
    assert vl.month_to_quarter("2025-12") == "2025Q4"


def test_vendor_bucketing_averages_and_passes_through_quarters():
    conn = sqlite3.connect(":memory:")
    conn.executescript((ROOT / "db" / "schema.sql").read_text())
    conn.execute("INSERT INTO sources (name,url,type,language) VALUES ('t','u','earnings','en')")
    conn.execute("INSERT INTO documents (source_id,url,retrieved_at,raw_path,sha256,title,language) VALUES (1,'u','t','p','s','t','en')")
    conn.execute("INSERT INTO entities (name_en, entity_type) VALUES ('A','company')")
    conn.execute("INSERT INTO entities (name_en, entity_type) VALUES ('B','company')")
    # two vendors, same calendar quarter, one via YYYY-MM and one via YYYYQ#
    conn.execute("INSERT INTO metrics (entity_id,metric_name,period,value,unit,document_id) VALUES (1,'china_revenue_pct','2025-01',30,'pct',1)")
    conn.execute("INSERT INTO metrics (entity_id,metric_name,period,value,unit,document_id) VALUES (2,'china_revenue_pct','2025Q1',40,'pct',1)")
    buckets = vl.vendor_panel_by_quarter(conn)
    assert buckets["2025Q1"] == pytest.approx(35.0)   # (30+40)/2
    conn.close()


def test_vendor_render_flags_small_n_and_positive_sign():
    data = {
        "rows": [{"quarter": "2025Q1", "vendor_china_pct": 30.0, "ratio": 0.17}],
        "n": 5, "corr_lag0": 0.44, "corr_lag1": 0.62, "n_lag1": 4,
    }
    md = vl.render(data)
    assert "Descriptive only" in md
    assert "n = 5" in md
    assert "POSITIVE" in md          # observed positive sign interpreted
    assert "cycle" in md.lower()


# ---- chip_vs_equipment ---------------------------------------------------------

def test_chip_series_are_8542_and_distinct_from_equipment():
    assert all("8542" in m for m in cve.CHIP_SERIES)
    assert all("8486" in m for m in cve.EQUIPMENT_SERIES)
    # same origins on both sides so the comparison is apples-to-apples
    assert (
        sorted(o for o, _ in cve.CHIP_SERIES.values())
        == sorted(o for o, _ in cve.EQUIPMENT_SERIES.values())
    )


def test_chip_build_indexes_to_base(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.executescript((ROOT / "db" / "schema.sql").read_text())
    conn.execute("INSERT INTO sources (name,url,type,language) VALUES ('t','u','trade_stats','en')")
    conn.execute("INSERT INTO documents (source_id,url,retrieved_at,raw_path,sha256,title,language) VALUES (1,'u','t','p','s','t','en')")
    conn.execute("INSERT INTO entities (name_en, entity_type) VALUES ('China','country')")
    # two full-coverage quarters for both HS codes; chips double, equip flat
    for qi, (q, months) in enumerate([("2025Q1", ["2025-01","2025-02","2025-03"]),
                                       ("2025Q2", ["2025-04","2025-05","2025-06"])]):
        for mo in months:
            conn.execute("INSERT INTO fx_rates (currency,period,usd_per_unit,document_id) VALUES ('USD',?,1.0,1)", (mo,))
            conn.execute("INSERT INTO fx_rates (currency,period,usd_per_unit,document_id) VALUES ('EUR',?,1.0,1)", (mo,))
            conn.execute("INSERT INTO fx_rates (currency,period,usd_per_unit,document_id) VALUES ('JPY',?,1.0,1)", (mo,))
            for series in (cve.EQUIPMENT_SERIES, cve.CHIP_SERIES):
                chip = series is cve.CHIP_SERIES
                for metric in series:
                    val = (200 if chip and qi == 1 else 100)  # chips double in Q2
                    conn.execute("INSERT INTO metrics (entity_id,metric_name,period,value,unit,document_id) VALUES (1,?,?,?,'x',1)", (metric, mo, val))
    data = cve.build(conn)
    assert [r["quarter"] for r in data["rows"]] == ["2025Q1", "2025Q2"]
    assert data["rows"][0]["chip_idx"] == pytest.approx(100)
    assert data["rows"][1]["chip_idx"] == pytest.approx(200)     # chips doubled
    assert data["rows"][1]["equip_idx"] == pytest.approx(100)    # equipment flat
    conn.close()
