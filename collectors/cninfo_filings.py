"""Collector: quarterly reports of listed Chinese semicap & foundry companies.

What this does: for each company in COMPANIES and each period in PERIODS
(Q1 and Q3 reports, 2023-2026 — the short filings that fit the extraction
pipeline), queries cninfo (巨潮资讯网, the official disclosure platform),
downloads the report PDF to data/raw/cninfo/, and records it in
`sources`/`documents` (language 'zh') plus the company in `entities`.

Q2 and Q4 are NOT collected: they live inside half-year and annual reports
(large documents) — deriving them by subtraction is proposed in
analysis/methodology.md and waits for approval.

SMEE (上海微电子) is not here: unlisted, files nothing on cninfo.

How you'd know it broke: prints one line per company/period — "ingested",
"already have", or "no filing (pre-listing?)" for gaps, which also land in
review_queue exactly once so they're tracked in the database.
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

# (period tag, cninfo category, publication window, title keyword)
PERIODS = [
    ("2023Q1", "category_yjdbg_szsh", "2023-04-01~2023-06-30", "一季度报告"),
    ("2023Q3", "category_sjdbg_szsh", "2023-10-01~2023-12-31", "三季度报告"),
    ("2024Q1", "category_yjdbg_szsh", "2024-04-01~2024-06-30", "一季度报告"),
    ("2024Q3", "category_sjdbg_szsh", "2024-10-01~2024-12-31", "三季度报告"),
    ("2025Q1", "category_yjdbg_szsh", "2025-04-01~2025-06-30", "一季度报告"),
    ("2025Q3", "category_sjdbg_szsh", "2025-10-01~2025-12-31", "三季度报告"),
    ("2026Q1", "category_yjdbg_szsh", "2026-04-01~2026-06-30", "一季度报告"),
]

# Half-year and annual report SUMMARIES (摘要) — short documents that carry
# the headline revenue table. Full half-year/annual reports are hundreds of
# pages and are deliberately not collected. Q2 and Q4 are later DERIVED from
# these by subtraction (analysis/derive_quarters.py).
# (period tag, sort key for first_period gate, category, window, title keyword)
SUMMARY_PERIODS = [
    ("2023H1", "2023Q2", "category_bndbg_szsh", "2023-07-01~2023-09-30", "半年度报告摘要"),
    ("2023",   "2023Q4", "category_ndbg_szsh",  "2024-01-01~2024-06-30", "年度报告摘要"),
    ("2024H1", "2024Q2", "category_bndbg_szsh", "2024-07-01~2024-09-30", "半年度报告摘要"),
    ("2024",   "2024Q4", "category_ndbg_szsh",  "2025-01-01~2025-06-30", "年度报告摘要"),
    ("2025H1", "2025Q2", "category_bndbg_szsh", "2025-07-01~2025-09-30", "半年度报告摘要"),
    ("2025",   "2025Q4", "category_ndbg_szsh",  "2026-01-01~2026-06-30", "年度报告摘要"),
]

# Full annual reports (300+ pages) exceed the extraction API's PDF limits,
# so for segment revenue we download them, locate the 分行业 (revenue by
# segment) pages with pypdf, and archive ONLY that excerpt as the document.
# The excerpt is the evidence a human would check; the URL points at the
# full filing. Years and publication windows:
ANNUAL_FULL = [
    ("2023", "2024-01-01~2024-06-30"),
    ("2024", "2025-01-01~2025-06-30"),
    ("2025", "2026-01-01~2026-06-30"),
]
SEGMENT_KEYWORDS = ["分行业", "营业收入构成", "主营业务分行业"]
SLICE_MAX_PAGES = 8

SOURCE = {
    "name": "cninfo",
    "url": "https://www.cninfo.com.cn",
    "type": "filing",
    "language": "zh",
}

# column: 'szse' = Shenzhen-listed, 'sse' = Shanghai-listed (incl. STAR board)
# first_period: first quarter the company reports as a listed company.
COMPANIES = [
    {"code": "002371", "column": "szse", "name_en": "Naura",        "name_zh": "北方华创", "layer": "equipment", "first_period": "2023Q1"},
    {"code": "688012", "column": "sse",  "name_en": "AMEC",         "name_zh": "中微公司", "layer": "equipment", "first_period": "2023Q1"},
    {"code": "688082", "column": "sse",  "name_en": "ACM Shanghai", "name_zh": "盛美上海", "layer": "equipment", "first_period": "2023Q1"},
    {"code": "688072", "column": "sse",  "name_en": "Piotech",      "name_zh": "拓荆科技", "layer": "equipment", "first_period": "2023Q1"},
    {"code": "688037", "column": "sse",  "name_en": "Kingsemi",     "name_zh": "芯源微",   "layer": "equipment", "first_period": "2023Q1"},
    {"code": "688120", "column": "sse",  "name_en": "Hwatsing",     "name_zh": "华海清科", "layer": "equipment", "first_period": "2023Q1"},
    {"code": "688981", "column": "sse",  "name_en": "SMIC",         "name_zh": "中芯国际", "layer": "foundry",   "first_period": "2023Q1"},
    # Hua Hong's A-share listed 2023-08: first quarterly report is Q3 2023.
    {"code": "688347", "column": "sse",  "name_en": "Hua Hong",     "name_zh": "华虹公司", "layer": "foundry",   "first_period": "2023Q3"},
]


def connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path, timeout=60)
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


def find_report(session, code, column, org_id, category, se_date, keyword):
    """Return the announcement dict for the report, or None."""
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
            "category": category,
            "trade": "",
            "seDate": se_date,
        },
        timeout=30,
    )
    resp.raise_for_status()
    want_summary = "摘要" in keyword
    for ann in resp.json().get("announcements") or []:
        title = ann.get("announcementTitle", "")
        if "英文" in title:
            continue
        if not want_summary and "摘要" in title:
            continue
        # '半年度报告摘要' contains '年度报告摘要' as a substring — when we want
        # the ANNUAL summary, explicitly reject half-year titles.
        if keyword == "年度报告摘要" and "半年度" in title:
            continue
        if keyword in title:
            return ann
    return None


def ingest_pdf(conn, source_id, company, period_tag, ann, content):
    sha = hashlib.sha256(content).hexdigest()
    existing = conn.execute(
        "SELECT id FROM documents WHERE sha256 = ?", (sha,)
    ).fetchone()
    if existing:
        return existing[0], False
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    ann_date = ann["adjunctUrl"].split("/")[1]  # finalpage/YYYY-MM-DD/xxx.PDF
    slug = company["name_en"].lower().replace(" ", "_")
    raw_path = RAW_DIR / f"{ann_date}_{company['code']}_{slug}_{period_tag.lower()}.pdf"
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


def slice_segment_pages(pdf_bytes):
    """Find the revenue-by-segment pages in a full annual report and return
    (sliced_pdf_bytes, first_page_1indexed, last_page_1indexed), or None if
    no segment keyword is found. Deterministic pypdf text scan."""
    import io

    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(pdf_bytes))
    # The segment table sits in the business-discussion section, never in
    # the first few pages (table of contents) — scan pages 5..150 and score
    # each: the table page mentions a segment split AND revenue/cost/margin
    # column headers. Taking merely the first '分行业' mention can land on
    # narrative text pages ahead of the actual table.
    TABLE_HINTS = ["营业收入", "营业成本", "毛利率"]
    hit = None
    fallback = None
    for i in range(4, min(len(reader.pages), 150)):
        try:
            text = reader.pages[i].extract_text() or ""
        except Exception:
            continue
        has_split = any(kw in text for kw in SEGMENT_KEYWORDS + ["分产品"])
        if not has_split:
            continue
        if fallback is None:
            fallback = i
        if sum(h in text for h in TABLE_HINTS) >= 2:
            hit = i
            break
    if hit is None:
        hit = fallback
    if hit is None:
        return None
    first = max(0, hit - 1)
    last = min(len(reader.pages) - 1, first + SLICE_MAX_PAGES - 1)
    writer = PdfWriter()
    writer.add_page(reader.pages[0])  # cover page identifies the filing
    for i in range(first, last + 1):
        writer.add_page(reader.pages[i])
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue(), first + 1, last + 1


def collect_segment_slices(conn, source_id, session, org_ids):
    """Download equipment makers' full annual reports, archive only the
    segment-table excerpt as a document (title marks it 节选/excerpt)."""
    for company in [c for c in COMPANIES if c["layer"] == "equipment"]:
        for year, se_date in ANNUAL_FULL:
            have = conn.execute(
                "SELECT 1 FROM documents WHERE title LIKE ?",
                (f"%{company['name_zh']}%{year}年年度报告%节选%",),
            ).fetchone()
            if have:
                print(f"{company['name_en']} FY{year} segment excerpt: already have")
                continue
            if company["code"] not in org_ids:
                org_ids[company["code"]] = resolve_org_id(session, company["code"])
            ann = find_report(
                session, company["code"], company["column"],
                org_ids[company["code"]], "category_ndbg_szsh", se_date, "年度报告",
            )
            if ann is None:
                print(f"{company['name_en']} FY{year}: no full annual report found")
                continue
            pdf = session.get(STATIC_HOST + ann["adjunctUrl"], timeout=300)
            pdf.raise_for_status()
            sliced = slice_segment_pages(pdf.content)
            if sliced is None:
                reason = (
                    f"segment slice: no 分行业 keyword found in"
                    f" {company['name_en']} FY{year} annual report"
                )
                conn.execute(
                    "INSERT INTO review_queue (item_type, item_id, reason)"
                    " VALUES ('collector', NULL, ?)",
                    (reason,),
                )
                print(f"{company['name_en']} FY{year}: {reason}")
                continue
            slice_bytes, first, last = sliced
            sha = hashlib.sha256(slice_bytes).hexdigest()
            if conn.execute(
                "SELECT 1 FROM documents WHERE sha256 = ?", (sha,)
            ).fetchone():
                continue
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            slug = company["name_en"].lower().replace(" ", "_")
            ann_date = ann["adjunctUrl"].split("/")[1]
            raw_path = RAW_DIR / f"{ann_date}_{company['code']}_{slug}_fy{year}_segments_excerpt.pdf"
            if raw_path.exists():
                raw_path = raw_path.with_name(f"{raw_path.stem}_{sha[:8]}.pdf")
            raw_path.write_bytes(slice_bytes)
            retrieved_at = datetime.datetime.now(datetime.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            conn.execute(
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
                    f"{company['name_zh']} {year}年年度报告（分行业节选 pp.{first}-{last}）",
                ),
            )
            print(
                f"{company['name_en']} FY{year}: excerpt pp.{first}-{last}"
                f" archived ({len(slice_bytes)} bytes, full report"
                f" {len(pdf.content)} bytes not persisted)"
            )
            conn.commit()
            time.sleep(1)  # rule 7


def main():
    conn = connect()
    source_id = ensure_source(conn)
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    org_ids = {}

    all_periods = [(tag, tag, cat, se, kw) for tag, cat, se, kw in PERIODS] + [
        (tag, sort_key, cat, se, kw) for tag, sort_key, cat, se, kw in SUMMARY_PERIODS
    ]
    for company in COMPANIES:
        ensure_entity(conn, company)
        for period_tag, sort_key, category, se_date, keyword in all_periods:
            if sort_key < company["first_period"]:
                continue
            year = period_tag[:4]
            # Cache: skip if we already hold this company/period filing.
            # Annual summaries need the doubled 年 ('2023年年度报告摘要') so the
            # pattern can't accidentally match a half-year summary title.
            if keyword == "年度报告摘要":
                pattern = f"%{company['name_zh']}%{year}年年度报告摘要%"
            else:
                pattern = f"%{company['name_zh']}%{year}年%{keyword}%"
            have = conn.execute(
                "SELECT 1 FROM documents WHERE title LIKE ?", (pattern,)
            ).fetchone()
            if have:
                print(f"{company['name_en']} {period_tag}: already have")
                continue

            if company["code"] not in org_ids:
                org_ids[company["code"]] = resolve_org_id(session, company["code"])
            ann = find_report(
                session, company["code"], company["column"],
                org_ids[company["code"]], category, se_date, keyword,
            )
            if ann is None:
                reason = (
                    f"cninfo: no {period_tag} report found for"
                    f" {company['name_en']} ({company['code']}) in {se_date}"
                )
                already_flagged = conn.execute(
                    "SELECT 1 FROM review_queue WHERE reason = ?", (reason,)
                ).fetchone()
                if not already_flagged:
                    conn.execute(
                        "INSERT INTO review_queue (item_type, item_id, reason)"
                        " VALUES ('collector', NULL, ?)",
                        (reason,),
                    )
                print(f"{company['name_en']} {period_tag}: no filing — flagged for review")
                continue

            pdf = session.get(STATIC_HOST + ann["adjunctUrl"], timeout=120)
            pdf.raise_for_status()
            doc_id, is_new = ingest_pdf(conn, source_id, company, period_tag, ann, pdf.content)
            status = "ingested" if is_new else "identical bytes already stored"
            print(
                f"{company['name_en']} {period_tag}: {status} —"
                f" {ann['announcementTitle']} ({len(pdf.content)} bytes, document id={doc_id})"
            )
            time.sleep(1)  # rule 7: polite pacing
        conn.commit()

    collect_segment_slices(conn, source_id, session, org_ids)
    conn.close()


if __name__ == "__main__":
    sys.exit(main())
