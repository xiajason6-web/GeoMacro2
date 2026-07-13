"""Tests: domestic-semicap numerator derivation (P1.2 of the work order).

Seed: quarterly revenue 10,000 CNY; semicap share 90% (FY2025); domestic
share 95% (FY2025) -> domestic semicap = 10,000 x 0.90 x 0.95 = 8,550.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import derive_domestic_semicap as dds  # noqa: E402


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.executescript((ROOT / "db" / "schema.sql").read_text())
    conn.execute("INSERT INTO sources (name, url, type, language) VALUES ('t','u','filing','zh')")
    conn.execute(
        "INSERT INTO documents (source_id,url,retrieved_at,raw_path,sha256,title,language)"
        " VALUES (1,'u','t','p','s1','t','zh')"
    )
    conn.execute(
        "INSERT INTO entities (name_en, entity_type, supply_chain_layer)"
        " VALUES ('EquipCo','company','equipment')"
    )
    yield conn
    conn.close()


def add(conn, metric, period, value, conf=0.9):
    conn.execute(
        "INSERT INTO metrics (entity_id, metric_name, period, value, unit,"
        " document_id, extraction_confidence) VALUES (1, ?, ?, ?, 'x', 1, ?)",
        (metric, period, value, conf),
    )


def result(conn, period):
    return conn.execute(
        "SELECT value, notes, extraction_confidence FROM metrics"
        " WHERE metric_name = 'domestic_semicap_revenue_cny' AND period = ?",
        (period,),
    ).fetchone()


def test_both_shares_applied(db):
    add(db, "quarterly_revenue_cny", "2025Q1", 10_000, 0.99)
    add(db, "semicap_segment_share_pct", "2025", 90.0, 0.95)
    add(db, "domestic_revenue_share_pct", "2025", 95.0, 0.9)
    dds.derive_for_entity(db, 1, "EquipCo")
    value, notes, conf = result(db, "2025Q1")
    assert value == pytest.approx(8_550)
    assert "ESTIMATED" not in notes
    assert conf == 0.9  # min of the three input confidences


def test_fallback_year_flagged_estimated(db):
    add(db, "quarterly_revenue_cny", "2026Q1", 10_000)
    add(db, "semicap_segment_share_pct", "2025", 90.0)
    add(db, "domestic_revenue_share_pct", "2025", 95.0)
    dds.derive_for_entity(db, 1, "EquipCo")
    value, notes, _ = result(db, "2026Q1")
    assert value == pytest.approx(8_550)
    assert "ESTIMATED(share-year)" in notes


def test_missing_domestic_split_assumes_100_and_flags(db):
    add(db, "quarterly_revenue_cny", "2025Q1", 10_000)
    add(db, "semicap_segment_share_pct", "2025", 90.0)
    dds.derive_for_entity(db, 1, "EquipCo")
    value, notes, _ = result(db, "2025Q1")
    assert value == pytest.approx(9_000)  # 100% domestic assumed
    assert "ESTIMATED(no-domestic-split)" in notes
    flagged, = db.execute(
        "SELECT COUNT(*) FROM review_queue WHERE reason LIKE '%no 分地区%'"
    ).fetchone()
    assert flagged == 1


def test_no_segment_share_at_all_goes_to_review(db):
    add(db, "quarterly_revenue_cny", "2025Q1", 10_000)
    n = dds.derive_for_entity(db, 1, "EquipCo")
    assert n == 0
    assert result(db, "2025Q1") is None
    flagged, = db.execute(
        "SELECT COUNT(*) FROM review_queue WHERE reason LIKE '%no semicap segment share%'"
    ).fetchone()
    assert flagged == 1


def test_rerun_replaces_not_duplicates(db):
    add(db, "quarterly_revenue_cny", "2025Q1", 10_000)
    add(db, "semicap_segment_share_pct", "2025", 90.0)
    add(db, "domestic_revenue_share_pct", "2025", 95.0)
    dds.derive_for_entity(db, 1, "EquipCo")
    dds.derive_for_entity(db, 1, "EquipCo")
    count, = db.execute(
        "SELECT COUNT(*) FROM metrics WHERE metric_name='domestic_semicap_revenue_cny'"
    ).fetchone()
    assert count == 1
