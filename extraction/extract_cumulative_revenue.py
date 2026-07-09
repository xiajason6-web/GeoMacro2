"""Extraction: cumulative revenue from half-year/annual summaries + YTD.

What this does: three kinds of cumulative revenue, each schema-validated:
  - 半年度报告摘要 (H1 summary)  -> metric 'h1_revenue_cny',    period '2023H1'
  - 年度报告摘要   (FY summary)  -> metric 'fy_revenue_cny',    period '2023'
  - 三季度报告 missing a single-quarter figure -> extract the Jan-Sep
    cumulative instead   -> metric 'ytd9m_revenue_cny', period '2024YTD9M'
These are inputs for analysis/derive_quarters.py, which computes the missing
Q2/Q3/Q4 single quarters by subtraction (deterministic Python — the LLM
never does arithmetic). Failures land in review_queue as always.

How you'd know it broke: one line per document with the value, or the
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
        "year": {"type": "string", "description": "Fiscal year, e.g. '2024'"},
        "revenue_cny": {
            "type": ["number", "null"],
            "description": (
                "营业收入 for the requested scope, in CNY yuan exactly as"
                " printed (convert 万元/千元 to 元). null if not stated."
            ),
        },
        "evidence": {"type": "string", "description": "Table/section where the figure appears"},
        "confidence": {"type": "number", "description": "0.0-1.0"},
    },
    "required": ["year", "revenue_cny", "evidence", "confidence"],
    "additionalProperties": False,
}

SCOPE_PROMPTS = {
    "h1": "本半年度（1-6月累计）的营业收入",
    "full_year": "本年度（全年）的营业收入",
    "ytd_9m": "年初至报告期末（1-9月累计）的营业收入",
}

PROMPT_TMPL = """\
这是一家中国上市公司的定期报告（或摘要）。请提取{scope_zh}。

规则：
- revenue_cny 必须是报告中实际印出的数字，单位换算为人民币元
 （注意表头"单位：元/万元/千元"）。
- 只提取指定口径的数字：{scope_zh}。不要使用其他口径。
- year 是报告所属的会计年度。
- evidence 指出数字出现的表格/章节名称，便于人工核对。
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


def validate(data, expected_year):
    errors = []
    if not isinstance(data, dict):
        return ["payload is not a JSON object"]
    for field in SCHEMA["required"]:
        if field not in data:
            errors.append(f"missing required field: {field}")
    if errors:
        return errors
    if data["year"] != expected_year:
        errors.append(f"year mismatch: expected {expected_year}, got {data['year']!r}")
    rev = data["revenue_cny"]
    if rev is not None:
        if not isinstance(rev, (int, float)) or isinstance(rev, bool):
            errors.append(f"revenue_cny must be number or null: {rev!r}")
        elif not (1e6 <= rev <= 1e12):
            errors.append(f"revenue_cny implausible (units?): {rev!r}")
    if not isinstance(data["evidence"], str) or not data["evidence"].strip():
        errors.append("evidence must be non-empty")
    conf = data["confidence"]
    if not isinstance(conf, (int, float)) or isinstance(conf, bool) or not (0 <= conf <= 1):
        errors.append(f"confidence invalid: {conf!r}")
    return errors


def pending(conn):
    """(doc_id, raw_path, title, entity_id, name_en, scope, metric, period, year)
    for every summary/Q3 document still missing its cumulative metric."""
    docs = conn.execute(
        "SELECT d.id, d.raw_path, d.title, e.id, e.name_en FROM documents d"
        " JOIN sources s ON s.id = d.source_id AND s.name = 'cninfo'"
        " JOIN entities e ON instr(d.title, e.name_zh) > 0 ORDER BY d.id"
    ).fetchall()
    out = []
    for doc_id, raw_path, title, entity_id, name_en in docs:
        year_match = re.search(r"(20\d\d)年", title)
        if not year_match:
            continue
        year = year_match.group(1)
        if "半年度报告摘要" in title:
            scope, metric, period = "h1", "h1_revenue_cny", f"{year}H1"
        elif "年度报告摘要" in title:
            scope, metric, period = "full_year", "fy_revenue_cny", year
        elif "三季度报告" in title:
            # Only Q3 reports whose single-quarter figure is missing: extract YTD.
            has_q = conn.execute(
                "SELECT 1 FROM metrics WHERE document_id = ?"
                " AND metric_name = 'quarterly_revenue_cny'",
                (doc_id,),
            ).fetchone()
            if has_q:
                continue
            scope, metric, period = "ytd_9m", "ytd9m_revenue_cny", f"{year}YTD9M"
        else:
            continue
        done = conn.execute(
            "SELECT 1 FROM metrics WHERE document_id = ? AND metric_name = ?",
            (doc_id, metric),
        ).fetchone()
        if done:
            continue
        out.append((doc_id, raw_path, title, entity_id, name_en, scope, metric, period, year))
    return out


def extract(pdf_bytes, scope, model):
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=1024,
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
                    {"type": "text", "text": PROMPT_TMPL.format(scope_zh=SCOPE_PROMPTS[scope])},
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
        print("nothing to extract")
        conn.close()
        return 0

    total_in = total_out = failures = 0
    for doc_id, raw_path, title, entity_id, name_en, scope, metric, period, year in todo:
        print(f"{name_en} {period} ({scope}): doc id={doc_id}")
        pdf_bytes = (REPO_ROOT / raw_path).read_bytes()
        try:
            data, usage = extract(pdf_bytes, scope, model)
        except Exception as exc:
            conn.execute(
                "INSERT INTO review_queue (item_type, item_id, reason)"
                " VALUES ('extraction', ?, ?)",
                (doc_id, f"cumulative extraction failed: {exc}"),
            )
            conn.commit()
            failures += 1
            continue
        total_in += usage.input_tokens
        total_out += usage.output_tokens

        errors = validate(data, year)
        if not errors and data["revenue_cny"] is None:
            errors = ["revenue not stated in document | " + data["evidence"]]
        if errors:
            conn.execute(
                "INSERT INTO review_queue (item_type, item_id, reason)"
                " VALUES ('extraction', ?, ?)",
                (doc_id, "; ".join(errors)[:500]),
            )
            conn.commit()
            failures += 1
            continue

        conn.execute(
            "INSERT OR IGNORE INTO metrics"
            " (entity_id, metric_name, period, value, unit, currency, document_id,"
            "  extraction_confidence, notes)"
            " VALUES (?, ?, ?, ?, 'CNY', 'CNY', ?, ?, ?)",
            (
                entity_id,
                metric,
                period,
                float(data["revenue_cny"]),
                doc_id,
                float(data["confidence"]),
                f"scope: {scope} | evidence: {data['evidence']}",
            ),
        )
        conn.commit()
        print(f"  {period}: {data['revenue_cny']:,.0f} CNY (confidence {data['confidence']})")

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with USAGE_LOG.open("a") as f:
        f.write(
            f"{stamp} model={model} input_tokens={total_in} output_tokens={total_out}"
            f" note=extract_cumulative_revenue n={len(todo)}\n"
        )
    print(f"\nextracted {len(todo) - failures}/{len(todo)}; failures flagged: {failures}")
    conn.close()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
