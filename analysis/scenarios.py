"""Probabilistic scenario framework that self-monitors against live data.

The Eurasia/BCA staple — bull/base/bear with probabilities — but made
auto-falsifiable: each scenario in config/scenarios.json carries machine-
checkable `consistent_if` conditions on the tracker's OWN latest exports. This
module evaluates them and reports which scenario current data is most
consistent with, so the scenario set grades itself instead of resting on
punditry. Probabilities are house judgment (stated as such); at this n they are
never fitted.

Deterministic. Outputs:
  data/exports/scenarios.md      — the scenario table + current-consistency read
  data/exports/scenarios.json    — evaluated scenarios (for the dashboard)

Run:  .venv/bin/python analysis/scenarios.py
"""

import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPORTS = REPO_ROOT / "data" / "exports"
CONFIG = REPO_ROOT / "config" / "scenarios.json"
OUT_MD = EXPORTS / "scenarios.md"
OUT_JSON = EXPORTS / "scenarios.json"


def current_metrics(exports=EXPORTS):
    """The live values the scenarios are checked against — latest full-coverage
    quarter. Returns {metric: value or None}."""
    def rd(name):
        p = exports / name
        return pd.read_csv(p) if p.exists() else pd.DataFrame()

    m = {"ratio_latest": None, "domestic_yoy_pct": None,
         "chip_share_latest": None, "us_equip_latest_bn": None}

    ratio = rd("indigenization_ratio.csv")
    if not ratio.empty:
        full = ratio[ratio["ratio"].notna()
                     & (ratio["missing_origins"].fillna("") == "Taiwan")]
        if not full.empty:
            last = full.iloc[-1]
            m["ratio_latest"] = float(last["ratio"])
            q = last["quarter"]
            y, n = q.split("Q")
            py = f"{int(y) - 1}Q{n}"
            allr = ratio.set_index("quarter")
            if py in allr.index:
                a = float(last["domestic_semicap_usd"])
                b = float(allr.loc[py, "domestic_semicap_usd"])
                if b:
                    m["domestic_yoy_pct"] = 100.0 * (a - b) / b

    chips = rd("chip_self_sufficiency.csv")
    if not chips.empty:
        m["chip_share_latest"] = float(chips.iloc[-1]["chip_domestic_share"])

    cf = rd("did_counterfactual.csv")
    if not cf.empty:
        m["us_equip_latest_bn"] = float(cf.iloc[-1]["us_actual_usd"]) / 1e9

    return m


def check(cond, metrics):
    """Evaluate one condition. Returns True/False, or None if the metric is
    unavailable (condition can't be judged yet)."""
    v = metrics.get(cond["metric"])
    if v is None:
        return None
    op, target = cond["op"], cond["value"]
    if op == "gte":
        return v >= target
    if op == "lte":
        return v <= target
    if op == "between":
        return target[0] <= v <= target[1]
    return None


def evaluate(config=None, metrics=None):
    config = config if config is not None else json.loads(CONFIG.read_text())
    metrics = metrics if metrics is not None else current_metrics()
    out = []
    for s in config["scenarios"]:
        results = [check(c, metrics) for c in s["consistent_if"]]
        judged = [r for r in results if r is not None]
        n_hit = sum(1 for r in judged if r)
        out.append({
            **{k: s[k] for k in ("id", "name", "probability", "thesis",
                                 "confirming", "falsifying", "exposed")},
            "conditions_hit": n_hit,
            "conditions_judged": len(judged),
            "conditions_total": len(s["consistent_if"]),
            "fully_consistent": len(judged) > 0 and n_hit == len(judged),
        })
    # "live-consistent" = highest hit-fraction, tie broken by probability
    def score(s):
        frac = s["conditions_hit"] / s["conditions_judged"] if s["conditions_judged"] else -1
        return (frac, s["probability"])
    live = max(out, key=score) if out else None
    return {"as_of": config.get("as_of"), "metrics": metrics,
            "scenarios": out, "live_consistent_id": live["id"] if live else None}


def build_md(ev):
    m = ev["metrics"]
    def fmt(x, pct=True):
        if x is None:
            return "n/a"
        return f"{x:.1%}" if pct else f"{x:+.0f}%"
    live = next((s for s in ev["scenarios"] if s["id"] == ev["live_consistent_id"]), None)
    lines = [
        "# Scenarios — probabilistic, self-monitoring",
        "",
        "House-judgment probabilities (not fitted — n is too small). Each"
        " scenario's `consistent_if` conditions are checked against the"
        " tracker's own latest exports, so the set grades itself.",
        "",
        f"**Current read** (as of {ev['as_of']}): ratio"
        f" {fmt(m['ratio_latest'])}, domestic revenue YoY"
        f" {fmt(m['domestic_yoy_pct'], pct=False)}, chip share"
        f" {fmt(m['chip_share_latest'])}, US equipment"
        f" ${m['us_equip_latest_bn']:.2f}bn/qtr."
        + (f" Data is most consistent with **{live['name']}**"
           f" ({live['conditions_hit']}/{live['conditions_judged']} conditions"
           f" met)." if live else ""),
        "",
        "| Scenario | Prob | Live fit | Thesis |",
        "|---|---|---|---|",
    ]
    for s in ev["scenarios"]:
        fit = f"{s['conditions_hit']}/{s['conditions_judged']}" if s["conditions_judged"] else "—"
        star = " ◀ live" if s["id"] == ev["live_consistent_id"] else ""
        lines.append(f"| **{s['name']}**{star} | {s['probability']:.0%} | {fit} |"
                     f" {s['thesis'][:120]}… |")
    lines += ["", "## Detail", ""]
    for s in ev["scenarios"]:
        lines += [
            f"### {s['name']} — {s['probability']:.0%}",
            f"- **Thesis.** {s['thesis']}",
            f"- **Confirming.** {s['confirming']}",
            f"- **Falsifying.** {s['falsifying']}",
            f"- **Exposure.** {s['exposed']}",
            "",
        ]
    lines += [
        "_Probabilities are house judgment, edited in config/scenarios.json"
        " (auditable, git-timestamped). Research, not investment advice._",
    ]
    return "\n".join(lines)


def main():
    ev = evaluate()
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(ev, indent=2))
    md = build_md(ev)
    OUT_MD.write_text(md)
    print(md)
    print(f"\nwrote {OUT_MD.relative_to(REPO_ROOT)} and {OUT_JSON.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
