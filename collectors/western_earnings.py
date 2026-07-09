"""Collector: Western semicap earnings documents (Phase 0: ASML only).

What this does: downloads ASML's latest quarterly investor-relations
presentation, saves an untouched raw copy under data/raw/asml/, and records
it in the `sources` and `documents` tables. Raw files are never overwritten,
and a document whose bytes we already have (same sha256) is skipped, so
re-running this script is always safe.

How you'd know it broke: run it and it prints either "ingested document id=N"
or "already have <url>". Any exception (network error, HTTP error, database
error) crashes loudly with a traceback and a non-zero exit code — it never
writes partial data silently.
"""

import datetime
import hashlib
import sqlite3
import sys
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"
RAW_DIR = REPO_ROOT / "data" / "raw" / "asml"

# Rule 7: identify honestly on every request.
USER_AGENT = "ChinaTechFlowsTracker/0.1 (research; contact: jx3@williams.edu)"

SOURCE = {
    "name": "ASML IR",
    "url": "https://www.asml.com/en/investors/financial-results",
    "type": "earnings",
    "language": "en",
}

# Phase 0: one known document, hardcoded. Later phases will discover the
# latest quarter automatically from the financial-results index page.
DOCUMENTS = [
    {
        "url": "https://ourbrand.asml.com/asset/d7b914e6-fdd1-4262-b805-d80f3efcb39a/2026_04_15_Presentation-Investor-Relations-Q1-2026.pdf",
        "title": "ASML Q1 2026 Investor Relations presentation",
        "doc_date": "2026-04-15",
        "filename": "2026-04-15_asml_ir_presentation_q1_2026.pdf",
    },
]


def connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_source(conn):
    """Insert the ASML IR source row if it doesn't exist; return its id."""
    conn.execute(
        "INSERT OR IGNORE INTO sources (name, url, type, language)"
        " VALUES (:name, :url, :type, :language)",
        SOURCE,
    )
    row = conn.execute(
        "SELECT id FROM sources WHERE name = ?", (SOURCE["name"],)
    ).fetchone()
    return row[0]


def fetch(url):
    print(f"fetching {url}")
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    resp.raise_for_status()
    return resp.content


def ingest_document(conn, source_id, url, content, title, doc_date, raw_path, repo_root=REPO_ROOT):
    """Save raw bytes and record one document row.

    Returns the new documents.id, or None if these exact bytes were already
    ingested (sha256 match — our duplicate guard).
    """
    sha = hashlib.sha256(content).hexdigest()
    existing = conn.execute(
        "SELECT id FROM documents WHERE sha256 = ?", (sha,)
    ).fetchone()
    if existing:
        return None

    raw_path.parent.mkdir(parents=True, exist_ok=True)
    if raw_path.exists():
        # Never overwrite: same name but different bytes gets a suffixed name.
        raw_path = raw_path.with_name(f"{raw_path.stem}_{sha[:8]}{raw_path.suffix}")
    raw_path.write_bytes(content)

    retrieved_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    cur = conn.execute(
        "INSERT INTO documents"
        " (source_id, url, retrieved_at, raw_path, sha256, doc_date, title, language)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            source_id,
            url,
            retrieved_at,
            str(raw_path.relative_to(repo_root)),
            sha,
            doc_date,
            title,
            "en",
        ),
    )
    return cur.lastrowid


def main():
    conn = connect()
    source_id = ensure_source(conn)
    for doc in DOCUMENTS:
        # Cache aggressively: never re-fetch a URL we already ingested.
        if conn.execute(
            "SELECT 1 FROM documents WHERE url = ?", (doc["url"],)
        ).fetchone():
            print(f"already have {doc['url']}")
            continue
        content = fetch(doc["url"])
        doc_id = ingest_document(
            conn,
            source_id,
            doc["url"],
            content,
            doc["title"],
            doc["doc_date"],
            RAW_DIR / doc["filename"],
        )
        if doc_id is None:
            print(f"identical bytes already ingested, skipping {doc['url']}")
        else:
            print(f"ingested document id={doc_id} ({len(content)} bytes)")
    conn.commit()
    conn.close()


if __name__ == "__main__":
    sys.exit(main())
