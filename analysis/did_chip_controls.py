"""Causal effect of the US CHIP controls on US chip exports to China — the
same difference-in-differences as did_export_controls.py, run one layer up on
HS 8542 (integrated circuits) instead of HS 8486 (equipment). This is the
"Jensen layer": the A100/H100 cutoff (Oct 2022), the A800/H800 ban (Oct 2023),
and the later H20 restrictions (2025) all live here.

WHY THIS WORKS WITHOUT A DOMESTIC NUMERATOR. The DiD identifies off the
DENOMINATOR — US-origin chip exports vs allied-origin chip exports — so it needs
no domestic chip-output series (which is geo-blocked anyway; see
collectors/nbs_ic_output.py). It reuses the audited OLS / design / event-study /
placebo machinery from did_export_controls.py unchanged; only the input series
changes to HS 8542.

WHAT IT CAN AND CANNOT SAY (state it, don't bury it):
  - HS 8542 is ALL integrated circuits, not just controlled AI accelerators.
    Most US IC exports to China (analog, microcontrollers, older logic) are NOT
    controlled, so they DILUTE the treatment. A US-specific drop that survives
    this dilution is therefore a strong signal; a small/absent one is ambiguous
    (could be dilution, not absence of effect). The estimate is a LOWER BOUND on
    the effect on the controlled GPU subset.
  - Same five-origin / cycle-differenced design and the same 5-origin inference
    caveat (placebo p floor 0.20) as the equipment DiD.

Outputs (parallel to the equipment DiD, 'chip' infix):
  data/exports/did_chip_controls.md
  data/exports/did_chip_summary.csv, did_chip_event_study.csv,
  did_chip_coefficients.csv   (for the dashboard)
"""

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import indigenization_ratio as ir  # noqa: E402
import did_export_controls as de  # noqa: E402  (reuse the audited DiD machinery)

DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"
OUT_DIR = REPO_ROOT / "data" / "exports"

# HS 8542 (integrated circuits) mirror-export series, same five origins.
CHIP_SERIES = {
    "mirror_exports_eu27_hs8542_eur": ("EU27", "EUR"),
    "mirror_exports_jp_hs8542_jpy": ("Japan", "JPY"),
    "mirror_exports_us_hs8542_usd": ("US", "USD"),
    "mirror_exports_kr_hs8542_usd": ("Korea", "USD"),
    "mirror_exports_sg_hs8542_usd": ("Singapore", "USD"),
}


def chip_suppression(panel, basket=None):
    """US chip imports the controls removed: rebuild US on the allied basket
    path from the anchor quarter and difference against actual, in USD/qtr.
    (The chip layer has no clean domestic ratio, so we report the $ suppressed,
    not a counterfactual ratio.)"""
    basket = de.COUNTERFACTUAL_BASKET if basket is None else basket
    p = panel.copy()
    p["quarter"] = p.month.map(ir.month_to_quarter)
    counts = p.groupby(["origin", "quarter"]).month.nunique()
    complete = counts[counts == 3].reset_index()
    complete = complete[complete.month == 3][["origin", "quarter"]]
    pq = (p.merge(complete, on=["origin", "quarter"])
            .groupby(["origin", "quarter"]).value_usd.sum().reset_index())
    wide = pq.pivot(index="quarter", columns="origin", values="value_usd").sort_index()
    us_anchor = wide.loc[de.ANCHOR_QUARTER, de.TREATED]
    basket_anchor = wide.loc[de.ANCHOR_QUARTER, basket].sum()
    rows = []
    for q in wide.index:
        if q < de.ANCHOR_QUARTER or wide.loc[q, basket].isna().any():
            continue
        if pd.isna(wide.loc[q, de.TREATED]):
            continue
        us_cf = us_anchor * (wide.loc[q, basket].sum() / basket_anchor)
        us_actual = wide.loc[q, de.TREATED]
        rows.append({
            "quarter": q,
            "us_actual_bn": us_actual / 1e9,
            "us_counterfactual_bn": us_cf / 1e9,
            "us_suppressed_bn": (us_cf - us_actual) / 1e9,
        })
    return pd.DataFrame(rows).set_index("quarter")


