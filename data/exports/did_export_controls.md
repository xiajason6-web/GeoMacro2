# Causal effect of US export controls on China's WFE import mix

A difference-in-differences that identifies the treatment effect of
the unilateral US export-control waves, using allied origins (EU27,
Japan, Korea, Singapore) as the control group and year-month fixed
effects to absorb the fab-capex demand cycle. Monthly panel of HS 8486
equipment exports to China, converted to USD through `fx_rates`.

## 1. The identified treatment effect (TWFE DiD)

`log(imports) = origin FE + month FE + b0·(US×post-Oct2022) + b1·(US×post-Oct2023) + b2·(US×post-Dec2024)`

Panel backfilled to 2021-01 so all three control waves are in-sample,
with a genuine pre-treatment window before the first. Month fixed
effects absorb the common WFE demand cycle, so each coefficient is the
US deviation from the allied path after a wave (coefficients are
incremental — each adds to the prior).

| Treatment term | Effect (log pts) | Level effect | HC1 se | cluster se (5 origins) |
|---|---|---|---|---|
| US × post-Oct-2022 | -0.360 | -30.2% | 0.095 | 0.216 |
| US × post-Oct-2023 (incremental) | -0.390 | -32.3% | 0.112 | 0.107 |
| US × post-Dec-2024 (incremental) | -0.769 | -53.6% | 0.149 | 0.068 |
| **Cumulative, all three waves** | **-1.519** | **-78.1%** | — | — |

US equipment exports to China ran **78% below**
the allied-implied path once all three waves were in force — after
differencing out the demand cycle that hit every origin equally. With
the panel now reaching a clean pre-Oct-2022 window, this is the FULL
measured control effect, no longer a lower bound.

## 2. Parallel trends (event study)

US×quarter coefficients relative to 2022Q2 (balanced panel:
US, Japan, Korea, Singapore). Pre-baseline coefficients should be ~0.

| Quarter | US effect (log pts) | pre-baseline? |
|---|---|---|
| 2021Q1 | -0.019 | yes |
| 2021Q2 | -0.097 | yes |
| 2021Q3 | +0.075 | yes |
| 2021Q4 | +0.004 | yes |
| 2022Q1 | -0.043 | yes |
| 2022Q2 | +0.000 |  |
| 2022Q3 | -0.141 |  |
| 2022Q4 | -0.214 |  |
| 2023Q1 | -0.269 |  |
| 2023Q2 | -0.289 |  |
| 2023Q3 | -0.215 |  |
| 2023Q4 | -0.320 |  |
| 2024Q1 | -0.520 |  |
| 2024Q2 | -0.553 |  |
| 2024Q3 | -0.602 |  |
| 2024Q4 | -0.825 |  |
| 2025Q1 | -0.817 |  |
| 2025Q2 | -1.071 |  |
| 2025Q3 | -1.433 |  |
| 2025Q4 | -1.770 |  |

Largest pre-baseline deviation: 0.097 log pts — small relative to the post-wave effects, consistent with parallel trends.

## 3. Inference, honestly (randomization across origins)

Five origins is too few clusters for asymptotic cluster-robust SEs, so
we reassign 'treatment' to each origin in turn and rank the real US
effect against that placebo distribution.

| Placebo-treated origin | Cumulative effect (log pts) |
|---|---|
| US ← actual | -1.519 |
| Korea | -0.307 |
| Japan | +0.243 |
| Singapore | +0.472 |
| EU27 | +1.178 |

Permutation p-value: **0.20** (share of origins that fell at
least as much as the US). With five origins the sharpest attainable p
is 0.20, which the US case reaches — the US is the single most
suppressed origin. The payoff here is the *magnitude* and the
counterfactual below, not a significance star; this is stated, not
hidden (cf. the vendor-lead null).

## 4. Payoff: counterfactual indigenization ratio

Rebuild US imports on the allied (Japan+Korea+Singapore) growth path
from 2022Q2 and recompute the flagship ratio. The gap is the
part of measured indigenization that is US-import **suppression** (a
denominator effect of the controls); the counterfactual level is
genuine domestic **substitution** (a numerator effect).

| Quarter | Actual ratio | Counterfactual ratio | Suppression (pp) |
|---|---|---|---|
| 2023Q1 | 14.6% | 13.8% | +0.8 |
| 2023Q2 | 13.5% | 12.9% | +0.6 |
| 2023Q3 | 11.5% | 11.1% | +0.5 |
| 2023Q4 | 12.0% | 11.4% | +0.6 |
| 2024Q1 | 9.8% | 9.1% | +0.8 |
| 2024Q2 | 11.9% | 11.1% | +0.8 |
| 2024Q3 | 13.4% | 12.4% | +1.0 |
| 2024Q4 | 18.6% | 17.1% | +1.6 |
| 2025Q1 | 17.4% | 15.9% | +1.5 |
| 2025Q2 | 16.0% | 14.4% | +1.7 |
| 2025Q3 | 18.7% | 16.5% | +2.1 |
| 2025Q4 | 22.0% | 19.7% | +2.3 |

By 2025Q4, of the 22.0% headline ratio,
**2.3pp** is attributable to suppressed US
imports and the remaining **19.7%** to
domestic substitution. Controls and substitution both move the number;
this splits them.

## 5. Ratio-level ITS (secondary, low power)

Interrupted time series on the ratio itself with the cycle as an
explicit control — the design the DiD exists to improve on, shown for
completeness. `logit(ratio) ~ log(cycle) + trend + step(Oct2023) +
step(Dec2024)`.

| Term | Coef | HC1 se |
|---|---|---|
| intercept | +16.792 | 6.816 |
| log_cycle | -0.824 | 0.301 |
| trend | +0.148 | 0.061 |
| step_Oct2023 | -0.242 | 0.192 |
| step_Dec2024 | -0.274 | 0.248 |

n = 12 quarters. Underpowered by construction —
the step signs are indicative; the DiD in §1 is the identified
estimate.

## 6. Robustness — drop Singapore (rerouting caveat)

Re-run with Singapore removed from BOTH the control group and the
counterfactual basket, since some US→Singapore flow is US firms
shipping via Singapore fabs (which would contaminate Singapore as a
control). The actual ratio is unchanged; only the control group and
the US counterfactual path move.

| | Full (5 origins) | Ex-Singapore |
|---|---|---|
| Cumulative US effect (log pts) | -1.519 | -1.497 |
| Cumulative level effect | -78.1% | -77.6% |
| Suppression at 2025Q4 (pp) | +2.3 | +2.0 |

The headline is robust to dropping Singapore — the estimate barely moves. Dashboard exposes this as a toggle (did_*_ex_sg.csv).

## Limits (falsifiers)

- **Rerouting.** Some US→Singapore flow is US firms shipping via
  Singapore fabs, which would understate the true US suppression and
  contaminate Singapore as a control. Dropping Singapore entirely (§6)
  barely moves the estimate, so this contamination is not load-bearing.
- **Allied tightening.** The Netherlands/Japan later adopted partial
  controls, making the control group imperfectly untreated and biasing
  the estimate toward zero — so the true US effect is if anything
  larger.
- **HS 8486 scope.** Includes flat-panel tools and parts; Taiwan origin
  is unobserved (permanent `missing_origins`). Same caveats as the
  flagship ratio.
- **Five origins.** Formal significance is limited; the case rests on
  magnitude, the parallel-trends event study, and the placebo ranking.

_Research output — finding → mechanism → exposed entities → confidence →
sources. Not investment advice; no buy/sell/short/price-target._