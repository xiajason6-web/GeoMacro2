"""Extraction: translate and classify Chinese policy events.

What this does: finds `events` rows whose summary_en is the
'PENDING_TRANSLATION' sentinel (produced by collectors/policy_monitor.py), and for each one makes an LLM call that
returns an English summary and a category from a fixed list. Validated
before the events row is updated; failures go to review_queue.

How you'd know it broke: prints one line per event with the category
assigned; token spend logged to data/llm_usage.log as always.
"""

import datetime
import json
import os
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"
USAGE_LOG = REPO_ROOT / "data" / "llm_usage.log"

CATEGORIES = [
    "export_control",      # 出口管制 measures by China
    "industrial_policy",   # development plans, guidance catalogs
    "subsidy",             # funds, tax breaks, financial support
    "procurement",         # government purchasing, tenders
    "standards",           # technical standards, certification
    "other",               # semiconductor-adjacent but none of the above
]

SCHEMA = {
    "type": "object",
    "properties": {
        "summary_en": {
            "type": "string",
            "description": "One-sentence English summary of what this policy document does",
        },
        "category": {"type": "string", "enum": CATEGORIES},
        "relevance": {
            "type": "string",
            "enum": ["high", "medium", "low"],
            "description": (
                "Relevance to semiconductor indigenization analysis: high ="
                " directly changes semicap/chip supply or demand; medium ="
                " sector-adjacent; low = mentions the sector incidentally"
            ),
        },
    },
    "required": ["summary_en", "category", "relevance"],
    "additionalProperties": False,
}

PROMPT_TMPL = """\
The following is the official title of a Chinese government policy document
(published {date} by {actor}). Translate it into a one-sentence English
summary, classify it, and rate its relevance to semiconductor-industry
analysis.

Title: {title}
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
    for field in SCHEMA["required"]:
        if field not in data:
            errors.append(f"missing required field: {field}")
    if errors:
        return errors
    if not isinstance(data["summary_en"], str) or not data["summary_en"].strip():
        errors.append("summary_en must be a non-empty string")
    if data["category"] not in CATEGORIES:
        errors.append(f"category not in {CATEGORIES}: {data['category']!r}")
    if data["relevance"] not in ("high", "medium", "low"):
        errors.append(f"relevance invalid: {data['relevance']!r}")
    return errors


def classify(title, date, actor, model):
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=512,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[
            {
                "role": "user",
                "content": PROMPT_TMPL.format(title=title, date=date, actor=actor),
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
    todo = conn.execute(
        "SELECT id, event_date, actor, summary_zh FROM events"
        " WHERE summary_en = 'PENDING_TRANSLATION' ORDER BY event_date"
    ).fetchall()
    if not todo:
        print("nothing to classify — all events have summary_en")
        conn.close()
        return 0

    total_in = total_out = failures = 0
    for event_id, date, actor, summary_zh in todo:
        try:
            data, usage = classify(summary_zh, date, actor, model)
        except Exception as exc:
            conn.execute(
                "INSERT INTO review_queue (item_type, item_id, reason) VALUES ('event_classify', ?, ?)",
                (event_id, f"classification call failed: {exc}"),
            )
            conn.commit()
            failures += 1
            continue
        total_in += usage.input_tokens
        total_out += usage.output_tokens
        errors = validate(data)
        if errors:
            conn.execute(
                "INSERT INTO review_queue (item_type, item_id, reason) VALUES ('event_classify', ?, ?)",
                (event_id, "validation failed: " + "; ".join(errors)),
            )
            conn.commit()
            failures += 1
            continue
        conn.execute(
            "UPDATE events SET summary_en = ?, category = ? WHERE id = ?",
            (
                f"{data['summary_en']} [relevance: {data['relevance']}]",
                data["category"],
                event_id,
            ),
        )
        conn.commit()
        print(f"event {event_id} [{date}] -> {data['category']}/{data['relevance']}: {data['summary_en'][:70]}")

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with USAGE_LOG.open("a") as f:
        f.write(
            f"{stamp} model={model} input_tokens={total_in} output_tokens={total_out}"
            f" note=translate_classify_policy n={len(todo)}\n"
        )
    print(f"classified {len(todo) - failures}/{len(todo)} events")
    conn.close()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
