"""Collector: mirror trade — partner-country exports to China.

What this does: pulls monthly export values to China for HS 8486 (semiconductor
manufacturing equipment) and HS 8542 (integrated circuits) from official
statistical APIs, saves every raw API response under data/raw/, records it in
`documents`, then deterministically parses the numbers into `metrics` rows
(entity = China, one row per month, each row pointing at the exact raw
response it came from). No LLM is involved — this is structured numeric data.

Sources:
  - Eurostat Comext (works today, no key): reporters EU27, Netherlands (≈ASML),
    Germany. Values in EUR.
  - US Census (needs free CENSUS_API_KEY in .env — https://api.census.gov/data/key_signup.html):
    skipped with a warning until the key exists.
  - Japan (needs free e-Stat appId — https://www.e-stat.go.jp/en/api/): not yet
    implemented; will be added with a real fixture once the key exists.

How you'd know it broke: each series prints "N months" on success. An API
error crashes loudly. A month that disappears from a previously fetched
series would show up as a shorter range in the printed output and in the
CSV export. Re-running never re-fetches byte-identical data into new rows.
"""

import datetime
import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"
RAW_DIR = REPO_ROOT / "data" / "raw" / "mirror_trade"
USER_AGENT = "ChinaTechFlowsTracker/0.1 (research; contact: jx3@williams.edu)"

BACKFILL_SINCE = "2023-07"  # three years back from July 2026

EUROSTAT_SOURCE = {
    "name": "Eurostat Comext",
    "url": "https://ec.europa.eu/eurostat/web/international-trade-in-goods/database",
    "type": "trade_stats",
    "language": "en",
}
EUROSTAT_API = (
    "https://ec.europa.eu/eurostat/api/comext/dissemination/statistics/1.0/data/DS-045409"
)

# One series per (reporter, HS product). flow=2 is EXPORT; partner=CN is China.
EUROSTAT_SERIES = [
    {"reporter": "EU27_2020", "product": "8486", "metric": "mirror_exports_eu27_hs8486_eur"},
    {"reporter": "EU27_2020", "product": "8542", "metric": "mirror_exports_eu27_hs8542_eur"},
    {"reporter": "NL", "product": "8486", "metric": "mirror_exports_nl_hs8486_eur"},
    {"reporter": "NL", "product": "8542", "metric": "mirror_exports_nl_hs8542_eur"},
    {"reporter": "DE", "product": "8486", "metric": "mirror_exports_de_hs8486_eur"},
    {"reporter": "DE", "product": "8542", "metric": "mirror_exports_de_hs8542_eur"},
]

CHINA_ENTITY = {
    "name_en": "China",
    "name_zh": "中国",
    "ticker": None,
    "exchange": None,
    "entity_type": "country",
    "supply_chain_layer": None,
}


def connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def load_env():
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def ensure_source(conn, source):
    conn.execute(
        "INSERT OR IGNORE INTO sources (name, url, type, language)"
        " VALUES (:name, :url, :type, :language)",
        source,
    )
    return conn.execute(
        "SELECT id FROM sources WHERE name = ?", (source["name"],)
    ).fetchone()[0]


def ensure_china_entity(conn):
    conn.execute(
        "INSERT OR IGNORE INTO entities"
        " (name_en, name_zh, ticker, exchange, entity_type, supply_chain_layer)"
        " VALUES (:name_en, :name_zh, :ticker, :exchange, :entity_type, :supply_chain_layer)",
        CHINA_ENTITY,
    )
    return conn.execute(
        "SELECT id FROM entities WHERE name_en = 'China'"
    ).fetchone()[0]


def eurostat_url(series, since=BACKFILL_SINCE):
    return (
        f"{EUROSTAT_API}?format=JSON&freq=M"
        f"&reporter={series['reporter']}&partner=CN&product={series['product']}"
        f"&flow=2&indicators=VALUE_IN_EUROS&sinceTimePeriod={since}"
    )


def parse_eurostat_response(payload):
    """JSON-stat (single series over time) -> list of (period 'YYYY-MM', value).

    The time dimension can include future months with no data yet; only
    indices present in `value` are returned. Deterministic — no guessing.
    """
    time_index = payload["dimension"]["time"]["category"]["index"]
    values = payload["value"]
    out = []
    for period, idx in sorted(time_index.items(), key=lambda kv: kv[1]):
        if str(idx) in values:
            out.append((period, float(values[str(idx)])))
        elif idx in values:  # some deserializers keep int keys
            out.append((period, float(values[idx])))
    return out


def ingest_raw(conn, source_id, url, content, title):
    """Save raw bytes + documents row. Returns (document_id, is_new)."""
    sha = hashlib.sha256(content).hexdigest()
    existing = conn.execute(
        "SELECT id FROM documents WHERE sha256 = ?", (sha,)
    ).fetchone()
    if existing:
        return existing[0], False
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
    raw_path = RAW_DIR / f"{stamp}_{title}.json"
    if raw_path.exists():
        raw_path = raw_path.with_name(f"{raw_path.stem}_{sha[:8]}.json")
    raw_path.write_bytes(content)
    retrieved_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    cur = conn.execute(
        "INSERT INTO documents"
        " (source_id, url, retrieved_at, raw_path, sha256, doc_date, title, language)"
        " VALUES (?, ?, ?, ?, ?, NULL, ?, 'en')",
        (source_id, url, retrieved_at, str(raw_path.relative_to(REPO_ROOT)), sha, title),
    )
    return cur.lastrowid, True


def write_metrics(conn, entity_id, metric_name, rows, unit, currency, document_id, note):
    """Insert one metrics row per (period, value), all citing document_id."""
    for period, value in rows:
        conn.execute(
            "INSERT OR IGNORE INTO metrics"
            " (entity_id, metric_name, period, value, unit, currency, document_id,"
            "  extraction_confidence, notes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 1.0, ?)",
            (entity_id, metric_name, period, value, unit, currency, document_id, note),
        )


def collect_eurostat(conn):
    source_id = ensure_source(conn, EUROSTAT_SOURCE)
    entity_id = ensure_china_entity(conn)
    for series in EUROSTAT_SERIES:
        url = eurostat_url(series)
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=120)
        resp.raise_for_status()
        title = f"eurostat_{series['reporter']}_hs{series['product']}_exports_to_cn"
        doc_id, is_new = ingest_raw(conn, source_id, url, resp.content, title)
        rows = parse_eurostat_response(resp.json())
        if not is_new:
            print(f"{series['metric']}: unchanged since last fetch ({len(rows)} months)")
            continue
        note = (
            f"{series['reporter']} exports to China, HS {series['product']},"
            " monthly value in euros (Eurostat Comext DS-045409, mirror of"
            " China imports)"
        )
        write_metrics(
            conn, entity_id, series["metric"], rows, "EUR", "EUR", doc_id, note
        )
        first = rows[0][0] if rows else "-"
        last = rows[-1][0] if rows else "-"
        print(f"{series['metric']}: {len(rows)} months ({first} .. {last}), document id={doc_id}")
        time.sleep(1)  # rule 7: be polite between requests
    conn.commit()


def collect_us_census(conn):
    if not os.environ.get("CENSUS_API_KEY"):
        print(
            "US Census: skipped — no CENSUS_API_KEY in .env. Free signup:"
            " https://api.census.gov/data/key_signup.html"
        )
        return
    # Implemented once a key exists so the first run can save a real fixture.
    print("US Census: key found but collector not yet implemented — next session.")


def main():
    load_env()
    conn = connect()
    collect_eurostat(conn)
    collect_us_census(conn)
    conn.close()


if __name__ == "__main__":
    sys.exit(main())
