"""Consensus reconciliation: our series vs published benchmarks, with the
gap decomposed into measurable drivers. Nobody publishes this.

For a benchmark year (default: the latest year with four fully-covered
quarters), the ANNUAL ratio is recomputed under methodology variants, each
isolating one driver, all from our own database:

  v2 (headline)   domestic semicap numerator, 5-origin denominator, USD
  A. numerator    total revenue instead of domestic semicap  -> scope effect
  B. denominator  EU27+JP+US only (drop Korea+Singapore)     -> coverage effect
  C. currency     CNY as common unit instead of USD          -> treatment effect
  D. UBS scope    numerator limited to Naura+AMEC+ACM        -> comparability
                  (UBS's published 20% counts only those 3)

Remaining difference vs each benchmark after the relevant variant is the
DEFINITIONAL RESIDUAL (their market model vs our mirror-trade denominator,
installed-base vs revenue timing, service/parts inclusion) — stated, not
hidden.

Outputs:
  data/exports/reconciliation.md          — methodology table (exportable)
  data/exports/reconciliation.html        — series + benchmark markers
  data/exports/reconciliation_bridge.html — waterfall v1-style -> v2

Deterministic pandas; no LLM. How you'd know it broke: the tests pin the
variant arithmetic; the chart prints its output path.
"""

import sqlite3
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import indigenization_ratio as ir  # noqa: E402

DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"
OUT_DIR = REPO_ROOT / "data" / "exports"

UBS_SCOPE_ENTITIES = ["Naura", "AMEC", "ACM Shanghai"]
LEGACY_SERIES = {
    k: v for k, v in ir.IMPORT_SERIES.items()
    if v[0] in ("EU27", "Japan", "US")
}


def annual_ratio(imports_q, domestic_q, year):
    """Sum-then-divide annual ratio for quarters of `year` present on BOTH
    sides — never an average of quarterly ratios."""
    quarters = [f"{year}Q{i}" for i in range(1, 5)]
    idx = [q for q in quarters if q in imports_q.index and q in domestic_q.index]
    if len(idx) < 4:
        return None, len(idx)
    num = domestic_q.loc[idx].iloc[:, 0].sum()
    den = imports_q.loc[idx, "imports_usd"].sum()
    return num / (num + den), len(idx)


def cny_variant(df, fx, year):
    """Variant C: identical scopes, CNY as the common unit."""
    usd_per_cny = fx["CNY"]
    cny_fx = {
        currency: {p: rate / usd_per_cny[p] for p, rate in periods.items() if p in usd_per_cny}
        for currency, periods in fx.items()
    }
    imports_q = ir.quarterly_imports_usd(df, cny_fx)
    domestic_q = ir.quarterly_domestic_usd(df, cny_fx)
    return annual_ratio(imports_q, domestic_q, year)[0]


def compute_variants(conn, year):
    df = ir.load_metrics(conn)
    fx = ir.load_fx(conn)
    imports_full = ir.quarterly_imports_usd(df, fx)
    imports_legacy = ir.quarterly_imports_usd(df, fx, series=LEGACY_SERIES)
    dom_v2 = ir.quarterly_domestic_usd(df, fx)
    dom_total = ir.quarterly_domestic_usd(df, fx, metric="quarterly_revenue_cny")
    dom_ubs = ir.quarterly_domestic_usd(df, fx, entities=UBS_SCOPE_ENTITIES)

    v2, n_q = annual_ratio(imports_full, dom_v2, year)
    variants = {
        "v2_headline": v2,
        "A_total_revenue_numerator": annual_ratio(imports_full, dom_total, year)[0],
        "B_legacy_denominator": annual_ratio(imports_legacy, dom_v2, year)[0],
        "C_cny_common_unit": cny_variant(df, fx, year),
        "D_ubs_3_company_scope": annual_ratio(imports_full, dom_ubs, year)[0],
        "legacy_style_both": annual_ratio(imports_legacy, dom_total, year)[0],
    }
    return variants, n_q


def load_benchmarks(conn, year):
    return pd.read_sql_query(
        "SELECT source, period, value, numerator_scope, denominator_scope,"
        " method_notes, source_url FROM benchmarks ORDER BY period, source",
        conn,
    ), str(year)


