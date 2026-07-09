"""Red team: the strongest case AGAINST the current thesis, from our own DB.

What this does: assembles the current indigenization series, the methodology
bias table, and recent events from the database, then makes one LLM call
that must argue AGAINST the thesis "China's semicap indigenization is
accelerating," citing the pipeline's own numbers and known biases. The
output is a schema-validated draft saved to data/exports/red_team_DATE.md
and included in the weekly digest — for human review, never auto-published.

Model: judgment work, not extraction, so this defaults to claude-sonnet-5
(one call per digest; override with REDTEAM_MODEL in .env).

How you'd know it broke: prints the output path; validation failures land
in review_queue like any extraction failure.
"""

import datetime
import json
import os
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"
USAGE_LOG = REPO_ROOT / "data" / "llm_usage.log"
OUT_DIR = REPO_ROOT / "data" / "exports"

SCHEMA = {
    "type": "object",
    "properties": {
        "counter_thesis": {
            "type": "string",
            "description": "One-paragraph strongest-form statement of the case against",
        },
        "arguments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "evidence": {
                        "type": "string",
                        "description": "Specific numbers/series/biases from the provided data — no outside facts",
                    },
                },
                "required": ["claim", "evidence"],
                "additionalProperties": False,
            },
        },
        "what_would_change_my_mind": {
            "type": "string",
            "description": "The data that, if collected, would settle the disagreement",
        },
    },
    "required": ["counter_thesis", "arguments", "what_would_change_my_mind"],
    "additionalProperties": False,
}

PROMPT_TMPL = """\
You are the red team for a research pipeline tracking China's semiconductor
equipment indigenization. The house thesis is: "China's semicap
indigenization is accelerating — domestic WFE share roughly doubled from
~17% (2023Q3) to ~37% (2026Q1)."

Argue the STRONGEST case against this thesis or its interpretation. Rules:
- Use ONLY the data and documented biases below. Do not invent numbers.
- Attack the measurement first (biases, coverage, composition), then the
  interpretation (what else could produce this pattern).
- 3-5 arguments, each citing specific figures from the data provided.

=== Indigenization series (quarter, imports CNY, domestic CNY, n_companies, ratio) ===
{series}

=== Documented biases (from methodology.md) ===
{biases}

=== Recent events (last 90 days) ===
{events}
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


def gather_inputs(conn):
    series_csv = (OUT_DIR / "indigenization_ratio.csv")
    series = series_csv.read_text() if series_csv.exists() else "(not computed yet)"

    methodology = (REPO_ROOT / "analysis" / "methodology.md").read_text()
    # Keep only the bias tables — enough for the red team, keeps tokens down.
    biases = "\n".join(
        line for line in methodology.splitlines() if line.startswith("|")
    )

    events = conn.execute(
        "SELECT event_date, category, COALESCE(summary_en, summary_zh)"
        " FROM events WHERE event_date >= date('now', '-90 days')"
        " ORDER BY event_date DESC LIMIT 30"
    ).fetchall()
    events_text = "\n".join(f"{d} [{c}] {s[:120]}" for d, c, s in events) or "(none)"
    return series, biases, events_text


def generate(conn, model):
    import anthropic

    series, biases, events_text = gather_inputs(conn)
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[
            {
                "role": "user",
                "content": PROMPT_TMPL.format(
                    series=series, biases=biases, events=events_text
                ),
            }
        ],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("model refused; check stop_details")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text), response.usage


def validate(data):
    errors = []
    if not isinstance(data, dict):
        return ["payload is not a JSON object"]
    for field in SCHEMA["required"]:
        if field not in data:
            errors.append(f"missing required field: {field}")
    if errors:
        return errors
    if not isinstance(data["arguments"], list) or not (1 <= len(data["arguments"]) <= 8):
        errors.append("arguments must be a list of 1-8 items")
    else:
        for i, arg in enumerate(data["arguments"]):
            if not isinstance(arg, dict) or not arg.get("claim") or not arg.get("evidence"):
                errors.append(f"argument {i} missing claim/evidence")
    return errors


def render_markdown(data):
    lines = ["## Red team: the case against", ""]
    lines.append(data["counter_thesis"])
    lines.append("")
    for i, arg in enumerate(data["arguments"], 1):
        lines.append(f"**{i}. {arg['claim']}**")
        lines.append(f"   Evidence: {arg['evidence']}")
        lines.append("")
    lines.append(f"**What would change the red team's mind:** {data['what_would_change_my_mind']}")
    return "\n".join(lines)


def main():
    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set (see .env.example)")
        return 1
    model = os.environ.get("REDTEAM_MODEL", "claude-sonnet-5")

    conn = connect()
    try:
        data, usage = generate(conn, model)
    except Exception as exc:
        conn.execute(
            "INSERT INTO review_queue (item_type, item_id, reason) VALUES ('red_team', NULL, ?)",
            (f"red team call failed: {exc}",),
        )
        conn.commit()
        conn.close()
        print(f"red team failed: {exc}")
        return 1

    errors = validate(data)
    if errors:
        conn.execute(
            "INSERT INTO review_queue (item_type, item_id, reason) VALUES ('red_team', NULL, ?)",
            ("validation failed: " + "; ".join(errors),),
        )
        conn.commit()
        conn.close()
        print("red team output failed validation:", errors)
        return 1

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with USAGE_LOG.open("a") as f:
        f.write(
            f"{stamp} model={model} input_tokens={usage.input_tokens}"
            f" output_tokens={usage.output_tokens} note=red_team\n"
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"red_team_{datetime.date.today().isoformat()}.md"
    out_path.write_text(render_markdown(data))
    print(f"wrote {out_path.relative_to(REPO_ROOT)}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
