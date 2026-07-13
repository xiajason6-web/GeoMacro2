"""Derive the audited numerator: domestic semicap revenue per quarter.

    domestic_semicap_revenue_cny(q) =
        quarterly_revenue_cny(q)            # extracted or DERIVED (Q2/Q4)
      x semicap_segment_share_pct(year)/100  # from annual 分行业 tables
      x domestic_revenue_share_pct(year)/100 # from annual 分地区 tables

Pure Python arithmetic — no LLM near any number. Both the total revenue and
this derived figure live in `metrics`, so the difference is auditable row
by row. Flags carried in notes:
  ESTIMATED(share-year): a quarter after the last disclosed fiscal year uses
      the most recent disclosed shares (e.g. 2026 quarters use FY2025).
  ESTIMATED(no-domestic-split): no 分地区 disclosure at all -> 100% domestic
      assumed and the company-year is flagged to review_queue.
Re-runs recompute in place (INSERT OR REPLACE on the same document_id).

How you'd know it broke: prints one line per company with quarter count and
the applied shares; tests in tests/test_domestic_semicap.py pin the math.
"""

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"

METRIC_OUT = "domestic_semicap_revenue_cny"


def connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def year_shares(conn, entity_id, metric):
    """{fiscal year: (value, confidence)} for a share metric, latest doc wins."""
    rows = conn.execute(
        "SELECT period, value, COALESCE(extraction_confidence, 1.0) FROM metrics"
        " WHERE entity_id = ? AND metric_name = ?"
        " ORDER BY document_id",
        (entity_id, metric),
    ).fetchall()
    return {period: (value, conf) for period, value, conf in rows}


def pick_share(shares, year):
    """(value, confidence, estimated_flag) — exact year, else most recent
    earlier year (flagged), else earliest (flagged), else None."""
    if year in shares:
        v, c = shares[year]
        return v, c, False
    if not shares:
        return None
    earlier = [y for y in shares if y <= year]
    pick = max(earlier) if earlier else min(shares)
    v, c = shares[pick]
    return v, c, True


def derive_for_entity(conn, entity_id, name_en):
    seg_shares = year_shares(conn, entity_id, "semicap_segment_share_pct")
    dom_shares = year_shares(conn, entity_id, "domestic_revenue_share_pct")

    quarters = conn.execute(
        "SELECT m.period, m.value, COALESCE(m.extraction_confidence, 1.0), m.document_id"
        " FROM metrics m"
        " WHERE m.entity_id = ? AND m.metric_name = 'quarterly_revenue_cny'"
        " AND m.document_id = (SELECT MAX(m2.document_id) FROM metrics m2"
        "   WHERE m2.entity_id = m.entity_id AND m2.metric_name = m.metric_name"
        "   AND m2.period = m.period)"
        " ORDER BY m.period",
        (entity_id,),
    ).fetchall()
    if not quarters:
        return 0

    n = 0
    for period, revenue, rev_conf, rev_doc in quarters:
        year = period[:4]
        flags = []

        seg = pick_share(seg_shares, year)
        if seg is None:
            conn.execute(
                "INSERT INTO review_queue (item_type, item_id, reason)"
                " VALUES ('derivation', ?, ?)",
                (entity_id, f"{name_en}: no semicap segment share for any year"),
            )
            return 0
        seg_v, seg_c, seg_est = seg
        if seg_est:
            flags.append("ESTIMATED(share-year)")

        dom = pick_share(dom_shares, year)
        if dom is None:
            dom_v, dom_c, dom_est = 100.0, 1.0, True
            flags.append("ESTIMATED(no-domestic-split)")
            conn.execute(
                "INSERT INTO review_queue (item_type, item_id, reason)"
                " VALUES ('derivation', ?, ?)",
                (entity_id, f"{name_en}: no 分地区 disclosure — 100% domestic assumed"),
            )
        else:
            dom_v, dom_c, dom_est = dom
            if dom_est and "ESTIMATED(share-year)" not in flags:
                flags.append("ESTIMATED(share-year)")

        value = revenue * (seg_v / 100.0) * (dom_v / 100.0)
        confidence = round(min(rev_conf, seg_c, dom_c), 2)
        note = (
            f"DERIVED (python): quarterly_revenue x {seg_v:.1f}% semicap"
            f" x {dom_v:.1f}% domestic"
            + (" | " + " ".join(flags) if flags else "")
        )
        conn.execute(
            "INSERT OR REPLACE INTO metrics"
            " (entity_id, metric_name, period, value, unit, currency, document_id,"
            "  extraction_confidence, notes)"
            " VALUES (?, ?, ?, ?, 'CNY', 'CNY', ?, ?, ?)",
            (entity_id, METRIC_OUT, period, value, rev_doc, confidence, note),
        )
        n += 1
    print(f"{name_en}: {n} quarters (semicap {sorted(seg_shares) or '-'}, domestic {sorted(dom_shares) or '-'})")
    return n


def main():
    conn = connect()
    companies = conn.execute(
        "SELECT id, name_en FROM entities"
        " WHERE entity_type = 'company' AND supply_chain_layer = 'equipment'"
        " ORDER BY id"
    ).fetchall()
    total = 0
    for entity_id, name_en in companies:
        total += derive_for_entity(conn, entity_id, name_en)
    conn.commit()
    print(f"\n{total} domestic-semicap quarters derived/updated")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
