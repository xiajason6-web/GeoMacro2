"""P4 tests: nowcast arithmetic (carry-forward, vendor factor, extrapolation).

All seeds use USD-reporting series with usd_per_unit=1.0 so the expected
values are trivially hand-checkable.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import indigenization_ratio as ir  # noqa: E402
import nowcast as nc  # noqa: E402


def months_2025_2026():
    out = []
    for year in (2025, 2026):
        for m in range(1, 13):
            out.append(f"{year}-{m:02d}")
    return out


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
        "INSERT INTO entities (name_en, entity_type, supply_chain_layer)"
        " VALUES ('EquipCo','company','equipment')"
    )
    for period in months_2025_2026():
        for currency in ("USD", "CNY"):
            conn.execute(
                "INSERT INTO fx_rates (currency, period, usd_per_unit, document_id)"
                " VALUES (?, ?, ?, 1)",
                (currency, period, 1.0 if currency == "USD" else 0.25),
            )
    yield conn
    conn.close()


def add_import(conn, period, value, metric="mirror_exports_us_hs8486_usd"):
    conn.execute(
        "INSERT INTO metrics (entity_id, metric_name, period, value, unit, document_id)"
        " VALUES (1, ?, ?, ?, 'x', 1)",
        (metric, period, value),
    )


def test_quarter_helpers():
    assert nc.quarter_months("2026Q2") == ["2026-04", "2026-05", "2026-06"]
    assert nc.prev_quarter("2026Q1") == "2025Q4"
    assert nc.prev_quarter("2026Q2", 4) == "2025Q2"
    assert nc.prev_quarter("2025Q4", -1) == "2026Q1"


def test_carry_forward_fill(db):
    # US series: constant 100/month through 2026-04; May/June missing.
    for m in [f"2025-{i:02d}" for i in range(1, 13)] + ["2026-01", "2026-02", "2026-03", "2026-04"]:
        add_import(db, m, 100)
    df = ir.load_metrics(db)
    fx = ir.load_fx(db)
    est, sigma, drivers = nc.estimate_imports(db, df, fx, "2026Q2")
    assert est == pytest.approx(300)          # 100 observed + 2x100 filled
    assert sigma == pytest.approx(0)          # constant history -> zero dispersion
    assert any("1 filled" not in d and "2 filled" in d for d in drivers)


def test_vendor_factor_caps_and_applies(db):
    for m in [f"2025-{i:02d}" for i in range(1, 13)] + ["2026-01", "2026-02", "2026-03", "2026-04"]:
        add_import(db, m, 100)
    # Vendor panel: base window (2026-02..04, the carry-forward months) mean 40,
    # target window (2026-05) mean 10 -> raw 0.25 -> capped at 0.7.
    for date, pct in (("2026-02", 40.0), ("2026-05", 10.0)):
        db.execute(
            "INSERT INTO hifreq_signals (signal_date, signal_type, entity_id,"
            " value, unit, summary_en, document_id, retrieved_at)"
            " VALUES (?, 'vendor_china_revenue', NULL, ?, 'pct', ?, 1, 't')",
            (date + "-15", pct, f"sig {date}"),
        )
    df = ir.load_metrics(db)
    fx = ir.load_fx(db)
    est, _sigma, drivers = nc.estimate_imports(db, df, fx, "2026Q2")
    # filled portion 200 scaled by 0.7 -> 140; total = 100 + 140 = 240
    assert est == pytest.approx(240)
    assert any("vendor factor 0.70" in d for d in drivers)


def test_numerator_extrapolation(db):
    vals = {
        "2024Q4": 100, "2025Q1": 100, "2025Q2": 100,
        "2025Q4": 110, "2026Q1": 120,
    }
    for period, v in vals.items():
        db.execute(
            "INSERT INTO metrics (entity_id, metric_name, period, value, unit, document_id)"
            " VALUES (2, 'domestic_semicap_revenue_cny', ?, ?, 'x', 1)",
            (period, v),
        )
    df = ir.load_metrics(db)
    fx = ir.load_fx(db)
    est, sigma, drivers, measured = nc.estimate_numerator(df, fx, "2026Q2")
    # g = (110+120)/(100+100) = 1.15; base = 2025Q2 (100) * 1.15 = 115 CNY
    # -> USD at 0.25 = 28.75
    assert measured is False
    assert est == pytest.approx(28.75)
    assert any("EXTRAPOLATED" in d for d in drivers)


def test_measured_quarter_uses_measured(db):
    db.execute(
        "INSERT INTO metrics (entity_id, metric_name, period, value, unit, document_id)"
        " VALUES (2, 'domestic_semicap_revenue_cny', '2026Q2', 400, 'x', 1)"
    )
    df = ir.load_metrics(db)
    fx = ir.load_fx(db)
    est, sigma, drivers, measured = nc.estimate_numerator(df, fx, "2026Q2")
    assert measured is True
    assert sigma == 0.0
    assert est == pytest.approx(400 * 0.25)


def test_band_ordering(db):
    for m in [f"2025-{i:02d}" for i in range(1, 13)] + ["2026-01", "2026-02", "2026-03"]:
        add_import(db, m, 100 + (hash(m) % 20))  # some dispersion
    for period, v in (("2025Q2", 100), ("2025Q4", 110), ("2026Q1", 120), ("2024Q4", 100), ("2025Q1", 100)):
        db.execute(
            "INSERT INTO metrics (entity_id, metric_name, period, value, unit, document_id)"
            " VALUES (2, 'domestic_semicap_revenue_cny', ?, ?, 'x', 1)",
            (period, v),
        )
    out = nc.make_nowcast(db, "2026Q2")
    assert out is not None
    assert out["low"] <= out["ratio"] <= out["high"]
