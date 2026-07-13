"""P3 tests: vendor-filing collector/extraction helpers and Big Fund signals.

Fixtures: edgar_amat_submissions.json (real EDGAR submissions index) and
bigfund_search.json (real cninfo full-text search response), both retrieved
2026-07-13.
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "collectors"))
sys.path.insert(0, str(ROOT / "extraction"))

import big_fund  # noqa: E402
import extract_vendor_china as evc  # noqa: E402
import vendor_china_revenue as vcr  # noqa: E402

EDGAR_FIXTURE = Path(__file__).parent / "fixtures" / "edgar_amat_submissions.json"
BIGFUND_FIXTURE = Path(__file__).parent / "fixtures" / "bigfund_search.json"


# ---- EDGAR submissions parsing -------------------------------------------------

def test_recent_filings_returns_only_quarterly_and_annual():
    payload = json.loads(EDGAR_FIXTURE.read_text())
    filings = vcr.recent_filings(payload, n=6)
    assert len(filings) == 6
    assert {f["form"] for f in filings} <= {"10-Q", "10-K"}
    for f in filings:
        assert f["report_date"] and f["primary_doc"].endswith(".htm")
    # newest first
    dates = [f["filing_date"] for f in filings]
    assert dates == sorted(dates, reverse=True)


def test_filing_url_shape():
    url = vcr.filing_url(
        "0000006951",
        {"accession": "0001628280-26-037227", "primary_doc": "amat-20260426.htm"},
    )
    assert url == (
        "https://www.sec.gov/Archives/edgar/data/6951/000162828026037227/"
        "amat-20260426.htm"
    )


# ---- China snippet windowing ----------------------------------------------------

def test_china_snippets_merges_windows_and_caps():
    html = (
        "<html><body>" + "x " * 5000
        + "<p>Revenue in China was $1,000 for the quarter.</p>" + "y " * 500
        + "<p>China accounted for 30% of net revenue.</p>" + "z " * 5000
        + "</body></html>"
    )
    out = evc.china_snippets(html, window=200, cap=5000)
    assert "China was $1,000" in out
    assert "30% of net revenue" in out
    assert len(out) <= 5000
    # windowing keeps only ~200 chars around each mention, not the ~21k text
    assert len(out) < 2000


def test_china_snippets_empty_when_no_mention():
    assert evc.china_snippets("<p>nothing relevant</p>") == ""


# ---- vendor validation -----------------------------------------------------------

def test_vendor_validate():
    good = {
        "fiscal_period_end": "2026-04-26",
        "china_revenue_pct": 27.0,
        "basis": "b", "evidence": "e", "confidence": 0.9,
    }
    assert evc.validate(good, "2026-04-26") == []
    assert evc.validate(dict(good, fiscal_period_end="2026-01-01"), "2026-04-26") != []
    assert evc.validate(dict(good, china_revenue_pct=150), "2026-04-26") != []


# ---- Big Fund parsing and signal dedupe -------------------------------------------

def test_bigfund_parse():
    payload = json.loads(BIGFUND_FIXTURE.read_text())
    signals = big_fund.parse_announcements(payload.get("announcements") or [])
    assert signals, "fixture should contain announcements"
    for sig in signals:
        assert "<em>" not in sig["title"]
        assert sig["url"].startswith("https://static.cninfo.com.cn/")
        assert len(sig["date"].split("-")) == 3


def test_signal_emit_dedupes():
    conn = sqlite3.connect(":memory:")
    conn.executescript((ROOT / "db" / "schema.sql").read_text())
    conn.execute("INSERT INTO sources (name, url, type, language) VALUES ('t','u','earnings','en')")
    conn.execute(
        "INSERT INTO documents (source_id,url,retrieved_at,raw_path,sha256,title,language)"
        " VALUES (1,'u','t','p','s1','t','en')"
    )
    conn.execute(
        "INSERT INTO entities (name_en, entity_type, supply_chain_layer)"
        " VALUES ('Applied Materials','company','equipment_foreign')"
    )
    assert evc.emit_signal(conn, 1, "Applied Materials", 1, "2026-05-21", "2026-04", 27.0) is True
    assert evc.emit_signal(conn, 1, "Applied Materials", 1, "2026-05-21", "2026-04", 27.0) is False
    count, = conn.execute("SELECT COUNT(*) FROM hifreq_signals").fetchone()
    assert count == 1
    conn.close()


def test_foreign_vendors_never_enter_numerator():
    """Layer 'equipment_foreign' must not satisfy the ratio's equipment filter."""
    sys.path.insert(0, str(ROOT / "analysis"))
    import pandas as pd
    import indigenization_ratio as ir

    df = pd.DataFrame(
        [
            {"entity": "Applied Materials", "layer": "equipment_foreign",
             "metric_name": "domestic_semicap_revenue_cny", "period": "2026Q1",
             "value": 999.0, "notes": None},
        ]
    )
    out = ir.quarterly_domestic_usd(df, {"CNY": {"2026-01": 0.25}})
    assert out.empty
