"""Single-panel research note over db/tracker.sqlite outputs.

Structured like an equity-research report: one central thesis, evidence that
builds to it, risks, and what to watch — not a multi-panel dashboard. Reads
top-to-bottom. Every number traces to an archived source document; nothing
here writes to the database.

Run locally:   .venv/bin/streamlit run streamlit_app.py
Deployed:      Streamlit Community Cloud pointed at this file.
"""

from pathlib import Path

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parent
EXPORTS = REPO_ROOT / "data" / "exports"

st.set_page_config(page_title="China Semiconductor Indigenization — Research Note",
                   layout="centered")


@st.cache_data(ttl=3600)
def csv(name):
    p = EXPORTS / name
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


ratio = csv("indigenization_ratio.csv")
ratio_full = ratio[ratio.get("ratio").notna() & (ratio.get("missing_origins").fillna("") == "Taiwan")] \
    if not ratio.empty else ratio
did = csv("did_summary.csv")
cf = csv("did_counterfactual.csv")
layers = csv("chip_self_sufficiency.csv")
ches = csv("did_chip_event_study.csv")
chs = csv("did_chip_summary.csv")

d = did.iloc[0] if not did.empty else None

PLOT = dict(height=360, margin=dict(t=44, r=10, b=10, l=10),
            legend=dict(orientation="h", y=-0.22))

# ─────────────────────────────────────────────────────────────────────────────
# Masthead + thesis
# ─────────────────────────────────────────────────────────────────────────────
st.title("China Semiconductor Indigenization")
st.subheader("Substitution, not sanctions — and why the scoreboard is wrong")
st.caption(
    "Thematic research · 2026-07-21 · finding → mechanism → exposed entities →"
    " confidence → sources. **Not investment advice** — no buy/sell/target."
)

if d is not None:
    st.info(
        "**Thesis.** China's localization of chip-making tools is real and"
        " durable, but it is mostly **self-driven, not sanctions-driven**: US"
        f" export controls explain only ~{d.latest_suppression_pp:.1f}pp of the"
        f" {d.latest_ratio_actual:.0%} domestic share. Control effectiveness is"
        " **layer-specific** — durable where the product can't be redesigned"
        " around a rule (lithography tools; US exports"
        f" {d.cumulative_pct_effect:.0%} and staying down), porous where it can"
        " (chips; US sales bit, then recovered via compliant parts). The"
        " decisive variable is therefore one un-respinnable chokepoint —"
        " **domestic advanced lithography** — and the aggregate self-sufficiency"
        " ratio that dominates the debate is the wrong gauge for it."
    )

# ─────────────────────────────────────────────────────────────────────────────
# Summary — our variant view
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("### Summary — where we differ from consensus")
if d is not None:
    st.markdown(
        "- **Consensus** (Bernstein ~21%, and the headlines) reads a rising"
        " self-sufficiency ratio as proof that controls are either working or"
        " backfiring. We find the ratio is mostly **autonomous substitution**"
        " that would be happening regardless.\n"
        "- **We can split the number.** Of the"
        f" {d.latest_ratio_actual:.0%} domestic share,"
        f" ~{d.latest_suppression_pp:.1f}pp is US-import *suppression* and"
        f" ~{d.latest_ratio_counterfactual:.0%} is genuine domestic"
        " *substitution*. Nobody else publishes a counterfactual.\n"
        "- **The US-specific import collapse is real**"
        f" ({d.cumulative_pct_effect:.0%}, cycle-adjusted) — but the allied"
        " coalition is leaky and the US channel is nearly exhausted.\n"
        "- **At the chip layer the same controls barely stick** — US sales bit,"
        " then recovered as firms shipped export-compliant redesigns.\n"
        "- **Net:** the controls are a durable tax on US toolmakers, a temporary"
        " speed bump on Chinese compute, and near-irrelevant to the ratio"
        " everyone watches."
    )