def analyze(conn):
    panel = de.load_panel(conn, series=CHIP_SERIES)
    did, _, _ = de.run_did(panel)
    placebo, p_value = de.randomization_inference(
        panel, did["cumulative_after_Dec2024"]["coef"]
    )
    es = de.event_study(panel)
    supp = chip_suppression(panel)
    # The chip layer's story is the SHAPE, not a single coefficient: a trough
    # (controls bite) then a recovery (firms ship compliant parts). Locate it.
    post = es[~es.is_pre]
    trough = post.loc[post.coef.idxmin()]
    latest = es.iloc[-1]
    shape = {
        "trough_quarter": trough.quarter,
        "trough_pct": np.exp(trough.coef) - 1,
        "latest_quarter": latest.quarter,
        "latest_pct": np.exp(latest.coef) - 1,
        "max_pre_trend": es[es.is_pre].coef.abs().max(),
        "us_most_suppressed": min(placebo, key=placebo.get) == de.TREATED,
    }
    return did, placebo, p_value, es, supp, shape


def write_csvs(did, placebo, p_value, es, supp, shape):
    es.to_csv(OUT_DIR / "did_chip_event_study.csv", index=False)
    terms = ["US x post_Oct2022", "US x post_Oct2023", "US x post_Dec2024"]
    pd.DataFrame([
        {"term": t, "coef": did[t]["coef"], "pct_effect": did[t]["pct_effect"],
         "hc1_se": did[t]["hc1_se"], "cluster_se": did[t]["cluster_se"]}
        for t in terms
    ]).to_csv(OUT_DIR / "did_chip_coefficients.csv", index=False)
    latest = supp.iloc[-1]
    pd.DataFrame([{
        "cumulative_pct_effect": did["cumulative_after_Dec2024"]["pct_effect"],
        "cumulative_log_pts": did["cumulative_after_Dec2024"]["coef"],
        "placebo_p_value": p_value,
        "n_origins": len(placebo),
        "trough_quarter": shape["trough_quarter"],
        "trough_pct": shape["trough_pct"],
        "latest_es_quarter": shape["latest_quarter"],
        "latest_es_pct": shape["latest_pct"],
        "max_pre_trend": shape["max_pre_trend"],
        "us_most_suppressed": shape["us_most_suppressed"],
        "latest_quarter": latest.name,
        "latest_us_actual_bn": latest.us_actual_bn,
        "latest_us_counterfactual_bn": latest.us_counterfactual_bn,
        "latest_us_suppressed_bn": latest.us_suppressed_bn,
        "anchor_quarter": de.ANCHOR_QUARTER,
    }]).to_csv(OUT_DIR / "did_chip_summary.csv", index=False)
    print("wrote data/exports/did_chip_{event_study,coefficients,summary}.csv")


