"""Seed the benchmarks table: published third-party indigenization estimates.

What this does: registers the archived source pages (data/raw/benchmarks/)
as documents and inserts the SEED rows below. The seeds are hand-written
code — reviewable in a git diff like the exposure map — and every value was
read from the archived page, not from memory. A figure whose source page
could not be archived does NOT get seeded (e.g. Yole's 23%, paywalled) and
sits in review_queue instead.

How you'd know it broke: prints rows inserted; UNIQUE(source, period) makes
re-runs no-ops.
"""

import datetime
import hashlib
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"
RAW_DIR = REPO_ROOT / "data" / "raw" / "benchmarks"

SOURCE = {
    "name": "Third-party benchmarks",
    "url": "https://github.com/xiajason6-web/GeoMacro2",
    "type": "press",
    "language": "en",
}

# archive_file -> the already-downloaded page under data/raw/benchmarks/
SEEDS = [
    {
        "source": "Bernstein (via BigGo Finance)",
        "archive_file": "20260713_biggo_bernstein.html",
        "source_url": "https://finance.biggo.com/news/71354c86-2831-4eed-be01-cc593e5faf88",
        "numerator_scope": "Chinese vendors' semiconductor-equipment sales (all domestic vendors)",
        "denominator_scope": "China semiconductor equipment market",
        "rows": [
            ("2024", 13.0, "'approximately 13% in 2024'; baseline 4% in 2018"),
            ("2025", 21.0, "'reaching about 21% in 2025'; by category: etch ~31%, thin-film ~27%, litho/metrology <10%"),
        ],
    },
    {
        "source": "UBS (via EE Times)",
        "archive_file": "20260713_eetimes.html",
        "source_url": "https://www.eetimes.com/how-china-struggles-to-reach-wfe-self-sufficiency/",
        "numerator_scope": "ACM Research + AMEC + Naura ONLY (3 companies — narrower than this tracker's 6)",
        "denominator_scope": "China total WFE outlays (~$42.75bn in 2024 per UBS)",
        "rows": [
            ("2025", 20.0, "'about 20% of China's total WFE outlays in 2025'"),
            ("2026E", 24.0, "UBS projection"),
            ("2027E", 31.0, "UBS projection"),
        ],
    },
    {
        "source": "CSIS",
        "archive_file": "20260713_csis.html",
        "source_url": "https://www.csis.org/analysis/chinas-localization-drive-semiconductors-gains-impetus-allied-chip-export-controls",
        "numerator_scope": "Chinese-made semiconductor manufacturing equipment",
        "denominator_scope": "China domestic equipment market",
        "rows": [
            ("2024", 25.0, "'surged from 25 percent to 35 percent of the market between 2024 and 2025'"),
            ("2025", 35.0, "same passage; CSIS notes gains 'probably reflect sales of equipment serving the mature nodes'; exceeds MIC2025 30% target"),
        ],
    },
]


def connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def register_document(conn, source_id, seed):
    path = RAW_DIR / seed["archive_file"]
    content = path.read_bytes()
    sha = hashlib.sha256(content).hexdigest()
    row = conn.execute("SELECT id FROM documents WHERE sha256 = ?", (sha,)).fetchone()
    if row:
        return row[0]
    retrieved_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return conn.execute(
        "INSERT INTO documents"
        " (source_id, url, retrieved_at, raw_path, sha256, doc_date, title, language)"
        " VALUES (?, ?, ?, ?, ?, NULL, ?, 'en')",
        (
            source_id,
            seed["source_url"],
            retrieved_at,
            str(path.relative_to(REPO_ROOT)),
            sha,
            f"benchmark source: {seed['source']}",
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

    inserted = 0
    for seed in SEEDS:
        if not (RAW_DIR / seed["archive_file"]).exists():
            print(f"MISSING archive for {seed['source']} — rows NOT seeded")
            continue
        doc_id = register_document(conn, source_id, seed)
        for period, value, note in seed["rows"]:
            cur = conn.execute(
                "INSERT OR IGNORE INTO benchmarks"
                " (source, period, value, numerator_scope, denominator_scope,"
                "  method_notes, source_url, document_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    seed["source"], period, value, seed["numerator_scope"],
                    seed["denominator_scope"], note, seed["source_url"], doc_id,
                ),
            )
            inserted += cur.rowcount
    # Unverifiable user-cited figure — tracked, never seeded on faith.
    reason = (
        "benchmark citation pending: Yole ~23% (2025?) — yolegroup.com blocks"
        " fetching; needs manual capture of the report/billet before seeding"
    )
    if not conn.execute(
        "SELECT 1 FROM review_queue WHERE reason = ?", (reason,)
    ).fetchone():
        conn.execute(
            "INSERT INTO review_queue (item_type, item_id, reason)"
            " VALUES ('benchmark', NULL, ?)",
            (reason,),
        )
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM benchmarks").fetchone()[0]
    print(f"{inserted} benchmark rows inserted (table: {total})")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
