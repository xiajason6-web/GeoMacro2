"""Tests for the trade-facing layer: exposure ladder gate + surprise math."""

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import exposure_ladder as el  # noqa: E402
import consensus_gap as sm  # noqa: E402


# ---- exposure ladder -----------------------------------------------------------

@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript((ROOT / "db" / "schema.sql").read_text())
    yield conn
    conn.close()


def test_ladder_sync_idempotent_and_gated(db):
    el.sync(db)
    n1, = db.execute("SELECT COUNT(*) FROM instrument_exposure").fetchone()
    assert n1 == len(el.LADDER)
    # all start unreviewed -> excluded from published rows
    assert el.rows_for_output(db, include_unreviewed=False) == []
    assert len(el.rows_for_output(db, include_unreviewed=True)) == n1
    # re-sync adds nothing
    el.sync(db)
    n2, = db.execute("SELECT COUNT(*) FROM instrument_exposure").fetchone()
    assert n2 == n1


def test_ladder_approve_publishes(db):
    el.sync(db)
    el.approve(db, "all")
    published = el.rows_for_output(db, include_unreviewed=False)
    assert len(published) == len(el.LADDER)
    # ordering: benefit first, then harm, mixed, neutral
    signs = [r[3] for r in published]
    assert signs.index("benefit") < signs.index("harm") < signs.index("neutral")


def test_ladder_sign_vocabulary_enforced(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO instrument_exposure (instrument, instrument_type,"
            " exposure_sign, confidence, mechanism)"
            " VALUES ('X', 'equity', 'long', 'high', 'm')"  # 'long' is not allowed
        )


def test_ladder_has_discernment():
    # A credible ladder is not all one-directional — it must include mixed
    # and neutral calls, not just clean winners/losers.
    signs = {row["exposure_sign"] for row in el.LADDER}
    assert {"benefit", "harm", "mixed", "neutral"} <= signs


# ---- surprise model ------------------------------------------------------------

def test_catalyst_prefers_vendor_factor():
    drivers = (
        "US: fully observed ($0.22bn)\n"
        "Korea: 0/3 months observed; 3 filled at carry-forward $0.33bn/mo\n"
        "vendor factor 0.76 (panel mean 26% vs 35%) -> applied: -1.34bn"
    )
    assert sm.catalyst_from_drivers(drivers).startswith("vendor factor 0.76")


def test_catalyst_falls_back_to_carry_forward():
    drivers = (
        "EU27: fully observed ($1.38bn)\n"
        "Singapore: 0/3 months observed; 3 filled at carry-forward $0.88bn/mo"
    )
    assert "carry-forward" in sm.catalyst_from_drivers(drivers)


def _seed_full_quarter(conn, quarter="2025Q4", ratio_num=200, ratio_imp=800):
    """Minimal full-coverage quarter so persistence_baseline resolves."""
    conn.execute("INSERT INTO sources (name,url,type,language) VALUES ('t','u','trade_stats','en')")
    conn.execute("INSERT INTO documents (source_id,url,retrieved_at,raw_path,sha256,title,language) VALUES (1,'u','t','p','s1','t','en')")
    conn.execute("INSERT INTO entities (name_en, entity_type) VALUES ('China','country')")
    conn.execute("INSERT INTO entities (name_en, entity_type, supply_chain_layer) VALUES ('Co','company','equipment')")
    year, q = quarter[:4], int(quarter[-1])
    months = [f"{year}-{(q-1)*3+i:02d}" for i in (1, 2, 3)]
    for mo in months:
        for cur in ("USD", "CNY"):
            conn.execute("INSERT INTO fx_rates (currency,period,usd_per_unit,document_id) VALUES (?,?,?,1)",
                         (cur, mo, 1.0 if cur == "USD" else 1.0))
        for metric in ("mirror_exports_eu27_hs8486_eur", "mirror_exports_jp_hs8486_jpy",
                       "mirror_exports_us_hs8486_usd", "mirror_exports_kr_hs8486_usd",
                       "mirror_exports_sg_hs8486_usd"):
            conn.execute("INSERT INTO metrics (entity_id,metric_name,period,value,unit,document_id) VALUES (1,?,?,?,'x',1)",
                         (metric, mo, ratio_imp / 15))  # 5 series x 3 months
        conn.execute("INSERT INTO fx_rates (currency,period,usd_per_unit,document_id) VALUES ('EUR',?,1.0,1) ON CONFLICT DO NOTHING", (mo,))
        conn.execute("INSERT OR IGNORE INTO fx_rates (currency,period,usd_per_unit,document_id) VALUES ('JPY',?,1.0,1)", (mo,))
    conn.execute("INSERT INTO metrics (entity_id,metric_name,period,value,unit,document_id) VALUES (2,'domestic_semicap_revenue_cny',?,?,'x',1)",
                 (quarter, ratio_num))


def test_surprise_is_nowcast_minus_persistence(db):
    _seed_full_quarter(db, "2025Q4", ratio_num=200, ratio_imp=800)  # ratio 200/1000 = 0.20
    db.execute(
        "INSERT INTO nowcasts (made_at,target_quarter,ratio_nowcast,ratio_low,"
        "ratio_high,numerator_usd,imports_usd,drivers,methodology_version)"
        " VALUES ('2026-01-01','2026Q1',0.30,0.27,0.33,1,1,"
        "'vendor factor 0.9 -> applied: -0.1bn','nc-1.0.0')"
    )
    data = sm.build(db)
    assert data["baseline_quarter"] == "2025Q4"
    assert data["baseline"] == pytest.approx(0.20)
    row = data["rows"][0]
    assert row["surprise_pp"] == pytest.approx(10.0)   # 0.30 - 0.20
    assert row["direction"] == "above"
    assert row["catalyst"].startswith("vendor factor")
