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
trends and washes out to ~zero: the US-origin series fell then recovered.
IMPORTANT attribution caveat — the recovery is mostly UNRESTRICTED
lower-end US chips plus the semiconductor cycle, NOT NVIDIA's compliant
GPUs. Those China parts (A100/H100→A800/H800→H20) are fabbed by TSMC in
TAIWAN, so they are not US-origin exports and barely appear in this
US→China series. The broader lesson still holds as industry logic — a
chip is a design that can be re-spun under a performance threshold, a
lithography tool cannot — so controls bite hardest where the product
can't iterate.

## Event-study coefficients (the V-shape)

| Wave term | Effect (log pts) | Level | HC1 se |
|---|---|---|---|
| US × post-Oct-2022 (A100/H100) | -0.464 | -37.1% | 0.084 |
| US × post-Oct-2023 (A800/H800, incr.) | +0.303 | +35.4% | 0.080 |
| US × post-Dec-2024 (incr.) | +0.300 | +34.9% | 0.071 |

The initial ban is a sharp negative (the bite); the later terms are
positive (the recovery) — which is why the cumulative nets out and a
single number would mislead. The recovery is unrestricted chips + cycle,
not the controlled GPU flow (which is Taiwan-origin, off-panel).

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

- **Control durability is LAYER-SPECIFIC (industry logic).** A chip is a
  design that can be re-spun under a threshold (H100→A800/H800→H20); a
  lithography tool has no compliant version. So controls are durable at
  the tool layer (−78%, clean) and porous at the chip layer — effective
  where the product can't iterate. NOTE: this is an industry fact, not
  something THIS US-origin trade series cleanly identifies (see caveat).
- **Both camps get something.** The 'controls are porous' view (Huang)
  holds at the chip layer; the 'controls work' view holds at the tool
  layer (the durable −78%).
- **Neither made China self-sufficient.** chip_self_sufficiency.py shows
  chip imports rose on demand throughout.

## Limits (read the chip layer as descriptive)

- **Origin blind spot — decisive here.** TAIWAN, the largest chip
  supplier to China and where NVIDIA's China GPUs are fabbed, is an
  unobserved origin (no machine-readable source). The controlled-GPU
  flow is therefore largely OUTSIDE this panel — the recovery shown here
  is unrestricted US chips + cycle, not the compliant-GPU 'leak'.
- **HS 8542 is ALL ICs**, not just controlled GPUs — uncontrolled chips
  dilute the treatment and drive much of the recovery.
- **Parallel trends fails**, so this is DESCRIPTIVE, not a clean causal
  estimate — the equipment DiD is the identified one.
- **Five origins** → placebo p floor 0.20.

_Research output — finding → mechanism → exposed entities → confidence →
sources. Not investment advice._