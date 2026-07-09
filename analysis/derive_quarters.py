"""Derive missing single quarters from cumulative figures. Pure arithmetic.

What this does (deterministic Python — no LLM near any number):
    Q2 = H1 - Q1
    Q3 = YTD9M - H1          (only where the Q3 report lacked a quarterly figure)
    Q4 = FY - H1 - Q3
Each derived value is written to `metrics` as quarterly_revenue_cny with
notes starting 'DERIVED', confidence = min of the inputs' confidences, and
document_id = the cumulative document it was derived from. A derivation is
only performed when the target quarter is missing, and a result that is
negative or exceeds its minuend goes to review_queue instead of metrics.

How you'd know it broke: prints each derivation with its inputs; the tests
in tests/test_derive_quarters.py pin the arithmetic and the sanity guards.
"""

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"

YEARS = ["2023", "2024", "2025"]


def connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_metric(conn, entity_id, metric, period):
    """Latest-document row for (entity, metric, period) -> (value, confidence,
    document_id, metric_id) or None."""
    row = conn.execute(
        "SELECT value, COALESCE(extraction_confidence, 1.0), document_id, id"
        " FROM metrics WHERE entity_id = ? AND metric_name = ? AND period = ?"
        " ORDER BY document_id DESC LIMIT 1",
        (entity_id, metric, period),
    ).fetchone()
    return row


def insert_derived(conn, entity_id, period, value, confidence, source_doc_id, formula, input_ids):
    conn.execute(
        "INSERT OR IGNORE INTO metrics"
        " (entity_id, metric_name, period, value, unit, currency, document_id,"
        "  extraction_confidence, notes)"
        " VALUES (?, 'quarterly_revenue_cny', ?, ?, 'CNY', 'CNY', ?, ?, ?)",
        (
            entity_id,
            period,
            value,
            source_doc_id,
            confidence,
            f"DERIVED (python): {formula} | input metric ids: {input_ids}",
        ),
    )


def derive_for_entity(conn, entity_id, name_en):
    """Run all derivations for one company. Returns list of (period, value)."""
    results = []
    for year in YEARS:
        q1 = get_metric(conn, entity_id, "quarterly_revenue_cny", f"{year}Q1")
        q3 = get_metric(conn, entity_id, "quarterly_revenue_cny", f"{year}Q3")
        h1 = get_metric(conn, entity_id, "h1_revenue_cny", f"{year}H1")
        fy = get_metric(conn, entity_id, "fy_revenue_cny", year)
        ytd9 = get_metric(conn, entity_id, "ytd9m_revenue_cny", f"{year}YTD9M")

        # Q3 first (a derived Q3 feeds the Q4 derivation below).
        if q3 is None and ytd9 and h1:
            value = ytd9[0] - h1[0]
            if 0 < value < ytd9[0]:
                conf = round(min(ytd9[1], h1[1]), 2)
                insert_derived(
                    conn, entity_id, f"{year}Q3", value, conf, ytd9[2],
                    f"YTD9M({year}) - H1({year})", [ytd9[3], h1[3]],
                )
                results.append((f"{year}Q3", value))
                q3 = get_metric(conn, entity_id, "quarterly_revenue_cny", f"{year}Q3")
            else:
                flag(conn, entity_id, f"{name_en} {year}Q3 derivation implausible: {value:,.0f}")

        if get_metric(conn, entity_id, "quarterly_revenue_cny", f"{year}Q2") is None and h1 and q1:
            value = h1[0] - q1[0]
            if 0 < value < h1[0]:
                conf = round(min(h1[1], q1[1]), 2)
                insert_derived(
                    conn, entity_id, f"{year}Q2", value, conf, h1[2],
                    f"H1({year}) - Q1({year})", [h1[3], q1[3]],
                )
                results.append((f"{year}Q2", value))
            else:
                flag(conn, entity_id, f"{name_en} {year}Q2 derivation implausible: {value:,.0f}")

        if get_metric(conn, entity_id, "quarterly_revenue_cny", f"{year}Q4") is None and fy and h1 and q3:
            value = fy[0] - h1[0] - q3[0]
            if 0 < value < fy[0]:
                conf = round(min(fy[1], h1[1], q3[1]), 2)
                insert_derived(
                    conn, entity_id, f"{year}Q4", value, conf, fy[2],
                    f"FY({year}) - H1({year}) - Q3({year})", [fy[3], h1[3], q3[3]],
                )
                results.append((f"{year}Q4", value))
            else:
                flag(conn, entity_id, f"{name_en} {year}Q4 derivation implausible: {value:,.0f}")
    return results


def flag(conn, entity_id, reason):
    conn.execute(
        "INSERT INTO review_queue (item_type, item_id, reason)"
        " VALUES ('derivation', ?, ?)",
        (entity_id, reason),
    )
    print(f"  !! {reason} — flagged for review")


def main():
    conn = connect()
    companies = conn.execute(
        "SELECT id, name_en FROM entities WHERE entity_type = 'company' ORDER BY id"
    ).fetchall()
    total = 0
    for entity_id, name_en in companies:
        results = derive_for_entity(conn, entity_id, name_en)
        for period, value in results:
            print(f"{name_en} {period}: {value:,.0f} CNY (derived)")
        total += len(results)
    conn.commit()
    print(f"\n{total} quarters derived")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
