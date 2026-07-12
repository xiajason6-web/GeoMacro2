# China WFE Indigenization Ratio — Methodology (DRAFT, not publishable yet)

## The metric

For each quarter *q*:

```
ratio(q) = domestic equipment revenue(q) / (domestic equipment revenue(q) + equipment imports(q))
```

This approximates the share of China's wafer-fab-equipment (WFE) spending
captured by domestic toolmakers. It is a *market-share* measure, not a
capability measure: a rising ratio can mean domestic tools winning sockets,
or export controls removing the foreign alternative, or both. Interpretation
belongs in the digest, not in the number.

## Numerator: domestic equipment revenue

- Source: quarterly reports filed on cninfo by listed Chinese equipment
  makers, extracted by LLM with schema validation, one metrics row per
  filing, every row traceable to the PDF (`quarterly_revenue_cny`).
- Companies currently covered: Naura, AMEC, ACM Shanghai, Piotech, Kingsemi,
  Hwatsing (supply_chain_layer = 'equipment'; SMIC and Hua Hong are
  collected but excluded — they are foundries, i.e. equipment *buyers*).

### Known biases (numerator)

| Bias | Direction | Planned fix |
|---|---|---|
| ~~Total revenue includes non-semicap segments~~ **FIXED**: quarterly revenue is now scaled to the semicap-equipment share disclosed in each company's annual report (metric `semicap_segment_share_pct`, extracted from 分行业/分产品 tables; the share is computed in Python from extracted segment values; quarters after the last disclosed year use the most recent share) | resolved (residuals: within-year share drift; segment granularity — e.g. Naura's 电子工艺装备 line still bundles some non-semi equipment, and AMEC's FY2025 table discloses a single segment) | refresh each April when annual reports land |
| Some revenue is export revenue, not China sales | overstates | segment/geography disclosures where available |
| Unlisted domestic makers (SMEE, CETC tools) missing | understates | trade press / tender data (Phase 4) |
| Only Q1 collected so far — series is one point | n/a | backfill prior quarters (see Backfill plan) |

## Denominator addend: equipment imports

- Concept: China's imports of HS 8486 (machines for semiconductor
  manufacture), measured as *mirror data* — partner countries' reported
  exports to China. Mirror data is used because China Customs' portal is not
  automatable (HTTP 412 anti-bot; recorded in review_queue).
- Currently: EU27 exports (Eurostat Comext DS-045409, monthly, EUR), Japan
  exports (e-Stat 普通貿易統計 品別国別表, monthly, JPY — note e-Stat
  zero-fills unpublished months; the parser drops all-zero months rather
  than record phantom zero trade), and US exports (Census
  timeseries/intltrade, monthly, USD). The three cover the large majority
  of WFE exports to China.
- Conversion to CNY: ECB monthly-average reference rates (CNY/EUR directly;
  JPY and USD via EUR crosses), applied month by month.
- Complete quarters only: a quarter missing any month is excluded rather
  than reported low.

### Known biases (denominator)

| Bias | Direction on ratio | Planned fix |
|---|---|---|
| Korea/Taiwan/Singapore exports missing (smaller than EU/JP/US) | ratio somewhat overstated | mirror collectors for KR (KOSIS), TW (MOF), SG later |
| Mirror data measures exports FOB at partner border, not arrivals CIF China | slightly understates imports | acceptable; note in publication |
| HS 8486 includes flat-panel-display tools | mixed, small | acceptable at HS4; HS6 split later if needed |
| Domestic revenue counted in CNY of sale vs imports at customs value | small | acceptable |

## Error bars (planned, not yet implemented)

Once US + Japan import series exist, the published series will carry a band:

- **Lower bound**: numerator = listed-company *semicap segment* revenue only;
  denominator includes a rest-of-world import estimate (Korea, Taiwan,
  Singapore mirror exports).
- **Upper bound**: numerator = listed total revenue + a trade-press-based
  SMEE/unlisted allowance; denominator = US+JP+EU only.

Until then the series is labeled WORKING and every output carries the
coverage caveat automatically.

## Backfill plan (needs Jason's OK before building)

Chinese quarterly disclosure is asymmetric: Q1 and Q3 have short quarterly
reports (fit the extraction pipeline as-is); Q2 lives inside the half-year
report and Q4 inside the annual report — both far larger documents. Proposal:

1. Backfill Q1/Q3 reports 2023–2026 directly (same collector, different
   `seDate`/category — cheap).
2. For Q2/Q4, extract *cumulative* revenue from half-year/annual report
   summary tables (first ~20 pages contain the headline table) and derive
   the quarter by subtraction, flagging derived values in notes.

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
