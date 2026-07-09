"""Chart the indigenization ratio and its two components.

What this does: reads data/exports/indigenization_ratio.csv (produced by
indigenization_ratio.py) and writes an interactive HTML chart to
data/exports/indigenization_ratio.html — bars for domestic revenue and
imports (CNY), a line for the ratio. Open the HTML file in a browser.

How you'd know it broke: it prints the output path on success, or a clear
message if the CSV is missing/empty.
"""

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

REPO_ROOT = Path(__file__).resolve().parent.parent
IN_PATH = REPO_ROOT / "data" / "exports" / "indigenization_ratio.csv"
OUT_PATH = REPO_ROOT / "data" / "exports" / "indigenization_ratio.html"


def main():
    if not IN_PATH.exists():
        print("run analysis/indigenization_ratio.py first")
        return 1
    df = pd.read_csv(IN_PATH)
    if df.empty:
        print("indigenization_ratio.csv is empty — nothing to chart")
        return 1

    fig = go.Figure()
    fig.add_bar(
        x=df.quarter, y=df.domestic_cny / 1e9, name="Domestic equipment revenue (bn CNY)"
    )
    fig.add_bar(x=df.quarter, y=df.imports_cny / 1e9, name="Equipment imports (bn CNY)")
    fig.add_scatter(
        x=df.quarter,
        y=df.ratio,
        name="Indigenization ratio",
        yaxis="y2",
        mode="lines+markers",
    )
    fig.update_layout(
        title=(
            "China WFE indigenization ratio — WORKING SERIES"
            "<br><sub>Import coverage: EU27 only (US, Japan pending) — ratio overstated</sub>"
        ),
        barmode="group",
        yaxis=dict(title="bn CNY"),
        yaxis2=dict(title="ratio", overlaying="y", side="right", range=[0, 1]),
        legend=dict(orientation="h", y=-0.2),
    )
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(OUT_PATH, include_plotlyjs="cdn")
    print(f"wrote {OUT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
