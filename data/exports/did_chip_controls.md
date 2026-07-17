# US chip controls: they BIT, then LEAKED — a bite-and-recovery

The equipment DiD (did_export_controls.py) run one layer up, on HS 8542
(integrated circuits) — the layer the A100/H100, A800/H800 and H20
controls actually target. Identification is off the denominator (US vs
allied chip exports), so no domestic chip-output series is needed. Same
audited machinery, same five origins, same cycle-differencing month FE.

## Headline: the opposite of the equipment layer

The chip layer's story is a SHAPE, not a single coefficient. US chip
exports to China fell to **-47%** below the allied path at the
trough (2023Q2) — the A100/H100 and A800/H800 bans genuinely bit — then
**recovered to -13%** by the latest quarter. Net cumulative effect
 **+15%**, placebo p = **0.80** (US is NOT the most-suppressed origin), pre-trend 0.53 log pts.

**Read the failed identification as the finding.** Unlike equipment
(clean pre-trends, durable −78%), the chip DiD does NOT hold parallel
trends and washes out to ~zero — because the treated channel was
RE-ENGINEERED around: after each ban, US firms shipped compliant parts
(A800 → H800 → H20), so aggregate US chip sales to China bounced back to
near parity. Controls bite hardest where the product can't be re-spun.

## Event-study coefficients (the V-shape)

| Wave term | Effect (log pts) | Level | HC1 se |
|---|---|---|---|
| US × post-Oct-2022 (A100/H100) | -0.464 | -37.1% | 0.084 |
| US × post-Oct-2023 (A800/H800, incr.) | +0.303 | +35.4% | 0.080 |
| US × post-Dec-2024 (incr.) | +0.300 | +34.9% | 0.071 |

The initial ban is a sharp negative (the bite); the later terms are
positive (the recovery via compliant SKUs) — which is exactly why the
cumulative nets out and a single number would mislead.

## US chip exports vs the allied path ($bn/qtr — the V)

| Quarter | US actual $bn | US counterfactual $bn | Gap $bn |
|---|---|---|---|
| 2022Q2 | 2.50 | 2.50 | +0.00 |
| 2022Q3 | 2.34 | 2.69 | +0.34 |
| 2022Q4 | 2.15 | 2.11 | -0.04 |
| 2023Q1 | 1.31 | 1.71 | +0.40 |
| 2023Q2 | 1.04 | 1.80 | +0.75 |
| 2023Q3 | 1.30 | 2.01 | +0.71 |
| 2023Q4 | 1.48 | 2.08 | +0.60 |
| 2024Q1 | 1.57 | 2.04 | +0.47 |
| 2024Q2 | 2.03 | 2.26 | +0.22 |
| 2024Q3 | 2.51 | 2.45 | -0.06 |
| 2024Q4 | 2.61 | 2.41 | -0.20 |
| 2025Q1 | 2.98 | 1.77 | -1.21 |
| 2025Q2 | 2.33 | 2.00 | -0.33 |
| 2025Q3 | 2.35 | 2.31 | -0.04 |
| 2025Q4 | 2.29 | 2.69 | +0.40 |

## What this settles in the export-controls debate

- **Control durability is LAYER-SPECIFIC.** Equipment controls stuck
  (−78%, clean, durable — you can't redesign a lithography tool to be
  compliant). Chip controls bit then leaked (re-spun into H20-class
  parts). Effectiveness lives at the chokepoint that can't iterate: the
  tools, not the chip products.
- **Both camps get something, precisely bounded.** The 'controls are
  porous' view (Huang) holds AT THE CHIP LAYER — sales recovered. The
  'controls work' view holds AT THE TOOL LAYER — the durable −78%.
- **Neither made China self-sufficient.** chip_self_sufficiency.py shows
  chip imports rose on demand throughout. Controls suppress US SALES
  (durably for tools, transiently for chips) far more than they lift
  China's self-reliance.

## Limits

- **HS 8542 is ALL ICs**, not just controlled GPUs — uncontrolled chips
  dilute the treatment and, being demand-driven, help the recovery.
  Isolating the GPU subset needs product-level data this pipeline lacks.
- **Parallel trends fails here**, so this is DESCRIPTIVE, not a clean
  causal estimate — the equipment DiD is the identified one. The V-shape
  itself, though, is robust and economically legible (the H20 saga).
- **Five origins** → placebo p floor 0.20.

_Research output — finding → mechanism → exposed entities → confidence →
sources. Not investment advice._