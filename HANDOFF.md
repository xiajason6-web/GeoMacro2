# HANDOFF — China Tech Flows tracker (migration note)

Self-contained state so a fresh session (or a new person) can pick up cold.
Last updated end of the session that built the trade layer + analytical
findings + book synthesis.

## What this is

A boring, auditable pipeline that measures how fast China is localizing
wafer-fab equipment (WFE), from primary sources, and turns it into research
outputs. It is thematic global-macro research made quantitatively rigorous.
Framing rule (non-negotiable): outputs are research — finding → mechanism →
exposed entities → confidence → sources. NEVER buy/sell/short/price-target.

## Where everything lives

- Local repo: `/Users/jasonxia/tracker` (git). Python 3.9 venv at `.venv`.
  Run things as `.venv/bin/python ...`, tests `.venv/bin/python -m pytest tests/ -q`.
- GitHub: https://github.com/xiajason6-web/GeoMacro2 (public). Username
  `xiajason6-web`; push needs a classic PAT with `repo` + `workflow` scopes
  (osxkeychain remembers it). `GIT_TERMINAL_PROMPT=0 git push`.
- Dashboard: Streamlit Community Cloud, `streamlit_app.py`, auto-refreshes on
  each data commit.
- Secrets: `.env` (gitignored) holds `ANTHROPIC_API_KEY`, `CENSUS_API_KEY`,
  `ESTAT_APP_ID`. Same three are GitHub Actions secrets. (The Anthropic key
  was pasted in chat during setup — rotate it in the console when convenient.)

## Cost: ~$0.50/month. Whole project to date cost ~$4.24 of LLM calls.
Normal nights = $0 (idempotent collectors, no new docs → no API calls).
GitHub Actions + Streamlit are free (public repo).

## Architecture (5 layers; every number traces to an archived document)

1. Collect — `collectors/*.py`, one per source, → SQLite + provenance
   (source URL, sha256, retrieved_at). No LLM.
2. Extract — `extraction/*.py`, Claude (Haiku default via EXTRACTION_MODEL)
   with strict JSON schema, VALIDATED before any write; failures →
   `review_queue`, never guessed. LLM never does arithmetic.
3. Store — one SQLite file `db/tracker.sqlite`. Schema in `db/schema.sql`
   (CHANGING schema requires Jason's OK — but he's approved every addition
   this project; the DB has been rebuilt/altered in place each time).
4. Analyze — `analysis/*.py`, deterministic pandas.
5. Interpret — `review/*.py`, drafts for human review; nothing auto-publishes.

## Collectors (nightly via .github/workflows/daily.yml, each fails alone)

- `mirror_trade.py` — China WFE + IC imports as MIRROR data (partner exports
  to China). HS 8486 (equipment) + HS 8542 (chips). Origins: EU27 (Eurostat),
  Japan (e-Stat, drops zero-filled unpublished months), US (Census), Korea +
  Singapore (UN Comtrade keyless preview, 1 period/call, ~2mo lag). Taiwan =
  NO machine-readable source, permanently in `missing_origins`. China customs
  (GACC) blocked by anti-bot (412) → mirror data is the workaround.
- `fx_rates.py` — ECB monthly averages → `fx_rates` table as USD-per-unit
  (CNY, EUR, JPY, USD). THE currency chokepoint: all aggregation converts to
  USD through this table before summing.
- `cninfo_filings.py` — Q1/Q3 quarterly reports + H1/annual SUMMARIES for 6
  listed equipment makers (Naura, AMEC, ACM Shanghai, Piotech, Kingsemi,
  Hwatsing) + 2 foundries (SMIC, Hua Hong). Also downloads full annual
  reports and slices ONLY the 分行业 segment pages (pypdf) to stay small.
  Periods are CALENDAR-GENERATED (build_periods etc.) so new filing seasons
  auto-appear. SMEE unlisted → not here.
- `entity_list.py` — BIS Entity List rules (Federal Register API) → events.
- `policy_monitor.py` — gov.cn policy library → events (PENDING_TRANSLATION
  sentinel, classified later).
- `vendor_china_revenue.py` — AMAT/LRCX/KLA 10-Q/10-K from SEC EDGAR;
  vendors tagged `equipment_foreign` so they CAN'T enter the domestic
  numerator. Leads Chinese prints by weeks.
- `big_fund.py` — 国家集成电路产业投资基金 announcements (cninfo search) →
  hifreq_signals.
- `western_earnings.py` — ASML IR PDFs (China revenue %).
- `benchmarks.py` — seeds `benchmarks` table from ARCHIVED analyst pages
  (Bernstein 21% 2025, UBS 20% 3-co scope, CSIS 35%). Yole 23% NOT seeded
  (paywalled) → review_queue.
- `customs_imports.py` — GACC attempt; records the block, uses mirror instead.

