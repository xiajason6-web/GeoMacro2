"""Collector: China domestic IC output (NBS) — currently geo-blocked.

What this does: attempts to reach China's National Bureau of Statistics data
API (data.stats.gov.cn/easyquery.htm) for the monthly "集成电路产量" (integrated
circuit output) series — the canonical official measure of how many chips China
actually produces. As of July 2026 the endpoint returns HTTP 403 to non-China
IPs (an edge geo-block, not just a bot check); we will not try to evade it
(rule 7). When the fetch fails, this script records the gap in `review_queue`
so the missing national-output series is visible in the database, then exits
non-zero — exactly like collectors/customs_imports.py does for GACC.

Why it matters: the equipment indigenization ratio has a real domestic-output
numerator (listed toolmakers). The CHIP layer does not — no domestic IC-output
series is machine-readable from here. NBS national output would be the clean
one; CXMT (DRAM) and YMTC (NAND) are unlisted so publish nothing. Until NBS is
reachable, analysis/chip_self_sufficiency.py uses an INTERIM PROXY: the
combined revenue of the two listed pure-play foundries (SMIC + Hua Hong) as a
floor on domestic logic output. That proxy is directional only (foundries also
serve non-China customers and exclude memory/IDM/captive output).

Manual fallback for later: NBS output is republished in the monthly statistical
communiqués (PDF) and in the annual yearbook; if we adopt those this script
becomes the ingester for files downloaded by hand into data/inbox/.

How you'd know it broke: it prints an ingest summary (if NBS ever becomes
reachable) or "flagged for review". A silent exit is impossible.
"""

import datetime
import sqlite3
import sys
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"
USER_AGENT = "ChinaTechFlowsTracker/0.1 (research; contact: jx3@williams.edu)"

# Monthly IC-output indicator (集成电路产量, 当期值) in the NBS monthly DB (hgyd).
NBS_URL = "https://data.stats.gov.cn/easyquery.htm"
NBS_PARAMS = {
    "m": "QueryData", "dbcode": "hgyd", "rowcode": "zb", "colcode": "sj",
    "wds": "[]", "dfwds": '[{"wdcode":"zb","valuecode":"A020H0K"}]',
}


def connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def main():
    conn = connect()
    try:
        resp = requests.get(
            NBS_URL, params=NBS_PARAMS,
            headers={"User-Agent": USER_AGENT}, timeout=30,
        )
        status = resp.status_code
        # A real data payload is JSON with returndata; a block is HTML/403.
        looks_like_data = (
            status == 200 and "returndata" in resp.text and "returncode" in resp.text
        )
    except requests.RequestException as exc:
        status, looks_like_data = f"request failed: {exc}", False

    if looks_like_data:
        print(
            "NBS easyquery returned data — the geo-block may have lifted. The"
            " parser is not implemented yet; flagging so we build it."
        )
        reason = "NBS IC-output reachable (HTTP 200 data) — implement parser"
    else:
        reason = (
            f"NBS national IC-output not automatable (got: {status}); using"
            " SMIC+Hua Hong foundry-revenue proxy in chip_self_sufficiency.py"
            " until resolved"
        )
        print(reason)

    today = datetime.date.today().isoformat()
    already = conn.execute(
        "SELECT 1 FROM review_queue WHERE item_type = 'collector'"
        " AND reason LIKE 'NBS%' AND date(created_at) = ?",
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
