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

# ---- causal effect of export controls (DiD) --------------------------------------

exports_dir = REPO_ROOT / "data" / "exports"
if (exports_dir / "did_summary.csv").exists() and (exports_dir / "did_event_study.csv").exists():
    st.header("Causal effect of export controls (difference-in-differences)")

    # Robustness toggle: the ex-Singapore variant drops Singapore from both the
    # control group and the counterfactual basket (US->Singapore rerouting
    # caveat). Falls back to the full variant if the variant CSVs aren't present.
    variants = {"Full allied control (EU27+JP+KR+SG)": ""}
    if (exports_dir / "did_summary_ex_sg.csv").exists():
        variants["Drop Singapore (rerouting robustness)"] = "_ex_sg"
    choice = st.radio(
        "Control group", list(variants), horizontal=True,
        help="Robustness check: does the estimate survive removing Singapore,"
             " where some 'exports' are US firms rerouting via Singapore fabs?",
    )
    sfx = variants[choice]

    s = pd.read_csv(exports_dir / f"did_summary{sfx}.csv").iloc[0]
    es = pd.read_csv(exports_dir / f"did_event_study{sfx}.csv")
    cf = pd.read_csv(exports_dir / f"did_counterfactual{sfx}.csv")
    did_coef_csv = exports_dir / f"did_coefficients{sfx}.csv"

    st.caption(
        "The ratio has no untreated control group, so identification moves to"
        " the denominator: US-origin imports (hit by unilateral US controls) vs"
        " allied origins (same fabs, same demand cycle, not bound by the US"
        " rules). Year-month fixed effects absorb the fab-capex cycle, so the"
        " estimate is the US deviation from the allied path after each control"
        f" wave. Anchor: {s.anchor_quarter} (pre-control)."
    )

    m1, m2, m3 = st.columns(3)
    m1.metric(
        "US exports vs allied path (all 3 waves)",
        f"{s.cumulative_pct_effect:.0%}",
        help="Cumulative treatment effect after Oct-2022 + Oct-2023 + Dec-2024,"
             " cycle differenced out. Level effect from the DiD coefficients.",
    )
    m2.metric(
        f"US-suppression share of the {s.latest_ratio_actual:.0%} ratio ({s.latest_quarter})",
        f"{s.latest_suppression_pp:.1f} pp",
        help="How much of the headline indigenization ratio is US-import"
             " suppression (a denominator effect of the controls) vs genuine"
             " domestic substitution. Most of the ratio is substitution.",
    )
    m3.metric(
        "Placebo p-value",
        f"{s.placebo_p_value:.2f}",
        help=f"Randomization inference across {int(s.n_origins)} origins — the"
             " sharpest attainable p is 1/n. The case rests on magnitude and the"
             " parallel-trends event study, not a significance star.",
    )

    c1, c2 = st.columns(2)
    with c1:
        pre, post = es[es.is_pre], es[~es.is_pre]
        fige = go.Figure()
        fige.add_scatter(
            x=pre.quarter, y=pre.coef, mode="markers", name="pre-baseline",
            marker=dict(color="#7f7f7f", size=8),
            error_y=dict(type="data", array=1.96 * pre.se, color="#bbbbbb"),
        )
        fige.add_scatter(
            x=post.quarter, y=post.coef, mode="lines+markers", name="post-wave",
            line=dict(color="#d62728"),
            error_y=dict(type="data", array=1.96 * post.se, color="#f4b5b5"),
        )
        fige.add_hline(y=0, line_dash="dot", line_color="gray")
        fige.add_vline(x=str(s.anchor_quarter), line_dash="dash", line_color="green")
        fige.update_layout(
            title="Event study: US vs allied (log-point deviation)",
            yaxis=dict(title="log points"), height=380,
            legend=dict(orientation="h", y=-0.25), margin=dict(t=40),
        )
        st.plotly_chart(fige, use_container_width=True)
        st.caption(
            "Flat, near-zero coefficients *before* the green baseline = parallel"
            " trends (the design's key assumption); the steady decline after is"
            " the control effect accumulating across the three waves."
        )
    with c2:
        figc = go.Figure()
        figc.add_scatter(
            x=cf.quarter, y=cf.ratio_counterfactual, mode="lines",
            name="Counterfactual (US tracks allies)",
            line=dict(color="#7f7f7f", dash="dash"),
        )
        figc.add_scatter(
            x=cf.quarter, y=cf.ratio_actual, mode="lines+markers",
            name="Actual ratio", line=dict(color="#1f77b4"),
            fill="tonexty", fillcolor="rgba(214,39,40,0.15)",
        )
        figc.update_layout(
            title="Actual vs counterfactual indigenization ratio",
            yaxis=dict(title="ratio", tickformat=".0%"), height=380,
            legend=dict(orientation="h", y=-0.25), margin=dict(t=40),
        )
        st.plotly_chart(figc, use_container_width=True)
        st.caption(
            "Shaded gap = US-import suppression (denominator effect of controls)."
            " The counterfactual line is domestic substitution — the part that"
            " would have happened anyway. Substitution does the heavy lifting."
        )

    if did_coef_csv.exists():
        with st.expander("DiD coefficients & method"):
            coef = pd.read_csv(did_coef_csv)
            coef["level_effect"] = coef.pct_effect.map(lambda v: f"{v:+.1%}")
            coef["coef"] = coef.coef.map(lambda v: f"{v:+.3f}")
            coef["hc1_se"] = coef.hc1_se.map(lambda v: f"{v:.3f}")
            st.dataframe(
                coef[["term", "coef", "level_effect", "hc1_se"]],
                hide_index=True, use_container_width=True,
            )
            st.caption(
                "Coefficients are incremental (each adds to the prior wave)."
                " Full write-up, limits and falsifiers in"
                " data/exports/did_export_controls.md. Research output, not"
                " investment advice."
            )

