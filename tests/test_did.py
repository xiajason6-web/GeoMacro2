"""DiD causal-module tests (analysis/did_export_controls.py).

Two layers:

1. Pure-numpy OLS recovery on synthetic design — the estimator returns the
   planted coefficients (auditing the normal-equations code by hand).

2. Full pipeline on a synthetic in-memory DB with a KNOWN planted treatment
   effect. All fx set to 1 so USD == native value. Four origins share an
   identical flat import path of 100/month; the US path is multiplied by
   exp(-0.3) from Oct-2022, additionally exp(-0.2) from Oct-2023, and
   additionally exp(-0.5) from Dec-2024, so the DiD must recover the three
   incremental coefficients. The panel straddles Oct-2022 (starts 2022-01) so
   the first wave is identified rather than collinear with the US fixed
   effect. Because controls are flat, the allied counterfactual for US is
   constant, so US suppression is non-negative and the counterfactual ratio
   never exceeds the actual ratio.
"""

import math
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import did_export_controls as did  # noqa: E402

MONTHS = [f"{y}-{m:02d}" for y in (2022, 2023, 2024, 2025) for m in range(1, 13)]
# USD-denominated origins keep the arithmetic transparent (fx=1 anyway).
ORIGIN_METRIC = {
    "US": "mirror_exports_us_hs8486_usd",
    "Korea": "mirror_exports_kr_hs8486_usd",
    "Singapore": "mirror_exports_sg_hs8486_usd",
    "Japan": "mirror_exports_jp_hs8486_jpy",
}
B0, B1, B2 = -0.3, -0.2, -0.5


def test_ols_recovers_planted_coefficients():
    # y = 3 + 2*x1 - 1*x2, no noise -> exact recovery
    X = np.array([[1, 0, 0], [1, 1, 0], [1, 0, 1], [1, 1, 1], [1, 2, 1]], float)
    y = 3 + 2 * X[:, 1] - 1 * X[:, 2]
    beta, resid, _ = did.ols(X, y)
    assert np.allclose(beta, [3, 2, -1])
    assert np.allclose(resid, 0, atol=1e-9)


def test_robust_ses_finite_and_positive():
    rng = np.arange(20)
    X = np.column_stack([np.ones(20), rng % 3, rng % 5])
    y = 1.0 + 0.5 * (rng % 3) - 0.3 * (rng % 5)
    beta, resid, XtXi = did.ols(X, y)
    for se in (did.hc1_se(X, resid, XtXi),
               did.cluster_se(X, resid, XtXi, rng % 4)):
        assert np.all(np.isfinite(se)) and np.all(se >= 0)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.executescript((ROOT / "db" / "schema.sql").read_text())
    conn.execute("INSERT INTO sources (name,url,type,language) VALUES ('t','u','trade_stats','en')")
    conn.execute(
        "INSERT INTO documents (source_id,url,retrieved_at,raw_path,sha256,title,language)"
        " VALUES (1,'u','t','p','s1','t','en')"
    )
    # fx = 1 for every currency/month so value_usd == value
    for cur in ("USD", "JPY", "EUR", "CNY"):
        for m in MONTHS:
            conn.execute(
                "INSERT INTO fx_rates (currency,period,usd_per_unit,document_id)"
                " VALUES (?,?,1.0,1)", (cur, m))
        # quarterly CNY rate too (numerator converts quarter periods)
    # import origins
    for origin, metric in ORIGIN_METRIC.items():
        conn.execute(
            "INSERT INTO entities (name_en,entity_type,supply_chain_layer)"
            " VALUES (?, 'company','trade')", (f"origin_{origin}",))
        eid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for m in MONTHS:
            val = 100.0
            if origin == "US":
                if m >= did.WAVE_OCT2022:
                    val *= math.exp(B0)
                if m >= did.WAVE_OCT2023:
                    val *= math.exp(B1)
                if m >= did.WAVE_DEC2024:
                    val *= math.exp(B2)
            conn.execute(
                "INSERT INTO metrics (entity_id,metric_name,period,value,unit,currency,document_id)"
                " VALUES (?,?,?,?, 'USD_mn', ?, 1)",
                (eid, metric, m, val, "JPY" if origin == "Japan" else "USD"))
    # one equipment maker with flat domestic semicap revenue each quarter
    conn.execute(
        "INSERT INTO entities (name_en,entity_type,supply_chain_layer)"
        " VALUES ('Naura','company','equipment')")
    nid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    for y in (2023, 2024, 2025):
        for q in range(1, 5):
            conn.execute(
                "INSERT INTO metrics (entity_id,metric_name,period,value,unit,currency,document_id)"
                " VALUES (?, 'domestic_semicap_revenue_cny', ?, 50.0, 'CNY_mn','CNY',1)",
                (nid, f"{y}Q{q}"))
    conn.commit()
    return conn


def test_did_recovers_planted_treatment_effect(db):
    panel = did.load_panel(db)
    out, _, _ = did.run_did(panel)
    assert out["US x post_Oct2022"]["coef"] == pytest.approx(B0, abs=1e-6)
    assert out["US x post_Oct2023"]["coef"] == pytest.approx(B1, abs=1e-6)
    assert out["US x post_Dec2024"]["coef"] == pytest.approx(B2, abs=1e-6)
    assert out["cumulative_after_Dec2024"]["coef"] == pytest.approx(B0 + B1 + B2, abs=1e-6)


def test_placebo_ranks_us_most_suppressed(db):
    panel = did.load_panel(db)
    out, _, _ = did.run_did(panel)
    placebo, p = did.randomization_inference(
        panel, out["cumulative_after_Dec2024"]["coef"])
    assert min(placebo, key=placebo.get) == "US"
    assert p == pytest.approx(0.25)  # 1 of 4 origins is this extreme


def test_event_study_baseline_zero_and_parallel_pretrend(db):
    panel = did.load_panel(db)
    es = did.event_study(panel)
    base = es[es.quarter == did.ANCHOR_QUARTER].coef.iloc[0]
    assert base == pytest.approx(0.0, abs=1e-9)
    pre = es[es.is_pre]
    assert pre.coef.abs().max() == pytest.approx(0.0, abs=1e-9)  # flat pre-treatment


def test_counterfactual_ratio_never_above_actual(db):
    panel = did.load_panel(db)
    cf = did.counterfactual_ratio(db, panel)
    assert len(cf) > 0
    assert (cf.suppression_pp >= -1e-9).all()
    assert (cf.ratio_counterfactual <= cf.ratio_actual + 1e-9).all()