## Extraction

- `extract_filing_revenue.py` — quarterly revenue (Mandarin filings).
- `extract_cumulative_revenue.py` — H1/FY/YTD9M cumulative (for Q2/Q4 derive).
- `extract_segment_revenue.py` — semicap segment share (分行业) per co-year.
- `extract_domestic_share.py` — domestic (境内) share (分地区) per co-year.
- `translate_classify_policy.py` — policy events → category/relevance.
- `extract_vendor_china.py` — vendor China revenue % + hifreq_signals.

## Analysis

- `derive_quarters.py` — Q2=H1−Q1, Q3=YTD9M−H1, Q4=FY−H1−Q3 (pure python).
- `derive_domestic_semicap.py` — the audited numerator:
  quarterly_revenue × semicap_segment_share × domestic_share. Both total and
  adjusted stored. ESTIMATED flags for share-year fallback / no-split.
- `indigenization_ratio.py` — FLAGSHIP. ratio = domestic semicap USD /
  (domestic semicap USD + mirror imports USD). methodology v2.0.0. Full
  coverage = missing_origins is only "Taiwan". Reduced-coverage quarters kept
  but flagged. Archives v1 series to data/exports/history/.
- `reconciliation.py` — our series vs benchmarks + gap DECOMPOSITION (numerator
  scope / import coverage / currency / company scope). The differentiator.
- `nowcast.py` — current-quarter ESTIMATE (nc-1.0.0): carry-forward filled
  months scaled by vendor-signal factor + extrapolated revenue; scenario
  band (NOT a CI); stores every run in `nowcasts` table for a track record.
- `consensus_gap.py` — (was surprise.py) nowcast vs persistence baseline =
  the delta a trader trades. Dashboard tab "Nowcast vs consensus".
- `exposure_map.py` — 48 differentiated event→entity transmission links,
  human_reviewed gate. ALL 48 APPROVED.
- `exposure_ladder.py` — 11 instruments (ACMR benefit, AMAT/LRCX/ASML harm,
  foundries/KLAC mixed, SMH/USDCNH neutral) mapped to the theme, human_reviewed
  gate. ALL 11 APPROVED.
- `chip_vs_equipment.py` — HS8486 vs HS8542 import trajectories.
- `vendor_lead.py` — vendor panel vs ratio lead-lag (honest: n too small,
  cycle dominates).
- `charts.py`, `export_metrics_csv.py`.

## Review layer

- `weekly_digest.py` — Monday draft (data changes, ratio, events+exposure,
  nowcast, trade-note falsifiers, review queue). Opens as a GitHub issue.
- `trade_note.py` — the thematic-pod audition doc: thesis, nowcast-vs-consensus,
  mechanism, exposure ladder, leading indicators, FALSIFIERS, method/limits,
  NOT-advice disclaimer top+bottom. (red_team.py was REMOVED; falsifiers do
  its job now.)

## DB tables
sources, documents, entities, metrics, events, exposure_links (v2, +neutral,
+human_reviewed), review_queue, fx_rates, benchmarks, hifreq_signals,
nowcasts, instrument_exposure.

## Current numbers (as of this session)
- Flagship ratio, full-coverage: ~11.5% (2023Q3) → 22.0% (2025Q4). In the
  Bernstein/consensus band. The ~36% "latest" is a PARTIAL-DATA artifact
  (Korea+Singapore imports lag ~2mo) — dashboard flags it, nowcast completes
  it to ~25%.
- Reconciliation: our 2025 ≈ 18.7% vs Bernstein 21%; gap decomposes mostly to
  import coverage + company scope, NOT numerator adjustments.

## THREE KEY FINDINGS (the analytical payoff — all in the data)
1. Substitution, not demand destruction: total China WFE demand ROSE to a 2024
   record then contracted in 2025 (SEMI; not literally "flat") while domestic
   doubled ($1.3→3.1bn) — the substitution holds through both, refuting
   "controls just wrecked the market." (Audit fix: earlier "flat ~$12-14bn/qtr"
   was imprecise — demand rose-then-fell, and the /qtr figure ran high partly
   from HS8486 flat-panel contamination; see methodology.md audit.)
2. The import decline is US-SPECIFIC: US-origin exports to China −69%
   (2023H2→2025H2) while EU/Japan/Korea/Singapore held flat-to-up. China
   de-Americanized, it did not decouple; the allied coalition is leaky.
   CAVEAT: some US→Singapore is US firms rerouting via Singapore fabs.
3. Tools localize faster than chips: HS8486 equipment imports +6% while HS8542
   chip imports +34% (2023Q3→2025Q4). The debate conflates these.
Plus an honest null: vendor-lead correlation came out POSITIVE (cycle
dominates substitution at short horizons; n=5 too small anyway).

