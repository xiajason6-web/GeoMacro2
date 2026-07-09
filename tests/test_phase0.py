"""Phase 0 fixture tests.

What this covers:
1. The extraction validator accepts a known-good payload and rejects bad ones.
2. The collector's ingest logic records a document correctly and refuses to
   double-ingest identical bytes (the sha256 guard).
3. (Only when an API key is available) the real extraction against the saved
   ASML Q1 2026 presentation returns the known-good values: period 2026Q1,
   China at 19% — a figure independently corroborated by press coverage of
   ASML's Q1 2026 results.

Run with:  .venv/bin/python -m pytest tests/ -v
"""

import hashlib
import os
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "extraction"))
sys.path.insert(0, str(ROOT / "collectors"))

import schemas  # noqa: E402
import western_earnings  # noqa: E402

FIXTURE_PDF = Path(__file__).parent / "fixtures" / "asml_ir_q1_2026.pdf"

GOOD_PAYLOAD = {
    "period": "2026Q1",
    "china_pct": 19,
    "basis": "total net sales",
    "evidence": "Slide 5, 'Total net sales by region' pie chart, China 19%",
    "confidence": 0.9,
}


# ---- 1. validator ----------------------------------------------------------

def test_validator_accepts_known_good():
    assert schemas.validate_earnings_region(GOOD_PAYLOAD) == []


def test_validator_accepts_null_china_pct():
    payload = dict(GOOD_PAYLOAD, china_pct=None)
    assert schemas.validate_earnings_region(payload) == []


@pytest.mark.parametrize(
    "bad",
    [
        dict(GOOD_PAYLOAD, china_pct=190),                  # out of range
        dict(GOOD_PAYLOAD, china_pct="19%"),                # wrong type
        dict(GOOD_PAYLOAD, period="Q1 2026"),               # wrong format
        dict(GOOD_PAYLOAD, confidence=1.5),                 # out of range
        dict(GOOD_PAYLOAD, evidence=""),                    # empty evidence
        {k: v for k, v in GOOD_PAYLOAD.items() if k != "basis"},  # missing field
        dict(GOOD_PAYLOAD, extra_field="surprise"),          # unexpected field
        "not even a dict",
    ],
)
def test_validator_rejects_bad_payloads(bad):
    assert schemas.validate_earnings_region(bad) != []


# ---- 2. collector ingest ----------------------------------------------------

@pytest.fixture
def db(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript((ROOT / "db" / "schema.sql").read_text())
    yield conn
    conn.close()


def test_ingest_document_records_row_and_sha(db, tmp_path):
    source_id = western_earnings.ensure_source(db)
    content = FIXTURE_PDF.read_bytes()
    doc_id = western_earnings.ingest_document(
        db, source_id, "https://example.com/x.pdf", content,
        "ASML Q1 2026", "2026-04-15", tmp_path / "raw" / "x.pdf", repo_root=tmp_path,
    )
    assert doc_id is not None
    sha, raw_path = db.execute(
        "SELECT sha256, raw_path FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    assert sha == hashlib.sha256(content).hexdigest()
    assert (tmp_path / raw_path).read_bytes() == content  # raw copy is byte-identical


def test_ingest_document_skips_duplicate_bytes(db, tmp_path):
    source_id = western_earnings.ensure_source(db)
    content = FIXTURE_PDF.read_bytes()
    first = western_earnings.ingest_document(
        db, source_id, "https://example.com/x.pdf", content,
        "t", "2026-04-15", tmp_path / "a.pdf", repo_root=tmp_path,
    )
    second = western_earnings.ingest_document(
        db, source_id, "https://example.com/other-url.pdf", content,
        "t", "2026-04-15", tmp_path / "b.pdf", repo_root=tmp_path,
    )
    assert first is not None
    assert second is None  # identical bytes are never ingested twice
    count = db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    assert count == 1


# ---- 3. real extraction (needs API key; skipped otherwise) -------------------

def _api_key_available():
    import extract_earnings_region
    extract_earnings_region.load_env()
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


@pytest.mark.skipif(
    not _api_key_available(), reason="ANTHROPIC_API_KEY not set (in env or .env)"
)
def test_extraction_matches_known_good_values():
    import extract_earnings_region

    model = os.environ.get("EXTRACTION_MODEL", "claude-haiku-4-5")
    data, _usage = extract_earnings_region.extract_from_pdf(
        FIXTURE_PDF.read_bytes(), model
    )
    assert schemas.validate_earnings_region(data) == []
    assert data["period"] == "2026Q1"
    # Press coverage of ASML's Q1 2026 results consistently reports China at
    # 19% of sales (down from 36% in Q4 2025).
    assert data["china_pct"] == pytest.approx(19, abs=0.5)
