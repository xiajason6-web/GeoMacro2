"""Phase 3 tests: the indigenization ratio arithmetic on synthetic data.

These seed an in-memory database with hand-computed numbers so the expected
ratio is known exactly — if the pandas logic ever changes behavior (currency
conversion, incomplete-quarter handling, missing-series handling, foundry
exclusion, double-count guard), these fail.

Hand-computed expectations for the seeded Q1 2026:
  EUR imports: 100+200+300 = 600 EUR at 8.0 CNY/EUR          =  4,800 CNY
  JPY imports: 20k+20k+20k = 60,000 JPY at 8.0/16.0 = 0.5    = 30,000 CNY
  USD imports: 100+100+100 = 300 USD at 8.0/2.0 = 4.0        =  1,200 CNY
  imports total                                              = 36,000 CNY
  domestic equipment revenue                                  = 12,000 CNY
  ratio = 12,000 / 48,000                                     = 0.25
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
    for month, eur_value in [("2026-01", 100), ("2026-02", 200), ("2026-03", 300)]:
        add_metric(conn, "China", "mirror_exports_eu27_hs8486_eur", month, eur_value)
        add_metric(conn, "China", "mirror_exports_jp_hs8486_jpy", month, 20_000)
        add_metric(conn, "China", "mirror_exports_us_hs8486_usd", month, 100)
        add_metric(conn, "China", "fx_cny_per_eur_monthly_avg", month, 8.0)
        add_metric(conn, "China", "fx_jpy_per_eur_monthly_avg", month, 16.0)
        add_metric(conn, "China", "fx_usd_per_eur_monthly_avg", month, 2.0)
    add_metric(conn, "EquipCo", "quarterly_revenue_cny", "2026Q1", 12_000)


def test_ratio_arithmetic(db):
    seed_complete_quarter(db)
    out = ir.compute_ratio(db)
    row = out.loc["2026Q1"]
    assert row.imports_cny == pytest.approx(36_000)  # EUR 4,800 + JPY 30,000 + USD 1,200
    assert row.n_import_series == 3
    assert row.domestic_cny == 12_000
    assert row.ratio == pytest.approx(0.25)


def test_incomplete_quarter_excluded(db):
    seed_complete_quarter(db)
    # Q2 2026: both series present but only one month each -> excluded
    add_metric(db, "China", "mirror_exports_eu27_hs8486_eur", "2026-04", 999)
    add_metric(db, "China", "mirror_exports_jp_hs8486_jpy", "2026-04", 999)
    add_metric(db, "China", "mirror_exports_us_hs8486_usd", "2026-04", 999)
    add_metric(db, "China", "fx_cny_per_eur_monthly_avg", "2026-04", 8.0)
    add_metric(db, "China", "fx_jpy_per_eur_monthly_avg", "2026-04", 16.0)
    add_metric(db, "China", "fx_usd_per_eur_monthly_avg", "2026-04", 2.0)
    out = ir.compute_ratio(db)
    assert "2026Q2" not in out.dropna(subset=["imports_cny"]).index


def test_quarter_missing_one_series_excluded(db):
    seed_complete_quarter(db)
    # Q3 2025: full EUR quarter but NO Japan data at all -> excluded, because
    # summing a partial-coverage quarter would understate imports silently.
    for month in ("2025-07", "2025-08", "2025-09"):
        add_metric(db, "China", "mirror_exports_eu27_hs8486_eur", month, 100)
        add_metric(db, "China", "fx_cny_per_eur_monthly_avg", month, 8.0)
        add_metric(db, "China", "fx_jpy_per_eur_monthly_avg", month, 16.0)
    out = ir.compute_ratio(db)
    assert "2025Q3" not in out.dropna(subset=["imports_cny"]).index


def test_foundry_revenue_excluded(db):
    seed_complete_quarter(db)
    add_metric(db, "FoundryCo", "quarterly_revenue_cny", "2026Q1", 999_999)
    out = ir.compute_ratio(db)
    assert out.loc["2026Q1"].domestic_cny == 12_000


def test_nl_de_series_not_double_counted(db):
    seed_complete_quarter(db)
    for month in ("2026-01", "2026-02", "2026-03"):
        add_metric(db, "China", "mirror_exports_nl_hs8486_eur", month, 5_000)
    out = ir.compute_ratio(db)
    assert out.loc["2026Q1"].imports_cny == pytest.approx(36_000)


def test_month_to_quarter():
    assert ir.month_to_quarter("2026-01") == "2026Q1"
    assert ir.month_to_quarter("2026-03") == "2026Q1"
    assert ir.month_to_quarter("2026-04") == "2026Q2"
    assert ir.month_to_quarter("2026-12") == "2026Q4"


def test_segment_share_adjusts_numerator(db):
    seed_complete_quarter(db)
    # EquipCo disclosed FY2025 semicap share of 50% — with no FY2026 row yet,
    # 2026 quarters fall back to the most recent earlier year.
    add_metric(db, "EquipCo", "semicap_segment_share_pct", "2025", 50.0)
    out = ir.compute_ratio(db)
    assert out.loc["2026Q1"].domestic_cny == 6_000       # 12,000 * 0.5
    assert out.loc["2026Q1"].ratio == pytest.approx(6_000 / 42_000)


def test_no_segment_data_means_no_adjustment(db):
    seed_complete_quarter(db)
    out = ir.compute_ratio(db)
    assert out.loc["2026Q1"].domestic_cny == 12_000      # factor defaults to 1.0
