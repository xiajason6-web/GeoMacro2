# China WFE Indigenization Ratio — Methodology v2.0.0

## Version history

| Version | Date | Change |
|---|---|---|
| v1 | 2026-07-09 | Total listed-co revenue (later segment-adjusted), CNY common unit, imports EU27+JP+US. Archived at data/exports/history/indigenization_ratio_v1.csv |
| v2.0.0 | 2026-07-12 | Numerator = domestic semicap revenue (segment x region adjusted); common unit USD via fx_rates table; imports add Korea + Singapore; per-quarter origin-coverage fields; methodology_version stamped on every row |

## The metric

For each quarter *q*, all values converted to USD through the `fx_rates`
table (ECB monthly averages) BEFORE aggregation — native currencies are
never summed:

```
ratio(q) = domestic semicap revenue(q) / (domestic semicap revenue(q) + equipment imports(q))
```

This approximates the share of China's wafer-fab-equipment (WFE) spending
captured by domestic toolmakers. It is a *market-share* measure, not a
capability measure: a rising ratio can mean domestic tools winning sockets,
or export controls removing the foreign alternative, or both. Interpretation
belongs in the digest, not in the number.

## Numerator: domestic equipment revenue

- Source: quarterly reports filed on cninfo by listed Chinese equipment
  makers, extracted by LLM with schema validation (`quarterly_revenue_cny`),
  then scaled by two disclosed annual shares into
  `domestic_semicap_revenue_cny` (python arithmetic, both figures stored so
  the adjustment is auditable):
  - semicap segment share (分行业/分产品 tables, `semicap_segment_share_pct`)
  - domestic share (分地区 tables, `domestic_revenue_share_pct`) — note this
    split covers total revenue; applying it to the semicap segment assumes
    equal export propensity across segments (documented approximation).
  Quarters beyond the last disclosed fiscal year reuse the latest shares and
  are flagged ESTIMATED; the flag count appears as `n_estimated` per quarter.
- Companies currently covered: Naura, AMEC, ACM Shanghai, Piotech, Kingsemi,
  Hwatsing (supply_chain_layer = 'equipment'; SMIC and Hua Hong are
  collected but excluded — they are foundries, i.e. equipment *buyers*).

### Known biases (numerator)

| Bias | Direction | Planned fix |
|---|---|---|
| ~~Total revenue includes non-semicap segments~~ **FIXED**: quarterly revenue is now scaled to the semicap-equipment share disclosed in each company's annual report (metric `semicap_segment_share_pct`, extracted from 分行业/分产品 tables; the share is computed in Python from extracted segment values; quarters after the last disclosed year use the most recent share) | resolved (residuals: within-year share drift; segment granularity — e.g. Naura's 电子工艺装备 line still bundles some non-semi equipment, and AMEC's FY2025 table discloses a single segment) | refresh each April when annual reports land |
| ~~Some revenue is export revenue~~ **FIXED v2**: numerator scaled by disclosed 分地区 domestic share (residual: split covers total revenue, not per-segment) | resolved | refresh annually |
| Unlisted domestic makers (SMEE, CETC tools) missing | understates | trade press / tender data |

## Denominator addend: equipment imports

- Concept: China's imports of HS 8486 (machines for semiconductor
  manufacture), measured as *mirror data* — partner countries' reported
  exports to China. Mirror data is used because China Customs' portal is not
  automatable (HTTP 412 anti-bot; recorded in review_queue).
- Currently: EU27 (Eurostat Comext, EUR), Japan (e-Stat 品別国別表, JPY —
  e-Stat zero-fills unpublished months; the parser drops all-zero months),
  US (Census timeseries/intltrade, USD), Korea and Singapore (UN Comtrade
  keyless preview, USD, ~2-month publication lag). Taiwan has no
  machine-readable source and is permanently listed in `missing_origins`.
- Coverage policy: a series enters a quarter only with all 3 months
  published; a quarter missing a series is NOT dropped — the gap is named in
  `coverage_origins` / `missing_origins` so reduced-coverage quarters are
  visibly not comparable (the dashboard marks them).


### Known biases (denominator)

| Bias | Direction on ratio | Planned fix |
|---|---|---|
| ~~Korea/Singapore missing~~ **FIXED v2** via UN Comtrade; Taiwan remains missing (no machine-readable source) | Taiwan gap: ratio overstated a few pp | revisit TW MOF portal with dedicated effort |
| Mirror data measures exports FOB at partner border, not arrivals CIF China | slightly understates imports | acceptable; note in publication |
| HS 8486 includes flat-panel-display tools | mixed, small | acceptable at HS4; HS6 split later if needed |
| Domestic revenue counted in CNY of sale vs imports at customs value | small | acceptable |

## Comparability rules for readers

- Compare only quarters with identical `coverage_origins`.
- `n_estimated` > 0 means share-year fallbacks are in play (typically the
  quarters after the last annual report).
- The latest fully-covered quarter is the headline; the newest quarter is
  usually reduced-coverage until Comtrade publishes (~2-month lag).

## Reproduction

```
.venv/bin/python collectors/mirror_trade.py
.venv/bin/python collectors/fx_rates.py
.venv/bin/python collectors/cninfo_filings.py
.venv/bin/python extraction/extract_filing_revenue.py   # needs ANTHROPIC_API_KEY
.venv/bin/python analysis/indigenization_ratio.py
.venv/bin/python analysis/charts.py
```

Every number in the output CSV traces to a `metrics` row, which traces to a
`documents` row, which points at an archived raw file and its source URL.
