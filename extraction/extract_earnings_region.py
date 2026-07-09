"""Extraction: China revenue share from a Western earnings document.

What this does: loads the most recent ASML document from the database, sends
the raw PDF to the Claude API with a strict JSON schema (see schemas.py),
validates the response, and writes exactly one row to `metrics`, tied to the
document it came from. If validation fails — or the model can't find the
number — nothing goes into metrics; instead a row lands in `review_queue`
for you and the script exits non-zero.

How you'd know it broke: it prints the token spend and the extracted values
on success, or the validation errors and a "flagged for review" line on
failure. It also appends one line per run to data/llm_usage.log so token
spend is auditable over time.

Model choice (rule 8): defaults to claude-haiku-4-5, the smallest/cheapest
model that supports PDF input and structured outputs. Override with
EXTRACTION_MODEL in .env if the fixture test shows it isn't accurate enough.
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

ENTITY = {
    "name_en": "ASML",
    "name_zh": "阿斯麦",
    "ticker": "ASML",
    "exchange": "NASDAQ",
    "entity_type": "company",
    "supply_chain_layer": "equipment",
}

PROMPT = """\
This is a quarterly investor-relations presentation from ASML, a semiconductor
lithography equipment maker. Find the sales-by-region breakdown for the quarter
the presentation reports, and extract China's share.

Rules:
- Only report a percentage that is actually printed in the document (as a chart
  label or in text). If no China percentage is printed anywhere, set china_pct
  to null.
- Use the most recent quarter's figure if several quarters are shown.
- 'basis' must repeat the document's own wording for what the split covers
  (for example 'net system sales' vs 'total net sales' — these differ).
- 'period' is the quarter the presentation reports, like '2026Q1'.
"""


def load_env():
    """Minimal .env loader — no extra dependency. Existing env vars win."""
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def extract_from_pdf(pdf_bytes, model):
    """One LLM call: PDF in, schema-constrained JSON out.

    Returns (data, usage) where data is the parsed dict (NOT yet validated)
    and usage is the API usage object for spend logging.
    """
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=2048,
        output_config={
            "format": {"type": "json_schema", "schema": schemas.EARNINGS_REGION_SCHEMA}
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
    print("token spend:", line.strip())


def ensure_entity(conn):
    conn.execute(
        "INSERT OR IGNORE INTO entities"
        " (name_en, name_zh, ticker, exchange, entity_type, supply_chain_layer)"
        " VALUES (:name_en, :name_zh, :ticker, :exchange, :entity_type, :supply_chain_layer)",
        ENTITY,
    )
    return conn.execute(
        "SELECT id FROM entities WHERE name_en = ?", (ENTITY["name_en"],)
    ).fetchone()[0]


def flag_for_review(conn, document_id, reason):
    conn.execute(
        "INSERT INTO review_queue (item_type, item_id, reason) VALUES (?, ?, ?)",
        ("extraction", document_id, reason),
    )
    conn.commit()
    print(f"flagged for review (document id={document_id}): {reason}")


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
    doc = conn.execute(
        "SELECT d.id, d.raw_path, d.title FROM documents d"
        " JOIN sources s ON s.id = d.source_id"
        " WHERE s.name = 'ASML IR' ORDER BY d.id DESC LIMIT 1"
    ).fetchone()
    if doc is None:
        print("no ASML document in the database — run collectors/western_earnings.py first")
        return 1
    doc_id, raw_path, title = doc

    # Skip if this document was already extracted (safe to re-run).
    entity_id = ensure_entity(conn)
    already = conn.execute(
        "SELECT id FROM metrics WHERE document_id = ? AND metric_name = 'china_revenue_pct'",
        (doc_id,),
    ).fetchone()
    if already:
        print(f"metrics row already exists for document id={doc_id} (metrics id={already[0]})")
        conn.close()
        return 0

    print(f"extracting from: {title} (document id={doc_id}, model={model})")
    pdf_bytes = (REPO_ROOT / raw_path).read_bytes()
    data, usage = extract_from_pdf(pdf_bytes, model)
    log_usage(model, usage, f"extract_earnings_region doc_id={doc_id}")

    errors = schemas.validate_earnings_region(data)
    if errors:
        flag_for_review(conn, doc_id, "validation failed: " + "; ".join(errors) + f" | raw: {json.dumps(data)[:500]}")
        return 1
    if data["china_pct"] is None:
        flag_for_review(conn, doc_id, "model reports no China percentage printed in document | " + data["evidence"])
        return 1

    conn.execute(
        "INSERT INTO metrics"
        " (entity_id, metric_name, period, value, unit, currency, document_id,"
        "  extraction_confidence, notes)"
        " VALUES (?, 'china_revenue_pct', ?, ?, 'pct', NULL, ?, ?, ?)",
        (
            entity_id,
            data["period"],
            float(data["china_pct"]),
            doc_id,
            float(data["confidence"]),
            f"basis: {data['basis']} | evidence: {data['evidence']}",
        ),
    )
    conn.commit()

    row = conn.execute(
        "SELECT m.id, e.name_en, m.metric_name, m.period, m.value, m.unit,"
        "       m.extraction_confidence, m.notes, d.url"
        " FROM metrics m JOIN entities e ON e.id = m.entity_id"
        " JOIN documents d ON d.id = m.document_id"
        " WHERE m.document_id = ? AND m.metric_name = 'china_revenue_pct'",
        (doc_id,),
    ).fetchone()
    conn.close()

    print("\nwritten to metrics and read back from the database:")
    for label, value in zip(
        ["metrics.id", "entity", "metric", "period", "value", "unit", "confidence", "notes", "source url"],
        row,
    ):
        print(f"  {label:12} {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