# ─────────────────────────────────────────────────────────────────────────────
# 1 — The phenomenon
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("### 1 · The phenomenon: domestic share is rising")
if not ratio_full.empty:
    f1 = go.Figure()
    f1.add_scatter(x=ratio_full.quarter, y=ratio_full.ratio, mode="lines+markers",
                   line=dict(color="#1f77b4"), name="Domestic WFE share")
    f1.update_layout(title="China wafer-fab-equipment: domestic share of spending",
                     yaxis=dict(tickformat=".0%", title="ratio"), **PLOT)
    st.plotly_chart(f1, use_container_width=True)
    first, last = ratio_full.iloc[0], ratio_full.iloc[-1]
    st.markdown(
        f"Domestic toolmakers' share rose from **{first.ratio:.0%}**"
        f" ({first.quarter}) to **{last.ratio:.0%}** ({last.quarter}) — a slow,"
        " policy-driven substitution of foreign tools by domestic ones. But a"
        " rising ratio has three possible causes — domestic tools winning"
        " sockets, foreign supply being blocked, or the capex cycle — and the"
        " debate conflates them. The rest of this note separates them."
    )

# ─────────────────────────────────────────────────────────────────────────────
# 2 — It's substitution, not sanctions
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("### 2 · It's substitution, not sanctions")
if not cf.empty and d is not None:
    f2 = go.Figure()
    f2.add_scatter(x=cf.quarter, y=cf.ratio_counterfactual, mode="lines",
                   name="Counterfactual (US tracks allies)",
                   line=dict(color="#7f7f7f", dash="dash"))
    f2.add_scatter(x=cf.quarter, y=cf.ratio_actual, mode="lines+markers",
                   name="Actual ratio", line=dict(color="#1f77b4"),
                   fill="tonexty", fillcolor="rgba(214,39,40,0.15)")
    f2.update_layout(title="Actual vs counterfactual — the shaded gap is the controls",
                     yaxis=dict(tickformat=".0%", title="ratio"), **PLOT)
    st.plotly_chart(f2, use_container_width=True)
    st.markdown(
        "We estimate the causal effect of the export controls with a"
        " difference-in-differences that uses allied equipment exporters"
        " (EU/Japan/Korea/Singapore) as the counterfactual for what US exports"
        " would have done, differencing out the fab-capex cycle. **Absent the"
        f" controls, the ratio would be ~{d.latest_ratio_counterfactual:.0%}"
        f" instead of {d.latest_ratio_actual:.0%}** — the controls added"
        f" ~{d.latest_suppression_pp:.1f}pp; the other"
        f" ~{d.latest_ratio_counterfactual:.0%} is domestic substitution riding"
        " the capex cycle and the state Big Fund (¥344bn Phase III). The US"
        f" decline is dramatic in percentage terms ({d.cumulative_pct_effect:.0%})"
        " but small in ratio terms, because the US was already a small and"
        " shrinking share of China's tool imports. **Substitution does the"
        " heavy lifting.**"
    )

# ─────────────────────────────────────────────────────────────────────────────
# 3 — Two layers, opposite outcomes
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("### 3 · Two layers, opposite outcomes")
if not layers.empty:
    f3 = go.Figure()
    f3.add_scatter(x=layers.quarter, y=layers.equipment_ratio, mode="lines+markers",
                   name="Tools — domestic share (identified)", line=dict(color="#1f77b4"))
    f3.add_scatter(x=layers.quarter, y=layers.chip_domestic_share, mode="lines+markers",
                   name="Frontier chips — domestic share (proxy)",
                   line=dict(color="#d62728", dash="dash"))
    f3.update_layout(title="Tools localize; frontier chips lag",
                     yaxis=dict(tickformat=".0%", title="share", range=[0, 0.3]), **PLOT)
    st.plotly_chart(f3, use_container_width=True)

if not ches.empty and not chs.empty:
    c = chs.iloc[0]
    ches = ches.copy()
    ches["level"] = np.exp(ches.coef) - 1
    pre, post = ches[ches.is_pre], ches[~ches.is_pre]
    f4 = go.Figure()
    f4.add_scatter(x=pre.quarter, y=pre.level, mode="markers", name="pre-baseline",
                   marker=dict(color="#7f7f7f", size=8))
    f4.add_scatter(x=post.quarter, y=post.level, mode="lines+markers",
                   name="US chip exports vs allied path", line=dict(color="#d62728"))
    f4.add_hline(y=0, line_dash="dot", line_color="gray")
    f4.update_layout(title="Chip controls: they bit, then leaked",
                     yaxis=dict(tickformat=".0%", title="% deviation from allied path"),
                     **PLOT)
    st.plotly_chart(f4, use_container_width=True)

