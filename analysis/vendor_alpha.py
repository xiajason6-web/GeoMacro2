"""The edge layer — P vs Q: our structural view vs the market's cyclical read.

This is what turns a fundamental tracker into equity research: not "what is
China's tool-share" (the fundamental, P) but "where does our identified view
differ from what the price implies" (the divergence, the alpha).

THE HONEST Q PROBLEM. True consensus / option-implied expectations for the
foreign toolmakers' China business are paywalled — we cannot observe Q directly
on free data. So Q enters as a STATED ASSUMPTION, not a measured number: the
market tends to treat China-revenue swings as CYCLICAL (recoverable when capex
recovers). Our DiD identifies a large, DURABLE substitution effect — a chunk of
the China-share loss is STRUCTURAL, not cyclical. The edge is that gap.

  P (our view)   : tool substitution is structural (DiD −78%, clean pre-trends;
                   domestic revenue compounding) → foreign China share keeps
                   eroding beyond the cycle.
  Q (priced)     : ASSUMED cyclical — China revenue mean-reverts with capex.
  alpha          : the structural (non-cyclical) portion of the erosion, most
                   pronounced where the category localizes first.

Per name we report realized China-revenue erosion (peak→latest), classify the
DRIVER (structural substitution vs export-control denial vs cyclical/mixed),
and state the divergence + confidence. Because substitution is a slow,
cycle-dominated signal at short horizons (the vendor-lead null), the expression
is CYCLE-NEUTRAL — long domestic winners / short foreign losers, beta hedged —
and the confidence is deliberately modest at this n.

Deterministic. Outputs: data/exports/vendor_alpha.md + vendor_alpha.csv.
Research, not investment advice — direction and mechanism only, no sizing.
"""

import sqlite3
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import indigenization_ratio as ir  # noqa: E402

DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"
OUT_MD = REPO_ROOT / "data" / "exports" / "vendor_alpha.md"
OUT_CSV = REPO_ROOT / "data" / "exports" / "vendor_alpha.csv"

# Driver classification, grounded in the exposure-ladder mechanisms: which part
# of each vendor's China-share loss is STRUCTURAL substitution (the alpha) vs
# export-control denial vs cyclical/normalization (not a clean substitution play).
DRIVER = {
    "AMAT": ("structural substitution",
             "Etch/deposition/CMP localize first (Naura/AMEC/Piotech/Hwatsing) — the cleanest structural erosion."),
    "LRCX": ("structural substitution",
             "Etch/deposition plus NAND-heavy China exposure; loses the most-localized categories first."),
    "KLAC": ("control-denial (not clean)",
             "Metrology/inspection localizes slowest; KLA's China fall is more export-control denial than domestic substitution — not a pure indigenization play."),
    "ASML": ("normalization (mixed)",
             "EUV already embargoed; DUV China revenue normalizing from the 2023-24 stockpiling peak toward ~20% — cyclical/normalization, not fresh substitution."),
}


def load_vendor_china(conn):
    df = pd.read_sql_query(
        "SELECT e.name_en, e.ticker, m.period, m.value FROM metrics m"
        " JOIN entities e ON e.id = m.entity_id"
        " WHERE m.metric_name = 'china_revenue_pct'", conn)
    if df.empty:
        return df
    df["quarter"] = df.period.map(
        lambda p: p if "Q" in p else ir.month_to_quarter(p))
    return df.sort_values(["ticker", "quarter"])


def load_ladder(conn):
    return pd.read_sql_query(
        "SELECT instrument, exposure_sign, confidence FROM instrument_exposure"
        " WHERE human_reviewed = 1", conn).set_index("instrument")


