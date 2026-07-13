"""Collector: Big Fund (国家集成电路产业投资基金) announcements from cninfo.

Why: shareholder-registration changes involving the National IC Fund —
stake increases, reductions, new investments — are a high-frequency signal
of state capital allocation across the sector, visible in listed-company
announcements weeks before any policy write-up.

What this does: full-text searches cninfo announcements for the fund's name
over the last 400 days, archives the result JSON, and writes one
hifreq_signals row per announcement (signal_type 'big_fund_announcement',
entity linked when the company is one we track). Announcement PDFs are not
downloaded — the title + link is the signal; deep-dives are manual.

How you'd know it broke: prints announcements found / new signals; the Big
Fund makes moves every few weeks, so a long silence is suspicious.
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
RAW_DIR = REPO_ROOT / "data" / "raw" / "big_fund"
USER_AGENT = "ChinaTechFlowsTracker/0.2 (research; contact: jx3@williams.edu)"

QUERY_API = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
STATIC_HOST = "https://static.cninfo.com.cn/"
SEARCH_KEY = "国家集成电路产业投资基金"
LOOKBACK_DAYS = 400

SOURCE = {
    "name": "cninfo Big Fund search",
    "url": "https://www.cninfo.com.cn",
    "type": "filing",
    "language": "zh",
}


def connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def fetch_announcements(session, column, se_date):
    """One page of full-text search results for the fund name."""
    resp = session.post(
        QUERY_API,
        data={
            "pageNum": "1",
            "pageSize": "30",
            "column": column,
            "tabName": "fulltext",
            "plate": "",
            "stock": "",
            "searchkey": SEARCH_KEY,
            "secid": "",
            "category": "",
            "trade": "",
            "seDate": se_date,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.content, resp.json().get("announcements") or []


def parse_announcements(announcements):
    """Deterministic: cninfo rows -> signal dicts."""
    out = []
    for ann in announcements:
        title = (ann.get("announcementTitle") or "").replace("<em>", "").replace("</em>", "")
        url_part = ann.get("adjunctUrl") or ""
        date = url_part.split("/")[1] if "/" in url_part else None
        if not title or not date:
            continue
        out.append(
            {
                "date": date,
                "sec_code": ann.get("secCode") or "",
                "sec_name": (ann.get("secName") or "").strip(),
                "title": title.strip(),
                "url": STATIC_HOST + url_part,
            }
        )
    return out


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

    today = datetime.date.today()
    se_date = f"{today - datetime.timedelta(days=LOOKBACK_DAYS)}~{today}"
    retrieved_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    new_signals = 0
    for column in ("szse", "sse"):
        content, announcements = fetch_announcements(session, column, se_date)
        signals = parse_announcements(announcements)
        print(f"{column}: {len(signals)} announcements mentioning the Big Fund")

        sha = hashlib.sha256(content).hexdigest()
        row = conn.execute(
            "SELECT id FROM documents WHERE sha256 = ?", (sha,)
        ).fetchone()
        if row:
            doc_id = row[0]
        else:
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            stamp = today.strftime("%Y%m%d")
            raw_path = RAW_DIR / f"{stamp}_bigfund_{column}.json"
            if raw_path.exists():
                raw_path = raw_path.with_name(f"{raw_path.stem}_{sha[:8]}.json")
            raw_path.write_bytes(content)
            doc_id = conn.execute(
                "INSERT INTO documents"
                " (source_id, url, retrieved_at, raw_path, sha256, doc_date, title, language)"
                " VALUES (?, ?, ?, ?, ?, NULL, ?, 'zh')",
                (
                    source_id,
                    f"{QUERY_API}?searchkey={SEARCH_KEY}&column={column}",
                    retrieved_at,
                    str(raw_path.relative_to(REPO_ROOT)),
                    sha,
                    f"cninfo Big Fund search ({column})",
                ),
            ).lastrowid

        for sig in signals:
            summary = f"{sig['sec_name']}({sig['sec_code']}): {sig['title']} [{sig['url']}]"
            if conn.execute(
                "SELECT 1 FROM hifreq_signals WHERE signal_type = 'big_fund_announcement'"
                " AND signal_date = ? AND summary_en = ?",
                (sig["date"], summary),
            ).fetchone():
                continue
            entity = conn.execute(
                "SELECT id FROM entities WHERE ticker = ?", (sig["sec_code"],)
            ).fetchone()
            conn.execute(
                "INSERT INTO hifreq_signals"
                " (signal_date, signal_type, entity_id, value, unit, summary_en,"
                "  document_id, retrieved_at)"
                " VALUES (?, 'big_fund_announcement', ?, NULL, NULL, ?, ?, ?)",
                (sig["date"], entity[0] if entity else None, summary, doc_id, retrieved_at),
            )
            new_signals += 1
        conn.commit()
        time.sleep(1)  # rule 7

    total = conn.execute(
        "SELECT COUNT(*) FROM hifreq_signals WHERE signal_type='big_fund_announcement'"
    ).fetchone()[0]
    print(f"{new_signals} new Big Fund signals (total: {total})")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
