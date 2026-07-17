"""Chip-layer DiD tests (analysis/did_chip_controls.py).

The DiD/event-study machinery is already pinned by test_did.py; here we test
the chip-specific pieces: the module runs on an HS 8542 panel, and the
bite-then-recovery SHAPE is detected. Synthetic in-memory DB, fx = 1. Four
origins flat at 100/month; the US chip series is cut (exp(-0.6)) from Oct-2022
then recovers (exp(+0.6)) from Oct-2023 — a planted V. So: trough is negative,
latest recovers above the trough, and suppression at the trough is positive
(US below the allied-implied counterfactual).
"""

import math
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import did_export_controls as de  # noqa: E402
import did_chip_controls as dc  # noqa: E402

MONTHS = [f"{y}-{m:02d}" for y in (2022, 2023, 2024, 2025) for m in range(1, 13)]
ORIGIN_METRIC = {  # HS 8542 series, USD-denominated where possible
    "US": "mirror_exports_us_hs8542_usd",
    "Korea": "mirror_exports_kr_hs8542_usd",
    "Singapore": "mirror_exports_sg_hs8542_usd",
    "Japan": "mirror_exports_jp_hs8542_jpy",
}
DIP, RECOVER = -0.6, +0.6  # cut at Oct-2022, recover at Oct-2023


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.executescript((ROOT / "db" / "schema.sql").read_text())
    conn.execute("INSERT INTO sources (name,url,type,language) VALUES ('t','u','trade_stats','en')")
    conn.execute(
        "INSERT INTO documents (source_id,url,retrieved_at,raw_path,sha256,title,language)"
        " VALUES (1,'u','t','p','s1','t','en')"
    )
    for cur in ("USD", "JPY", "EUR", "CNY"):
        for m in MONTHS:
            conn.execute(
                "INSERT INTO fx_rates (currency,period,usd_per_unit,document_id)"
                " VALUES (?,?,1.0,1)", (cur, m))
    conn.execute(
        "INSERT INTO entities (name_en,entity_type,supply_chain_layer)"
        " VALUES ('China','country',NULL)")
    cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    for origin, metric in ORIGIN_METRIC.items():
        cur = "JPY" if origin == "Japan" else "USD"
        for m in MONTHS:
            val = 100.0
            if origin == "US":
                if m >= de.WAVE_OCT2022:
                    val *= math.exp(DIP)
                if m >= de.WAVE_OCT2023:
                    val *= math.exp(RECOVER)
            conn.execute(
                "INSERT INTO metrics (entity_id,metric_name,period,value,unit,currency,document_id)"
                " VALUES (?,?,?,?, 'USD_mn', ?, 1)", (cid, metric, m, val, cur))
    conn.commit()
    return conn


def test_chip_did_detects_bite_then_recovery(db):
    did, placebo, p_value, es, supp, shape = dc.analyze(db)
    # bite: trough is clearly negative
    assert shape["trough_pct"] < -0.2
    # recovery: latest is above the trough (net effect washes toward zero)
    assert shape["latest_pct"] > shape["trough_pct"]
    # the planted net effect is ~0 (DIP + RECOVER cancel), not a durable drop
    assert did["cumulative_after_Dec2024"]["coef"] == pytest.approx(DIP + RECOVER, abs=1e-6)


def test_chip_suppression_positive_at_trough(db):
    panel = de.load_panel(db, series=dc.CHIP_SERIES)
    supp = dc.chip_suppression(panel)
    # during the dip (US below allied path) suppression is positive
    assert supp.loc["2023Q2", "us_suppressed_bn"] > 0
    # after recovery it returns toward zero
    assert supp.loc["2025Q4", "us_suppressed_bn"] == pytest.approx(0.0, abs=1e-9)
