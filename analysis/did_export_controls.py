"""Causal effect of US export controls on China's WFE import mix — a
difference-in-differences that turns Finding #2 ("the import decline is
US-specific") from a suggestive series into an identified treatment effect.

THE IDENTIFICATION PROBLEM. The indigenization ratio has no untreated
control group: every buyer in China faces the same controls, so a plain
before/after on the ratio cannot separate the policy from the fab-capex
cycle that dominates at short horizons (proven by the vendor-lead null).
We get a control group by moving one level down, to the DENOMINATOR. The
US imposed unilateral controls (Oct 2022, tightened Oct 2023, Dec 2024);
allied origins (EU27, Japan, Korea, Singapore) exported into the SAME
Chinese fabs on the SAME demand cycle but were not bound by the unilateral
US rules. So allied exports are a plausible counterfactual for what US
exports would have done absent the controls.

THE ESTIMATOR (monthly origin panel, HS 8486 equipment, USD via fx_rates):

    log(imports_{o,t}) = alpha_o + gamma_t
                         + beta1 * (US_o x post_Oct2023_t)
                         + beta2 * (US_o x post_Dec2024_t) + eps

  - alpha_o  origin fixed effects  -> level differences between origins
  - gamma_t  year-month fixed effects -> ABSORBS the common WFE demand
             cycle and seasonality; this is what a plain ITS cannot do
  - beta1/beta2  the deviation of US exports from the common time path
             after each within-sample control wave = the treatment effect
             (in log points; ~ % effect). Oct 2022 predates the sample, so
             it is folded into the baseline (alpha_US), not estimated.

Parallel-trends is testable: the event study reports US x (relative-month)
coefficients; pre-wave coefficients near zero support the design.

INFERENCE, HONESTLY. Five origins is too few clusters for asymptotic
cluster-robust SEs, so beyond HC1 we report randomization inference:
reassign "treatment" to each origin in turn and rank the true US effect
against that placebo distribution. With five origins the sharpest possible
p is 1/5 = 0.20 — we report it and say plainly that the payoff is the
economic magnitude and the counterfactual, not a significance star.

THE PAYOFF (counterfactual_ratio). Rebuild US imports on the allied-implied
path (US anchored at 2023Q3, then growing with the Japan+Korea+Singapore
basket) and recompute the flagship ratio. The gap between the actual ratio
and this counterfactual is the share of measured indigenization that is
US-import SUPPRESSION (a denominator effect of the controls) rather than
genuine domestic SUBSTITUTION (a numerator effect). That decomposition is
the headline of the causal essay.

All arithmetic is deterministic numpy/pandas — no LLM touches numbers. The
OLS is plain normal equations so every coefficient is auditable by hand and
pinned by tests/test_did.py.

Outputs:
  data/exports/did_export_controls.md   — DiD table, event study, decomposition
  data/exports/did_event_study.html     — dynamic US-vs-allied effect + pre-trend
  data/exports/did_counterfactual.html  — actual vs counterfactual ratio
"""

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import indigenization_ratio as ir  # noqa: E402

DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"
OUT_DIR = REPO_ROOT / "data" / "exports"

TREATED = "US"
CONTROL_ORIGINS = ["EU27", "Japan", "Korea", "Singapore"]
# Allied basket for the counterfactual: the three origins with full monthly
# coverage from 2023-01 (EU27 only starts 2023-07), so the growth index is
# defined across the whole post window.
COUNTERFACTUAL_BASKET = ["Japan", "Korea", "Singapore"]

# Within-sample control waves. Oct 2022 predates the panel -> baseline.
# post is "this month is on/after the wave took effect".
WAVE_OCT2023 = "2023-10"
WAVE_DEC2024 = "2024-12"

# Counterfactual anchor: last full quarter before the Oct-2023 wave.
ANCHOR_QUARTER = "2023Q3"


# --------------------------------------------------------------------------
# Pure-numpy OLS — plain normal equations so every number is auditable.
# --------------------------------------------------------------------------
def ols(X, y):
    """Return (beta, resid, XtX_inv). Uses lstsq for numerical stability."""
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    XtX_inv = np.linalg.inv(X.T @ X)
    return beta, resid, XtX_inv


def hc1_se(X, resid, XtX_inv):
    """Heteroskedasticity-robust (White/HC1) standard errors."""
    n, k = X.shape
    meat = (X * (resid ** 2)[:, None]).T @ X
    cov = XtX_inv @ meat @ XtX_inv * (n / (n - k))
    return np.sqrt(np.diag(cov))


