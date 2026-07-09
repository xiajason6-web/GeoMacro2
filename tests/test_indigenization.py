"""Phase 3 tests: the indigenization ratio arithmetic on synthetic data.

These seed an in-memory database with hand-computed numbers so the expected
ratio is known exactly — if the pandas logic ever changes behavior (currency
conversion, incomplete-quarter handling, foundry exclusion, double-count
guard), these fail.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import indigenization_ratio as ir  # noqa: E402


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
    conn.execute(
        "INSERT INTO entities (name_en, entity_type, supply_chain_layer) VALUES ('EquipCo','company','equipment')"
    )
    conn.execute(
        "INSERT INTO entities (name_en, entity_type, supply_chain_layer) VALUES ('FoundryCo','company','foundry')"
    )
    yield conn
    conn.close()


def add_metric(conn, entity, metric, period, value):
    entity_id = conn.execute(
        "SELECT id FROM entities WHERE name_en = ?", (entity,)
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO metrics (entity_id, metric_name, period, value, unit, document_id)"
        " VALUES (?, ?, ?, ?, 'x', 1)",
        (entity_id, metric, period, value),
    )


def seed_complete_quarter(conn):
    # Q1 2026 imports: 100+200+300 = 600 EUR; fx 8.0 -> 4800 CNY
    for month, value in [("2026-01", 100), ("2026-02", 200), ("2026-03", 300)]:
        add_metric(conn, "China", "mirror_exports_eu27_hs8486_eur", month, value)
        add_metric(conn, "China", "fx_cny_per_eur_monthly_avg", month, 8.0)
    # domestic equipment revenue 12000 CNY
    add_metric(conn, "EquipCo", "quarterly_revenue_cny", "2026Q1", 12000)


def test_ratio_arithmetic(db):
    seed_complete_quarter(db)
    out = ir.compute_ratio(db)
    row = out.loc["2026Q1"]
    assert row.imports_eur == 600
    assert row.fx_cny_per_eur == 8.0
    assert row.imports_cny == 4800
    assert row.domestic_cny == 12000
    assert row.ratio == pytest.approx(12000 / (12000 + 4800))  # 0.714285...


def test_incomplete_quarter_excluded(db):
    seed_complete_quarter(db)
    # Q2 2026 has only one month of imports -> must NOT appear as an import quarter
    add_metric(db, "China", "mirror_exports_eu27_hs8486_eur", "2026-04", 999)
    add_metric(db, "China", "fx_cny_per_eur_monthly_avg", "2026-04", 8.0)
    out = ir.compute_ratio(db)
    assert "2026Q2" not in out.dropna(subset=["imports_eur"]).index


def test_foundry_revenue_excluded(db):
    seed_complete_quarter(db)
    add_metric(db, "FoundryCo", "quarterly_revenue_cny", "2026Q1", 999999)
    out = ir.compute_ratio(db)
    assert out.loc["2026Q1"].domestic_cny == 12000  # foundry not in numerator


def test_nl_de_series_not_double_counted(db):
    seed_complete_quarter(db)
    # NL/DE are subsets of EU27; even if present they must not enter the sum
    for month in ("2026-01", "2026-02", "2026-03"):
        add_metric(db, "China", "mirror_exports_nl_hs8486_eur", month, 5000)
    out = ir.compute_ratio(db)
    assert out.loc["2026Q1"].imports_eur == 600


def test_month_to_quarter():
    assert ir.month_to_quarter("2026-01") == "2026Q1"
    assert ir.month_to_quarter("2026-03") == "2026Q1"
    assert ir.month_to_quarter("2026-04") == "2026Q2"
    assert ir.month_to_quarter("2026-12") == "2026Q4"
