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

# Quarterly revenue from a Chinese-listed company's quarterly report
# (一季度报告 etc.), extracted in-language. summary_zh and summary_en are both
# stored per the Mandarin-document rule in CLAUDE.md.
FILING_REVENUE_SCHEMA = {
    "type": "object",
    "properties": {
        "period": {
            "type": "string",
            "description": "Fiscal quarter the report covers, formatted like '2026Q1'",
        },
        "revenue_cny": {
            "type": ["number", "null"],
            "description": (
                "营业收入 (operating revenue) for the quarter in CNY yuan, "
                "exactly as printed (e.g. 10322612345.67). null only if the "
                "report does not state quarterly revenue."
            ),
        },
        "revenue_yoy_pct": {
            "type": ["number", "null"],
            "description": (
                "Year-over-year revenue change in percent as printed "
                "(e.g. 25.80), or null if not stated."
            ),
        },
        "summary_zh": {
            "type": "string",
            "description": "一两句中文总结：本季度收入及主要变动原因（按报告原文）",
        },
        "summary_en": {
            "type": "string",
            "description": "One-two sentence English summary of the quarter's revenue and stated drivers",
        },
        "evidence": {
            "type": "string",
            "description": "Where the figure appears (section/table name in the report) so a human can verify quickly",
        },
        "confidence": {
            "type": "number",
            "description": "Extraction confidence 0.0-1.0",
        },
    },
    "required": [
        "period",
        "revenue_cny",
        "revenue_yoy_pct",
        "summary_zh",
        "summary_en",
        "evidence",
        "confidence",
    ],
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


def validate_filing_revenue(data):
    """Return a list of error strings; empty list means the payload is valid."""
    errors = []
    if not isinstance(data, dict):
        return ["payload is not a JSON object"]

    for field in FILING_REVENUE_SCHEMA["required"]:
        if field not in data:
            errors.append(f"missing required field: {field}")
    if errors:
        return errors

    if not isinstance(data["period"], str) or not _PERIOD_RE.match(data["period"]):
        errors.append(f"period must look like '2026Q1', got: {data['period']!r}")

    rev = data["revenue_cny"]
    if rev is not None:
        if not isinstance(rev, (int, float)) or isinstance(rev, bool):
            errors.append(f"revenue_cny must be a number or null, got: {rev!r}")
        elif not (1e6 <= rev <= 1e12):
            # A listed semicap company's quarterly revenue below 1M or above
            # 1T yuan means the units are wrong (万元 vs 元 confusion).
            errors.append(f"revenue_cny implausible (check 元 vs 万元 units): {rev!r}")

    yoy = data["revenue_yoy_pct"]
    if yoy is not None:
        if not isinstance(yoy, (int, float)) or isinstance(yoy, bool):
            errors.append(f"revenue_yoy_pct must be a number or null, got: {yoy!r}")
        elif not (-100 <= yoy <= 1000):
            errors.append(f"revenue_yoy_pct out of range: {yoy!r}")

    for field in ("summary_zh", "summary_en", "evidence"):
        if not isinstance(data[field], str) or not data[field].strip():
            errors.append(f"{field} must be a non-empty string")

    conf = data["confidence"]
    if not isinstance(conf, (int, float)) or isinstance(conf, bool):
        errors.append(f"confidence must be a number, got: {conf!r}")
    elif not (0 <= conf <= 1):
        errors.append(f"confidence out of range 0-1: {conf!r}")

    unexpected = set(data) - set(FILING_REVENUE_SCHEMA["properties"])
    if unexpected:
        errors.append(f"unexpected fields: {sorted(unexpected)}")

    return errors