def build(conn):
    v = load_vendor_china(conn)
    if v.empty:
        return None
    ladder = load_ladder(conn)
    rows = []
    for tkr, g in v.groupby("ticker"):
        g = g.sort_values("quarter")
        latest = g.iloc[-1]
        peak = g.value.max()
        driver, note = DRIVER.get(tkr, ("unclassified", ""))
        led = ladder.loc[tkr] if tkr in ladder.index else None
        rows.append({
            "ticker": tkr,
            "name": latest.name_en,
            "latest_china_pct": float(latest.value),
            "latest_quarter": latest.quarter,
            "peak_china_pct": float(peak),
            "erosion_pp": float(peak - latest.value),
            "n_obs": int(len(g)),
            "driver": driver,
            "driver_note": note,
            "exposure_sign": (led.exposure_sign if led is not None else ""),
            "confidence": (led.confidence if led is not None else "low"),
        })
    df = pd.DataFrame(rows)
    order = {"structural substitution": 0, "control-denial (not clean)": 1,
             "normalization (mixed)": 2, "unclassified": 3}
    return df.sort_values("driver", key=lambda s: s.map(order)).reset_index(drop=True)


def render(df):
    struct = df[df.driver == "structural substitution"]
    lines = [
        "# The edge — P vs Q: structural vs cyclical erosion",
        "",
        "_Where our identified view differs from what the price implies. Q"
        " (consensus / priced) is not observable on free data, so it enters as a"
        " STATED ASSUMPTION: the market prices China-revenue swings as CYCLICAL."
        " Our DiD says a chunk of the tool-share loss is STRUCTURAL. The edge is"
        " that gap. Direction and mechanism only — no sizing._",
        "",
        "| Vendor | Latest China % | Peak | Erosion (pp) | Driver | Exposure | Conf | n |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for _, r in df.iterrows():
        lines.append(
            f"| {r['name']} ({r.ticker}) | {r.latest_china_pct:.0f}%"
            f" ({r.latest_quarter}) | {r.peak_china_pct:.0f}% | {r.erosion_pp:+.0f} |"
            f" {r.driver} | {r.exposure_sign} | {r.confidence} | {r.n_obs} |"
        )
    lines += [
        "",
        "## The divergence, per driver",
        "",
        "- **Structural substitution (the alpha).** "
        + ", ".join(f"{r['name']} ({r.ticker})" for _, r in struct.iterrows())
        + " lose the categories that localize first (etch/deposition/CMP). If"
        " the market reads their China erosion as cyclical (recoverable with"
        " capex), it is under-pricing a *permanent* share loss the DiD"
        " identifies. This is where the theme has edge.",
        "- **Control-denial (not a clean play).** KLA's China fall is steeper but"
        " is more export-control denial than domestic substitution — metrology"
        " localizes slowly. Do not trade it as an indigenization proxy.",
        "- **Normalization (mixed).** ASML's China revenue is normalizing from a"
        " stockpiling peak (EUV already embargoed) — cyclical, not fresh"
        " substitution.",
        "",
        "## Expression and honesty",
        "",
        "- **Cycle-neutral by construction.** The vendor-lead null showed the"
        " capex cycle dominates substitution at short horizons, so the edge only"
        " survives if the beta is hedged: long domestic winners / short foreign"
        " losers, not outright. The alpha is the *structural* residual.",
        "- **Confidence is modest by design.** China-% prints are noisy and n is"
        " small (single-digit quarters); the peak→latest erosion is directional,"
        " not a precise decomposition. This is the apparatus + framing; it"
        " sharpens as quarters accumulate — and the calls ledger scores it.",
        "",
        "_Research, not investment advice. No ratings, targets, or sizing._",
    ]
    return "\n".join(lines)


def main():
    conn = sqlite3.connect(DB_PATH)
    df = build(conn)
    conn.close()
    if df is None or df.empty:
        print("no vendor china-revenue data yet")
        return 1
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    md = render(df)
    OUT_MD.write_text(md)
    print(md)
    print(f"\nwrote {OUT_MD.relative_to(REPO_ROOT)} and {OUT_CSV.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
