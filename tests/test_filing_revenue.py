"""Phase 2 fixture tests: cninfo filings and Mandarin revenue extraction.

Fixture: tests/fixtures/naura_q1_2026.pdf is Naura's (北方华创, 002371) real
2026 Q1 quarterly report as filed on cninfo, retrieved 2026-07-09. Press
coverage of the filing (Eastmoney, Sohu, 2026-05-01) reports Q1 2026
operating revenue of 10.323 billion CNY, +25.80% year over year — those are
the expected values for the live-extraction test.
"""

import os
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "extraction"))
sys.path.insert(0, str(ROOT / "collectors"))

import schemas  # noqa: E402

FIXTURE_PDF = Path(__file__).parent / "fixtures" / "naura_q1_2026.pdf"

GOOD_PAYLOAD = {
    "period": "2026Q1",
    "revenue_cny": 10_323_000_000,
    "revenue_yoy_pct": 25.80,
    "summary_zh": "本季度营业收入103.23亿元，同比增长25.80%。",
    "summary_en": "Q1 revenue of 10.32bn CNY, up 25.8% year over year.",
    "evidence": "主要会计数据表，本报告期营业收入",
    "confidence": 0.95,
}


# ---- validator ---------------------------------------------------------------

def test_validator_accepts_known_good():
    assert schemas.validate_filing_revenue(GOOD_PAYLOAD) == []


def test_validator_accepts_null_yoy():
    assert schemas.validate_filing_revenue(dict(GOOD_PAYLOAD, revenue_yoy_pct=None)) == []


@pytest.mark.parametrize(
    "bad",
    [
        dict(GOOD_PAYLOAD, revenue_cny=103.23),        # 亿元 pasted as 元 — implausible
        dict(GOOD_PAYLOAD, revenue_cny="103亿"),        # wrong type
        dict(GOOD_PAYLOAD, revenue_yoy_pct=25000),     # absurd yoy
        dict(GOOD_PAYLOAD, period="2026年一季度"),      # wrong period format
        dict(GOOD_PAYLOAD, summary_zh=""),             # empty Chinese summary
        {k: v for k, v in GOOD_PAYLOAD.items() if k != "summary_en"},
        dict(GOOD_PAYLOAD, bonus_field=1),
    ],
)
def test_validator_rejects_bad_payloads(bad):
    assert schemas.validate_filing_revenue(bad) != []


# ---- pending-filings query ----------------------------------------------------

@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript((ROOT / "db" / "schema.sql").read_text())
    conn.execute(
        "INSERT INTO sources (name, url, type, language) VALUES ('cninfo', 'u', 'filing', 'zh')"
    )
    conn.execute(
        "INSERT INTO entities (name_en, name_zh, entity_type) VALUES ('Naura', '北方华创', 'company')"
    )
    conn.execute(
        "INSERT INTO documents (source_id, url, retrieved_at, raw_path, sha256, title, language)"
        " VALUES (1, 'u', 't', 'p', 'abc', '北方华创 2026年一季度报告', 'zh')"
    )
    yield conn
    conn.close()


def test_pending_filings_finds_unextracted_document(db):
    import extract_filing_revenue

    rows = extract_filing_revenue.pending_filings(db)
    assert len(rows) == 1
    doc_id, _path, title, entity_id, name_en = rows[0]
    assert name_en == "Naura"

    # Once the metric exists, the document drops out of the queue.
    db.execute(
        "INSERT INTO metrics (entity_id, metric_name, period, value, unit, document_id)"
        " VALUES (?, 'quarterly_revenue_cny', '2026Q1', 1e9, 'CNY', ?)",
        (entity_id, doc_id),
    )
    assert extract_filing_revenue.pending_filings(db) == []


# ---- real extraction (needs API key; skipped otherwise) -----------------------

def _api_key_available():
    import extract_filing_revenue
    extract_filing_revenue.load_env()
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


@pytest.mark.skipif(
    not _api_key_available(), reason="ANTHROPIC_API_KEY not set (in env or .env)"
)
def test_extraction_matches_press_reported_values():
    import extract_filing_revenue

    model = os.environ.get("EXTRACTION_MODEL", "claude-haiku-4-5")
    data, _usage = extract_filing_revenue.extract_from_pdf(
        FIXTURE_PDF.read_bytes(), model
    )
    assert schemas.validate_filing_revenue(data) == []
    assert data["period"] == "2026Q1"
    # Press-corroborated: 103.23亿元 revenue, +25.80% yoy.
    assert data["revenue_cny"] == pytest.approx(10.323e9, rel=0.005)
    assert data["revenue_yoy_pct"] == pytest.approx(25.80, abs=0.1)
