"""Export the metrics table to a CSV you can eyeball in a spreadsheet.

What this does: joins metrics with entities and documents and writes
data/exports/metrics.csv. If the same metric/period was ever ingested from
more than one raw document (e.g. a source revised its numbers), only the row
from the most recent document is exported — the older rows stay in the
database as provenance.

How you'd know it broke: it prints the row count and output path; the CSV
has a header row and one line per metric-period. Zero rows means the
collectors haven't run.
"""

import csv
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"
OUT_PATH = REPO_ROOT / "data" / "exports" / "metrics.csv"

QUERY = """
SELECT e.name_en AS entity,
       m.metric_name,
       m.period,
       m.value,
       m.unit,
       m.currency,
       m.extraction_confidence,
       d.url AS source_url,
       d.retrieved_at
FROM metrics m
JOIN entities e ON e.id = m.entity_id
JOIN documents d ON d.id = m.document_id
WHERE m.document_id = (
    SELECT MAX(m2.document_id) FROM metrics m2
    WHERE m2.entity_id = m.entity_id
      AND m2.metric_name = m.metric_name
      AND m2.period = m.period
)
ORDER BY m.metric_name, m.period
"""


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(QUERY).fetchall()
    conn.close()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", newline="") as f:
        writer = csv.writer(f)
        if rows:
            writer.writerow(rows[0].keys())
            for row in rows:
                writer.writerow(list(row))
    print(f"wrote {len(rows)} rows to {OUT_PATH.relative_to(REPO_ROOT)}")
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())
