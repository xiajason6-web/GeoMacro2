"""Phase 1 fixture tests for the mirror-trade collector.

Fixture: tests/fixtures/eurostat_nl_hs8486.json is a real Eurostat Comext API
response (Netherlands exports of HS 8486 to China, monthly, retrieved
2026-07-09). Known-good values below were read from that response.
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "collectors"))

import mirror_trade  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "eurostat_nl_hs8486.json"


@pytest.fixture
def payload():
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript((ROOT / "db" / "schema.sql").read_text())
    yield conn
    conn.close()


# ---- parsing ----------------------------------------------------------------

def test_parse_returns_all_populated_months(payload):
    rows = mirror_trade.parse_eurostat_response(payload)
    assert len(rows) == 34
    assert rows[0] == ("2023-07", 451701097.0)   # known-good first month
    assert rows[-1] == ("2026-04", 61123357.0)   # known-good last month


def test_parse_skips_future_months_without_data(payload):
    # The API's time index includes 2026-05..2026-12 with no values yet;
    # inventing zeros for them would corrupt every downstream series.
    rows = mirror_trade.parse_eurostat_response(payload)
    periods = [p for p, _ in rows]
    assert "2026-05" not in periods
    assert "2026-12" not in periods
    assert periods == sorted(periods)  # chronological


# ---- storage ----------------------------------------------------------------

def test_ingest_raw_dedupes_identical_bytes(db, tmp_path, monkeypatch):
    monkeypatch.setattr(mirror_trade, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(mirror_trade, "REPO_ROOT", tmp_path)
    source_id = mirror_trade.ensure_source(db, mirror_trade.EUROSTAT_SOURCE)
    content = FIXTURE.read_bytes()
    doc1, new1 = mirror_trade.ingest_raw(db, source_id, "https://x", content, "t")
    doc2, new2 = mirror_trade.ingest_raw(db, source_id, "https://x", content, "t")
    assert new1 is True
    assert new2 is False
    assert doc1 == doc2  # same bytes -> same document row


def test_write_metrics_rows_link_to_document(db, tmp_path, monkeypatch, payload):
    monkeypatch.setattr(mirror_trade, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(mirror_trade, "REPO_ROOT", tmp_path)
    source_id = mirror_trade.ensure_source(db, mirror_trade.EUROSTAT_SOURCE)
    entity_id = mirror_trade.ensure_china_entity(db)
    doc_id, _ = mirror_trade.ingest_raw(
        db, source_id, "https://x", FIXTURE.read_bytes(), "t"
    )
    rows = mirror_trade.parse_eurostat_response(payload)
    mirror_trade.write_metrics(
        db, entity_id, "mirror_exports_nl_hs8486_eur", rows, "EUR", "EUR", doc_id, "note"
    )
    count, = db.execute("SELECT COUNT(*) FROM metrics").fetchone()
    assert count == 34
    # every row is traceable to the raw document
    orphans, = db.execute(
        "SELECT COUNT(*) FROM metrics WHERE document_id != ?", (doc_id,)
    ).fetchone()
    assert orphans == 0
    # re-writing the same document's rows is a no-op (UNIQUE guard)
    mirror_trade.write_metrics(
        db, entity_id, "mirror_exports_nl_hs8486_eur", rows, "EUR", "EUR", doc_id, "note"
    )
    count2, = db.execute("SELECT COUNT(*) FROM metrics").fetchone()
    assert count2 == 34


# ---- Japan (e-Stat) parsing ---------------------------------------------------

ESTAT_FIXTURE = Path(__file__).parent / "fixtures" / "estat_jp_hs8486_2026.json"


def test_estat_parse_drops_zero_filled_unpublished_months():
    payload = json.loads(ESTAT_FIXTURE.read_text())
    rows = mirror_trade.parse_estat_response(payload)
    periods = [p for p, _ in rows]
    # Table published Jan-May 2026; Jun-Dec are zero-filled by e-Stat and
    # must NOT appear as real zeros.
    assert periods == ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05"]
    # Known-good: Jan 2026 = 101,449,288 thousand yen summed across the five
    # HS-9 sub-codes, converted to yen.
    assert rows[0] == ("2026-01", 101_449_288_000)


# ---- dynamic reporting periods (cninfo) ---------------------------------------

def test_cninfo_periods_track_the_calendar():
    import datetime
    import cninfo_filings as cf

    # Mid-July 2026: Q1s through 2026 exist; 2026Q3's window hasn't opened;
    # H1 2026 summaries JUST opened (July 1); FY2025 annuals open, FY2026 not.
    today = datetime.date(2026, 7, 13)
    tags = [p[0] for p in cf.build_periods(today)]
    assert "2026Q1" in tags and "2026Q3" not in tags and "2023Q1" in tags
    stags = [p[0] for p in cf.build_summary_periods(today)]
    assert "2026H1" in stags and "2025" in stags and "2026" not in stags
    years = [y for y, _ in cf.build_annual_full(today)]
    assert years == ["2023", "2024", "2025"]

    # Same date next year: the new seasons appear without a code change.
    later = datetime.date(2026, 10, 2)
    assert "2026Q3" in [p[0] for p in cf.build_periods(later)]