## Quant/career framing (Simonian "Computational Global Macro")
- Alpha = your estimate − consensus (the reconciliation gap + US-specific
  decomposition + nowcast surprise). The ratio itself is a factor, not alpha.
- Beta = the fab-capex cycle, which DOMINATES substitution at short horizons
  (proven by the vendor-lead null). So the correct trade expression is
  CYCLE-NEUTRAL: long domestic winners / short foreign losers — hedge beta to
  isolate substitution alpha. This is the sharpest quant insight.
- Delta = exposure ladder (quantify via return-on-ratio regression).
- Gamma/convexity lives at the litho chokepoint (Kingsemi flat while peers
  doubled = the scanner bottleneck capping litho-adjacent tools).
- Game theory: US-specific decline = coalition free-rider problem; China
  substitution = best-response + Big Fund commitment device; tools-before-
  chips = iterated learning game.
- Career fit: political-risk / tech-policy research (CSET, Rhodium, CNAS,
  MERICS) and thematic-macro RESEARCH seats. Comparative-politics major is an
  ASSET here. Distribute NARROWCAST (get in front of ~30 specific people +
  defend it cold), not broadcast. Keep it free (compliance + credibility).

## Operational gotchas
- Nightly bot commits db/tracker.sqlite (binary) → merge conflicts when you
  also work. `.gitattributes` has a `keeplocal` driver; resolve by keeping
  local + re-running collectors (they re-fetch). Pattern: `git pull
  --no-rebase`, `git checkout --ours` the conflicted binaries, commit.
- Human-review gates: `python analysis/exposure_map.py approve-all` and
  `python analysis/exposure_ladder.py approve-all` (both already approved).
- e-Stat/ECB responses embed timestamps → value-level change detection avoids
  re-archiving identical data.

## Open items (review_queue + known)
Taiwan mirror data (no source), Yole 23% citation (paywalled), TEL filings
(Japanese IR), ijiwei trade press (JS-gated), a couple vendor 10-K exhibits.
All parked by CHOICE, tracked in review_queue — none load-bearing.

## CAUSAL LAYER — BUILT (was the highest-value next build)
`analysis/did_export_controls.py` (+ `tests/test_did.py`, wired into the
nightly analysis block). Difference-in-differences that IDENTIFIES the
export-control effect. Key design move: the ratio has no untreated control
group, so identification happens one level down, at the DENOMINATOR —
US-origin imports (treated by unilateral controls) vs allied origins
(EU27/JP/KR/SG, same fabs + same cycle, not bound by US rules). Monthly
origin panel of HS 8486 in USD; TWFE with year-month FE ABSORBING the
fab-capex cycle (the confounder the vendor-lead null flagged).
  - PANEL BACKFILLED TO 2021-01 (fx_rates.py SINCE, mirror_trade.py
    BACKFILL_SINCE/CENSUS_YEARS/COMTRADE_SINCE, e-Stat time_from — all widened;
    one-time historical pull done, idempotent thereafter). This put ALL THREE
    waves in-sample with a real pre-treatment window, and as a BONUS filled
    EU27 back to 2021 so the flagship's 2023Q1/Q2 flipped from reduced-coverage
    to full (ratios there moved 16.7%->14.6%, 17.4%->13.5% — EU now in denom).
  - Result: US exports ran ~78% below the allied-implied path cumulatively
    across all three waves (b0=-0.36 Oct22, b1=-0.39 Oct23 incr, b2=-0.77 Dec24
    incr; HC1 ses 0.10/0.11/0.15). This is now the FULL measured effect, not a
    lower bound.
  - Event study (baseline 2022Q2): FIVE pre-baseline quarters all within +-0.10
    log pts, then clean monotone divergence — textbook parallel trends. Placebo
    across origins: US is by far the most suppressed (-1.52 vs all controls near
    0 or positive; EU27 +1.18); permutation p=0.20 (sharpest attainable with 5
    origins — payoff is magnitude + counterfactual, not a star).
  - PAYOFF (essay headline): counterfactual indigenization ratio rebuilds US
    imports on the allied growth path from the pre-control 2022Q2 anchor. By
    2025Q4, of the 22.0% ratio only ~2.3pp is US-import SUPPRESSION; ~19.7pp is
    genuine domestic SUBSTITUTION. Robust to including Oct-2022 (was 1.6pp at 2
    waves). The US decline is dramatic in % but small in ratio terms because the
    US was already a small, shrinking import share — substitution does the heavy
    lifting. SHARPENS Finding #1; not vulnerable to "you skipped Oct-2022".
  - Secondary: ratio-level ITS with cycle control (n=12 now, underpowered by
    construction, shown for completeness — the design the DiD improves on).
  - Outputs: data/exports/did_export_controls.md, did_event_study.html,
    did_counterfactual.html. OLS is pure numpy (no new deps), all pinned by tests.