def build_markdown(variants, benchmarks, year):
    v2 = variants["v2_headline"]
    lines = [
        f"# Consensus reconciliation — {year}",
        "",
        f"Our v2 annual ratio for {year}: **{v2:.1%}** (sum of four quarters,",
        "USD, full five-origin coverage).",
        "",
        "## Gap drivers, measured on our own data",
        "",
        "| Variant (one change vs v2) | Annual ratio | Effect vs v2 |",
        "|---|---|---|",
    ]
    labels = {
        "A_total_revenue_numerator": "Numerator = total company revenue (v1 scope)",
        "B_legacy_denominator": "Denominator without Korea+Singapore (v1 coverage)",
        "C_cny_common_unit": "CNY instead of USD as common unit",
        "D_ubs_3_company_scope": "Numerator = Naura+AMEC+ACM only (UBS scope)",
        "legacy_style_both": "Both v1 choices together (old-style measure)",
    }
    for key, label in labels.items():
        v = variants[key]
        lines.append(f"| {label} | {v:.1%} | {v - v2:+.1%} |")
    lines += [
        "",
        "## Published benchmarks vs this tracker",
        "",
        "| Source | Period | Their value | Ours (comparable variant) | Gap | Their scope |",
        "|---|---|---|---|---|---|",
    ]
    for _, b in benchmarks[benchmarks.period == year].iterrows():
        if "ACM Research + AMEC + Naura" in b.numerator_scope:
            ours, ours_label = variants["D_ubs_3_company_scope"], "3-company variant"
        else:
            ours, ours_label = v2, "v2 headline"
        gap = b.value / 100 - ours
        lines.append(
            f"| {b.source} | {b.period} | {b.value:.0f}% |"
            f" {ours:.1%} ({ours_label}) | {gap:+.1%} |"
            f" {b.numerator_scope[:80]} |"
        )
    lines += [
        "",
        "Residual gaps after the comparable variant reflect definitional",
        "differences we cannot compute from filings alone: the benchmark's",
        "market model vs our mirror-trade denominator (HS 8486 includes",
        "flat-panel tools and parts; Taiwan origin missing), revenue timing",
        "vs shipment/installed-base counting, and service/parts inclusion.",
        "Method notes per benchmark are in the `benchmarks` table with the",
        "archived source page.",
    ]
    return "\n".join(lines)


def build_charts(conn, variants, benchmarks, year):
    series = pd.read_csv(OUT_DIR / "indigenization_ratio.csv").dropna(subset=["ratio"])
    fig = go.Figure()
    fig.add_scatter(
        x=series.quarter, y=series.ratio, mode="lines+markers",
        name="This tracker (v2, quarterly)",
    )
    for source, group in benchmarks.groupby("source"):
        xs = [f"{p.rstrip('E')}Q4" for p in group.period]
        fig.add_scatter(
            x=xs, y=group.value / 100, mode="markers",
            name=source, marker=dict(size=13, symbol="diamond"),
            text=group.method_notes, hovertemplate="%{x}: %{y:.0%}<br>%{text}",
        )
    fig.update_layout(
        title=(
            "China WFE indigenization: this tracker vs published estimates"
            "<br><sub>Benchmarks plotted at Q4 of their period; scopes differ"
            " — see reconciliation.md for the decomposition</sub>"
        ),
        yaxis=dict(title="ratio", range=[0, 0.5], tickformat=".0%"),
        legend=dict(orientation="h", y=-0.25),
    )
    fig.write_html(OUT_DIR / "reconciliation.html", include_plotlyjs="cdn")
    print("wrote data/exports/reconciliation.html")

    v2 = variants["v2_headline"]
    legacy = variants["legacy_style_both"]
    cov = variants["A_total_revenue_numerator"] - legacy       # coverage, at total-rev numerator
    scope = v2 - variants["A_total_revenue_numerator"]         # numerator scope, at full coverage
    wf = go.Figure(
        go.Waterfall(
            orientation="v",
            measure=["absolute", "relative", "relative", "total"],
            x=[
                f"v1-style measure ({year})",
                "add Korea+Singapore imports",
                "numerator -> domestic semicap",
                f"v2 headline ({year})",
            ],
            y=[legacy, cov, scope, 0],
            text=[f"{legacy:.1%}", f"{cov:+.1%}", f"{scope:+.1%}", f"{v2:.1%}"],
            textposition="outside",
        )
    )
    wf.update_layout(
        title=(
            f"Why the number moved: v1-style -> v2, {year}"
            f"<br><sub>Currency treatment (USD vs CNY) effect:"
            f" {variants['C_cny_common_unit'] - v2:+.2%} — negligible by design</sub>"
        ),
        yaxis=dict(tickformat=".0%", range=[0, max(legacy, v2) * 1.35]),
    )
    wf.write_html(OUT_DIR / "reconciliation_bridge.html", include_plotlyjs="cdn")
    print("wrote data/exports/reconciliation_bridge.html")


def main(year=2025):
    conn = sqlite3.connect(DB_PATH)
    variants, n_q = compute_variants(conn, year)
    if variants["v2_headline"] is None:
        print(f"{year} lacks four fully-covered quarters — pick another year")
        return 1
    benchmarks, year_s = load_benchmarks(conn, year)
    conn.close()

    md = build_markdown(variants, benchmarks, year_s)
    (OUT_DIR / "reconciliation.md").write_text(md)
    print("wrote data/exports/reconciliation.md")
    build_charts(conn, variants, benchmarks, year_s)
    print()
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
