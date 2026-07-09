"""Collector: BIS Entity List actions from the Federal Register.

What this does: queries the Federal Register API (free, official, JSON) for
Bureau of Industry and Security rules mentioning the Entity List since
2023-07, saves the raw response, and writes one `events` row per rule —
event_date, actor 'BIS', category 'entity_list' (title names the Entity
List) or 'export_control' (related BIS rule). No LLM: the API returns
structured English titles and abstracts, so ingestion is deterministic.
summary_zh stays NULL — translation is an extraction-layer job for later.

How you'd know it broke: prints "N rules, M new events". If BIS publishes a
rule and it never shows up here, the term filter or the API changed.
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
RAW_DIR = REPO_ROOT / "data" / "raw" / "federal_register"
USER_AGENT = "ChinaTechFlowsTracker/0.1 (research; contact: jx3@williams.edu)"

SINCE = "2023-07-01"
API_URL = "https://www.federalregister.gov/api/v1/documents.json"
PARAMS = {
    "conditions[agencies][]": "industry-and-security-bureau",
    "conditions[term]": '"entity list"',
    "conditions[type][]": "RULE",
    "conditions[publication_date][gte]": SINCE,
    "per_page": "100",
    "order": "newest",
    "fields[]": ["title", "publication_date", "document_number", "html_url", "abstract"],
}

SOURCE = {
    "name": "Federal Register",
    "url": "https://www.federalregister.gov",
    "type": "regulatory",
    "language": "en",
}


def connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def fetch_all_pages(session):
    """Follow next_page_url until exhausted; return (results, raw_pages)."""
    results, raw_pages = [], []
    url, params = API_URL, PARAMS
    while url:
        resp = session.get(url, params=params, timeout=60)
        resp.raise_for_status()
        raw_pages.append(resp.content)
        payload = resp.json()
        results.extend(payload.get("results") or [])
        url, params = payload.get("next_page_url"), None
    return results, raw_pages


def categorize(title):
    return "entity_list" if "entity list" in title.lower() else "export_control"


def summarize(rule):
    abstract = (rule.get("abstract") or "").strip()
    summary = rule["title"].strip()
    if abstract:
        summary += " — " + abstract
    return summary[:1000] + f" [{rule['html_url']}]"


def ingest(conn, source_id, rules, raw_pages):
    """Save raw pages as documents; insert one event per rule, deduped by
    (event_date, document_number embedded in summary is overkill) — we dedupe
    on event_date + title prefix, which is stable across refetches."""
    content = b"\n".join(raw_pages)
    sha = hashlib.sha256(content).hexdigest()
    existing = conn.execute(
        "SELECT id FROM documents WHERE sha256 = ?", (sha,)
    ).fetchone()
    if existing:
        doc_id = existing[0]
    else:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
        raw_path = RAW_DIR / f"{stamp}_bis_entity_list_rules.json"
        if raw_path.exists():
            raw_path = raw_path.with_name(f"{raw_path.stem}_{sha[:8]}.json")
        raw_path.write_bytes(content)
        retrieved_at = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        doc_id = conn.execute(
            "INSERT INTO documents"
            " (source_id, url, retrieved_at, raw_path, sha256, doc_date, title, language)"
            " VALUES (?, ?, ?, ?, ?, NULL, 'BIS entity-list rules (Federal Register API)', 'en')",
            (
                source_id,
                API_URL,
                retrieved_at,
                str(raw_path.relative_to(REPO_ROOT)),
                sha,
            ),
        ).lastrowid

    new_events = 0
    for rule in rules:
        title = rule["title"].strip()
        already = conn.execute(
            "SELECT 1 FROM events WHERE event_date = ? AND summary_en LIKE ?",
            (rule["publication_date"], title[:80] + "%"),
        ).fetchone()
        if already:
            continue
        conn.execute(
            "INSERT INTO events (event_date, category, actor, summary_en, summary_zh, document_id)"
            " VALUES (?, ?, 'BIS', ?, NULL, ?)",
            (rule["publication_date"], categorize(title), summarize(rule), doc_id),
        )
        new_events += 1
    return new_events


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

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    rules, raw_pages = fetch_all_pages(session)
    new_events = ingest(conn, source_id, rules, raw_pages)
    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    print(f"{len(rules)} rules fetched, {new_events} new events (events table: {total})")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
