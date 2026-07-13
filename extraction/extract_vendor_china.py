"""Extraction: China revenue share from vendor 10-Q/10-K filings + signals.

What this does: for each SEC vendor filing lacking a china_revenue_pct
metric, converts the HTML to text, keeps only the China-relevant windows
(the geographic-revenue disclosures), and makes one LLM call with a strict
schema. Valid results become:
  - a metrics row: china_revenue_pct, period = fiscal period end 'YYYY-MM'
  - a hifreq_signals row (signal_type 'vendor_china_revenue', dated the
    FILING date — that's when the market learned it)
It also backfills signals for any pre-existing china_revenue_pct rows
(e.g. ASML's, collected from IR PDFs).

How you'd know it broke: one line per filing with the share, or the
validation errors; spend in data/llm_usage.log.
"""

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
        "fiscal_period_end": {
            "type": "string",
            "description": "End date of the fiscal period reported, YYYY-MM-DD",
        },
        "china_revenue_pct": {
            "type": ["number", "null"],
            "description": (
                "China share of total net revenue for the QUARTER (three-month"
                " period) just ended, in percent 0-100, exactly as disclosed"
                " or computable from the disclosed China and total revenue"
                " amounts for that quarter. null if not disclosed."
            ),
        },
        "basis": {"type": "string", "description": "e.g. 'net revenue by geography, three months ended'"},
        "evidence": {"type": "string", "description": "table/section where disclosed"},
        "confidence": {"type": "number"},
    },
    "required": ["fiscal_period_end", "china_revenue_pct", "basis", "evidence", "confidence"],
    "additionalProperties": False,
}

