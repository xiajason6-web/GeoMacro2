"""Charts: the v2 ratio and the v1-vs-v2 revision comparison.

What this does: reads data/exports/indigenization_ratio.csv (methodology v2,
USD) and writes:
  - indigenization_ratio.html — components + ratio, with reduced-coverage
    quarters visually distinguished (open markers + hover shows origins)
  - ratio_revision.html — old series vs new series, so the revision is
    visible instead of silently replacing history

How you'd know it broke: prints both output paths, or a clear message if
inputs are missing.
"""

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

REPO_ROOT = Path(__file__).resolve().parent.parent
IN_PATH = REPO_ROOT / "data" / "exports" / "indigenization_ratio.csv"
V1_PATH = REPO_ROOT / "data" / "exports" / "history" / "indigenization_ratio_v1.csv"
OUT_MAIN = REPO_ROOT / "data" / "exports" / "indigenization_ratio.html"
OUT_REVISION = REPO_ROOT / "data" / "exports" / "ratio_revision.html"

FULL_COVERAGE = "EU27+Japan+Korea+Singapore+US"


def main_chart(df):
    fig = go.Figure()
    fig.add_bar(
        x=df.quarter, y=df.domestic_semicap_usd / 1e9,
        name="Domestic semicap revenue (bn USD)",
    )
    fig.add_bar(x=df.quarter, y=df.imports_usd / 1e9, name="Equipment imports (bn USD)")
    full = df[df.coverage_origins == FULL_COVERAGE]
    partial = df[df.coverage_origins != FULL_COVERAGE]
    fig.add_scatter(
        x=full.quarter, y=full.ratio, name="Ratio (full origin coverage)",
        yaxis="y2", mode="lines+markers",
    )
    fig.add_scatter(
        x=partial.quarter, y=partial.ratio,
        name="Ratio (REDUCED coverage — see hover)",
        yaxis="y2", mode="markers",
        marker=dict(symbol="circle-open", size=12),
        text=partial.coverage_origins, hovertemplate="%{x}: %{y:.1%}<br>origins: %{text}",
    )
    fig.update_layout(
        title=(
            "China WFE indigenization ratio — methodology v2 (USD)"
            "<br><sub>Numerator: domestic semicap revenue · Denominator: mirror"
            " imports EU27+JP+US+KR+SG (Taiwan unavailable)</sub>"
        ),
        barmode="group",
        yaxis=dict(title="bn USD"),
        yaxis2=dict(title="ratio", overlaying="y", side="right", range=[0, 0.6]),
        legend=dict(orientation="h", y=-0.25),
    )
    fig.write_html(OUT_MAIN, include_plotlyjs="cdn")
    print(f"wrote {OUT_MAIN.relative_to(REPO_ROOT)}")


def revision_chart(df):
    if not V1_PATH.exists():
        print("no v1 archive — revision chart skipped")
        return
    v1 = pd.read_csv(V1_PATH).dropna(subset=["ratio"])
    fig = go.Figure()
    fig.add_scatter(
        x=v1.quarter, y=v1.ratio, mode="lines+markers",
        name="v1: total revenue (segment-adj), CNY, EU27+JP+US",
        line=dict(dash="dot"),
    )
    fig.add_scatter(
        x=df.quarter, y=df.ratio, mode="lines+markers",
        name="v2: domestic semicap revenue, USD, +Korea+Singapore",
    )
    fig.update_layout(
        title=(
            "Methodology revision: v1 vs v2"
            "<br><sub>Same underlying documents; numerator scope, currency"
            " normalization, and import coverage changed — see methodology.md</sub>"
        ),
        yaxis=dict(title="indigenization ratio", range=[0, 0.5]),
        legend=dict(orientation="h", y=-0.25),
    )
    fig.write_html(OUT_REVISION, include_plotlyjs="cdn")
    print(f"wrote {OUT_REVISION.relative_to(REPO_ROOT)}")


def main():
    if not IN_PATH.exists():
        print("run analysis/indigenization_ratio.py first")
        return 1
    df = pd.read_csv(IN_PATH).dropna(subset=["ratio"])
    if df.empty:
        print("indigenization_ratio.csv has no computed ratios")
        return 1
    main_chart(df)
    revision_chart(df)
    return 0


if __name__ == "__main__":
    sys.exit(main())
