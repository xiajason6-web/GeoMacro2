"""Extraction: domestic (境内) vs export revenue split from annual excerpts.

Why: the indigenization numerator must be China-DOMESTIC semiconductor-
equipment sales. Chinese annual reports disclose a 分地区 (by region) revenue
table in the same section as the segment tables, so the excerpts archived by
the cninfo collector already contain it — no new collection.

What this does: one LLM call per excerpt lists the region rows (name +
revenue + is_domestic); the domestic share is computed in Python and stored
as metric 'domestic_revenue_share_pct' per company-year, with the full
region list in notes.

Documented approximation (carried onto every derived row that uses this):
the 分地区 split covers the company's TOTAL revenue — applying it to the
semicap segment assumes equipment and non-equipment revenue export at the
same rate. Where no region table is readable, the row goes to review_queue
and downstream derivation marks the company-year ESTIMATED (100% domestic).

How you'd know it broke: one line per excerpt with the share, or the
validation errors; spend in data/llm_usage.log.
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
        "regions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name_zh": {"type": "string"},
                    "revenue_cny": {
                        "type": "number",
                        "description": "该地区营业收入，换算为人民币元",
                    },
                    "is_domestic": {
                        "type": "boolean",
                        "description": "true = 中国境内/国内；false = 境外/国外/出口",
                    },
                },
                "required": ["name_zh", "revenue_cny", "is_domestic"],
                "additionalProperties": False,
            },
        },
        "evidence": {"type": "string", "description": "表格名称及位置"},
        "confidence": {"type": "number"},
    },
    "required": ["regions", "evidence", "confidence"],
    "additionalProperties": False,
}

PROMPT = """\
这是一家中国上市公司年度报告中主营业务情况部分的节选。请提取"分地区"
营业收入构成表（境内/境外 或 国内/国外）。

规则：
- 每个地区给出名称和营业收入（换算为人民币元，注意表头单位）。
- 使用本年度（本期）数，不要使用上年同期数。
- 如果节选中确实没有分地区收入表，返回空的 regions 列表。
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
    regions = data.get("regions")
    if not isinstance(regions, list):
        return ["regions must be a list"]
    for i, reg in enumerate(regions):
        if not reg.get("name_zh", "").strip():
            errors.append(f"region {i}: empty name")
        rev = reg.get("revenue_cny")
        if not isinstance(rev, (int, float)) or isinstance(rev, bool) or rev < 0:
            errors.append(f"region {i}: bad revenue {rev!r}")
        if not isinstance(reg.get("is_domestic"), bool):
            errors.append(f"region {i}: is_domestic must be boolean")
    if regions and not errors:
        total = sum(r["revenue_cny"] for r in regions)
        if not (1e6 <= total <= 1e12):
            errors.append(f"region total implausible (units?): {total!r}")
    conf = data.get("confidence")
    if not isinstance(conf, (int, float)) or isinstance(conf, bool) or not (0 <= conf <= 1):
        errors.append(f"confidence invalid: {conf!r}")
    return errors


def compute_share(regions):
    total = sum(r["revenue_cny"] for r in regions)
    domestic = sum(r["revenue_cny"] for r in regions if r["is_domestic"])
    return 100.0 * domestic / total, total, domestic


def pending(conn):
    return conn.execute(
        "SELECT d.id, d.raw_path, d.title, e.id, e.name_en FROM documents d"
        " JOIN sources s ON s.id = d.source_id AND s.name = 'cninfo'"
        " JOIN entities e ON instr(d.title, e.name_zh) > 0"
        " WHERE d.title LIKE '%分行业节选%'"
        "   AND NOT EXISTS (SELECT 1 FROM metrics m WHERE m.document_id = d.id"
        "                   AND m.metric_name = 'domestic_revenue_share_pct')"
        " ORDER BY d.id"
    ).fetchall()


def extract(pdf_bytes, model):
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=1536,
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
        print("nothing to extract — all excerpts have a domestic share or flag")
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
                (doc_id, f"domestic-share extraction failed: {exc}"),
            )
            conn.commit()
            failures += 1
            continue
        total_in += usage.input_tokens
        total_out += usage.output_tokens

        errors = validate(data)
        if not errors and not data["regions"]:
            errors = ["no region table found in excerpt | " + data["evidence"]]
        if errors:
            conn.execute(
                "INSERT INTO review_queue (item_type, item_id, reason)"
                " VALUES ('extraction', ?, ?)",
                (doc_id, f"domestic share {name_en} FY{year}: " + "; ".join(errors)[:400]),
            )
            conn.commit()
            failures += 1
            continue

        share, total, domestic = compute_share(data["regions"])
        reg_note = "; ".join(
            f"{r['name_zh']}={r['revenue_cny']:,.0f}"
            f"{' [domestic]' if r['is_domestic'] else ''}"
            for r in data["regions"]
        )
        conn.execute(
            "INSERT OR IGNORE INTO metrics"
            " (entity_id, metric_name, period, value, unit, currency, document_id,"
            "  extraction_confidence, notes)"
            " VALUES (?, 'domestic_revenue_share_pct', ?, ?, 'pct', NULL, ?, ?, ?)",
            (
                entity_id,
                year,
                round(share, 2),
                doc_id,
                float(data["confidence"]),
                f"computed in python: {domestic:,.0f}/{total:,.0f} |"
                f" split covers TOTAL revenue (see extract_domestic_share.py"
                f" docstring for the approximation) | {reg_note[:500]}"
                f" | evidence: {data['evidence'][:120]}",
            ),
        )
        conn.commit()
        print(f"  FY{year} domestic share: {share:.1f}% ({len(data['regions'])} regions)")

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with USAGE_LOG.open("a") as f:
        f.write(
            f"{stamp} model={model} input_tokens={total_in} output_tokens={total_out}"
            f" note=extract_domestic_share n={len(todo)}\n"
        )
    print(f"\nprocessed {len(todo) - failures}/{len(todo)}; failures flagged: {failures}")
    conn.close()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