PROMPT_TMPL = """\
These are excerpts from {company}'s SEC {form} (fiscal period ended
{report_date}). Find the revenue-by-geography disclosure and extract China's
share of revenue for the three-month period ended {report_date}.

Rules:
- Use the QUARTER (three months ended) figures, not year-to-date/annual,
  unless this is a 10-K annual disclosure with no quarterly split — then use
  the annual figure and say so in `basis`.
- If percentages are not printed, compute China amount / total amount from
  the same disclosed table is acceptable; state amounts in `evidence`.
- If the disclosure is absent from these excerpts, set china_revenue_pct to
  null.
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


def china_snippets(html, window=2500, cap=24000):
    """window/cap are widened for 10-Ks by the caller — annual reports put
    the geography table further from the word 'China' than 10-Qs do."""
    """HTML -> plain text -> merged windows around 'China' mentions."""
    from bs4 import BeautifulSoup

    text = BeautifulSoup(html, "lxml").get_text(" ")
    text = re.sub(r"\s+", " ", text)
    spans = []
    for m in re.finditer(r"China", text):
        start, end = max(0, m.start() - window), min(len(text), m.end() + window)
        if spans and start <= spans[-1][1]:
            spans[-1] = (spans[-1][0], end)
        else:
            spans.append((start, end))
    # Prioritize spans that look like the geographic-revenue disclosure —
    # in a 10-K, dozens of risk-factor 'China' mentions precede the note we
    # actually need, and a naive cap fills before reaching it.
    def looks_like_table(chunk):
        low = chunk.lower()
        return ("revenue" in low or "net sales" in low) and (
            "geograph" in low or "region" in low
        )

    chunks = [text[s:e] for s, e in spans]
    prioritized = [c for c in chunks if looks_like_table(c)] + [
        c for c in chunks if not looks_like_table(c)
    ]
    out, used = [], 0
    for chunk in prioritized:
        if used + len(chunk) > cap:
            continue
        out.append(chunk)
        used += len(chunk)
    return " [...] ".join(out)


def validate(data, expected_end):
    errors = []
    if not isinstance(data, dict):
        return ["payload is not a JSON object"]
    for field in SCHEMA["required"]:
        if field not in data:
            errors.append(f"missing required field: {field}")
    if errors:
        return errors
    if data["fiscal_period_end"] != expected_end:
        errors.append(
            f"fiscal_period_end mismatch: expected {expected_end},"
            f" got {data['fiscal_period_end']!r}"
        )
    pct = data["china_revenue_pct"]
    if pct is not None:
        if not isinstance(pct, (int, float)) or isinstance(pct, bool):
            errors.append(f"china_revenue_pct must be number or null: {pct!r}")
        elif not (0 <= pct <= 100):
            errors.append(f"china_revenue_pct out of range: {pct!r}")
    conf = data["confidence"]
    if not isinstance(conf, (int, float)) or isinstance(conf, bool) or not (0 <= conf <= 1):
        errors.append(f"confidence invalid: {conf!r}")
    return errors


def pending(conn):
    return conn.execute(
        "SELECT d.id, d.raw_path, d.title, d.doc_date, e.id, e.name_en FROM documents d"
        " JOIN sources s ON s.id = d.source_id AND s.name = 'SEC EDGAR'"
        " JOIN entities e ON d.title LIKE e.name_en || ' 10-%'"
        " WHERE NOT EXISTS (SELECT 1 FROM metrics m WHERE m.document_id = d.id"
        "                   AND m.metric_name = 'china_revenue_pct')"
        " ORDER BY d.id"
    ).fetchall()


def extract(text, company, form, report_date, model):
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[
            {
                "role": "user",
                "content": PROMPT_TMPL.format(
                    company=company, form=form, report_date=report_date
                ) + "\n\n=== EXCERPTS ===\n" + text,
            }
        ],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("model refused; check stop_details")
    return json.loads(next(b.text for b in response.content if b.type == "text")), response.usage


def emit_signal(conn, entity_id, name, doc_id, doc_date, period, pct):
    summary = f"{name}: China {pct:.1f}% of revenue (period {period})"
    exists = conn.execute(
        "SELECT 1 FROM hifreq_signals WHERE signal_type = 'vendor_china_revenue'"
        " AND summary_en = ?",
        (summary,),
    ).fetchone()
    if exists:
        return False
    conn.execute(
        "INSERT INTO hifreq_signals"
        " (signal_date, signal_type, entity_id, value, unit, summary_en,"
        "  document_id, retrieved_at)"
        " VALUES (?, 'vendor_china_revenue', ?, ?, 'pct', ?, ?, ?)",
        (
            doc_date or period, entity_id, pct, summary, doc_id,
            datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ),
    )
    return True


def backfill_existing_signals(conn):
    """ASML (and any other) china_revenue_pct rows -> signals if absent."""
    rows = conn.execute(
        "SELECT m.entity_id, e.name_en, m.document_id, d.doc_date, m.period, m.value"
        " FROM metrics m JOIN entities e ON e.id = m.entity_id"
        " JOIN documents d ON d.id = m.document_id"
        " WHERE m.metric_name = 'china_revenue_pct'"
    ).fetchall()
    n = 0
    for entity_id, name, doc_id, doc_date, period, value in rows:
        if emit_signal(conn, entity_id, name, doc_id, doc_date, period, value):
            n += 1
    conn.commit()
    if n:
        print(f"backfilled {n} vendor signals from existing metrics")


def main():
    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set (see .env.example)")
        return 1
    model = os.environ.get("EXTRACTION_MODEL", "claude-haiku-4-5")

    conn = connect()
    todo = pending(conn)
    total_in = total_out = failures = 0
    for doc_id, raw_path, title, doc_date, entity_id, name_en in todo:
        m = re.search(r"\(period ended (\d{4}-\d{2}-\d{2})\)", title)
        form = "10-K" if "10-K" in title else "10-Q"
        report_date = m.group(1)
        print(f"{name_en} {form} {report_date}: doc id={doc_id}")
        html = (REPO_ROOT / raw_path).read_bytes()
        wide = form == "10-K"
        snippets = china_snippets(
            html.decode("utf-8", errors="ignore"),
            window=6000 if wide else 2500,
            cap=60000 if wide else 24000,
        )
        if not snippets:
            conn.execute(
                "INSERT INTO review_queue (item_type, item_id, reason)"
                " VALUES ('extraction', ?, ?)",
                (doc_id, f"vendor china: no 'China' text found in {title}"),
            )
            conn.commit()
            failures += 1
            continue
        try:
            data, usage = extract(snippets, name_en, form, report_date, model)
        except Exception as exc:
            conn.execute(
                "INSERT INTO review_queue (item_type, item_id, reason)"
                " VALUES ('extraction', ?, ?)",
                (doc_id, f"vendor china extraction failed: {exc}"),
            )
            conn.commit()
            failures += 1
            continue
        total_in += usage.input_tokens
        total_out += usage.output_tokens

        errors = validate(data, report_date)
        if not errors and data["china_revenue_pct"] is None:
            errors = ["china revenue not disclosed in excerpts | " + data["evidence"]]
        if errors:
            conn.execute(
                "INSERT INTO review_queue (item_type, item_id, reason)"
                " VALUES ('extraction', ?, ?)",
                (doc_id, f"vendor china {name_en} {report_date}: " + "; ".join(errors)[:400]),
            )
            conn.commit()
            failures += 1
            continue

        period = report_date[:7]
        conn.execute(
            "INSERT OR IGNORE INTO metrics"
            " (entity_id, metric_name, period, value, unit, currency, document_id,"
            "  extraction_confidence, notes)"
            " VALUES (?, 'china_revenue_pct', ?, ?, 'pct', NULL, ?, ?, ?)",
            (
                entity_id, period, float(data["china_revenue_pct"]), doc_id,
                float(data["confidence"]),
                f"{form} | basis: {data['basis'][:150]} | evidence: {data['evidence'][:200]}",
            ),
        )
        emit_signal(conn, entity_id, name_en, doc_id, doc_date, period,
                    float(data["china_revenue_pct"]))
        conn.commit()
        print(f"  China {data['china_revenue_pct']:.1f}% of revenue ({data['basis'][:60]})")

    backfill_existing_signals(conn)
    if todo:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with USAGE_LOG.open("a") as f:
            f.write(
                f"{stamp} model={model} input_tokens={total_in} output_tokens={total_out}"
                f" note=extract_vendor_china n={len(todo)}\n"
            )
    print(f"\nprocessed {len(todo) - failures}/{len(todo)}; failures flagged: {failures}")
    conn.close()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
