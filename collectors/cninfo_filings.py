"""Collector: quarterly reports of listed Chinese semicap & foundry companies.

What this does: for each company in COMPANIES, queries cninfo (巨潮资讯网 —
the official disclosure platform for Chinese listed companies) for its
2026 Q1 quarterly report (一季度报告), downloads the PDF to data/raw/cninfo/,
and records it in `sources`/`documents` (language 'zh') plus the company in
`entities`. The reports are short (~10 pages) and disclose quarterly revenue
— the input for the Phase 3 indigenization ratio.

SMEE (上海微电子) is NOT here: it is unlisted and files nothing on cninfo.
Its numbers can only come from trade press or tenders in later phases.

How you'd know it broke: prints one line per company — either "ingested" with
the filing title, "already have", or "NO FILING FOUND" (which also lands in
review_queue so the gap is tracked in the database).
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
RAW_DIR = REPO_ROOT / "data" / "raw" / "cninfo"
USER_AGENT = "ChinaTechFlowsTracker/0.1 (research; contact: jx3@williams.edu)"

SEARCH_API = "https://www.cninfo.com.cn/new/information/topSearch/query"
QUERY_API = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
STATIC_HOST = "https://static.cninfo.com.cn/"

# Q1 2026 reports are published April-June 2026.
CATEGORY = "category_yjdbg_szsh"  # 一季度报告
SE_DATE = "2026-04-01~2026-06-30"
PERIOD_TAG = "2026Q1"

SOURCE = {
    "name": "cninfo",
    "url": "https://www.cninfo.com.cn",
    "type": "filing",
    "language": "zh",
}

# column: 'szse' = Shenzhen-listed, 'sse' = Shanghai-listed (incl. STAR board)
COMPANIES = [
    {"code": "002371", "column": "szse", "name_en": "Naura",        "name_zh": "北方华创", "layer": "equipment"},
    {"code": "688012", "column": "sse",  "name_en": "AMEC",         "name_zh": "中微公司", "layer": "equipment"},
    {"code": "688082", "column": "sse",  "name_en": "ACM Shanghai", "name_zh": "盛美上海", "layer": "equipment"},
    {"code": "688072", "column": "sse",  "name_en": "Piotech",      "name_zh": "拓荆科技", "layer": "equipment"},
    {"code": "688037", "column": "sse",  "name_en": "Kingsemi",     "name_zh": "芯源微",   "layer": "equipment"},
    {"code": "688120", "column": "sse",  "name_en": "Hwatsing",     "name_zh": "华海清科", "layer": "equipment"},
    {"code": "688981", "column": "sse",  "name_en": "SMIC",         "name_zh": "中芯国际", "layer": "foundry"},
    {"code": "688347", "column": "sse",  "name_en": "Hua Hong",     "name_zh": "华虹公司", "layer": "foundry"},
]


def connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_source(conn):
    conn.execute(
        "INSERT OR IGNORE INTO sources (name, url, type, language)"
        " VALUES (:name, :url, :type, :language)",
        SOURCE,
    )
    return conn.execute(
        "SELECT id FROM sources WHERE name = ?", (SOURCE["name"],)
    ).fetchone()[0]


def ensure_entity(conn, company):
    conn.execute(
        "INSERT OR IGNORE INTO entities"
        " (name_en, name_zh, ticker, exchange, entity_type, supply_chain_layer)"
        " VALUES (?, ?, ?, ?, 'company', ?)",
        (
            company["name_en"],
            company["name_zh"],
            company["code"],
            "SZSE" if company["column"] == "szse" else "SSE",
            company["layer"],
        ),
    )
    return conn.execute(
        "SELECT id FROM entities WHERE name_en = ?", (company["name_en"],)
    ).fetchone()[0]


def resolve_org_id(session, code):
    resp = session.post(SEARCH_API, data={"keyWord": code, "maxNum": "10"}, timeout=30)
    resp.raise_for_status()
    for item in resp.json():
        if item.get("code") == code:
            return item["orgId"]
    raise LookupError(f"cninfo search found no orgId for {code}")


def find_quarterly_report(session, code, column, org_id):
    """Return the announcement dict for the Q1 report, or None."""
    resp = session.post(
        QUERY_API,
        data={
            "pageNum": "1",
            "pageSize": "30",
            "column": column,
            "tabName": "fulltext",
            "plate": "",
            "stock": f"{code},{org_id}",
            "searchkey": "",
            "secid": "",
            "category": CATEGORY,
            "trade": "",
            "seDate": SE_DATE,
        },
        timeout=30,
    )
    resp.raise_for_status()
    announcements = resp.json().get("announcements") or []
    for ann in announcements:
        title = ann.get("announcementTitle", "")
        # Skip corrections/summaries; take the report itself.
        if "摘要" in title or "英文" in title:
            continue
        if "一季度报告" in title or "第一季度报告" in title:
            return ann
    return None


def ingest_pdf(conn, source_id, company, ann, content):
    sha = hashlib.sha256(content).hexdigest()
    existing = conn.execute(
        "SELECT id FROM documents WHERE sha256 = ?", (sha,)
    ).fetchone()
    if existing:
        return existing[0], False
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    ann_date = ann["adjunctUrl"].split("/")[1]  # finalpage/YYYY-MM-DD/xxx.PDF
    raw_path = RAW_DIR / f"{ann_date}_{company['code']}_{company['name_en'].lower().replace(' ', '_')}_q1_2026.pdf"
    if raw_path.exists():
        raw_path = raw_path.with_name(f"{raw_path.stem}_{sha[:8]}.pdf")
    raw_path.write_bytes(content)
    retrieved_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    cur = conn.execute(
        "INSERT INTO documents"
        " (source_id, url, retrieved_at, raw_path, sha256, doc_date, title, language)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, 'zh')",
        (
            source_id,
            STATIC_HOST + ann["adjunctUrl"],
            retrieved_at,
            str(raw_path.relative_to(REPO_ROOT)),
            sha,
            ann_date,
            f"{company['name_zh']} {ann['announcementTitle']}",
        ),
    )
    return cur.lastrowid, True


def main():
    conn = connect()
    source_id = ensure_source(conn)
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    for company in COMPANIES:
        ensure_entity(conn, company)
        # Cache: skip if we already hold this company's Q1 2026 filing.
        have = conn.execute(
            "SELECT 1 FROM documents WHERE title LIKE ? AND doc_date >= '2026-04-01'",
            (f"%{company['name_zh']}%一季度报告%",),
        ).fetchone()
        if have:
            print(f"{company['name_en']}: already have Q1 2026 filing")
            continue

        org_id = resolve_org_id(session, company["code"])
        ann = find_quarterly_report(session, company["code"], company["column"], org_id)
        if ann is None:
            reason = (
                f"cninfo: no Q1 2026 quarterly report found for"
                f" {company['name_en']} ({company['code']}) in {SE_DATE}"
            )
            print(f"{company['name_en']}: NO FILING FOUND — flagged for review")
            conn.execute(
                "INSERT INTO review_queue (item_type, item_id, reason) VALUES ('collector', NULL, ?)",
                (reason,),
            )
            continue

        pdf = session.get(STATIC_HOST + ann["adjunctUrl"], timeout=120)
        pdf.raise_for_status()
        doc_id, is_new = ingest_pdf(conn, source_id, company, ann, pdf.content)
        status = "ingested" if is_new else "identical bytes already stored"
        print(
            f"{company['name_en']}: {status} — {ann['announcementTitle']}"
            f" ({len(pdf.content)} bytes, document id={doc_id})"
        )
        time.sleep(1)  # rule 7: polite pacing

    conn.commit()
    conn.close()


if __name__ == "__main__":
    sys.exit(main())