# ---- chip layer vs equipment layer (self-sufficiency) ----------------------------

chip_ss_csv = REPO_ROOT / "data" / "exports" / "chip_self_sufficiency.csv"
if chip_ss_csv.exists():
    css = pd.read_csv(chip_ss_csv)
    st.header("Two layers of self-sufficiency: tools vs frontier chips")
    st.caption(
        "The debate treats 'chip self-sufficiency' as one number. It's at least"
        " two. The equipment ratio (the tools) has a clean domestic numerator;"
        " the chip layer (where AI accelerators live) is proxied by SMIC + Hua"
        " Hong foundry output vs HS 8542 chip imports — DIRECTIONAL only (see"
        " limits). The national IC-output series (NBS) is geo-blocked from here."
    )
    figl = go.Figure()
    figl.add_scatter(
        x=css.quarter, y=css.equipment_ratio, mode="lines+markers",
        name="Equipment ratio (tools — identified)", line=dict(color="#1f77b4"),
    )
    figl.add_scatter(
        x=css.quarter, y=css.chip_domestic_share, mode="lines+markers",
        name="Chip domestic share (frontier — proxy)",
        line=dict(color="#d62728", dash="dash"),
    )
    figl.update_layout(
        yaxis=dict(title="share / ratio", tickformat=".0%", range=[0, 0.3]),
        legend=dict(orientation="h", y=-0.25), height=380, margin=dict(t=20),
    )
    st.plotly_chart(figl, use_container_width=True)
    if len(css) >= 2:
        first, last = css.iloc[0], css.iloc[-1]
        d1, d2, d3 = st.columns(3)
        d1.metric("Domestic logic output (proxy)",
                  f"+{last.domestic_logic_idx - 100:.0f}%",
                  help=f"SMIC+Hua Hong revenue growth, {first.quarter}→{last.quarter}.")
        d2.metric("Chip imports (same window)",
                  f"+{last.chip_imports_idx - 100:.0f}%",
                  help="Imports rose too — demand outran substitution.")
        d3.metric("Chip share vs equipment ratio",
                  f"{last.chip_domestic_share:.0%} vs {last.equipment_ratio:.0%}",
                  help="Tools localize faster than the frontier chips they make.")
    st.caption(
        "Read: domestic logic output roughly doubled, but chip imports rose with"
        " AI/electronics demand, so the chip share barely moved while the"
        " equipment ratio surged — China localizes the factory faster than the"
        " frontier product. Proxy limits (foundry revenue includes non-China"
        " sales; excludes memory/IDM; imports include re-export) are in"
        " data/exports/chip_self_sufficiency.md."
    )

# ---- chip controls DiD -----------------------------------------------------------

