"""Extraction: revenue-by-segment from annual report excerpts.

What this does: for each 分行业 excerpt archived by the cninfo collector,
one LLM call lists the segments (name + revenue) and classifies each as
semiconductor-equipment or not. The semicap SHARE is then computed in
Python (sum of semicap segments / sum of all segments — the LLM never does
arithmetic) and stored as one metrics row per company-year:
metric 'semicap_segment_share_pct', period = fiscal year. The full segment
list and classification lands in the row's notes for human review.

Cross-check: the segment total must be within 40% of the independently
extracted fy_revenue_cny (segment tables cover 主营业务 and can exclude
minor other income); a bigger gap goes to review_queue instead of metrics.

How you'd know it broke: one line per excerpt with the computed share, or
the validation errors; spend in data/llm_usage.log.
"""

import base64
import datetime
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"
USAGE_LOG = REPO_ROOT / "data" / "llm_usage.log"

SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name_zh": {"type": "string"},
                    "revenue_cny": {
                        "type": "number",
                        "description": "该分部营业收入，换算为人民币元",
                    },
                    "is_semicap_equipment": {
                        "type": "boolean",
                        "description": (
                            "true 仅当该分部收入来自半导体制造设备（刻蚀、薄膜"
                            "沉积、清洗、CMP、涂胶显影、检测等晶圆制造设备及其"
                            "配件服务）。光伏/锂电/真空/新能源装备、电子元器件"
                            "等为 false。"
                        ),
                    },
                },
                "required": ["name_zh", "revenue_cny", "is_semicap_equipment"],
                "additionalProperties": False,
            },
        },
        "evidence": {"type": "string", "description": "表格名称及页码"},
        "confidence": {"type": "number"},
    },
    "required": ["segments", "evidence", "confidence"],
    "additionalProperties": False,
}

PROMPT = """\
这是一家中国上市公司年度报告中"主营业务分行业/分产品情况"部分的节选。
请提取营业收入的分部构成。

规则：
- 如同时存在"分行业"和"分产品"两个表，使用划分更细的那个。
- 每个分部给出名称和营业收入（换算为人民币元，注意表头单位）。
- is_semicap_equipment 的判断标准见字段说明：只有半导体制造设备
 （及其配件/服务）为 true。
- 使用本年度（本期）数，不要使用上年同期数。
"""


def load_env():
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def validate(data):
    errors = []
    if not isinstance(data, dict):
        return ["payload is not a JSON object"]
    segments = data.get("segments")
    if not isinstance(segments, list) or not segments:
        return ["segments must be a non-empty list"]
    for i, seg in enumerate(segments):
        if not seg.get("name_zh", "").strip():
            errors.append(f"segment {i}: empty name")
        rev = seg.get("revenue_cny")
        if not isinstance(rev, (int, float)) or isinstance(rev, bool) or rev < 0:
            errors.append(f"segment {i}: bad revenue {rev!r}")
        if not isinstance(seg.get("is_semicap_equipment"), bool):
            errors.append(f"segment {i}: is_semicap_equipment must be boolean")
    total = sum(s.get("revenue_cny") or 0 for s in segments)
    if not errors and not (1e6 <= total <= 1e12):
        errors.append(f"segment total implausible (units?): {total!r}")
    conf = data.get("confidence")
    if not isinstance(conf, (int, float)) or isinstance(conf, bool) or not (0 <= conf <= 1):
        errors.append(f"confidence invalid: {conf!r}")
    return errors


def compute_share(segments):
    """Python arithmetic: semicap share in percent, 0-100."""
    total = sum(s["revenue_cny"] for s in segments)
    semicap = sum(s["revenue_cny"] for s in segments if s["is_semicap_equipment"])
    return 100.0 * semicap / total, total, semicap


