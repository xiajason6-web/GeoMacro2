"""Collector: ECB reference rates -> the fx_rates table (USD per unit).

Why: the tracker aggregates trade values reported in EUR, JPY, USD and CNY.
Rule: NEVER sum native-currency values — everything converts to USD through
fx_rates first (analysis reads only this table for conversion).

What this does: fetches three ECB monthly-average series (CNY/EUR, USD/EUR,
JPY/EUR — free, keyless, official), derives USD-per-unit for each currency
(EUR direct; CNY and JPY as EUR crosses; USD = 1.0 by definition), and
upserts fx_rates keyed (currency, period). Rows only change when the ECB
revises or extends a series — change detection is on VALUES, not response
bytes, because ECB responses embed a timestamp and hash differently on
every fetch.

How you'd know it broke: prints per-currency month counts; a missing recent
month means the ECB hasn't published it or this collector stopped running.
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

SINCE = "2023-01"
ECB_SERIES = {
    "CNY": f"https://data-api.ecb.europa.eu/service/data/EXR/M.CNY.EUR.SP00.A?startPeriod={SINCE}&format=jsondata",
    "USD": f"https://data-api.ecb.europa.eu/service/data/EXR/M.USD.EUR.SP00.A?startPeriod={SINCE}&format=jsondata",
    "JPY": f"https://data-api.ecb.europa.eu/service/data/EXR/M.JPY.EUR.SP00.A?startPeriod={SINCE}&format=jsondata",
}

SOURCE = {
    "name": "ECB reference rates",
    "url": "https://data.ecb.europa.eu",
    "type": "trade_stats",
    "language": "en",
}


def connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def parse_ecb_response(payload):
    """SDMX-JSON -> {period 'YYYY-MM': units_per_eur}."""
    observations = payload["dataSets"][0]["series"]["0:0:0:0:0"]["observations"]
    periods = [
        v["id"] for v in payload["structure"]["dimensions"]["observation"][0]["values"]
    ]
    return {
        period: float(observations[str(i)][0])
        for i, period in enumerate(periods)
        if str(i) in observations
    }


def usd_per_unit_rates(per_eur):
    """{currency: {period: units_per_eur}} -> {currency: {period: usd_per_unit}}.

    usd_per_eur is direct; crosses: usd_per_X = usd_per_eur / X_per_eur.
    USD itself is 1.0 for every period the USD/EUR series covers.
    """
    usd_eur = per_eur["USD"]
    out = {"EUR": dict(usd_eur), "USD": {p: 1.0 for p in usd_eur}}
    for currency in ("CNY", "JPY"):
        out[currency] = {
            p: usd_eur[p] / rate
            for p, rate in per_eur[currency].items()
            if p in usd_eur and rate
        }
    return out


def archive_raw(conn, source_id, currency, url, content):
    """Store the raw ECB response once per distinct byte content."""
    sha = hashlib.sha256(content).hexdigest()
    row = conn.execute("SELECT id FROM documents WHERE sha256 = ?", (sha,)).fetchone()
    if row:
        return row[0]
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
    raw_path = RAW_DIR / f"{stamp}_ecb_{currency.lower()}_per_eur.json"
    if raw_path.exists():
        raw_path = raw_path.with_name(f"{raw_path.stem}_{sha[:8]}.json")
    raw_path.write_bytes(content)
    retrieved_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return conn.execute(
        "INSERT INTO documents"
        " (source_id, url, retrieved_at, raw_path, sha256, doc_date, title, language)"
        " VALUES (?, ?, ?, ?, ?, NULL, ?, 'en')",
        (
            source_id,
            url,
            retrieved_at,
            str(raw_path.relative_to(REPO_ROOT)),
            sha,
            f"ECB {currency} per EUR monthly average",
        ),
    ).lastrowid


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

    per_eur, raw = {}, {}
    for currency, url in ECB_SERIES.items():
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=120)
        resp.raise_for_status()
        per_eur[currency] = parse_ecb_response(json.loads(resp.content))
        raw[currency] = (url, resp.content)

    rates = usd_per_unit_rates(per_eur)

    # Value-level change detection: only touch fx_rates (and only archive the
    # raw response) when a period's rate is new or actually different.
    changed_currencies = set()
    for currency, series in rates.items():
        existing = dict(
            conn.execute(
                "SELECT period, usd_per_unit FROM fx_rates WHERE currency = ?",
                (currency,),
            )
        )
        delta = {
            p: v
            for p, v in series.items()
            if p not in existing or abs(existing[p] - v) > 1e-12
        }
        if not delta:
            print(f"{currency}: unchanged ({len(series)} months)")
            continue
        # USD rows derive from the USD/EUR response; crosses from their own.
        src_currency = currency if currency in raw else "USD"
        url, content = raw[src_currency]
        doc_id = archive_raw(conn, source_id, src_currency, url, content)
        for period, value in delta.items():
            conn.execute(
                "INSERT OR REPLACE INTO fx_rates"
                " (currency, period, usd_per_unit, document_id) VALUES (?, ?, ?, ?)",
                (currency, period, value, doc_id),
            )
        changed_currencies.add(currency)
        print(
            f"{currency}: {len(delta)} new/revised months"
            f" ({min(delta)} .. {max(delta)}), document id={doc_id}"
        )

    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM fx_rates").fetchone()[0]
    print(f"fx_rates table: {total} rows")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
