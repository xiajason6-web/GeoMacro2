"""Scenario-framework tests (analysis/scenarios.py).

Checks the config is well-formed (probabilities sum to 1), the condition
operators evaluate correctly, and evaluate() picks the live-consistent
scenario from injected metrics.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import scenarios as sc  # noqa: E402


def test_config_probabilities_sum_to_one():
    cfg = json.loads((ROOT / "config" / "scenarios.json").read_text())
    total = sum(s["probability"] for s in cfg["scenarios"])
    assert total == pytest.approx(1.0)
    for s in cfg["scenarios"]:
        for c in s["consistent_if"]:
            assert c["op"] in ("gte", "lte", "between")


def test_check_operators():
    m = {"ratio_latest": 0.22, "x": None}
    assert sc.check({"metric": "ratio_latest", "op": "gte", "value": 0.20}, m) is True
    assert sc.check({"metric": "ratio_latest", "op": "lte", "value": 0.20}, m) is False
    assert sc.check({"metric": "ratio_latest", "op": "between", "value": [0.2, 0.28]}, m) is True
    assert sc.check({"metric": "x", "op": "gte", "value": 1}, m) is None  # unavailable


def test_evaluate_picks_live_consistent():
    cfg = {
        "as_of": "t",
        "scenarios": [
            {"id": "base", "name": "Base", "probability": 0.6, "thesis": "",
             "confirming": "", "falsifying": "", "exposed": "",
             "consistent_if": [
                 {"metric": "ratio_latest", "op": "between", "value": [0.2, 0.28]},
                 {"metric": "domestic_yoy_pct", "op": "gte", "value": 0}]},
            {"id": "stall", "name": "Stall", "probability": 0.4, "thesis": "",
             "confirming": "", "falsifying": "", "exposed": "",
             "consistent_if": [
                 {"metric": "ratio_latest", "op": "lte", "value": 0.21}]},
        ],
    }
    metrics = {"ratio_latest": 0.22, "domestic_yoy_pct": 29.0}
    ev = sc.evaluate(config=cfg, metrics=metrics)
    assert ev["live_consistent_id"] == "base"
    base = next(s for s in ev["scenarios"] if s["id"] == "base")
    assert base["conditions_hit"] == 2 and base["fully_consistent"] is True
    stall = next(s for s in ev["scenarios"] if s["id"] == "stall")
    assert stall["conditions_hit"] == 0