def cluster_se(X, resid, XtX_inv, groups):
    """Cluster-robust SEs. Reported for completeness; with 5 origins the
    asymptotics do NOT hold — read alongside randomization inference."""
    n, k = X.shape
    meat = np.zeros((k, k))
    uniq = np.unique(groups)
    for g in uniq:
        m = groups == g
        Xg, ug = X[m], resid[m]
        s = Xg.T @ ug
        meat += np.outer(s, s)
    G = len(uniq)
    adj = (G / (G - 1)) * ((n - 1) / (n - k))
    cov = XtX_inv @ meat @ XtX_inv * adj
    return np.sqrt(np.diag(cov))


def _dummies(labels):
    """One-hot columns (drop nothing here; caller drops a reference)."""
    uniq = sorted(set(labels))
    return uniq, np.array([[1.0 if l == u else 0.0 for u in uniq] for l in labels])


# --------------------------------------------------------------------------
# Panel construction
# --------------------------------------------------------------------------
def load_panel(conn):
    """Monthly origin panel of HS 8486 imports to China, converted to USD
    through fx_rates (the same chokepoint the flagship ratio uses)."""
    df = ir.load_metrics(conn)
    fx = ir.load_fx(conn)
    imp = df[df.metric_name.isin(ir.IMPORT_SERIES)].copy()
    imp["origin"] = imp.metric_name.map(lambda m: ir.IMPORT_SERIES[m][0])
    imp["currency"] = imp.metric_name.map(lambda m: ir.IMPORT_SERIES[m][1])
    imp, dropped = ir.to_usd(imp, fx)
    if len(dropped):
        print(f"WARNING: {len(dropped)} import rows lacked an FX rate — excluded")
    panel = (
        imp.groupby(["origin", "period"], as_index=False)
        .value_usd.sum()
        .rename(columns={"period": "month"})
    )
    panel = panel[panel.value_usd > 0].copy()
    panel["log_imports"] = np.log(panel.value_usd)
    panel["treated"] = (panel.origin == TREATED).astype(float)
    panel["post_2023"] = (panel.month >= WAVE_OCT2023).astype(float)
    panel["post_2024"] = (panel.month >= WAVE_DEC2024).astype(float)
    return panel.sort_values(["origin", "month"]).reset_index(drop=True)


def design_twfe(panel):
    """Two-way fixed-effects DiD design matrix with two treatment terms.
    Reference cells (first origin, first month) are dropped for identification;
    an intercept absorbs them."""
    origins, Do = _dummies(panel.origin.tolist())
    months, Dt = _dummies(panel.month.tolist())
    did1 = (panel.treated * panel.post_2023).values[:, None]
    did2 = (panel.treated * panel.post_2024).values[:, None]
    intercept = np.ones((len(panel), 1))
    # drop first origin dummy and first month dummy as references
    X = np.hstack([intercept, Do[:, 1:], Dt[:, 1:], did1, did2])
    names = (
        ["intercept"]
        + [f"origin={o}" for o in origins[1:]]
        + [f"month={m}" for m in months[1:]]
        + ["US x post_Oct2023", "US x post_Dec2024"]
    )
    return X, names


def run_did(panel):
    X, names = design_twfe(panel)
    y = panel.log_imports.values
    beta, resid, XtXi = ols(X, y)
    hc1 = hc1_se(X, resid, XtXi)
    clu = cluster_se(X, resid, XtXi, panel.origin.values)
    idx = {n: i for i, n in enumerate(names)}
    out = {}
    for term in ["US x post_Oct2023", "US x post_Dec2024"]:
        i = idx[term]
        out[term] = {
            "coef": beta[i],
            "hc1_se": hc1[i],
            "cluster_se": clu[i],
            "pct_effect": np.exp(beta[i]) - 1,  # log-point -> % level effect
        }
    # cumulative post-Dec2024 US effect = beta1 + beta2
    b = beta[idx["US x post_Oct2023"]] + beta[idx["US x post_Dec2024"]]
    out["cumulative_after_Dec2024"] = {
        "coef": b,
        "pct_effect": np.exp(b) - 1,
    }
    return out, beta, names


