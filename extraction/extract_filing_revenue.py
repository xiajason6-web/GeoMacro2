"""Extraction: quarterly revenue from Chinese-listed company filings.

What this does: finds every cninfo filing in `documents` that doesn't yet
have a revenue metric, sends each PDF (Mandarin, ~10 pages) to the Claude
API with a strict JSON schema, validates the response, and writes one
`metrics` row per filing (metric_name 'quarterly_revenue_cny', value in
yuan). Both a Chinese and an English summary are kept in the notes, per the
Mandarin-document rule. Failures land in `review_queue`, never in metrics.

How you'd know it broke: prints one line per filing with the extracted
revenue, or the validation errors. Token spend is printed per call and
appended to data/llm_usage.log. Exit code is non-zero if anything was
flagged for review.

Model (rule 8): claude-haiku-4-5 by default; override with EXTRACTION_MODEL
in .env if the fixture test in tests/test_filing_revenue.py disagrees with
press-corroborated numbers.
"""

import base64
import datetime
import json
import os
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import schemas  # noqa: E402

DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"
USAGE_LOG = REPO_ROOT / "data" / "llm_usage.log"

PROMPT = """\
这是一家中国上市公司的季度报告。请从报告中提取本季度的营业收入。

规则：
- revenue_cny 必须是报告中实际印出的本季度营业收入，单位为人民币元。
  注意报表单位：如果表头写"单位：元"则直接使用；如果写"单位：万元"或
  "单位：千元"，请换算成元。
- 只使用"本报告期"（单季度）数字，不要使用年初至今累计数。
- revenue_yoy_pct 是报告中披露的营业收入同比增减百分比，如未披露则为 null。
- summary_zh / summary_en：一到两句话总结本季度收入情况及报告中说明的原因。
- evidence：指出数字出现的位置（章节/表格名称），便于人工核对。
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


def extract_from_pdf(pdf_bytes, model):
    """One LLM call: Mandarin filing PDF in, schema-constrained JSON out."""
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=2048,
        output_config={
            "format": {"type": "json_schema", "schema": schemas.FILING_REVENUE_SCHEMA}
        },
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
        raise RuntimeError("model refused the request; check stop_details")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text), response.usage


def log_usage(model, usage, note):
    USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = (
        f"{stamp} model={model} input_tokens={usage.input_tokens}"
        f" output_tokens={usage.output_tokens} note={note}\n"
    )
    with USAGE_LOG.open("a") as f:
        f.write(line)
    print("  token spend:", line.strip())


def flag_for_review(conn, document_id, reason):
    conn.execute(
        "INSERT INTO review_queue (item_type, item_id, reason) VALUES (?, ?, ?)",
        ("extraction", document_id, reason),
    )
    conn.commit()
    print(f"  flagged for review (document id={document_id}): {reason[:200]}")


def pending_filings(conn):
    """cninfo documents with no quarterly_revenue_cny metric yet, joined to
    the entity whose Chinese name appears in the document title."""
    return conn.execute(
        "SELECT d.id, d.raw_path, d.title, e.id, e.name_en"
        " FROM documents d"
        " JOIN sources s ON s.id = d.source_id AND s.name = 'cninfo'"
        " JOIN entities e ON instr(d.title, e.name_zh) > 0"
        " WHERE NOT EXISTS ("
        "   SELECT 1 FROM metrics m WHERE m.document_id = d.id"
        "     AND m.metric_name = 'quarterly_revenue_cny')"
        " ORDER BY d.id"
    ).fetchall()


def main():
    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add"
            " your key (never committed — .env is gitignored)."
        )
        return 1
    model = os.environ.get("EXTRACTION_MODEL", "claude-haiku-4-5")

    conn = connect()
    todo = pending_filings(conn)
    if not todo:
        print("nothing to extract — all cninfo filings already have revenue metrics")
        conn.close()
        return 0

    failures = 0
    for doc_id, raw_path, title, entity_id, name_en in todo:
        print(f"{name_en}: extracting from {title} (document id={doc_id}, model={model})")
        pdf_bytes = (REPO_ROOT / raw_path).read_bytes()
        try:
            data, usage = extract_from_pdf(pdf_bytes, model)
        except Exception as exc:  # API/parse errors -> review, keep going
            flag_for_review(conn, doc_id, f"extraction call failed: {exc}")
            failures += 1
            continue
        log_usage(model, usage, f"extract_filing_revenue doc_id={doc_id}")

        errors = schemas.validate_filing_revenue(data)
        if errors:
            flag_for_review(
                conn, doc_id,
                "validation failed: " + "; ".join(errors) + f" | raw: {json.dumps(data, ensure_ascii=False)[:500]}",
            )
            failures += 1
            continue
        if data["revenue_cny"] is None:
            flag_for_review(conn, doc_id, "model reports no quarterly revenue printed | " + data["evidence"])
            failures += 1
            continue

        conn.execute(
            "INSERT OR IGNORE INTO metrics"
            " (entity_id, metric_name, period, value, unit, currency, document_id,"
            "  extraction_confidence, notes)"
            " VALUES (?, 'quarterly_revenue_cny', ?, ?, 'CNY', 'CNY', ?, ?, ?)",
            (
                entity_id,
                data["period"],
                float(data["revenue_cny"]),
                doc_id,
                float(data["confidence"]),
                f"yoy: {data['revenue_yoy_pct']}% | {data['summary_zh']} | {data['summary_en']}"
                f" | evidence: {data['evidence']}",
            ),
        )
        conn.commit()
        yoy = data["revenue_yoy_pct"]
        print(
            f"  {data['period']} revenue: {data['revenue_cny']:,.0f} CNY"
            f" ({'+' if yoy and yoy >= 0 else ''}{yoy}% yoy),"
            f" confidence {data['confidence']}"
        )

    conn.close()
    if failures:
        print(f"\n{failures} filing(s) flagged for review")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