st.markdown(
    "China is localizing the **factory faster than the frontier product it"
    " makes**: domestic logic output roughly doubled, yet chip imports rose"
    " *faster* on AI demand, so the chip share barely moved while the equipment"
    " ratio surged. And the controls themselves behave **oppositely** across the"
    " two layers — durable for tools, transient for chips. The reason is"
    " mechanical: **a chip is a design that can be re-spun just under a"
    " performance threshold (H100 → A800/H800 → H20); a lithography tool has no"
    " compliant version.** Control bites where the product can't iterate."
)
st.warning(
    "**Read the chip layer as descriptive, not identified.** NVIDIA's China"
    " GPUs are fabbed in Taiwan, so they are not US-origin exports and barely"
    " appear in this US→China series; the recovery shown is mostly *unrestricted*"
    " lower-end US chips plus the cycle. Parallel trends also fails here — the"
    " equipment DiD in §2 is the cleanly identified estimate."
)

# ─────────────────────────────────────────────────────────────────────────────
# 4 — The worldview
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("### 4 · The worldview this builds to")
st.markdown(
    "- **Both debate camps overweight the controls.** The self-sufficiency"
    " ratio is mostly cycle plus slow structural drift; the controls move it a"
    " couple of points. \"Controls are choking China\" and \"controls backfired"
    " and accelerated indigenization\" both mis-attribute an autonomous trend.\n"
    "- **Control durability is layer-specific**, so leverage lives at the one"
    " chokepoint that can't be re-spun: the tools, not the chips.\n"
    "- **The whole contest reduces to a single race — domestic advanced"
    " lithography.** Crack it and the ceiling lifts: China could then make its"
    " own frontier chips and the chip controls become moot too. Fail, and the"
    " tool controls remain the binding constraint regardless of how many GPUs"
    " leak through.\n"
    "- **The aggregate ratio is the wrong scoreboard.** The strategically"
    " meaningful metric is frontier-node yield and domestic-EUV progress —"
    " which almost nobody tracks. That gap is the opportunity."
)

# ─────────────────────────────────────────────────────────────────────────────
# 5 — Risks to the thesis
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("### 5 · Risks to the thesis (audited against outside sources)")
st.markdown(
    "- **Measurement.** The import code (HS 8486) includes flat-panel-display"
    " tools, so the denominator is inflated and the true localization ratio is"
    " *higher* than shown — the level here is a lower bound.\n"
    "- **Identification.** Allies (Netherlands, Japan) adopted their own China"
    " controls from mid-2023, partially contaminating the control group; this"
    " biases the US effect toward zero, so the −78% is a *conservative* lower"
    " bound. It is robust across control-group variants (about −72% to −78%).\n"
    "- **Chip layer.** US-origin-only and Taiwan-blind, so it is descriptive,"
    " not identified (see §3 caveat).\n"
    "- **Small N.** Five supplier origins cap statistical significance; the case"
    " rests on effect *magnitude* and clean pre-trends, not a p-value."
)

# ─────────────────────────────────────────────────────────────────────────────
# 6 — What to watch
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("### 6 · What to watch")
st.markdown(
    "- **Allied-origin equipment imports** — the next substitution battleground."
    " The US channel is nearly exhausted (~$0.4bn/qtr and falling), so the next"
    " leg must displace Japanese/European/Korean tools.\n"
    "- **Domestic advanced lithography** (SMEE, Huawei-linked SiCarrier) — the"
    " ceiling variable; the single most consequential place a surprise could"
    " land.\n"
    "- **Coalition cohesion** — whether the allied leak widens or closes decides"
    " the ceiling more than US resolve does.\n"
    "- **Policy-headline reaction function** — a new control wave should move the"
    " ratio only ~1–2pp on this model; a materially larger jump is the"
    " information-rich surprise."
)

st.divider()
st.caption(
    "Pipeline: collectors → validated extraction → SQLite → deterministic"
    " analysis. Full method, limits and the external assumption audit in"
    " analysis/methodology.md · github.com/xiajason6-web/GeoMacro2 · research,"
    " not investment advice."
)