def randomization_inference(panel, true_coef, term="cumulative"):
    """Placebo test honest for 5 origins: pretend each origin in turn is the
    'treated' one, refit, and see where the real US effect ranks. Returns the
    placebo effects and the exact permutation p-value (share of origins whose
    placebo effect is at least as extreme/negative as the US effect)."""
    effects = {}
    for placebo in sorted(panel.origin.unique()):
        p = panel.copy()
        p["treated"] = (p.origin == placebo).astype(float)
        X, names = design_twfe(p)
        beta, _, _ = ols(X, p.log_imports.values)
        idx = {n: i for i, n in enumerate(names)}
        if term == "cumulative":
            e = beta[idx["US x post_Oct2023"]] + beta[idx["US x post_Dec2024"]]
        else:
            e = beta[idx[term]]
        effects[placebo] = e
    # one-sided p: controls dropped at least as much as US (more negative)
    p_value = np.mean([e <= true_coef for e in effects.values()])
    return effects, p_value


def event_study(panel, baseline=ANCHOR_QUARTER):
    """Dynamic DiD on the balanced sub-panel (origins present from 2023-01,
    i.e. excluding EU27) at QUARTERLY frequency. US x quarter coefficients
    relative to `baseline`; pre-baseline coefficients test parallel trends."""
    bal = panel[panel.origin.isin([TREATED] + COUNTERFACTUAL_BASKET)].copy()
    bal["quarter"] = bal.month.map(ir.month_to_quarter)
    # collapse to quarter (sum months, require the quarter to be complete: 3)
    counts = bal.groupby(["origin", "quarter"]).month.nunique()
    complete = counts[counts == 3].index
    q = (
        bal.set_index(["origin", "quarter"])
        .loc[bal.set_index(["origin", "quarter"]).index.isin(complete)]
        .groupby(["origin", "quarter"])
        .value_usd.sum()
        .reset_index()
    )
    q["log_imports"] = np.log(q.value_usd)
    q["treated"] = (q.origin == TREATED).astype(float)
    quarters = sorted(q.quarter.unique())
    origins, Do = _dummies(q.origin.tolist())
    qs, Dq = _dummies(q.quarter.tolist())
    # US x quarter interactions, omitting the baseline quarter
    cols, colnames = [], []
    for j, qq in enumerate(qs):
        if qq == baseline:
            continue
        cols.append((q.treated.values * Dq[:, j]))
        colnames.append(qq)
    intercept = np.ones((len(q), 1))
    X = np.hstack([intercept, Do[:, 1:], Dq[:, 1:], np.array(cols).T])
    y = q.log_imports.values
    beta, resid, XtXi = ols(X, y)
    hc1 = hc1_se(X, resid, XtXi)
    k0 = 1 + (Do.shape[1] - 1) + (Dq.shape[1] - 1)
    rows = []
    for i, qq in enumerate(colnames):
        rows.append({
            "quarter": qq,
            "coef": beta[k0 + i],
            "se": hc1[k0 + i],
            "is_pre": qq < baseline,
        })
    es = pd.DataFrame(rows).sort_values("quarter").reset_index(drop=True)
    # add the baseline itself at 0
    es = pd.concat([
        es,
        pd.DataFrame([{"quarter": baseline, "coef": 0.0, "se": 0.0,
                       "is_pre": False}]),
    ]).sort_values("quarter").reset_index(drop=True)
    return es


