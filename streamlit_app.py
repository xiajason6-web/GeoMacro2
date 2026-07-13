"""Read-only dashboard over db/tracker.sqlite.

What this does: renders the indigenization series, its components, company
revenue, the events-and-exposure view, and the open review queue — straight
from the SQLite file in the repo. Nothing here writes to the database, and
every caveat that the analysis layer prints is shown on screen too.

Run locally:   .venv/bin/streamlit run streamlit_app.py
Deployed:      Streamlit Community Cloud pointed at this file.
"""

import sqlite3
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parent
DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"

st.set_page_config(page_title="China Tech Flows", layout="wide")


@st.cache_data(ttl=3600)
def load(query):
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df


st.title("China Tech Flows — semiconductor indigenization tracker")
st.caption(
    "Research analysis only: transmission mechanisms and exposure, not"
    " investment advice. Every number traces to an archived source document."
)

# ---- indigenization series ----------------------------------------------------

ratio_csv = REPO_ROOT / "data" / "exports" / "indigenization_ratio.csv"
if ratio_csv.exists():
    ratio = pd.read_csv(ratio_csv).dropna(subset=["ratio"])
    st.header("Indigenization ratio (working series)")
    st.warning(
        "Methodology v2 (USD): numerator = domestic semicap revenue (segment-"
        " and region-adjusted from filings); denominator = mirror imports from"
        " EU27, Japan, US, Korea, Singapore (Taiwan unavailable). Quarters"
        " with reduced origin coverage are marked. See analysis/methodology.md."
    )
    col1, col2 = st.columns([2, 1])
    with col1:
        fig = go.Figure()
        fig.add_bar(x=ratio.quarter, y=ratio.domestic_semicap_usd / 1e9, name="Domestic semicap revenue (bn USD)")
        fig.add_bar(x=ratio.quarter, y=ratio.imports_usd / 1e9, name="Equipment imports (bn USD)")
        fig.add_scatter(
            x=ratio.quarter, y=ratio.ratio, name="Indigenization ratio",
            yaxis="y2", mode="lines+markers",
        )
        fig.update_layout(
            barmode="group",
            yaxis=dict(title="bn USD"),
            yaxis2=dict(title="ratio", overlaying="y", side="right", range=[0, 0.6]),
            legend=dict(orientation="h", y=-0.25),
            height=420,
            margin=dict(t=20),
        )
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        latest = ratio.iloc[-1]
        first = ratio.iloc[0]
        st.metric(
            f"Latest ({latest.quarter})",
            f"{latest.ratio:.1%}",
            f"{latest.ratio - first.ratio:+.1%} vs {first.quarter}",
        )
        st.dataframe(
            ratio[["quarter", "ratio", "coverage_origins", "n_estimated"]].assign(
                ratio=lambda d: d.ratio.map("{:.1%}".format)
            ),
            hide_index=True,
            use_container_width=True,
        )

# ---- company revenue ------------------------------------------------------------

st.header("Quarterly revenue — listed Chinese semicap & foundries")
rev = load(
    """
    SELECT e.name_en AS company, e.supply_chain_layer AS layer, m.period,
           m.value / 1e9 AS bn_cny,
           CASE WHEN m.notes LIKE 'DERIVED%' THEN 'derived' ELSE 'extracted' END AS origin
    FROM metrics m JOIN entities e ON e.id = m.entity_id
    WHERE m.metric_name = 'quarterly_revenue_cny'
      AND m.document_id = (
        SELECT MAX(m2.document_id) FROM metrics m2
        WHERE m2.entity_id = m.entity_id AND m2.metric_name = m.metric_name
          AND m2.period = m.period)
    ORDER BY m.period
    """
)
layer = st.radio("Layer", ["equipment", "foundry"], horizontal=True)
sub = rev[rev.layer == layer]
fig2 = go.Figure()
for company in sorted(sub.company.unique()):
    cdf = sub[sub.company == company]
    fig2.add_bar(x=cdf.period, y=cdf.bn_cny, name=company)
fig2.update_layout(barmode="stack", yaxis_title="bn CNY", height=380, margin=dict(t=20))
st.plotly_chart(fig2, use_container_width=True)
st.caption(
    f"{(sub.origin == 'derived').sum()} of {len(sub)} quarters are derived by"
    " subtraction from half-year/annual summaries (notes say DERIVED)."
)

# ---- mirror trade ---------------------------------------------------------------

st.header("China equipment imports (mirror data, HS 8486)")
imports = load(
    """
    SELECT m.metric_name, m.period, m.value FROM metrics m
    JOIN entities e ON e.id = m.entity_id AND e.name_en = 'China'
    WHERE m.metric_name IN ('mirror_exports_eu27_hs8486_eur',
                            'mirror_exports_jp_hs8486_jpy',
                            'mirror_exports_us_hs8486_usd')
      AND m.document_id = (
        SELECT MAX(m2.document_id) FROM metrics m2
        WHERE m2.entity_id = m.entity_id AND m2.metric_name = m.metric_name
          AND m2.period = m.period)
    ORDER BY m.period
    """
)
labels = {
    "mirror_exports_eu27_hs8486_eur": "EU27 (EUR)",
    "mirror_exports_jp_hs8486_jpy": "Japan (JPY)",
    "mirror_exports_us_hs8486_usd": "US (USD)",
}
fig3 = go.Figure()
for metric, label in labels.items():
    mdf = imports[imports.metric_name == metric]
    fig3.add_scatter(x=mdf.period, y=mdf.value, name=label, mode="lines")
fig3.update_layout(
    yaxis_title="monthly value (native currency)", height=380, margin=dict(t=20)
)
st.plotly_chart(fig3, use_container_width=True)
st.caption("Native currencies shown; the ratio converts via ECB monthly rates.")

# ---- events and exposure ---------------------------------------------------------

st.header("Recent events → exposure")
events = load(
    """
    SELECT ev.event_date, ev.category, ev.actor,
           COALESCE(NULLIF(ev.summary_en, 'PENDING_TRANSLATION'), ev.summary_zh) AS summary
    FROM events ev ORDER BY ev.event_date DESC LIMIT 25
    """
)
links = load(
    """
    SELECT x.event_category, e.name_en AS entity, x.direction, x.confidence
    FROM exposure_links x JOIN entities e ON e.id = x.entity_id
    """
)
for _, ev in events.iterrows():
    with st.expander(f"{ev.event_date} · [{ev.category}] {ev.summary[:110]}"):
        mapped = links[links.event_category == ev.category]
        if mapped.empty:
            st.write("No transmission mapping for this category yet.")
        else:
            st.dataframe(mapped[["entity", "direction", "confidence"]], hide_index=True)

# ---- review queue ----------------------------------------------------------------

st.header("Open review queue")
queue = load(
    "SELECT id, item_type, reason FROM review_queue WHERE status = 'open' ORDER BY id DESC"
)
if queue.empty:
    st.success("Queue is empty.")
else:
    st.dataframe(queue, hide_index=True, use_container_width=True)

st.caption(
    "Pipeline: collectors → validated extraction → SQLite → deterministic"
    " analysis → drafts for human review. github.com/xiajason6-web/GeoMacro2"
)
