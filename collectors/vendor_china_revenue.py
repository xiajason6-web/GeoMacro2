"""Collector: foreign vendors' SEC filings (China revenue disclosures).

Why: ASML/AMAT/Lam/KLA report weeks before Chinese quarterly filings and
disclose China revenue share — the single best leading indicator for the
import side of the indigenization ratio.

What this does: for each US-listed vendor, pulls the SEC EDGAR submissions
index (free JSON, honest UA required), archives the latest 10-Q/10-K primary
documents, and records them in `documents`. Extraction of the China share is
a separate LLM step (extraction/extract_vendor_china.py) that also emits
hifreq_signals rows. ASML is collected by western_earnings.py (IR PDFs);
TEL (Japanese IR) is deferred — tracked in review_queue.

Vendors get supply_chain_layer='equipment_foreign' so they can NEVER leak
into the domestic-equipment numerator (which filters layer='equipment').

How you'd know it broke: prints per-vendor filings found/ingested; a vendor
that stops appearing here after an earnings date means EDGAR moved.
"""

import datetime
import hashlib
import sqlite3
import sys
import time
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"
RAW_DIR = REPO_ROOT / "data" / "raw" / "sec_vendors"
USER_AGENT = "ChinaTechFlowsTracker/0.2 (research; contact: jx3@williams.edu)"

N_FILINGS = 6  # latest 10-Q/10-K per vendor (≈ 4 quarters + annual)

SOURCE = {
    "name": "SEC EDGAR",
    "url": "https://www.sec.gov/cgi-bin/browse-edgar",
    "type": "earnings",
    "language": "en",
}

VENDORS = [
    {"cik": "0000006951", "name_en": "Applied Materials", "ticker": "AMAT"},
    {"cik": "0000707549", "name_en": "Lam Research", "ticker": "LRCX"},
    {"cik": "0000319201", "name_en": "KLA", "ticker": "KLAC"},
]


def connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_vendor_entity(conn, vendor):
    conn.execute(
        "INSERT OR IGNORE INTO entities"
        " (name_en, name_zh, ticker, exchange, entity_type, supply_chain_layer)"
        " VALUES (?, NULL, ?, 'NASDAQ', 'company', 'equipment_foreign')",
        (vendor["name_en"], vendor["ticker"]),
    )
    return conn.execute(
        "SELECT id FROM entities WHERE name_en = ?", (vendor["name_en"],)
    ).fetchone()[0]


def recent_filings(payload, n=N_FILINGS):
    """Submissions JSON -> latest n 10-Q/10-K as dicts (deterministic)."""
    r = payload["filings"]["recent"]
    out = []
    for form, date, acc, doc, report_date in zip(
        r["form"], r["filingDate"], r["accessionNumber"],
        r["primaryDocument"], r["reportDate"],
    ):
        if form in ("10-Q", "10-K"):
            out.append(
                {
                    "form": form,
                    "filing_date": date,
                    "accession": acc,
                    "primary_doc": doc,
                    "report_date": report_date,
                }
            )
        if len(out) >= n:
            break
    return out


def filing_url(cik, filing):
    acc = filing["accession"].replace("-", "")
    return (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/"
        f"{filing['primary_doc']}"
    )


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

    for vendor in VENDORS:
        ensure_vendor_entity(conn, vendor)
        resp = session.get(
            f"https://data.sec.gov/submissions/CIK{vendor['cik']}.json", timeout=60
        )
        resp.raise_for_status()
        filings = recent_filings(resp.json())
        ingested = 0
        for filing in filings:
            url = filing_url(vendor["cik"], filing)
            if conn.execute(
                "SELECT 1 FROM documents WHERE url = ?", (url,)
            ).fetchone():
                continue
            doc_resp = session.get(url, timeout=120)
            doc_resp.raise_for_status()
            sha = hashlib.sha256(doc_resp.content).hexdigest()
            if conn.execute(
                "SELECT 1 FROM documents WHERE sha256 = ?", (sha,)
            ).fetchone():
                continue
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            raw_path = RAW_DIR / (
                f"{filing['filing_date']}_{vendor['ticker'].lower()}"
                f"_{filing['form'].replace('-', '').lower()}_{filing['report_date']}.htm"
            )
            raw_path.write_bytes(doc_resp.content)
            retrieved_at = datetime.datetime.now(datetime.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            conn.execute(
                "INSERT INTO documents"
                " (source_id, url, retrieved_at, raw_path, sha256, doc_date, title, language)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'en')",
                (
                    source_id, url, retrieved_at,
                    str(raw_path.relative_to(REPO_ROOT)), sha,
                    filing["filing_date"],
                    f"{vendor['name_en']} {filing['form']} (period ended {filing['report_date']})",
                ),
            )
            ingested += 1
            time.sleep(0.5)  # SEC fair-access
        print(f"{vendor['name_en']}: {len(filings)} filings found, {ingested} new ingested")
        conn.commit()
        time.sleep(0.5)

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