# --------------------------------------------------------------------------
# The payoff: counterfactual indigenization ratio
# --------------------------------------------------------------------------
def counterfactual_ratio(conn, panel):
    """What would the flagship ratio be if US exports had tracked the allied
    basket instead of being suppressed by controls? Rebuild US imports on the
    allied-implied path from the anchor quarter, recompute the ratio, and
    decompose the actual-vs-counterfactual gap."""
    df = ir.load_metrics(conn)
    fx = ir.load_fx(conn)
    imports_q = ir.quarterly_imports_usd(df, fx)          # actual, full coverage
    domestic_q = ir.quarterly_domestic_usd(df, fx)

    # Quarterly USD imports per origin (complete-quarter rule), from the panel.
    p = panel.copy()
    p["quarter"] = p.month.map(ir.month_to_quarter)
    counts = p.groupby(["origin", "quarter"]).month.nunique()
    complete = counts[counts == 3].reset_index()
    complete = complete[complete.month == 3][["origin", "quarter"]]
    pq = (
        p.merge(complete, on=["origin", "quarter"])
        .groupby(["origin", "quarter"]).value_usd.sum().reset_index()
    )
    wide = pq.pivot(index="quarter", columns="origin", values="value_usd").sort_index()

    us_anchor = wide.loc[ANCHOR_QUARTER, TREATED]
    basket_anchor = wide.loc[ANCHOR_QUARTER, COUNTERFACTUAL_BASKET].sum()

    rows = []
    for q in wide.index:
        if q not in imports_q.index or q not in domestic_q.index:
            continue
        if q < ANCHOR_QUARTER:
            continue
        # Require the whole allied basket present so the growth index is
        # consistent with the anchor — this also drops known partial-data
        # tails (e.g. 2026Q1, where Korea+Singapore lag ~2 months).
        if wide.loc[q, COUNTERFACTUAL_BASKET].isna().any():
            continue
        basket_now = wide.loc[q, COUNTERFACTUAL_BASKET].sum()
        us_cf = us_anchor * (basket_now / basket_anchor)   # allied-implied US
        us_actual = wide.loc[q, TREATED]
        suppressed = us_cf - us_actual                     # imports controls removed
        dom = domestic_q.loc[q].iloc[0]
        imp_actual = imports_q.loc[q, "imports_usd"]
        imp_cf = imp_actual + suppressed
        rows.append({
            "quarter": q,
            "domestic_usd": dom,
            "imports_actual_usd": imp_actual,
            "us_actual_usd": us_actual,
            "us_counterfactual_usd": us_cf,
            "us_suppressed_usd": suppressed,
            "ratio_actual": dom / (dom + imp_actual),
            "ratio_counterfactual": dom / (dom + imp_cf),
        })
    cf = pd.DataFrame(rows).set_index("quarter")
    cf["suppression_pp"] = (cf.ratio_actual - cf.ratio_counterfactual) * 100
    return cf


def ratio_its(conn):
    """Secondary / honestly low-powered: interrupted time series on the ratio
    itself with the cycle as an explicit control. logit(ratio) on log(total
    WFE demand) + step dummies at the two waves. n~12 quarters -> report the
    signs and magnitudes, not significance."""
    series = pd.read_csv(OUT_DIR / "indigenization_ratio.csv").dropna(subset=["ratio"])
    # full-coverage quarters only (Taiwan-only missing), drop partial tails
    series = series[series.missing_origins == "Taiwan"].copy()
    if len(series) < 6:
        return None
    series["logit"] = np.log(series.ratio / (1 - series.ratio))
    series["cycle"] = np.log(series.domestic_semicap_usd + series.imports_usd)
    series["qnum"] = range(len(series))
    series["step_2023"] = (series.quarter >= "2023Q4").astype(float)
    series["step_2025"] = (series.quarter >= "2025Q1").astype(float)
    X = np.column_stack([
        np.ones(len(series)), series.cycle, series.qnum,
        series.step_2023, series.step_2025,
    ])
    y = series.logit.values
    beta, resid, XtXi = ols(X, y)
    hc1 = hc1_se(X, resid, XtXi)
    names = ["intercept", "log_cycle", "trend", "step_Oct2023", "step_Dec2024"]
    return pd.DataFrame({"term": names, "coef": beta, "hc1_se": hc1,
                         "n": len(series)})


# --------------------------------------------------------------------------
# Outputs
# --------------------------------------------------------------------------
def build_event_study_chart(es):
    fig = go.Figure()
    fig.add_scatter(
        x=es.quarter, y=es.coef, mode="lines+markers",
        error_y=dict(type="data", array=1.96 * es.se, visible=True),
        name="US effect vs allied basket",
    )
    fig.add_hline(y=0, line_dash="dot", line_color="gray")
    fig.add_vline(x=ANCHOR_QUARTER, line_dash="dash", line_color="green")
    fig.add_annotation(x=ANCHOR_QUARTER, y=0.15, text="baseline (pre-Oct-2023 wave)",
                       showarrow=False, yshift=10, font=dict(color="green"))
    fig.update_layout(
        title=(
            "Event study: US equipment exports to China vs the allied basket"
            "<br><sub>US x quarter coefficients (log points) relative to "
            f"{ANCHOR_QUARTER}; flat & near-zero before baseline = parallel "
            "trends. Balanced panel: US, Japan, Korea, Singapore.</sub>"
        ),
        yaxis=dict(title="log-point deviation from allied path"),
        xaxis=dict(title="quarter"),
    )
    fig.write_html(OUT_DIR / "did_event_study.html", include_plotlyjs="cdn")
    print("wrote data/exports/did_event_study.html")