def render(did, placebo, p_value, es, supp, shape):
    b0, b1, b2 = (did["US x post_Oct2022"], did["US x post_Oct2023"],
                  did["US x post_Dec2024"])
    cum = did["cumulative_after_Dec2024"]
    tq, tp = shape["trough_quarter"], shape["trough_pct"]
    lp = shape["latest_pct"]
    lines = [
        "# US chip controls: they BIT, then LEAKED — a bite-and-recovery",
        "",
        "The equipment DiD (did_export_controls.py) run one layer up, on HS 8542",
        "(integrated circuits) — the layer the A100/H100, A800/H800 and H20",
        "controls actually target. Identification is off the denominator (US vs",
        "allied chip exports), so no domestic chip-output series is needed. Same",
        "audited machinery, same five origins, same cycle-differencing month FE.",
        "",
        "## Headline: the opposite of the equipment layer",
        "",
        "The chip layer's story is a SHAPE, not a single coefficient. US chip",
        f"exports to China fell to **{tp:+.0%}** below the allied path at the",
        f"trough ({tq}) — the A100/H100 and A800/H800 bans genuinely bit — then",
        f"**recovered to {lp:+.0%}** by the latest quarter. Net cumulative effect",
        f" **{cum['pct_effect']:+.0%}**, placebo p = **{p_value:.2f}** (US "
        + ("IS" if shape["us_most_suppressed"] else "is NOT")
        + " the most-suppressed origin), pre-trend "
        f"{shape['max_pre_trend']:.2f} log pts.",
        "",
        "**Read the failed identification as the finding.** Unlike equipment",
        "(clean pre-trends, durable −78%), the chip DiD does NOT hold parallel",
        "trends and washes out to ~zero: the US-origin series fell then recovered.",
        "IMPORTANT attribution caveat — the recovery is mostly UNRESTRICTED",
        "lower-end US chips plus the semiconductor cycle, NOT NVIDIA's compliant",
        "GPUs. Those China parts (A100/H100→A800/H800→H20) are fabbed by TSMC in",
        "TAIWAN, so they are not US-origin exports and barely appear in this",
        "US→China series. The broader lesson still holds as industry logic — a",
        "chip is a design that can be re-spun under a performance threshold, a",
        "lithography tool cannot — so controls bite hardest where the product",
        "can't iterate.",
        "",
        "## Event-study coefficients (the V-shape)",
        "",
        "| Wave term | Effect (log pts) | Level | HC1 se |",
        "|---|---|---|---|",
        f"| US × post-Oct-2022 (A100/H100) | {b0['coef']:+.3f} | {b0['pct_effect']:+.1%} | {b0['hc1_se']:.3f} |",
        f"| US × post-Oct-2023 (A800/H800, incr.) | {b1['coef']:+.3f} | {b1['pct_effect']:+.1%} | {b1['hc1_se']:.3f} |",
        f"| US × post-Dec-2024 (incr.) | {b2['coef']:+.3f} | {b2['pct_effect']:+.1%} | {b2['hc1_se']:.3f} |",
        "",
        "The initial ban is a sharp negative (the bite); the later terms are",
        "positive (the recovery) — which is why the cumulative nets out and a",
        "single number would mislead. The recovery is unrestricted chips + cycle,",
        "not the controlled GPU flow (which is Taiwan-origin, off-panel).",
        "",
        "## US chip exports vs the allied path ($bn/qtr — the V)",
        "",
        "| Quarter | US actual $bn | US counterfactual $bn | Gap $bn |",
        "|---|---|---|---|",
    ]
    for q, r in supp.iterrows():
        lines.append(
            f"| {q} | {r.us_actual_bn:.2f} | {r.us_counterfactual_bn:.2f} |"
            f" {r.us_suppressed_bn:+.2f} |"
        )
    lines += [
        "",
        "## What this settles in the export-controls debate",
        "",
        "- **Control durability is LAYER-SPECIFIC (industry logic).** A chip is a",
        "  design that can be re-spun under a threshold (H100→A800/H800→H20); a",
        "  lithography tool has no compliant version. So controls are durable at",
        "  the tool layer (−78%, clean) and porous at the chip layer — effective",
        "  where the product can't iterate. NOTE: this is an industry fact, not",
        "  something THIS US-origin trade series cleanly identifies (see caveat).",
        "- **Both camps get something.** The 'controls are porous' view (Huang)",
        "  holds at the chip layer; the 'controls work' view holds at the tool",
        "  layer (the durable −78%).",
        "- **Neither made China self-sufficient.** chip_self_sufficiency.py shows",
        "  chip imports rose on demand throughout.",
        "",
        "## Limits (read the chip layer as descriptive)",
        "",
        "- **Origin blind spot — decisive here.** TAIWAN, the largest chip",
        "  supplier to China and where NVIDIA's China GPUs are fabbed, is an",
        "  unobserved origin (no machine-readable source). The controlled-GPU",
        "  flow is therefore largely OUTSIDE this panel — the recovery shown here",
        "  is unrestricted US chips + cycle, not the compliant-GPU 'leak'.",
        "- **HS 8542 is ALL ICs**, not just controlled GPUs — uncontrolled chips",
        "  dilute the treatment and drive much of the recovery.",
        "- **Parallel trends fails**, so this is DESCRIPTIVE, not a clean causal",
        "  estimate — the equipment DiD is the identified one.",
        "- **Five origins** → placebo p floor 0.20.",
        "",
        "_Research output — finding → mechanism → exposed entities → confidence →",
        "sources. Not investment advice._",
    ]
    return "\n".join(lines)


def main():
    conn = sqlite3.connect(DB_PATH)
    did, placebo, p_value, es, supp, shape = analyze(conn)
    conn.close()
    if supp.empty:
        print("no chip panel yet — run collectors first")
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_csvs(did, placebo, p_value, es, supp, shape)
    md = render(did, placebo, p_value, es, supp, shape)
    (OUT_DIR / "did_chip_controls.md").write_text(md)
    print("wrote data/exports/did_chip_controls.md")
    print("=" * 78)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
