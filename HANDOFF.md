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
1. Substitution, not demand destruction: total WFE demand flat ~$12-14bn/qtr
   through 2025 while domestic doubled ($1.3→3.1bn) — refutes "controls just
   wrecked the market."
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

## HIGHEST-VALUE NEXT BUILD
Causal identification of the export-control effect: a difference-in-differences
around the control-wave dates (Oct 2022, Oct 2023, Dec 2024) or double-ML
controlling for total WFE demand (the cycle), to estimate the TREATMENT EFFECT
of controls on the ratio — moving from correlation+narrative to a causal
estimate (Simonian Ch 5 / López de Prado). This is the piece that makes it
publishable and is the natural headline of a second essay.

## Test suite: 88 passing. Run before committing anything.