def pending(conn):
    return conn.execute(
        "SELECT d.id, d.raw_path, d.title, e.id, e.name_en FROM documents d"
        " JOIN sources s ON s.id = d.source_id AND s.name = 'cninfo'"
        " JOIN entities e ON instr(d.title, e.name_zh) > 0"
        " WHERE d.title LIKE '%分行业节选%'"
        "   AND NOT EXISTS (SELECT 1 FROM metrics m WHERE m.document_id = d.id"
        "                   AND m.metric_name = 'semicap_segment_share_pct')"
        " ORDER BY d.id"
    ).fetchall()


def extract(pdf_bytes, model):
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=2048,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": base64.standard_b64encode(pdf_bytes).decode("ascii"),
                        },
                    },
                    {"type": "text", "text": PROMPT},
                ],
            }
        ],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("model refused; check stop_details")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text), response.usage


def main():
    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set (see .env.example)")
        return 1
    model = os.environ.get("EXTRACTION_MODEL", "claude-haiku-4-5")

    conn = connect()
    todo = pending(conn)
    if not todo:
        print("nothing to extract — all segment excerpts processed")
        conn.close()
        return 0

    total_in = total_out = failures = 0
    for doc_id, raw_path, title, entity_id, name_en in todo:
        year = re.search(r"(20\d\d)年年度报告", title).group(1)
        print(f"{name_en} FY{year}: doc id={doc_id}")
        try:
            data, usage = extract((REPO_ROOT / raw_path).read_bytes(), model)
        except Exception as exc:
            conn.execute(
                "INSERT INTO review_queue (item_type, item_id, reason)"
                " VALUES ('extraction', ?, ?)",
                (doc_id, f"segment extraction failed: {exc}"),
            )
            conn.commit()
            failures += 1
            continue
        total_in += usage.input_tokens
        total_out += usage.output_tokens

        errors = validate(data)
        if errors:
            conn.execute(
                "INSERT INTO review_queue (item_type, item_id, reason)"
                " VALUES ('extraction', ?, ?)",
                (doc_id, "; ".join(errors)[:500]),
            )
            conn.commit()
            failures += 1
            continue

        share, total, semicap = compute_share(data["segments"])

        # Cross-check against the independently extracted FY revenue.
        fy = conn.execute(
            "SELECT value FROM metrics WHERE entity_id = ?"
            " AND metric_name = 'fy_revenue_cny' AND period = ?"
            " ORDER BY document_id DESC LIMIT 1",
            (entity_id, year),
        ).fetchone()
        if fy and not (0.6 * fy[0] <= total <= 1.4 * fy[0]):
            conn.execute(
                "INSERT INTO review_queue (item_type, item_id, reason)"
                " VALUES ('extraction', ?, ?)",
                (
                    doc_id,
                    f"segment total {total:,.0f} deviates >40% from FY revenue"
                    f" {fy[0]:,.0f} ({name_en} {year}) — units or scope wrong",
                ),
            )
            conn.commit()
            failures += 1
            continue

        seg_note = "; ".join(
            f"{s['name_zh']}={s['revenue_cny']:,.0f}"
            f"{' [semicap]' if s['is_semicap_equipment'] else ''}"
            for s in data["segments"]
        )
        conn.execute(
            "INSERT OR IGNORE INTO metrics"
            " (entity_id, metric_name, period, value, unit, currency, document_id,"
            "  extraction_confidence, notes)"
            " VALUES (?, 'semicap_segment_share_pct', ?, ?, 'pct', NULL, ?, ?, ?)",
            (
                entity_id,
                year,
                round(share, 2),
                doc_id,
                float(data["confidence"]),
                f"computed in python: {semicap:,.0f}/{total:,.0f} | {seg_note[:600]}"
                f" | evidence: {data['evidence'][:150]}",
            ),
        )
        conn.commit()
        print(f"  FY{year} semicap share: {share:.1f}% ({len(data['segments'])} segments)")

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with USAGE_LOG.open("a") as f:
        f.write(
            f"{stamp} model={model} input_tokens={total_in} output_tokens={total_out}"
            f" note=extract_segment_revenue n={len(todo)}\n"
        )
    print(f"\nprocessed {len(todo) - failures}/{len(todo)}; failures flagged: {failures}")
    conn.close()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
