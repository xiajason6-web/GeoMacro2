"""Reconciliation tests: variant arithmetic on synthetic data (P2).

Seed, per month of 2025 (fx: EUR->2.0 USD, CNY->0.25 USD):
  EU27 imports 100 EUR -> 200 USD/mo -> 2,400 USD/yr  (legacy denominator)
  Korea imports 50 USD -> 600 USD/yr                   (full adds this)
Per quarter:
  Naura   domestic semicap 600 CNY -> 150 USD -> 600 USD/yr
  OtherCo domestic semicap 400 CNY -> 100 USD -> 400 USD/yr
  total revenue (both) 2,000 CNY -> 500 USD -> 2,000 USD/yr

Expected annual 2025 ratios:
  v2        = 1,000 / (1,000 + 3,000)  = 0.25
  A (total) = 2,000 / (2,000 + 3,000)  = 0.40
  B (legacy)= 1,000 / (1,000 + 2,400)  ~ 0.2941
  C (CNY)   = identical to v2
  D (Naura) =   600 / (  600 + 3,000)  ~ 0.1667
  legacy_both = 2,000 / (2,000+2,400)  ~ 0.4545
"""

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import reconciliation as rec  # noqa: E402


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.executescript((ROOT / "db" / "schema.sql").read_text())
    conn.execute("INSERT INTO sources (name, url, type, language) VALUES ('t','u','trade_stats','en')")
    conn.execute(
        "INSERT INTO documents (source_id,url,retrieved_at,raw_path,sha256,title,language)"
        " VALUES (1,'u','t','p','s1','t','en')"
    )
    conn.execute("INSERT INTO entities (name_en, entity_type) VALUES ('China','country')")
    for name in ("Naura", "OtherCo"):
        conn.execute(
            "INSERT INTO entities (name_en, entity_type, supply_chain_layer)"
            " VALUES (?, 'company', 'equipment')",
            (name,),
        )
    for month in range(1, 13):
        period = f"2025-{month:02d}"
        for currency, rate in (("EUR", 2.0), ("USD", 1.0), ("CNY", 0.25)):
            conn.execute(
                "INSERT INTO fx_rates (currency, period, usd_per_unit, document_id)"
                " VALUES (?, ?, ?, 1)",
                (currency, period, rate),
            )
        for metric, value in (
            ("mirror_exports_eu27_hs8486_eur", 100),
            ("mirror_exports_kr_hs8486_usd", 50),
        ):
            conn.execute(
                "INSERT INTO metrics (entity_id, metric_name, period, value, unit, document_id)"
                " VALUES (1, ?, ?, ?, 'x', 1)",
                (metric, period, value),
            )
    for q in range(1, 5):
        for name, semicap, total in (("Naura", 600, 1_200), ("OtherCo", 400, 800)):
            entity_id = conn.execute(
                "SELECT id FROM entities WHERE name_en = ?", (name,)
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO metrics (entity_id, metric_name, period, value, unit, document_id)"
                " VALUES (?, 'domestic_semicap_revenue_cny', ?, ?, 'x', 1)",
                (entity_id, f"2025Q{q}", semicap),
            )
            conn.execute(
                "INSERT INTO metrics (entity_id, metric_name, period, value, unit, document_id)"
                " VALUES (?, 'quarterly_revenue_cny', ?, ?, 'x', 1)",
                (entity_id, f"2025Q{q}", total),
            )
    yield conn
    conn.close()


def test_variant_arithmetic(db, monkeypatch):
    monkeypatch.setattr(rec, "UBS_SCOPE_ENTITIES", ["Naura"])
    variants, n_q = rec.compute_variants(db, 2025)
    assert n_q == 4
    assert variants["v2_headline"] == pytest.approx(0.25)
    assert variants["A_total_revenue_numerator"] == pytest.approx(0.40)
    assert variants["B_legacy_denominator"] == pytest.approx(1_000 / 3_400)
    assert variants["C_cny_common_unit"] == pytest.approx(0.25)
    assert variants["D_ubs_3_company_scope"] == pytest.approx(600 / 3_600)
    assert variants["legacy_style_both"] == pytest.approx(2_000 / 4_400)


def test_annual_ratio_requires_four_quarters(db):
    db.execute(
        "DELETE FROM metrics WHERE metric_name='domestic_semicap_revenue_cny'"
        " AND period='2025Q4'"
    )
    variants, _ = rec.compute_variants(db, 2025)
    assert variants["v2_headline"] is None


def test_markdown_pairs_ubs_with_comparable_variant(db, monkeypatch):
    monkeypatch.setattr(rec, "UBS_SCOPE_ENTITIES", ["Naura"])
    db.execute(
        "INSERT INTO benchmarks (source, period, value, numerator_scope,"
        " denominator_scope, method_notes, source_url)"
        " VALUES ('UBS (via EE Times)', '2025', 20.0,"
        " 'ACM Research + AMEC + Naura ONLY (3 companies)', 'x', 'n', 'u')"
    )
    import pandas as pd
    variants, _ = rec.compute_variants(db, 2025)
    benchmarks = pd.read_sql_query("SELECT * FROM benchmarks", db)
    md = rec.build_markdown(variants, benchmarks, "2025")
    assert "3-company variant" in md          # UBS compared against variant D
    assert "16.7%" in md                      # 600/3,600 rendered
