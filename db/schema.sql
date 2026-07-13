-- China Tech Flows Intelligence Pipeline — core schema.
-- Changing this file requires explicit human approval (see CLAUDE.md).

CREATE TABLE sources (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,       -- e.g. 'China Customs', 'cninfo', 'ASML IR'
    url         TEXT,                       -- the source's home, not a specific document
    type        TEXT NOT NULL,              -- 'customs' | 'filing' | 'earnings' | 'policy' | 'regulatory' | 'press' | 'trade_stats'
    language    TEXT NOT NULL DEFAULT 'en'  -- 'en' | 'zh'
);

CREATE TABLE documents (
    id           INTEGER PRIMARY KEY,
    source_id    INTEGER NOT NULL REFERENCES sources(id),
    url          TEXT NOT NULL,             -- exact URL fetched
    retrieved_at TEXT NOT NULL,             -- ISO 8601 UTC, e.g. '2026-07-09T14:03:00Z'
    raw_path     TEXT NOT NULL,             -- copy under data/raw/, never overwritten
    sha256       TEXT NOT NULL UNIQUE,      -- hash of raw bytes; blocks duplicate ingestion
    doc_date     TEXT,                      -- date the document is ABOUT (filing date), not fetch date
    title        TEXT,
    language     TEXT
);

CREATE TABLE entities (
    id                 INTEGER PRIMARY KEY,
    name_en            TEXT NOT NULL UNIQUE,
    name_zh            TEXT,                -- e.g. '北方华创'
    ticker             TEXT,                -- e.g. '002371'
    exchange           TEXT,                -- 'SZSE' | 'SSE-STAR' | 'HKEX' | 'NASDAQ' | ...
    entity_type        TEXT NOT NULL,       -- 'company' | 'fund' | 'agency'
    supply_chain_layer TEXT                 -- 'equipment' | 'foundry' | 'materials' | 'EDA' | 'design' | 'OSAT'
);

CREATE TABLE metrics (
    id                    INTEGER PRIMARY KEY,
    entity_id             INTEGER NOT NULL REFERENCES entities(id),
    metric_name           TEXT NOT NULL,    -- e.g. 'semicap_segment_revenue', 'china_revenue_pct'
    period                TEXT NOT NULL,    -- '2026Q1' | '2026-05' | '2026'
    value                 REAL NOT NULL,
    unit                  TEXT NOT NULL,    -- 'CNY_mn' | 'USD_mn' | 'pct' | 'units'
    currency              TEXT,             -- NULL for non-monetary metrics
    document_id           INTEGER NOT NULL REFERENCES documents(id),
    extraction_confidence REAL,             -- 0.0-1.0, from the extraction step
    notes                 TEXT,
    UNIQUE (entity_id, metric_name, period, document_id)
);

CREATE TABLE events (
    id          INTEGER PRIMARY KEY,
    event_date  TEXT NOT NULL,
    category    TEXT NOT NULL,              -- 'export_control' | 'entity_list' | 'subsidy' | 'tender' | 'policy' | ...
    actor       TEXT,                       -- 'BIS', 'MIIT', 'State Council', ...
    summary_en  TEXT NOT NULL,
    summary_zh  TEXT,
    document_id INTEGER NOT NULL REFERENCES documents(id)
);

CREATE TABLE exposure_links (
    id                  INTEGER PRIMARY KEY,
    event_category      TEXT NOT NULL,      -- joins conceptually to events.category
    channel_description TEXT NOT NULL,      -- the causal channel, spelled out in prose
    entity_id           INTEGER NOT NULL REFERENCES entities(id),
    direction           TEXT NOT NULL CHECK (direction IN ('benefit', 'harm', 'mixed')),
    confidence          TEXT NOT NULL CHECK (confidence IN ('low', 'medium', 'high')),
    rationale           TEXT NOT NULL
);

CREATE TABLE review_queue (
    id         INTEGER PRIMARY KEY,
    item_type  TEXT NOT NULL,               -- which table or pipeline stage flagged it
    item_id    INTEGER,                     -- row id in that table, if one exists yet
    reason     TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'dismissed')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Added 2026-07-12 (work order: common-currency normalization). One row per
-- (currency, period): how many USD one unit of the currency bought that
-- month (ECB reference-rate monthly averages; crosses derived via EUR).
-- Every aggregation across currencies must convert through this table.
CREATE TABLE fx_rates (
    currency     TEXT NOT NULL,            -- 'EUR' | 'JPY' | 'CNY' | 'USD' | ...
    period       TEXT NOT NULL,            -- 'YYYY-MM'
    usd_per_unit REAL NOT NULL,
    document_id  INTEGER NOT NULL REFERENCES documents(id),
    PRIMARY KEY (currency, period)
);
