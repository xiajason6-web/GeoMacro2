"""Chip self-sufficiency proxy tests (analysis/chip_self_sufficiency.py).

Synthetic in-memory DB, all fx = 1 so USD == native value. Two quarters:

  2025Q1: SMIC 100 + Hua Hong 50 CNY -> domestic logic 150 USD; chip imports
          5 origins x 100/mo x 3 = 1,500 USD -> share 150/1650 = 9.09%
  2025Q2: SMIC 200 + Hua Hong 100 -> 300 USD (index 200); imports unchanged
          1,500 -> share 300/1800 = 16.67%

Pins the foundry-proxy sum, the full-coverage chip-import total, and the
domestic-share + index arithmetic.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import indigenization_ratio as ir  # noqa: E402
import chip_self_sufficiency as css  # noqa: E402

MONTHS = [f"2025-{m:02d}" for m in range(1, 7)]  # 2025Q1 + Q2
FOUNDRY = {  # (entity, quarter) -> CNY revenue
    ("SMIC", "2025Q1"): 100.0, ("Hua Hong", "2025Q1"): 50.0,
    ("SMIC", "2025Q2"): 200.0, ("Hua Hong", "2025Q2"): 100.0,
}


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.executescript((ROOT / "db" / "schema.sql").read_text())
    conn.execute("INSERT INTO sources (name,url,type,language) VALUES ('t','u','trade_stats','en')")
    conn.execute(
        "INSERT INTO documents (source_id,url,retrieved_at,raw_path,sha256,title,language)"
        " VALUES (1,'u','t','p','s1','t','en')"
    )
    for cur in ("CNY", "EUR", "JPY", "USD"):
        for m in MONTHS:
            conn.execute(
                "INSERT INTO fx_rates (currency,period,usd_per_unit,document_id)"
                " VALUES (?,?,1.0,1)", (cur, m))
    # domestic foundries
    for name in ("SMIC", "Hua Hong"):
        conn.execute(
            "INSERT INTO entities (name_en,entity_type,supply_chain_layer)"
            " VALUES (?, 'company','foundry')", (name,))
        eid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for q in ("2025Q1", "2025Q2"):
            conn.execute(
                "INSERT INTO metrics (entity_id,metric_name,period,value,unit,currency,document_id)"
                " VALUES (?, 'quarterly_revenue_cny', ?, ?, 'CNY_mn','CNY',1)",
                (eid, q, FOUNDRY[(name, q)]))
    # chip imports (China entity), HS 8542, all five origins, 100/month
    conn.execute(
        "INSERT INTO entities (name_en,entity_type,supply_chain_layer)"
        " VALUES ('China','country',NULL)")
    cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    for metric, (_o, cur) in css.CHIP_SERIES.items():
        for m in MONTHS:
            conn.execute(
                "INSERT INTO metrics (entity_id,metric_name,period,value,unit,currency,document_id)"
                " VALUES (?,?,?,100.0,'USD_mn',?,1)", (cid, metric, m, cur))
    conn.commit()
    return conn


def test_foundry_proxy_sums_listed_foundries(db):
    df, fx = ir.load_metrics(db), ir.load_fx(db)
    foundry = css.quarterly_foundry_usd(df, fx)
    assert foundry["2025Q1"] == pytest.approx(150.0)
    assert foundry["2025Q2"] == pytest.approx(300.0)


def test_chip_imports_full_coverage_total(db):
    df, fx = ir.load_metrics(db), ir.load_fx(db)
    chips = css.chip_imports_usd(df, fx)
    assert chips["2025Q1"] == pytest.approx(1500.0)
    assert chips["2025Q2"] == pytest.approx(1500.0)


def test_domestic_share_and_index(db):
    data = css.build(db)
    t = data["rows"]
    assert data["base"] == "2025Q1"
    assert t.loc["2025Q1", "chip_domestic_share"] == pytest.approx(150 / 1650)
    assert t.loc["2025Q2", "chip_domestic_share"] == pytest.approx(300 / 1800)
    assert t.loc["2025Q2", "domestic_logic_idx"] == pytest.approx(200.0)
    assert t.loc["2025Q2", "chip_imports_idx"] == pytest.approx(100.0)
