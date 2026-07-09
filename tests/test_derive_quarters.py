"""Tests: quarter derivation arithmetic and sanity guards.

Synthetic seeds with hand-computed expectations:
  Q1=100, Q3=300 (extracted); H1=250, FY=1000, YTD9M=550
  -> Q2 = 250-100 = 150; Q4 = 1000-250-300 = 450
  Naura-style case (no Q3 extracted): Q3 = YTD9M-H1 = 550-250 = 300,
  then Q4 = 1000-250-300 = 450.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import derive_quarters as dq  # noqa: E402


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
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
        " document_id, extraction_confidence) VALUES (1, ?, ?, ?, 'CNY', 1, ?)",
        (metric, period, value, conf),
    )


def q(conn, period):
    row = conn.execute(
        "SELECT value, notes, extraction_confidence FROM metrics"
        " WHERE metric_name='quarterly_revenue_cny' AND period=?",
        (period,),
    ).fetchone()
    return row


def test_q2_and_q4_derivation(db, monkeypatch):
    monkeypatch.setattr(dq, "YEARS", ["2024"])
    add(db, "quarterly_revenue_cny", "2024Q1", 100, 0.99)
    add(db, "quarterly_revenue_cny", "2024Q3", 300, 0.95)
    add(db, "h1_revenue_cny", "2024H1", 250, 0.9)
    add(db, "fy_revenue_cny", "2024", 1000, 0.98)
    dq.derive_for_entity(db, 1, "EquipCo")

    value, notes, conf = q(db, "2024Q2")
    assert value == 150
    assert notes.startswith("DERIVED")
    assert conf == 0.9  # min(H1 0.9, Q1 0.99)

    value, notes, conf = q(db, "2024Q4")
    assert value == 450
    assert conf == 0.9


def test_q3_from_ytd_then_q4(db, monkeypatch):
    monkeypatch.setattr(dq, "YEARS", ["2024"])
    add(db, "quarterly_revenue_cny", "2024Q1", 100)
    add(db, "h1_revenue_cny", "2024H1", 250)
    add(db, "fy_revenue_cny", "2024", 1000)
    add(db, "ytd9m_revenue_cny", "2024YTD9M", 550)
    dq.derive_for_entity(db, 1, "EquipCo")
    assert q(db, "2024Q3")[0] == 300  # 550 - 250
    assert q(db, "2024Q4")[0] == 450  # 1000 - 250 - 300 (derived Q3 feeds Q4)


def test_existing_quarters_never_overwritten(db, monkeypatch):
    monkeypatch.setattr(dq, "YEARS", ["2024"])
    add(db, "quarterly_revenue_cny", "2024Q2", 12345)  # extracted, not derived
    add(db, "quarterly_revenue_cny", "2024Q1", 100)
    add(db, "h1_revenue_cny", "2024H1", 250)
    dq.derive_for_entity(db, 1, "EquipCo")
    assert q(db, "2024Q2")[0] == 12345
    count, = db.execute(
        "SELECT COUNT(*) FROM metrics WHERE period='2024Q2'"
    ).fetchone()
    assert count == 1


def test_implausible_derivation_flagged_not_inserted(db, monkeypatch):
    monkeypatch.setattr(dq, "YEARS", ["2024"])
    # H1 < Q1 would make Q2 negative — must flag, never insert.
    add(db, "quarterly_revenue_cny", "2024Q1", 400)
    add(db, "h1_revenue_cny", "2024H1", 250)
    dq.derive_for_entity(db, 1, "EquipCo")
    assert q(db, "2024Q2") is None
    flags, = db.execute(
        "SELECT COUNT(*) FROM review_queue WHERE item_type='derivation'"
    ).fetchone()
    assert flags == 1


def test_no_inputs_no_output(db, monkeypatch):
    monkeypatch.setattr(dq, "YEARS", ["2024"])
    results = dq.derive_for_entity(db, 1, "EquipCo")
    assert results == []
