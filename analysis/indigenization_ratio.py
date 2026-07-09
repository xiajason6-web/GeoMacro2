"""The flagship metric: domestic share of China's wafer-fab-equipment market.

    ratio(q) = domestic equipment revenue(q)
               ---------------------------------------------
               domestic equipment revenue(q) + imports(q)

All arithmetic here is deterministic pandas over the metrics table — no LLM
touches numbers (layer rule 4). Every input series carries its coverage
flags into the output, and the script refuses to present a partial-coverage
ratio as final: the CSV has an explicit `coverage` column and the console
output repeats the caveats.

Current known coverage gaps (also printed on every run):
  - imports: EU27 only until the US Census key and Japan e-Stat key are added
    -> denominator understated -> ratio OVERSTATED. Not publishable yet.
  - domestic revenue: listed companies' total revenue (includes non-semicap
    segments; excludes unlisted SMEE) — see analysis/methodology.md.

Output: data/exports/indigenization_ratio.csv + a printed table.
How you'd know it broke: the row count / quarters printed shrink, or the
tests in tests/test_indigenization.py fail.
"""

import sqlite3
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"
OUT_PATH = REPO_ROOT / "data" / "exports" / "indigenization_ratio.csv"

# Denominator import series: EU27 aggregate ONLY. The NL and DE series are
# subsets of EU27 — adding them would double-count. US and Japan series get
# appended here once their collectors exist.
IMPORT_METRICS_EUR = ["mirror_exports_eu27_hs8486_eur"]
IMPORT_COVERAGE = "EU27 only (US, Japan pending)"

FX_METRIC = "fx_cny_per_eur_monthly_avg"
REVENUE_METRIC = "quarterly_revenue_cny"


def month_to_quarter(period):
    """'2026-03' -> '2026Q1'"""
    year, month = period.split("-")
    return f"{year}Q{(int(month) - 1) // 3 + 1}"


def load_metrics(conn):
    return pd.read_sql_query(
        """
        SELECT e.name_en AS entity, e.supply_chain_layer AS layer,
               m.metric_name, m.period, m.value
        FROM metrics m
        JOIN entities e ON e.id = m.entity_id
        WHERE m.document_id = (
            SELECT MAX(m2.document_id) FROM metrics m2
            WHERE m2.entity_id = m.entity_id
              AND m2.metric_name = m.metric_name
              AND m2.period = m.period)
        """,
        conn,
    )


def quarterly_imports_cny(df):
    """Sum monthly EUR imports per quarter (complete quarters only) and
    convert with the quarterly-average FX rate. Returns DataFrame indexed by
    quarter with columns imports_eur, fx_cny_per_eur, imports_cny."""
    imports = df[df.metric_name.isin(IMPORT_METRICS_EUR)].copy()
    fx = df[df.metric_name == FX_METRIC].copy()
    if imports.empty or fx.empty:
        return pd.DataFrame(
            columns=["imports_eur", "fx_cny_per_eur", "imports_cny"]
        )

    imports["quarter"] = imports.period.map(month_to_quarter)
    # A quarter is complete only when all 3 months are present for every
    # import series — otherwise a partially reported quarter would look like
    # a collapse in imports.
    month_counts = imports.groupby(["quarter", "metric_name"]).period.nunique()
    complete = month_counts.groupby("quarter").min() == 3
    complete_quarters = complete[complete].index

    eur = (
        imports[imports.quarter.isin(complete_quarters)]
        .groupby("quarter")
        .value.sum()
        .rename("imports_eur")
    )

    fx["quarter"] = fx.period.map(month_to_quarter)
    rate = fx.groupby("quarter").value.mean().rename("fx_cny_per_eur")

    out = pd.concat([eur, rate], axis=1).dropna()
    out["imports_cny"] = out.imports_eur * out.fx_cny_per_eur
    return out


def quarterly_domestic_cny(df):
    """Sum quarterly revenue across equipment makers (foundries excluded).
    Returns DataFrame indexed by quarter with domestic_cny and n_companies."""
    rev = df[(df.metric_name == REVENUE_METRIC) & (df.layer == "equipment")]
    if rev.empty:
        return pd.DataFrame(columns=["domestic_cny", "n_companies"])
    grouped = rev.groupby("period").agg(
        domestic_cny=("value", "sum"), n_companies=("entity", "nunique")
    )
    grouped.index.name = "quarter"
    return grouped


def compute_ratio(conn):
    df = load_metrics(conn)
    imports = quarterly_imports_cny(df)
    domestic = quarterly_domestic_cny(df)
    out = imports.join(domestic, how="outer").sort_index()
    out["ratio"] = out.domestic_cny / (out.domestic_cny + out.imports_cny)
    out["coverage"] = f"imports: {IMPORT_COVERAGE}; revenue: listed cos only"
    return out


def main():
    conn = sqlite3.connect(DB_PATH)
    out = compute_ratio(conn)
    conn.close()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_PATH, index_label="quarter")

    print("=" * 72)
    print("China WFE indigenization ratio — WORKING SERIES, NOT PUBLISHABLE YET")
    print(f"  import coverage:  {IMPORT_COVERAGE} -> ratio currently OVERSTATED")
    print("  revenue coverage: listed equipment cos, total revenue (see methodology)")
    print("=" * 72)
    if out.empty:
        print("no data yet — run the collectors and the filing extraction first")
        return 1
    with pd.option_context("display.float_format", lambda v: f"{v:,.3f}"):
        print(out.to_string())
    ready = out.dropna(subset=["ratio"])
    print(f"\nquarters with both sides of the ratio: {len(ready)}")
    print(f"wrote {OUT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
