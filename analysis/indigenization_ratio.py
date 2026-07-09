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

# Denominator import series with their reporting currency. The NL and DE
# series are subsets of EU27 — adding them would double-count. The US series
# joins once its collector exists.
IMPORT_SERIES = {
    "mirror_exports_eu27_hs8486_eur": "EUR",
    "mirror_exports_jp_hs8486_jpy": "JPY",
}
IMPORT_COVERAGE = "EU27 + Japan (US pending)"

# Monthly CNY per unit of each currency, derived from ECB EUR crosses:
# cny_per_X = cny_per_eur / X_per_eur.
FX_CNY_EUR = "fx_cny_per_eur_monthly_avg"
FX_CROSSES = {"USD": "fx_usd_per_eur_monthly_avg", "JPY": "fx_jpy_per_eur_monthly_avg"}
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


def monthly_cny_rates(df):
    """Monthly CNY-per-unit rate for each import currency.

    Returns a DataFrame indexed by month period with one column per currency
    in {'EUR', 'JPY', 'USD'} (crosses only where their series exist)."""
    cny_eur = (
        df[df.metric_name == FX_CNY_EUR].set_index("period").value.rename("EUR")
    )
    rates = {"EUR": cny_eur}
    for currency, metric in FX_CROSSES.items():
        cross = df[df.metric_name == metric].set_index("period").value
        if not cross.empty:
            rates[currency] = (cny_eur / cross).rename(currency)
    return pd.DataFrame(rates)


def quarterly_imports_cny(df):
    """Convert each import series to CNY at monthly rates, then sum per
    quarter. A quarter counts only when every import series has all 3 months
    — otherwise a partially reported quarter would look like a collapse.

    Returns DataFrame indexed by quarter: imports_cny, n_import_series."""
    imports = df[df.metric_name.isin(IMPORT_SERIES)].copy()
    if imports.empty:
        return pd.DataFrame(columns=["imports_cny", "n_import_series"])
    rates = monthly_cny_rates(df)

    imports["currency"] = imports.metric_name.map(IMPORT_SERIES)
    imports["rate"] = imports.apply(
        lambda r: rates[r.currency].get(r.period) if r.currency in rates else None,
        axis=1,
    )
    imports = imports.dropna(subset=["rate"])
    imports["value_cny"] = imports.value * imports.rate
    imports["quarter"] = imports.period.map(month_to_quarter)

    month_counts = imports.groupby(["quarter", "metric_name"]).period.nunique()
    series_counts = imports.groupby("quarter").metric_name.nunique()
    complete = (month_counts.groupby("quarter").min() == 3) & (
        series_counts == len(IMPORT_SERIES)
    )
    complete_quarters = complete[complete].index

    grouped = (
        imports[imports.quarter.isin(complete_quarters)]
        .groupby("quarter")
        .agg(imports_cny=("value_cny", "sum"), n_import_series=("metric_name", "nunique"))
    )
    return grouped


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
