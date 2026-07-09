"""Every JSON schema used by LLM extraction calls, plus a validator for each.

What this does: defines the exact shape each extraction response must have,
and provides validate_* functions that return a list of human-readable error
strings (empty list = valid). Every extraction script must run the matching
validator BEFORE anything is written to the database — rule 6: a value that
fails validation goes to review_queue, never into metrics.

How you'd know it broke: the fixture tests in tests/test_phase0.py feed both
known-good and known-bad payloads through the validators; if a validator
starts accepting garbage or rejecting good data, those tests fail.
"""

import re

# China share of sales from a Western equipment maker's quarterly results
# document (Phase 0: ASML). The API's structured-output feature enforces this
# shape server-side; the validator below re-checks it plus the numeric ranges
# that JSON Schema on the API can't express.
EARNINGS_REGION_SCHEMA = {
    "type": "object",
    "properties": {
        "period": {
            "type": "string",
            "description": "Fiscal quarter the document reports, formatted like '2026Q1'",
        },
        "china_pct": {
            "type": ["number", "null"],
            "description": (
                "China's share of sales as a percentage between 0 and 100, "
                "exactly as printed in the document. null if the document "
                "does not print a China percentage anywhere."
            ),
        },
        "basis": {
            "type": "string",
            "description": (
                "What the percentage is a share of, using the document's own "
                "wording, e.g. 'net system sales' or 'total net sales'"
            ),
        },
        "evidence": {
            "type": "string",
            "description": (
                "Where the number appears (slide/page and title) and the "
                "surrounding labels, so a human can verify it in seconds"
            ),
        },
        "confidence": {
            "type": "number",
            "description": (
                "Extraction confidence between 0.0 and 1.0. Use below 0.7 if "
                "the number had to be inferred rather than read off a label."
            ),
        },
    },
    "required": ["period", "china_pct", "basis", "evidence", "confidence"],
    "additionalProperties": False,
}

_PERIOD_RE = re.compile(r"^\d{4}Q[1-4]$")


def validate_earnings_region(data):
    """Return a list of error strings; empty list means the payload is valid."""
    errors = []
    if not isinstance(data, dict):
        return ["payload is not a JSON object"]

    for field in EARNINGS_REGION_SCHEMA["required"]:
        if field not in data:
            errors.append(f"missing required field: {field}")
    if errors:
        return errors

    if not isinstance(data["period"], str) or not _PERIOD_RE.match(data["period"]):
        errors.append(f"period must look like '2026Q1', got: {data['period']!r}")

    pct = data["china_pct"]
    if pct is not None:
        if not isinstance(pct, (int, float)) or isinstance(pct, bool):
            errors.append(f"china_pct must be a number or null, got: {pct!r}")
        elif not (0 <= pct <= 100):
            errors.append(f"china_pct out of range 0-100: {pct!r}")

    for field in ("basis", "evidence"):
        if not isinstance(data[field], str) or not data[field].strip():
            errors.append(f"{field} must be a non-empty string")

    conf = data["confidence"]
    if not isinstance(conf, (int, float)) or isinstance(conf, bool):
        errors.append(f"confidence must be a number, got: {conf!r}")
    elif not (0 <= conf <= 1):
        errors.append(f"confidence out of range 0-1: {conf!r}")

    unexpected = set(data) - set(EARNINGS_REGION_SCHEMA["properties"])
    if unexpected:
        errors.append(f"unexpected fields: {sorted(unexpected)}")

    return errors
