"""Collector: China customs (GACC) imports of HS 8486/8542 — currently blocked.

What this does: attempts to reach China's official customs statistics portal
(stats.customs.gov.cn). As of July 2026 the portal sits behind an anti-bot
gate (HTTP 412) that we will not try to evade — rule 7. When the fetch
fails, this script records the failure in `review_queue` (so the gap is
visible in the database, not just in a terminal scrollback) and exits
non-zero.

In the meantime, mirror trade (collectors/mirror_trade.py — partner-country
exports to China) covers the same economic quantity from the other side of
the border, which is what the Phase 3 indigenization ratio needs.

Manual fallback for later: the GACC query platform allows human downloads of
monthly CSV files. If we adopt that, this script becomes the ingester for
files you download by hand into data/inbox/.

How you'd know it broke: it either prints an ingest summary (if GACC ever
becomes reachable) or "flagged for review". A silent exit is impossible.
"""

import datetime
import sqlite3
import sys
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"
USER_AGENT = "ChinaTechFlowsTracker/0.1 (research; contact: jx3@williams.edu)"

GACC_URL = "http://stats.customs.gov.cn/"


def connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def main():
    conn = connect()
    try:
        resp = requests.get(
            GACC_URL, headers={"User-Agent": USER_AGENT}, timeout=30
        )
        status = resp.status_code
    except requests.RequestException as exc:
        status = f"request failed: {exc}"

    if status == 200:
        print(
            "GACC portal responded 200 — the anti-bot gate may have lifted."
            " The query collector is not implemented yet; flagging so we"
            " revisit."
        )
        reason = "GACC portal reachable (HTTP 200) — implement query collector"
    else:
        reason = (
            f"GACC portal not automatable (got: {status}); using mirror trade"
            " (partner exports to China) until resolved"
        )
        print(reason)

    today = datetime.date.today().isoformat()
    # One review item per day at most — don't spam the queue on re-runs.
    already = conn.execute(
        "SELECT 1 FROM review_queue WHERE item_type = 'collector'"
        " AND reason LIKE 'GACC%' AND date(created_at) = ?",
        (today,),
    ).fetchone()
    if not already:
        conn.execute(
            "INSERT INTO review_queue (item_type, item_id, reason) VALUES (?, NULL, ?)",
            ("collector", reason),
        )
        conn.commit()
        print("flagged for review")
    else:
        print("already flagged today")
    conn.close()
    return 1


if __name__ == "__main__":
    sys.exit(main())