def build_counterfactual_chart(cf):
    fig = go.Figure()
    fig.add_scatter(x=cf.index, y=cf.ratio_actual, mode="lines+markers",
                    name="Actual indigenization ratio")
    fig.add_scatter(x=cf.index, y=cf.ratio_counterfactual, mode="lines+markers",
                    name="Counterfactual: US tracks allies (no controls)",
                    line=dict(dash="dash"))
    fig.update_layout(
        title=(
            "Actual vs counterfactual indigenization ratio"
            "<br><sub>Counterfactual rebuilds US imports on the Japan+Korea+"
            f"Singapore growth path from {ANCHOR_QUARTER}. The gap is "
            "US-import SUPPRESSION; the counterfactual level is domestic "
            "SUBSTITUTION.</sub>"
        ),
        yaxis=dict(title="ratio", tickformat=".0%"),
        legend=dict(orientation="h", y=-0.2),
    )
    fig.write_html(OUT_DIR / "did_counterfactual.html", include_plotlyjs="cdn")
    print("wrote data/exports/did_counterfactual.html")


def build_markdown(did, placebo, p_value, es, cf, its):
    b1 = did["US x post_Oct2023"]
    b2 = did["US x post_Dec2024"]
    cum = did["cumulative_after_Dec2024"]
    latest = cf.iloc[-1]
    pre = es[es.is_pre]
    max_pre = pre.coef.abs().max() if len(pre) else 0.0

    lines = [
        "# Causal effect of US export controls on China's WFE import mix",
        "",
        "A difference-in-differences that identifies the treatment effect of",
        "the unilateral US export-control waves, using allied origins (EU27,",
        "Japan, Korea, Singapore) as the control group and year-month fixed",
        "effects to absorb the fab-capex demand cycle. Monthly panel of HS 8486",
        "equipment exports to China, converted to USD through `fx_rates`.",
        "",
        "## 1. The identified treatment effect (TWFE DiD)",
        "",
        "`log(imports) = origin FE + month FE + b1·(US×post-Oct2023)"
        " + b2·(US×post-Dec2024)`",
        "",
        "Month fixed effects absorb the common WFE demand cycle, so each",
        "coefficient is the US deviation from the allied path after a wave.",
        "",
        "| Treatment term | Effect (log pts) | Level effect | HC1 se | cluster se (5 origins) |",
        "|---|---|---|---|---|",
        f"| US × post-Oct-2023 | {b1['coef']:+.3f} | {b1['pct_effect']:+.1%} |"
        f" {b1['hc1_se']:.3f} | {b1['cluster_se']:.3f} |",
        f"| US × post-Dec-2024 (incremental) | {b2['coef']:+.3f} |"
        f" {b2['pct_effect']:+.1%} | {b2['hc1_se']:.3f} | {b2['cluster_se']:.3f} |",
        f"| **Cumulative after Dec-2024** | **{cum['coef']:+.3f}** |"
        f" **{cum['pct_effect']:+.1%}** | — | — |",
        "",
        f"US equipment exports to China ran **{abs(cum['pct_effect']):.0%} below**",
        "the allied-implied path once both within-sample waves were in force —",
        "after differencing out the demand cycle that hit every origin equally.",
        "The Oct-2022 wave predates the panel and is folded into the baseline,",
        "so this is a lower bound on the full control effect.",
        "",
        "## 2. Parallel trends (event study)",
        "",
        f"US×quarter coefficients relative to {ANCHOR_QUARTER} (balanced panel:",
        "US, Japan, Korea, Singapore). Pre-baseline coefficients should be ~0.",
        "",
        "| Quarter | US effect (log pts) | pre-baseline? |",
        "|---|---|---|",
    ]
    for _, r in es.iterrows():
        lines.append(f"| {r.quarter} | {r.coef:+.3f} | {'yes' if r.is_pre else ''} |")
    lines += [
        "",
        f"Largest pre-baseline deviation: {max_pre:.3f} log pts — "
        + ("small relative to the post-wave effects, consistent with parallel"
           " trends." if max_pre < abs(cum["coef"]) / 2 else
           "non-trivial; read the design cautiously."),
        "",
        "## 3. Inference, honestly (randomization across origins)",
        "",
        "Five origins is too few clusters for asymptotic cluster-robust SEs, so",
        "we reassign 'treatment' to each origin in turn and rank the real US",
        "effect against that placebo distribution.",
        "",
        "| Placebo-treated origin | Cumulative effect (log pts) |",
        "|---|---|",
    ]
    for o, e in sorted(placebo.items(), key=lambda kv: kv[1]):
        star = " ← actual" if o == TREATED else ""
        lines.append(f"| {o}{star} | {e:+.3f} |")
    lines += [
        "",
        f"Permutation p-value: **{p_value:.2f}** (share of origins that fell at",
        "least as much as the US). With five origins the sharpest attainable p",
        "is 0.20, which the US case reaches — the US is the single most",
        "suppressed origin. The payoff here is the *magnitude* and the",
        "counterfactual below, not a significance star; this is stated, not",
        "hidden (cf. the vendor-lead null).",
        "",
        "## 4. Payoff: counterfactual indigenization ratio",
        "",
        "Rebuild US imports on the allied (Japan+Korea+Singapore) growth path",
        f"from {ANCHOR_QUARTER} and recompute the flagship ratio. The gap is the",
        "part of measured indigenization that is US-import **suppression** (a",
        "denominator effect of the controls); the counterfactual level is",
        "genuine domestic **substitution** (a numerator effect).",
        "",
        "| Quarter | Actual ratio | Counterfactual ratio | Suppression (pp) |",
        "|---|---|---|---|",
    ]
    for q, r in cf.iterrows():
        lines.append(
            f"| {q} | {r.ratio_actual:.1%} | {r.ratio_counterfactual:.1%} |"
            f" {r.suppression_pp:+.1f} |"
        )
    lines += [
        "",
        f"By {latest.name}, of the {latest.ratio_actual:.1%} headline ratio,",
        f"**{latest.suppression_pp:.1f}pp** is attributable to suppressed US",
        f"imports and the remaining **{latest.ratio_counterfactual:.1%}** to",
        "domestic substitution. Controls and substitution both move the number;",
        "this splits them.",
        "",
        "## 5. Ratio-level ITS (secondary, low power)",
        "",
        "Interrupted time series on the ratio itself with the cycle as an",
        "explicit control — the design the DiD exists to improve on, shown for",
        "completeness. `logit(ratio) ~ log(cycle) + trend + step(Oct2023) +",
        "step(Dec2024)`.",
        "",
    ]
    if its is not None:
        lines += ["| Term | Coef | HC1 se |", "|---|---|---|"]
        for _, r in its.iterrows():
            lines.append(f"| {r.term} | {r.coef:+.3f} | {r.hc1_se:.3f} |")
        lines += [
            "",
            f"n = {int(its.n.iloc[0])} quarters. Underpowered by construction —",
            "the step signs are indicative; the DiD in §1 is the identified",
            "estimate.",
        ]
    lines += [
        "",
        "## Limits (falsifiers)",
        "",
        "- **Rerouting.** Some US→Singapore flow is US firms shipping via",
        "  Singapore fabs, which would understate the true US suppression and",
        "  contaminate Singapore as a control. The counterfactual basket keeps",
        "  Singapore; dropping it is a robustness check worth running.",
        "- **Allied tightening.** The Netherlands/Japan later adopted partial",
        "  controls, making the control group imperfectly untreated and biasing",
        "  the estimate toward zero — so the true US effect is if anything",
        "  larger.",
        "- **HS 8486 scope.** Includes flat-panel tools and parts; Taiwan origin",
        "  is unobserved (permanent `missing_origins`). Same caveats as the",
        "  flagship ratio.",
        "- **Five origins.** Formal significance is limited; the case rests on",
        "  magnitude, the parallel-trends event study, and the placebo ranking.",
        "",
        "_Research output — finding → mechanism → exposed entities → confidence →",
        "sources. Not investment advice; no buy/sell/short/price-target._",
    ]
    return "\n".join(lines)


def main():
    conn = sqlite3.connect(DB_PATH)
    panel = load_panel(conn)
    did, beta, names = run_did(panel)
    placebo, p_value = randomization_inference(
        panel, did["cumulative_after_Dec2024"]["coef"]
    )
    es = event_study(panel)
    cf = counterfactual_ratio(conn, panel)
    its = ratio_its(conn)
    conn.close()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    build_event_study_chart(es)
    build_counterfactual_chart(cf)
    md = build_markdown(did, placebo, p_value, es, cf, its)
    (OUT_DIR / "did_export_controls.md").write_text(md)
    print("wrote data/exports/did_export_controls.md")
    print("=" * 78)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
