# Point-in-time backtest & vintage harness

_Vintages are reconstructed from git history — the state of the flagship ratio at each nightly commit — so every measurement here is no-lookahead by construction (methodology v2 full-coverage rows only)._

## Revision analysis — how provisional is a fresh print?

| Quarter | Vintages | First print | Latest | Revision (pp) | Coverage change |
|---|---|---|---|---|---|
| 2023Q1 | 2 | 16.7% | 14.6% | -2.1 | yes |
| 2023Q2 | 2 | 17.4% | 13.5% | -4.0 | yes |
| 2023Q3 | 2 | 11.5% | 11.5% | +0.0 |  |
| 2023Q4 | 2 | 12.0% | 12.0% | +0.0 |  |
| 2024Q1 | 2 | 9.8% | 9.8% | +0.0 |  |
| 2024Q2 | 2 | 11.9% | 11.9% | +0.0 |  |
| 2024Q3 | 2 | 13.4% | 13.4% | +0.0 |  |
| 2024Q4 | 2 | 18.6% | 18.6% | +0.0 |  |
| 2025Q1 | 2 | 17.4% | 17.4% | +0.0 |  |
| 2025Q2 | 2 | 16.0% | 16.0% | +0.0 |  |
| 2025Q3 | 2 | 18.7% | 18.7% | +0.0 |  |
| 2025Q4 | 2 | 22.0% | 22.0% | +0.0 |  |
| 2026Q1 | 2 | 36.4% | 36.4% | +0.0 |  |

Across 13 quarters seen in >1 vintage, the mean absolute revision from first print to latest is **0.5pp**.
The largest revisions coincide with COVERAGE changes (e.g. 2023Q2: 17.4% → 13.5%, -4.0pp, when EU27/Korea/Singapore backfilled) — the clearest reason not to over-trust a reduced-coverage print. Full-coverage quarters have been stable so far.

## Nowcast backtest — earliest call vs realized

_No target quarter has both a stored nowcast AND a realized full-coverage value yet (the nowcast targets are still open quarters). This resolves as quarters complete — same discipline as the calls ledger._

_Harness, not a verdict: n is tiny by design this early. Point-in-time discipline (git-vintage, no lookahead) is the deliverable; it earns its keep as vintages accumulate. Research, not investment advice._