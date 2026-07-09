"""Collector: ECB reference exchange rates (monthly average CNY per EUR).

Why this exists (small addition to the original architecture): the mirror
trade series is in euros and Chinese company revenue is in yuan. The
indigenization ratio needs them in one currency, so we collect the ECB's
official monthly-average CNY/EUR reference rate — a public, keyless API.
One script, one source, same pattern as every other collector.

What this does: fetches the monthly series since 2023-07, saves the raw
SDMX-JSON response, and writes one metrics row per month
(metric_name 'fx_cny_per_eur_monthly_avg').

How you'd know it broke: prints "N months (first .. last)". A missing recent
month in the CSV export means the ECB hasn't published it yet or this
collector stopped running.
"""

import datetime
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"
RAW_DIR = REPO_ROOT / "data" / "raw" / "fx"
USER_AGENT = "ChinaTechFlowsTracker/0.1 (research; contact: jx3@williams.edu)"

SINCE = "2023-07"
API_URL = (
    "https://data-api.ecb.europa.eu/service/data/EXR/M.CNY.EUR.SP00.A"
    f"?startPeriod={SINCE}&format=jsondata"
)

SOURCE = {
    "name": "ECB reference rates",
    "url": "https://data.ecb.europa.eu",
    "type": "trade_stats",
    "language": "en",
}


def connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def parse_ecb_response(payload):
    """SDMX-JSON -> list of (period 'YYYY-MM', cny_per_eur)."""
    observations = payload["dataSets"][0]["series"]["0:0:0:0:0"]["observations"]
    periods = [
        v["id"] for v in payload["structure"]["dimensions"]["observation"][0]["values"]
    ]
    return [
        (period, float(observations[str(i)][0]))
        for i, period in enumerate(periods)
        if str(i) in observations
    ]


def main():
    conn = connect()
    conn.execute(
        "INSERT OR IGNORE INTO sources (name, url, type, language)"
        " VALUES (:name, :url, :type, :language)",
        SOURCE,
    )
    source_id = conn.execute(
        "SELECT id FROM sources WHERE name = ?", (SOURCE["name"],)
    ).fetchone()[0]
    entity_id = conn.execute(
        "SELECT id FROM entities WHERE name_en = 'China'"
    ).fetchone()
    if entity_id is None:
        print("China entity missing — run collectors/mirror_trade.py first")
        return 1
    entity_id = entity_id[0]

    resp = requests.get(API_URL, headers={"User-Agent": USER_AGENT}, timeout=120)
    resp.raise_for_status()
    sha = hashlib.sha256(resp.content).hexdigest()
    existing = conn.execute(
        "SELECT id FROM documents WHERE sha256 = ?", (sha,)
    ).fetchone()
    if existing:
        print("unchanged since last fetch")
        conn.close()
        return 0

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
    raw_path = RAW_DIR / f"{stamp}_ecb_cny_eur_monthly.json"
    if raw_path.exists():
        raw_path = raw_path.with_name(f"{raw_path.stem}_{sha[:8]}.json")
    raw_path.write_bytes(resp.content)
    retrieved_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    cur = conn.execute(
        "INSERT INTO documents"
        " (source_id, url, retrieved_at, raw_path, sha256, doc_date, title, language)"
        " VALUES (?, ?, ?, ?, ?, NULL, 'ECB CNY per EUR monthly average', 'en')",
        (source_id, API_URL, retrieved_at, str(raw_path.relative_to(REPO_ROOT)), sha),
    )
    doc_id = cur.lastrowid

    rows = parse_ecb_response(json.loads(resp.content))
    for period, rate in rows:
        conn.execute(
            "INSERT OR IGNORE INTO metrics"
            " (entity_id, metric_name, period, value, unit, currency, document_id,"
            "  extraction_confidence, notes)"
            " VALUES (?, 'fx_cny_per_eur_monthly_avg', ?, ?, 'CNY_per_EUR', NULL, ?, 1.0,"
            "  'ECB reference rate, monthly average')",
            (entity_id, period, rate, doc_id),
        )
    conn.commit()
    print(f"{len(rows)} months ({rows[0][0]} .. {rows[-1][0]}), document id={doc_id}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
