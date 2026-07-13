"""Ratio v2 tests: USD normalization, coverage fields, numerator scope.

Hand-computed seed for 2026Q1 (fx: EUR->2.0, JPY->0.01, USD->1.0, CNY->0.25
USD per unit):
  EU27 imports  100+200+300 = 600 EUR  -> 1,200 USD
  Japan imports 20k x 3     = 60k JPY  ->   600 USD
  US imports    100 x 3     = 300 USD  ->   300 USD
  Korea imports 50 x 3      = 150 USD  ->   150 USD
  Singapore: no data                   -> named in missing_origins
  imports total                        -> 2,250 USD
  domestic semicap revenue  8,000 CNY  -> 2,000 USD
  ratio = 2,000 / 4,250 = 0.470588...
"""

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import indigenization_ratio as ir  # noqa: E402

Q1_MONTHS = ("2026-01", "2026-02", "2026-03")


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


def add_metric(conn, entity, metric, period, value, notes=None):
    entity_id = conn.execute(
        "SELECT id FROM entities WHERE name_en = ?", (entity,)
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO metrics (entity_id, metric_name, period, value, unit, document_id, notes)"
        " VALUES (?, ?, ?, ?, 'x', 1, ?)",
        (entity_id, metric, period, value, notes),
    )


def add_fx(conn, currency, period, usd_per_unit):
    conn.execute(
        "INSERT OR REPLACE INTO fx_rates (currency, period, usd_per_unit, document_id)"
        " VALUES (?, ?, ?, 1)",
        (currency, period, usd_per_unit),
    )


def seed(conn, fx_currencies=("EUR", "JPY", "USD", "CNY")):
    rates = {"EUR": 2.0, "JPY": 0.01, "USD": 1.0, "CNY": 0.25}
    for i, month in enumerate(Q1_MONTHS):
        for currency in fx_currencies:
            add_fx(conn, currency, month, rates[currency])
        add_metric(conn, "China", "mirror_exports_eu27_hs8486_eur", month, [100, 200, 300][i])
        add_metric(conn, "China", "mirror_exports_jp_hs8486_jpy", month, 20_000)
        add_metric(conn, "China", "mirror_exports_us_hs8486_usd", month, 100)
        add_metric(conn, "China", "mirror_exports_kr_hs8486_usd", month, 50)
    add_metric(conn, "EquipCo", "domestic_semicap_revenue_cny", "2026Q1", 8_000,
               notes="DERIVED (python): quarterly_revenue x 90.0% semicap x 95.0% domestic")


def test_usd_ratio_arithmetic(db):
    seed(db)
    row = ir.compute_ratio(db).loc["2026Q1"]
    assert row.imports_usd == pytest.approx(2_250)
    assert row.domestic_semicap_usd == pytest.approx(2_000)
    assert row.ratio == pytest.approx(2_000 / 4_250)
    assert row.methodology_version == ir.METHODOLOGY_VERSION


def test_coverage_fields_name_missing_origins(db):
    seed(db)
    row = ir.compute_ratio(db).loc["2026Q1"]
    assert row.coverage_origins == "EU27+Japan+Korea+US"
    assert "Singapore" in row.missing_origins
    assert "Taiwan" in row.missing_origins  # no machine-readable source, always named


def test_unconverted_values_never_aggregated(db):
    """THE currency guard (work order P1.1): remove the JPY rate — the JPY
    series must be EXCLUDED from the total, not summed at native value.
    If aggregation ever touches unconverted values, imports_usd would be
    inflated by ~60,000 native JPY and this fails loudly."""
    seed(db, fx_currencies=("EUR", "USD", "CNY"))  # no JPY rates
    row = ir.compute_ratio(db).loc["2026Q1"]
    assert row.imports_usd == pytest.approx(2_250 - 600)   # JPY leg gone
    assert "Japan" in row.missing_origins                  # gap named, not silent


def test_partial_quarter_series_excluded_and_named(db):
    seed(db)
    add_fx(db, "USD", "2026-01", 1.0)
    add_metric(db, "China", "mirror_exports_sg_hs8486_usd", "2026-01", 999)  # 1 of 3 months
    row = ir.compute_ratio(db).loc["2026Q1"]
    assert row.imports_usd == pytest.approx(2_250)         # partial series not summed
    assert "Singapore" in row.missing_origins


def test_estimated_flags_counted(db):
    seed(db)
    add_metric(db, "EquipCo", "domestic_semicap_revenue_cny", "2025Q4", 5_000,
               notes="DERIVED (python): ... | ESTIMATED(share-year)")
    for month in ("2025-10", "2025-11", "2025-12"):
        add_fx(db, "CNY", month, 0.25)
    out = ir.compute_ratio(db)
    assert out.loc["2025Q4"].n_estimated == 1
    assert out.loc["2026Q1"].n_estimated == 0


def test_foundry_rows_never_in_numerator(db):
    seed(db)
    add_metric(db, "FoundryCo", "domestic_semicap_revenue_cny", "2026Q1", 999_999)
    row = ir.compute_ratio(db).loc["2026Q1"]
    assert row.domestic_semicap_usd == pytest.approx(2_000)


def test_nl_de_series_not_double_counted(db):
    seed(db)
    for month in Q1_MONTHS:
        add_metric(db, "China", "mirror_exports_nl_hs8486_eur", month, 5_000)
    row = ir.compute_ratio(db).loc["2026Q1"]
    assert row.imports_usd == pytest.approx(2_250)


def test_month_to_quarter():
    assert ir.month_to_quarter("2026-01") == "2026Q1"
    assert ir.month_to_quarter("2026-12") == "2026Q4"
