"""The flagship metric: domestic share of China's wafer-fab-equipment market.

    ratio(q) = domestic semicap revenue(q, USD)
               ----------------------------------------------------
               domestic semicap revenue(q, USD) + imports(q, USD)

METHODOLOGY v2 (2026-07-12) — see analysis/methodology.md and the archived
v1 series in data/exports/history/ for the revision:
  - Common currency: every value converts to USD through the fx_rates table
    (ECB monthly averages) BEFORE any aggregation. Native-currency values
    are never summed; rows without a rate are excluded and counted.
  - Numerator: domestic_semicap_revenue_cny (quarterly revenue x disclosed
    semicap segment share x disclosed domestic share; ESTIMATED flags are
    carried through and counted per quarter).
  - Denominator: mirror exports to China from EU27, Japan, US, Korea and
    Singapore. A quarter includes every series with all 3 months published;
    series absent for that quarter are named in missing_origins rather than
    silently zero. Taiwan has no machine-readable source and is always
    listed as missing.
  - Every output row carries methodology_version.

All arithmetic is deterministic pandas — no LLM touches numbers.
Output: data/exports/indigenization_ratio.csv + a printed table.
"""

import shutil
import sqlite3
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"
OUT_PATH = REPO_ROOT / "data" / "exports" / "indigenization_ratio.csv"
HISTORY_DIR = REPO_ROOT / "data" / "exports" / "history"

METHODOLOGY_VERSION = "2.0.0"

# Import series (HS 8486) with origin label and reporting currency. The NL
# and DE series are subsets of EU27 — including them would double-count.
IMPORT_SERIES = {
    "mirror_exports_eu27_hs8486_eur": ("EU27", "EUR"),
    "mirror_exports_jp_hs8486_jpy": ("Japan", "JPY"),
    "mirror_exports_us_hs8486_usd": ("US", "USD"),
    "mirror_exports_kr_hs8486_usd": ("Korea", "USD"),
    "mirror_exports_sg_hs8486_usd": ("Singapore", "USD"),
}
# Origins we know exist but cannot source machine-readably (yet).
KNOWN_UNAVAILABLE = ["Taiwan"]

NUMERATOR_METRIC = "domestic_semicap_revenue_cny"


def month_to_quarter(period):
    """'2026-03' -> '2026Q1'"""
    year, month = period.split("-")
    return f"{year}Q{(int(month) - 1) // 3 + 1}"


