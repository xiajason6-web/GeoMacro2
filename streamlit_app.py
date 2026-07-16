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
    # A quarter is fully covered when the only missing origin is Taiwan
    # (which has no machine-readable source). Reduced-coverage quarters
    # understate imports -> overstate the ratio, so they must not headline.
    full = ratio[ratio.missing_origins.fillna("") == "Taiwan"]
    reduced = ratio[ratio.missing_origins.fillna("") != "Taiwan"]

    col1, col2 = st.columns([2, 1])
    with col1:
        fig = go.Figure()
        fig.add_bar(x=ratio.quarter, y=ratio.domestic_semicap_usd / 1e9, name="Domestic semicap revenue (bn USD)")
        fig.add_bar(x=ratio.quarter, y=ratio.imports_usd / 1e9, name="Equipment imports (bn USD)")
        fig.add_scatter(
            x=full.quarter, y=full.ratio, name="Ratio (full coverage)",
            yaxis="y2", mode="lines+markers",
        )
        if not reduced.empty:
            fig.add_scatter(
                x=reduced.quarter, y=reduced.ratio,
                name="Ratio (PARTIAL coverage — overstated)",
                yaxis="y2", mode="markers",
                marker=dict(symbol="circle-open", size=13, color="#d62728"),
                text=reduced.missing_origins,
                hovertemplate="%{x}: %{y:.1%}<br>missing: %{text}<extra></extra>",
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
        # Headline the latest FULLY-covered quarter, never a partial one.
        headline = full.iloc[-1]
        first = full.iloc[0]
        st.metric(
            f"Latest full-coverage quarter ({headline.quarter})",
            f"{headline.ratio:.1%}",
            f"{headline.ratio - first.ratio:+.1%} vs {first.quarter}",
        )
        if not reduced.empty:
            newest = reduced.iloc[-1]
            st.caption(
                f"⚠️ {newest.quarter} reads {newest.ratio:.1%} but is missing"
                f" {newest.missing_origins} on the imports side — overstated,"
                " not comparable. The nowcast below completes it."
            )
        st.dataframe(
            ratio[["quarter", "ratio", "coverage_origins", "n_estimated"]].assign(
                ratio=lambda d: d.ratio.map("{:.1%}".format)
            ),
            hide_index=True,
            use_container_width=True,
        )

# ---- nowcast (estimate — subordinate styling by design) --------------------------

nowcasts = load(
    "SELECT target_quarter, ratio_nowcast, ratio_low, ratio_high, made_at, drivers"
    " FROM nowcasts WHERE made_at = (SELECT MAX(made_at) FROM nowcasts)"
    " ORDER BY target_quarter"
)
if not nowcasts.empty and ratio_csv.exists():
    st.header("Nowcast — model estimate, not measured data")
    st.info(
        f"NOWCAST produced {nowcasts.made_at.iloc[0]}: fills unpublished months"
        " by carry-forward scaled by the vendor China-revenue signal, and"
        " extrapolates unreported revenue. Scenario band, not a confidence"
        " interval. The measured series above is the record; this is a bridge."
    )
    fign = go.Figure()
    fign.add_scatter(
        x=ratio.quarter, y=ratio.ratio, mode="lines+markers",
        name="Measured (v2)", line=dict(color="#1f77b4"),
    )
    fign.add_scatter(
        x=nowcasts.target_quarter, y=nowcasts.ratio_nowcast, mode="markers",
        name="NOWCAST (estimate)",
        marker=dict(symbol="diamond-open", size=14, color="#999999"),
        error_y=dict(
            type="data", symmetric=False,
            array=nowcasts.ratio_high - nowcasts.ratio_nowcast,
            arrayminus=nowcasts.ratio_nowcast - nowcasts.ratio_low,
        ),
    )
    fign.update_layout(
        yaxis=dict(title="ratio", range=[0, 0.5], tickformat=".0%"),
        legend=dict(orientation="h", y=-0.25), height=380, margin=dict(t=20),
    )
    st.plotly_chart(fign, use_container_width=True)
    for _, nc in nowcasts.iterrows():
        with st.expander(
            f"{nc.target_quarter}: {nc.ratio_nowcast:.1%}"
            f" [{nc.ratio_low:.1%} – {nc.ratio_high:.1%}] — drivers"
        ):
            st.text(nc.drivers)

# ---- consensus reconciliation ----------------------------------------------------

st.header("vs published estimates (consensus reconciliation)")
bench = load(
    "SELECT source, period, value, numerator_scope, method_notes, source_url"
    " FROM benchmarks ORDER BY period, source"
)
if not bench.empty and ratio_csv.exists():
    # Split the same way as the headline chart: only full-coverage quarters
    # are comparable to the benchmarks. Plotting the partial 2026Q1 (36.4%,
    # missing Korea+Singapore imports) here would show us as a false outlier
    # above every consensus estimate.
    b_full = ratio[ratio.missing_origins.fillna("") == "Taiwan"]
    b_reduced = ratio[ratio.missing_origins.fillna("") != "Taiwan"]
    figb = go.Figure()
    figb.add_scatter(
        x=b_full.quarter, y=b_full.ratio, mode="lines+markers",
        name="This tracker (v2, full coverage)",
    )
    if not b_reduced.empty:
        figb.add_scatter(
            x=b_reduced.quarter, y=b_reduced.ratio, mode="markers",
            name="This tracker (PARTIAL — not comparable)",
            marker=dict(symbol="circle-open", size=13, color="#d62728"),
            text=b_reduced.missing_origins,
            hovertemplate="%{x}: %{y:.1%}<br>missing imports: %{text}<extra></extra>",
        )
    for source, grp in bench.groupby("source"):
        figb.add_scatter(
            x=[f"{p.rstrip('E')}Q4" for p in grp.period], y=grp.value / 100,
            mode="markers", name=source, marker=dict(size=13, symbol="diamond"),
            text=grp.numerator_scope,
            hovertemplate="%{x}: %{y:.0%}<br>scope: %{text}",
        )
    figb.update_layout(
        yaxis=dict(title="ratio", range=[0, 0.5], tickformat=".0%"),
        legend=dict(orientation="h", y=-0.25), height=400, margin=dict(t=20),
    )
    st.plotly_chart(figb, use_container_width=True)
    st.caption(
        "Benchmark scopes differ from ours and from each other — the gap"
        " decomposition (numerator scope, import coverage, currency, company"
        " scope) is in data/exports/reconciliation.md; every benchmark row"
        " cites an archived source page."
    )
    st.dataframe(
        bench[["source", "period", "value", "numerator_scope"]],
        hide_index=True, use_container_width=True,
    )

# ---- exposure ladder + surprise --------------------------------------------------

st.header("Exposure ladder — theme → instruments (research, not advice)")
st.caption(
    "How each liquid instrument's business is exposed to rising indigenization"
    " — direction and mechanism only. No sizing, entries, or targets. Full"
    " reasoning and falsifiers in data/exports/trade_note.md."
)
ladder = load(
    "SELECT instrument, venue, exposure_sign, confidence, mechanism"
    " FROM instrument_exposure WHERE human_reviewed = 1"
    " ORDER BY CASE exposure_sign WHEN 'benefit' THEN 0 WHEN 'harm' THEN 1"
    " WHEN 'mixed' THEN 2 ELSE 3 END,"
    " CASE confidence WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END"
)
pending_ladder = load(
    "SELECT COUNT(*) AS n FROM instrument_exposure WHERE human_reviewed = 0"
).n[0]
if not ladder.empty:
    st.dataframe(ladder, hide_index=True, use_container_width=True)
if pending_ladder:
    st.caption(f"{pending_ladder} instrument rows pending human review are not shown.")

nc_rows = load(
    "SELECT target_quarter, ratio_nowcast, ratio_low, ratio_high FROM nowcasts"
    " WHERE made_at = (SELECT MAX(made_at) FROM nowcasts) ORDER BY target_quarter"
)
if not nc_rows.empty and ratio_csv.exists() and not full.empty:
    base_q = full.index.max() if hasattr(full, "index") else None
    baseline = float(full.iloc[-1].ratio)
    nxt = nc_rows.iloc[0]
    surprise_pp = (nxt.ratio_nowcast - baseline) * 100
    st.metric(
        f"Nowcast vs consensus — {nxt.target_quarter} vs persistence baseline",
        f"{nxt.ratio_nowcast:.1%}",
        f"{surprise_pp:+.1f} pp vs {baseline:.1%} (last full-coverage quarter)",
    )
    st.caption(
        "Traders trade the delta, not the level. Estimate only; band"
        f" {nxt.ratio_low:.1%}–{nxt.ratio_high:.1%}. See data/exports/consensus_gap.md."
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

st.header("China imports (mirror data)")
hs = st.radio(
    "Series", ["HS 8486 — chipmaking equipment", "HS 8542 — integrated circuits"],
    horizontal=True,
)
code = "8486" if "8486" in hs else "8542"
imports = load(
    f"""
    SELECT m.metric_name, m.period, m.value FROM metrics m
    JOIN entities e ON e.id = m.entity_id AND e.name_en = 'China'
    WHERE m.metric_name IN ('mirror_exports_eu27_hs{code}_eur',
                            'mirror_exports_jp_hs{code}_jpy',
                            'mirror_exports_us_hs{code}_usd',
                            'mirror_exports_kr_hs{code}_usd',
                            'mirror_exports_sg_hs{code}_usd')
      AND m.document_id = (
        SELECT MAX(m2.document_id) FROM metrics m2
        WHERE m2.entity_id = m.entity_id AND m2.metric_name = m.metric_name
          AND m2.period = m.period)
    ORDER BY m.period
    """
)
labels = {
    f"mirror_exports_eu27_hs{code}_eur": "EU27 (EUR)",
    f"mirror_exports_jp_hs{code}_jpy": "Japan (JPY)",
    f"mirror_exports_us_hs{code}_usd": "US (USD)",
    f"mirror_exports_kr_hs{code}_usd": "Korea (USD)",
    f"mirror_exports_sg_hs{code}_usd": "Singapore (USD)",
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
    SELECT x.event_category, e.name_en AS entity, x.direction, x.confidence,
           x.channel_description
    FROM exposure_links x JOIN entities e ON e.id = x.entity_id
    WHERE x.human_reviewed = 1
    """
)
pending_links = load(
    "SELECT COUNT(*) AS n FROM exposure_links WHERE human_reviewed = 0"
).n[0]
if pending_links:
    st.caption(f"{pending_links} exposure links pending human review are not shown.")
for _, ev in events.iterrows():
    with st.expander(f"{ev.event_date} · [{ev.category}] {ev.summary[:110]}"):
        mapped = links[links.event_category == ev.category]
        if mapped.empty:
            st.write("No transmission mapping for this category yet.")
        else:
            st.dataframe(
                mapped[["entity", "direction", "confidence", "channel_description"]],
                hide_index=True,
            )

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