chip_did_es = REPO_ROOT / "data" / "exports" / "did_chip_event_study.csv"
chip_did_sum = REPO_ROOT / "data" / "exports" / "did_chip_summary.csv"
if chip_did_es.exists() and chip_did_sum.exists():
    ces = pd.read_csv(chip_did_es)
    cs = pd.read_csv(chip_did_sum).iloc[0]
    import numpy as _np
    ces["level"] = _np.exp(ces.coef) - 1  # log pts -> % deviation from allied

    st.header("Did the chip controls work?")
    st.caption(
        "The SAME difference-in-differences, run on HS 8542 chips (the A100/H100,"
        " A800/H800, H20 layer). US chip exports to China vs the allied path,"
        " cycle-differenced. Contrast with the equipment DiD above: the tool"
        " controls stuck (−78%, durable); the chip controls did not."
    )
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Trough vs allied path", f"{cs.trough_pct:.0%}",
              help=f"Deepest US shortfall vs allied path, at {cs.trough_quarter} —"
                   " the bans genuinely bit.")
    k2.metric("Latest vs allied path", f"{cs.latest_es_pct:.0%}",
              help="US chip exports bounced back as NVIDIA shipped compliant"
                   " A800/H800/H20 parts.")
    k3.metric("Net cumulative effect", f"{cs.cumulative_pct_effect:+.0%}",
              help="Washes toward zero — the initial hit was undone by"
                   " re-engineering the product.")
    k4.metric("Placebo p", f"{cs.placebo_p_value:.2f}",
              help="US is NOT the most-suppressed origin over the full window —"
                   " no durable identified suppression, unlike equipment.")

    figv = go.Figure()
    pre, post = ces[ces.is_pre], ces[~ces.is_pre]
    figv.add_scatter(x=pre.quarter, y=pre.level, mode="markers", name="pre-baseline",
                     marker=dict(color="#7f7f7f", size=8))
    figv.add_scatter(x=post.quarter, y=post.level, mode="lines+markers",
                     name="US vs allied (post)", line=dict(color="#d62728"))
    figv.add_hline(y=0, line_dash="dot", line_color="gray")
    figv.add_vline(x=str(cs.anchor_quarter), line_dash="dash", line_color="green")
    figv.update_layout(
        title="US chip exports to China vs the allied-implied path",
        yaxis=dict(title="% deviation from allied path", tickformat=".0%"),
        height=380, legend=dict(orientation="h", y=-0.25), margin=dict(t=40),
    )
    st.plotly_chart(figv, use_container_width=True)
    st.markdown(
        "**How NVIDIA's product moves trace the curve.** The controls chased a"
        " moving product line, and each ban was answered with a redesigned,"
        " rules-compliant chip — so US chip sales to China cratered, then climbed"
        " back:\n\n"
        "- **Oct 2022 — A100/H100 cut off.** BIS performance thresholds bar"
        " NVIDIA's top data-center GPUs; US chip exports to China start falling.\n"
        "- **Late 2022→2023 — the A800/H800 workaround.** NVIDIA ships"
        " bandwidth-capped China-only parts. **Oct 2023** BIS bans those too —"
        " the trough (2023, roughly −47% below the allied path; US chip exports"
        " to China fell from ~$12bn to ~$5bn a year).\n"
        "- **2024 — the H20.** A further cut-down Hopper part engineered to clear"
        " the line sells in volume; exports recover toward the allied path.\n"
        "- **2025Q1 spike (well above the allied path).** Consistent with"
        " stockpiling ahead of the **April 2025** H20 license requirement (which"
        " forced a multi-billion-dollar NVIDIA write-down); exports soften after,"
        " then partially resume under a mid-2025 revenue-share arrangement.\n\n"
        "The mechanism is the whole point: a chip is a *design* that can be"
        " re-spun to the threshold; a lithography tool is not. That is why the"
        " identical controls are durable at the equipment layer (−78%) and"
        " porous at the chip layer. Neither, meanwhile, made China self-"
        "sufficient — chip imports rose on AI demand throughout."
    )
    st.caption(
        "Parallel trends fails here, so read the chip layer as descriptive; the"
        " equipment DiD is the cleanly identified estimate."
        " Full method and limits in data/exports/did_chip_controls.md."
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

st.caption(
    "Pipeline: collectors → validated extraction → SQLite → deterministic"
    " analysis → drafts for human review. github.com/xiajason6-web/GeoMacro2"
)
