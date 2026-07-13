"""Collector: semiconductor-related policy documents from gov.cn.

What this does: queries the State Council policy library search API
(sousuo.www.gov.cn — the JSON endpoint behind gov.cn's own policy pages)
for documents whose TITLE mentions semiconductor-related keywords, since
2023-07. Each new document becomes an `events` row with summary_zh = the
official title, category 'policy_unclassified', and summary_en set to the sentinel
'PENDING_TRANSLATION' (the schema requires a value). The extraction layer
(extraction/translate_classify_policy.py) later fills the real summary_en
and a proper category via LLM — collection and interpretation
stay separate.

MIIT/NDRC/MOFCOM site-specific collectors and trade press (ijiwei) are not
implemented yet: their pages are JS-rendered and need per-site work.
gov.cn's policy library covers State Council and ministry documents, which
is the highest-signal subset.

How you'd know it broke: prints per-keyword hit counts and "N new events".
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
RAW_DIR = REPO_ROOT / "data" / "raw" / "gov_cn"
USER_AGENT = "ChinaTechFlowsTracker/0.1 (research; contact: jx3@williams.edu)"

API = "https://sousuo.www.gov.cn/search-gov/data"
SINCE = "2023-07-01"
KEYWORDS = ["集成电路", "半导体", "出口管制"]

SOURCE = {
    "name": "gov.cn policy library",
    "url": "https://www.gov.cn/zhengce/",
    "type": "policy",
    "language": "zh",
}


def connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def fetch_keyword(session, keyword):
    resp = session.get(
        API,
        params={
            "t": "zhengcelibrary",
            "q": keyword,
            "timetype": "timezd",
            "mintime": SINCE,
            "maxtime": datetime.date.today().isoformat(),
            "sort": "pubtime",
            "sortType": "1",
            "searchfield": "title",
            "p": "1",
            "n": "50",
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.content, resp.json()


def parse_results(payload):
    """gov.cn search JSON -> list of {date, title, url, org}. Deterministic."""
    out = []
    cat_map = (payload.get("searchVO") or {}).get("catMap") or {}
    for cat in cat_map.values():
        for item in cat.get("listVO") or []:
            title = (item.get("title") or "").replace("<em>", "").replace("</em>", "")
            date = (item.get("pubtimeStr") or "").replace(".", "-")
            if not title or not date:
                continue
            out.append(
                {
                    "date": date,
                    "title": title.strip(),
                    "url": item.get("url") or "",
                    "org": (item.get("puborg") or "").strip(),
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

    new_events = 0
    for keyword in KEYWORDS:
        content, payload = fetch_keyword(session, keyword)
        results = parse_results(payload)
        print(f"keyword {keyword}: {len(results)} documents")

        sha = hashlib.sha256(content).hexdigest()
        existing = conn.execute(
            "SELECT id FROM documents WHERE sha256 = ?", (sha,)
        ).fetchone()
        if existing:
            doc_id = existing[0]
        else:
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
            raw_path = RAW_DIR / f"{stamp}_govcn_{keyword}.json"
            if raw_path.exists():
                raw_path = raw_path.with_name(f"{raw_path.stem}_{sha[:8]}.json")
            raw_path.write_bytes(content)
            retrieved_at = datetime.datetime.now(datetime.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            doc_id = conn.execute(
                "INSERT INTO documents"
                " (source_id, url, retrieved_at, raw_path, sha256, doc_date, title, language)"
                " VALUES (?, ?, ?, ?, ?, NULL, ?, 'zh')",
                (
                    source_id,
                    f"{API}?t=zhengcelibrary&q={keyword}&searchfield=title",
                    retrieved_at,
                    str(raw_path.relative_to(REPO_ROOT)),
                    sha,
                    f"gov.cn policy search: {keyword}",
                ),
            ).lastrowid

        for item in results:
            # Compare against the STORED form (title + [url] suffix) — comparing
            # the bare title never matches and duplicates every run.
            stored_zh = item["title"] + (f" [{item['url']}]" if item["url"] else "")
            already = conn.execute(
                "SELECT 1 FROM events WHERE event_date = ? AND summary_zh = ?",
                (item["date"], stored_zh),
            ).fetchone()
            if already:
                continue
            conn.execute(
                "INSERT INTO events"
                " (event_date, category, actor, summary_en, summary_zh, document_id)"
                " VALUES (?, 'policy_unclassified', ?, 'PENDING_TRANSLATION', ?, ?)",
                (item["date"], item["org"] or "State Council/ministries",
                 stored_zh, doc_id),
            )
            new_events += 1
        time.sleep(1)  # rule 7

    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    print(f"{new_events} new policy events (events table: {total})")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
