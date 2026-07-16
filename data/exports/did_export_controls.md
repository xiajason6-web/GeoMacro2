# Causal effect of US export controls on China's WFE import mix

A difference-in-differences that identifies the treatment effect of
the unilateral US export-control waves, using allied origins (EU27,
Japan, Korea, Singapore) as the control group and year-month fixed
effects to absorb the fab-capex demand cycle. Monthly panel of HS 8486
equipment exports to China, converted to USD through `fx_rates`.

## 1. The identified treatment effect (TWFE DiD)

`log(imports) = origin FE + month FE + b1·(US×post-Oct2023) + b2·(US×post-Dec2024)`

Month fixed effects absorb the common WFE demand cycle, so each
coefficient is the US deviation from the allied path after a wave.

| Treatment term | Effect (log pts) | Level effect | HC1 se | cluster se (5 origins) |
|---|---|---|---|---|
| US × post-Oct-2023 | -0.291 | -25.3% | 0.104 | 0.058 |
| US × post-Dec-2024 (incremental) | -0.767 | -53.6% | 0.147 | 0.054 |
| **Cumulative after Dec-2024** | **-1.058** | **-65.3%** | — | — |

US equipment exports to China ran **65% below**
the allied-implied path once both within-sample waves were in force —
after differencing out the demand cycle that hit every origin equally.
The Oct-2022 wave predates the panel and is folded into the baseline,
so this is a lower bound on the full control effect.

## 2. Parallel trends (event study)

US×quarter coefficients relative to 2023Q3 (balanced panel:
US, Japan, Korea, Singapore). Pre-baseline coefficients should be ~0.

| Quarter | US effect (log pts) | pre-baseline? |
|---|---|---|
| 2023Q1 | -0.054 | yes |
| 2023Q2 | -0.074 | yes |
| 2023Q3 | +0.000 |  |
| 2023Q4 | -0.104 |  |
| 2024Q1 | -0.305 |  |
| 2024Q2 | -0.337 |  |
| 2024Q3 | -0.387 |  |
| 2024Q4 | -0.610 |  |
| 2025Q1 | -0.601 |  |
| 2025Q2 | -0.856 |  |
| 2025Q3 | -1.217 |  |
| 2025Q4 | -1.555 |  |
| 2026Q1 | -1.638 |  |

Largest pre-baseline deviation: 0.074 log pts — small relative to the post-wave effects, consistent with parallel trends.

## 3. Inference, honestly (randomization across origins)

Five origins is too few clusters for asymptotic cluster-robust SEs, so
we reassign 'treatment' to each origin in turn and rank the real US
effect against that placebo distribution.

| Placebo-treated origin | Cumulative effect (log pts) |
|---|---|
| US ← actual | -1.058 |
| EU27 | -0.065 |
| Japan | +0.303 |
| Singapore | +0.402 |
| Korea | +0.428 |

Permutation p-value: **0.20** (share of origins that fell at
least as much as the US). With five origins the sharpest attainable p
is 0.20, which the US case reaches — the US is the single most
suppressed origin. The payoff here is the *magnitude* and the
counterfactual below, not a significance star; this is stated, not
hidden (cf. the vendor-lead null).

## 4. Payoff: counterfactual indigenization ratio

Rebuild US imports on the allied (Japan+Korea+Singapore) growth path
from 2023Q3 and recompute the flagship ratio. The gap is the
part of measured indigenization that is US-import **suppression** (a
denominator effect of the controls); the counterfactual level is
genuine domestic **substitution** (a numerator effect).

| Quarter | Actual ratio | Counterfactual ratio | Suppression (pp) |
|---|---|---|---|
| 2023Q3 | 11.5% | 11.5% | +0.0 |
| 2023Q4 | 12.0% | 11.9% | +0.1 |
| 2024Q1 | 9.8% | 9.5% | +0.3 |
| 2024Q2 | 11.9% | 11.6% | +0.3 |
| 2024Q3 | 13.4% | 12.9% | +0.5 |
| 2024Q4 | 18.6% | 17.8% | +0.9 |
| 2025Q1 | 17.4% | 16.6% | +0.8 |
| 2025Q2 | 16.0% | 15.0% | +1.0 |
| 2025Q3 | 18.7% | 17.2% | +1.4 |
| 2025Q4 | 22.0% | 20.4% | +1.6 |

By 2025Q4, of the 22.0% headline ratio,
**1.6pp** is attributable to suppressed US
imports and the remaining **20.4%** to
domestic substitution. Controls and substitution both move the number;
this splits them.

## 5. Ratio-level ITS (secondary, low power)

Interrupted time series on the ratio itself with the cycle as an
explicit control — the design the DiD exists to improve on, shown for
completeness. `logit(ratio) ~ log(cycle) + trend + step(Oct2023) +
step(Dec2024)`.

| Term | Coef | HC1 se |
|---|---|---|
| intercept | +9.240 | 13.395 |
| log_cycle | -0.487 | 0.578 |
| trend | +0.143 | 0.067 |
| step_Oct2023 | -0.235 | 0.195 |
| step_Dec2024 | -0.239 | 0.301 |

n = 10 quarters. Underpowered by construction —
the step signs are indicative; the DiD in §1 is the identified
estimate.

## Limits (falsifiers)

- **Rerouting.** Some US→Singapore flow is US firms shipping via
  Singapore fabs, which would understate the true US suppression and
  contaminate Singapore as a control. The counterfactual basket keeps
  Singapore; dropping it is a robustness check worth running.
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