## CHIP-LAYER SELF-SUFFICIENCY — BUILT (the frontier / "Jensen" layer)
`analysis/chip_self_sufficiency.py` (+ test, dashboard section, nightly).
The equipment ratio has a clean domestic numerator; the CHIP layer doesn't —
the clean national series (NBS 集成电路产量) is GEO-BLOCKED from US IPs (403),
recorded by new stub `collectors/nbs_ic_output.py` in review_queue (mirrors the
GACC/customs pattern; NOT in nightly to avoid spam). CXMT/YMTC unlisted.
  - Interim PROXY: domestic logic output = SMIC + Hua Hong quarterly revenue
    (USD) vs HS 8542 chip imports. DIRECTIONAL ONLY (numerator includes
    non-China foundry sales + excludes memory/IDM; HS8542 includes re-export +
    demand). Trend + contrast-with-equipment are the robust parts, not the level.
  - Finding (directly answers the Dwarkesh/Jensen debate): 2023Q1->2025Q4
    domestic logic output +113% BUT chip imports +48% too, so the chip domestic
    share crept only +3.2pp (8.2%->11.4%) while the equipment ratio surged +7.5pp
    (14.6%->22.0%). TOOLS LOCALIZE; FRONTIER LOGIC LAGS — China localizes the
    factory faster than the frontier product. AI/electronics demand outran
    substitution at the chip layer.
  - Outputs: data/exports/chip_self_sufficiency.{md,csv}; dashboard "Two layers
    of self-sufficiency" contrasts equipment ratio vs chip share.
## CHIP-LAYER DiD — BUILT (`analysis/did_chip_controls.py`, + test, dashboard)
The export-control DiD run on HS 8542 (chips) — Jensen's layer. Identifies off
the denominator (US vs allied chip exports), so no domestic numerator needed;
REUSES the audited did_export_controls machinery unchanged (load_panel now takes
a `series=` arg). THE RESULT IS THE OPPOSITE OF EQUIPMENT and that contrast is
the payoff:
  - Equipment: durable −78%, clean pre-trends. Chips: a V — US chip exports fell
    ~−47% below the allied path at the 2023Q2 trough (A100/H100 + A800/H800 bit),
    then RECOVERED to ~−13% by 2025 as firms shipped compliant parts
    (A800->H800->H20). Net cumulative ~+15%, placebo p=0.80, pre-trend 0.53 →
    parallel trends FAILS. Read the failed identification as the finding: the
    chip channel was re-engineered around.
  - Takeaway: control durability is LAYER-SPECIFIC — sticks at the tool
    chokepoint (can't re-spin a litho tool), leaks at the chip-product layer
    (fast design iteration). Both debate camps get a precisely-bounded point;
    neither layer's controls made China self-sufficient (imports rose on demand).
  - Honest: HS8542 is ALL ICs (uncontrolled chips dilute + aid the recovery);
    parallel trends fails so it's DESCRIPTIVE, not clean-causal (equipment DiD is
    the identified one). Outputs: did_chip_controls.md + did_chip_*.csv; dashboard
    "Did the chip controls work? Bite, then leak" (V-shape event study).

## ASSUMPTION AUDIT (2026-07) — researched against outside sources
Full verdict table in analysis/methodology.md ("External assumption audit").
Headlines: conclusions survive; equipment −78% is a conservative LOWER BOUND
(allies EU27+Japan partially treated from mid-2023 → attenuation); the flagship
ratio is a LOWER BOUND on true localization (HS8486 includes flat-panel tools);
the chip-layer NVIDIA/H20 mechanism was OVERSTATED and is now corrected
(NVIDIA GPUs are Taiwan-fabbed → barely in US-origin HS8542; the recovery is
unrestricted chips + cycle). Fixes shipped: clean-control DiD variant
(Korea+Singapore, −71.6% vs −78.1% full — robust); chip narrative rewritten;
"flat demand" softened; methodology limits table strengthened.

## NEXT CANDIDATES (pick with Jason)
1. **v3 data task (highest value): re-collect equipment imports at HS6, exclude
   8486.30 (flat-panel).** Removes the denominator contamination → truer (higher)
   flagship ratio. This changes the flagship number, so it's a METHODOLOGY
   revision needing Jason's OK — do it as its own validated pass, not a ride-along.
2. Isolate the controlled GPU subset (product-level data) + add Taiwan chip
   origin — would make the chip V a clean causal estimate on the right series.
3. Write the second essay off the two-layer story (equipment durable vs chip
   leaky) — draft in review/, human-edited, NOT auto-published (trade_note gate).
4. If NBS ever un-blocks (or via manual PDF ingest): real chip self-sufficiency
   ratio + its own DiD, demand-adjusted.

## Test suite: 99 passing. Run before committing anything.