def load_metrics(conn):
    return pd.read_sql_query(
        """
        SELECT e.name_en AS entity, e.supply_chain_layer AS layer,
               m.metric_name, m.period, m.value, m.notes
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


def load_fx(conn):
    """fx_rates table -> {currency: {period: usd_per_unit}}."""
    fx = {}
    for currency, period, rate in conn.execute(
        "SELECT currency, period, usd_per_unit FROM fx_rates"
    ):
        fx.setdefault(currency, {})[period] = rate
    return fx


def to_usd(df, fx, period_col="period"):
    """Convert df.value (currency per row) to df.value_usd via fx_rates.

    THE conversion chokepoint: aggregation code may only sum value_usd.
    Returns (converted_df, dropped_df) — rows whose (currency, period) has
    no rate are EXCLUDED from the converted frame, never passed through raw.
    """
    rates = df.apply(
        lambda r: fx.get(r.currency, {}).get(r[period_col]), axis=1
    )
    out = df.copy()
    out["value_usd"] = df.value * rates
    dropped = out[out.value_usd.isna()]
    return out.dropna(subset=["value_usd"]), dropped


def quarterly_imports_usd(df, fx):
    """Per-quarter USD imports with explicit origin coverage.

    A series enters a quarter only when all 3 months are present (a partial
    quarter would read as an import collapse). Series absent from a quarter
    are listed in missing_origins — the quarter is NOT dropped."""
    imports = df[df.metric_name.isin(IMPORT_SERIES)].copy()
    if imports.empty:
        return pd.DataFrame(
            columns=["imports_usd", "coverage_origins", "missing_origins"]
        )
    imports["origin"] = imports.metric_name.map(lambda m: IMPORT_SERIES[m][0])
    imports["currency"] = imports.metric_name.map(lambda m: IMPORT_SERIES[m][1])
    imports, dropped = to_usd(imports, fx)
    if len(dropped):
        print(f"WARNING: {len(dropped)} import rows lacked an FX rate — excluded")
    imports["quarter"] = imports.period.map(month_to_quarter)

    month_counts = imports.groupby(["quarter", "origin"]).period.nunique()
    complete = month_counts[month_counts == 3].reset_index()[["quarter", "origin"]]
    imports = imports.merge(complete, on=["quarter", "origin"])

    rows = []
    all_origins = [o for o, _ in IMPORT_SERIES.values()]
    for quarter, group in imports.groupby("quarter"):
        origins = sorted(group.origin.unique())
        missing = [o for o in all_origins if o not in origins] + KNOWN_UNAVAILABLE
        rows.append(
            {
                "quarter": quarter,
                "imports_usd": group.value_usd.sum(),
                "coverage_origins": "+".join(origins),
                "missing_origins": "+".join(missing) if missing else "",
            }
        )
    return pd.DataFrame(rows).set_index("quarter")


def quarterly_domestic_usd(df, fx):
    """Numerator: domestic semicap revenue per quarter in USD, plus company
    count and how many company-quarters carry an ESTIMATED flag."""
    rev = df[(df.metric_name == NUMERATOR_METRIC) & (df.layer == "equipment")].copy()
    if rev.empty:
        return pd.DataFrame(columns=["domestic_semicap_usd", "n_companies", "n_estimated"])
    rev["currency"] = "CNY"
    # Quarter periods ('2026Q1') convert at the quarter's average monthly rate.
    q_fx = {}
    for period, rate in fx.get("CNY", {}).items():
        q_fx.setdefault(month_to_quarter(period), []).append(rate)
    fx_q = {"CNY": {q: sum(v) / len(v) for q, v in q_fx.items()}}
    rev, dropped = to_usd(rev, fx_q)
    if len(dropped):
        print(f"WARNING: {len(dropped)} revenue rows lacked an FX rate — excluded")
    rev["estimated"] = rev.notes.str.contains("ESTIMATED", na=False)
    grouped = rev.groupby("period").agg(
        domestic_semicap_usd=("value_usd", "sum"),
        n_companies=("entity", "nunique"),
        n_estimated=("estimated", "sum"),
    )
    grouped.index.name = "quarter"
    return grouped


def compute_ratio(conn):
    df = load_metrics(conn)
    fx = load_fx(conn)
    imports = quarterly_imports_usd(df, fx)
    domestic = quarterly_domestic_usd(df, fx)
    out = imports.join(domestic, how="outer").sort_index()
    out["ratio"] = out.domestic_semicap_usd / (
        out.domestic_semicap_usd + out.imports_usd
    )
    out["methodology_version"] = METHODOLOGY_VERSION
    return out


def archive_v1_once():
    """Keep the pre-revision series so old vs new stays comparable."""
    if not OUT_PATH.exists():
        return
    head = OUT_PATH.read_text().splitlines()[0]
    if "methodology_version" in head:
        return  # already a versioned series; git history holds the rest
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    dest = HISTORY_DIR / "indigenization_ratio_v1.csv"
    if not dest.exists():
        shutil.copy(OUT_PATH, dest)
        print(f"archived v1 series to {dest.relative_to(REPO_ROOT)}")


def main():
    conn = sqlite3.connect(DB_PATH)
    out = compute_ratio(conn)
    conn.close()

    archive_v1_once()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_PATH, index_label="quarter")

    print("=" * 78)
    print(f"China WFE indigenization ratio — methodology v{METHODOLOGY_VERSION} (USD)")
    print("  numerator: domestic semicap revenue (segment- and region-adjusted)")
    print("  denominator: mirror imports, per-quarter origin coverage listed below")
    print("=" * 78)
    if out.empty:
        print("no data yet — run the collectors and extractions first")
        return 1
    cols = [
        "imports_usd", "domestic_semicap_usd", "ratio",
        "n_companies", "n_estimated", "coverage_origins", "missing_origins",
    ]
    with pd.option_context("display.float_format", lambda v: f"{v:,.3f}",
                           "display.width", 200):
        print(out[cols].to_string())
    ready = out.dropna(subset=["ratio"])
    print(f"\nquarters with both sides: {len(ready)}")
    print(f"wrote {OUT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
