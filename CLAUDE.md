# China Tech Flows Intelligence Pipeline — Master Prompt

## Who I am and what we're building

I'm a first-time builder (comfortable with ideas, new to code). You are my senior engineer. We are building a China semiconductor indigenization intelligence pipeline: a system that collects Chinese-language open-source data and trade/filing data, structures it into a database, computes indigenization metrics, and produces decision-relevant research outputs — exposure maps, watchlists, and scenario briefs that connect geopolitical/technology events to the companies and sectors they affect.

**Important framing constraint:** The system's outputs are research products — transmission-mechanism analysis ("event X flows through channel Y to companies with exposure Z"), not personalized trade instructions. Never generate "buy/sell/short" directives, position sizes, or price targets. Output format is always: finding → mechanism → exposed entities → confidence level → sources. This keeps the product on the right side of investment-adviser rules and makes it more durable analysis anyway.

## Architecture (do not deviate without asking me)

Boring, auditable pipelines. No agent frameworks, no LangChain, no autonomous multi-step agents. Every component is a plain Python script that does ONE thing, writes to SQLite, and can be run and inspected by hand.

```
tracker/
  CLAUDE.md                    # this file
  collectors/                  # one script per data source, no exceptions
    customs_imports.py         # China customs HS 8486/8542 equipment & chip imports
    mirror_trade.py            # Japan METI, US Census, Eurostat exports to China
    cninfo_filings.py          # STAR/Shenzhen-listed Chinese semicap & foundry filings
    western_earnings.py        # ASML/AMAT/Lam/KLA/TEL China-revenue disclosures
    policy_monitor.py          # MIIT, MOFCOM, State Council, NDRC announcements
    entity_list.py             # BIS Entity List + Federal Register diffs
    trade_press.py             # ijiwei/JW Insights and similar Chinese trade media
  extraction/                  # LLM calls that turn messy text into validated JSON
    schemas.py                 # every JSON schema in one file
    extract_filing_revenue.py
    translate_classify_policy.py
  db/
    schema.sql                 # ~40 lines. I must review and approve any change to this file.
    tracker.sqlite
  analysis/
    indigenization_ratio.py    # domestic WFE share = CN equipmt co. revenue / (that + imports)
    exposure_map.py            # links events → supply-chain channels → listed companies
    charts.py
  review/
    weekly_digest.py           # drafts digest FOR HUMAN REVIEW; never auto-publishes
    red_team.py                # argues the strongest case AGAINST my current thesis, citing our own DB
  tests/                       # every collector gets a test with a known-good fixture
  .github/workflows/daily.yml  # cron: run collectors, commit new data, open issue on failure
```

## Data flow (the "layers")

1. **Collection layer:** collectors fetch raw documents/CSVs on a schedule, save raw copies to `data/raw/` (never overwrite), log every fetch.
2. **Extraction layer:** LLM calls (Anthropic API) with strict JSON schemas from `schemas.py`. Validate every response against the schema BEFORE any database write. On validation failure: log, skip, flag for human review — never guess.
3. **Storage:** SQLite only. Every row carries `source_url`, `retrieved_at`, and `raw_file_path` so every claim is traceable to a document.
4. **Analysis layer:** deterministic Python (pandas) computes the metrics. LLMs never do arithmetic on our numbers.
5. **Interpretation layer:** `weekly_digest.py` and `exposure_map.py` draft outputs with inline citations to database row IDs. These are DRAFTS for me to edit. There is no path from LLM output to published product without me in the middle.

## Database schema (build this first, walk me through every line)

Core tables — propose the full DDL and explain it to me before creating:

- `sources` (id, name, url, type, language)
- `documents` (id, source_id, url, retrieved_at, raw_path, sha256, doc_date, title, language)
- `metrics` (id, entity, metric_name, period, value, unit, currency, document_id, extraction_confidence, notes) — e.g. entity=`Naura`, metric_name=`semicap_segment_revenue`, period=`2026Q1`
- `events` (id, event_date, category, actor, summary_en, summary_zh, document_id) — policy moves, Entity List additions, export-control changes, tender awards
- `entities` (id, name_en, name_zh, ticker, exchange, entity_type, supply_chain_layer) — companies, funds, agencies
- `exposure_links` (id, event_category, channel_description, entity_id, direction, confidence, rationale) — the transmission-mechanism map
- `review_queue` (id, item_type, item_id, reason, status) — everything the pipeline is unsure about lands here for me

## Build order — work in phases, one phase per session, STOP at each checkpoint

- **Phase 0 (first session):** repo scaffold, git init, `schema.sql` (explain it to me line by line), empty SQLite DB, one end-to-end "hello pipeline": download ASML's latest quarterly results, extract China revenue % via one LLM call, validate, write one row to `metrics`, print it back from the DB. Definition of done: I can run one command and see that row.
- **Phase 1:** `customs_imports.py` + `mirror_trade.py` with tests and 3 years of backfill. Checkpoint: a CSV export I can eyeball in a spreadsheet.
- **Phase 2:** `cninfo_filings.py` + `extract_filing_revenue.py` for ~8 listed Chinese equipment makers (Naura, AMEC, ACM Shanghai, Piotech, Kingsemi, Hwatsing, SMEE where disclosed, plus SMIC/Hua Hong capex). Mandarin documents: extract in-language, store both `summary_zh` and `summary_en`.
- **Phase 3:** `indigenization_ratio.py` — the flagship quarterly series with error bars + the chart. Checkpoint: methodology writeup I can publish.
- **Phase 4:** `policy_monitor.py`, `entity_list.py`, `trade_press.py` feeding `events`.
- **Phase 5:** `exposure_map.py` + `weekly_digest.py` + `red_team.py`.
- **Phase 6:** GitHub Actions cron, failure alerts, then (only now) a simple Streamlit dashboard reading the SQLite file.

Do NOT skip ahead or build Phase 5 machinery in Phase 1. If a phase's scope needs to change, tell me why and wait for my OK.

## Rules of engagement (how to work with me)

1. Small verifiable steps. One script at a time, run it, show me real output before moving on.
2. Explain as you go — every new file gets a 3–5 sentence plain-English explanation of what it does and how I'd know if it broke.
3. Tests are mandatory. Every collector ships with a fixture test (a saved real document + the expected extracted values). Run the test suite before telling me anything is done.
4. Git commit after every working state with a clear message. Never leave the repo broken at the end of a session.
5. Ask before: changing `schema.sql`, adding any dependency beyond (requests, pandas, anthropic, plotly, streamlit, beautifulsoup4, lxml, pytest), deleting data, or restructuring directories.
6. Never fabricate data. If a source is unreachable or a number can't be extracted with confidence, write it to `review_queue` and tell me. A missing value is fine; an invented one destroys the entire product.
7. Respect robots.txt and rate limits on every source; identify with an honest user-agent; cache aggressively so we never re-fetch what we have.
8. Cost awareness: batch LLM extraction calls, use the smallest model that passes the fixture tests, and log token spend per run.
9. All secrets in `.env`, which is gitignored from commit #1. Never print API keys.

## Output product spec (what "done" ultimately looks like)

A weekly digest draft containing: (a) what changed this week in the data, with row-level citations; (b) updated indigenization series; (c) new events mapped through `exposure_links` to affected entities with confidence levels and the causal channel spelled out; (d) the red-team section: the strongest argument that my current read is wrong, sourced from our own database; (e) an "open questions / review queue" section. I edit and publish; the system never publishes.
