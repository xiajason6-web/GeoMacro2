"""Public calls ledger — an append-only, auto-graded track record.

Mirrors the Iran model's calls ledger. `calls/ledger.json` is append-only and
git-timestamped; this module grades open calls against the repo's OWN committed
exports (the same numbers the research note shows) and reports the running
Brier score. It runs in the nightly pipeline, so the record self-grades without
anyone remembering to.

Rules of the ledger:
  - A call carries the model probability AT TIME OF CALL plus explicit criteria
    checkable from data/exports. Git history is the timestamp.
  - NEVER edit or delete a resolved call — a correction is a NEW call.
  - Brier score (0 = perfect, 0.25 = coin-flip on 50/50 calls; lower is better)
    is reported over all resolved calls.

Criteria types (all checkable from committed CSVs):
  ratio_gte / ratio_lte  full-coverage indigenization ratio for {quarter}
  us_equip_lte           US-origin HS 8486 exports to China in {quarter}, $bn
  chip_share_lte         frontier-chip domestic share (proxy) for {quarter}
  domestic_yoy_up        domestic semicap revenue {quarter} vs same q prior yr

A quarter grades only once it is present and FULL-COVERAGE in the exports
(reduced-coverage quarters stay open) — so a call never resolves on data that
was not yet complete.

Run:  .venv/bin/python analysis/calls.py     # grade + print the ledger
"""

import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPORTS = REPO_ROOT / "data" / "exports"
LEDGER = REPO_ROOT / "calls" / "ledger.json"


def load_context(exports=EXPORTS):
    """Load the committed exports the graders read, indexed by quarter."""
    def rd(name):
        p = exports / name
        return pd.read_csv(p) if p.exists() else pd.DataFrame()

    ratio = rd("indigenization_ratio.csv")
    if not ratio.empty:
        full = ratio[ratio["ratio"].notna()
                     & (ratio["missing_origins"].fillna("") == "Taiwan")]
    else:
        full = ratio
    idx = lambda df: df.set_index("quarter") if not df.empty else df
    return {
        "ratio_full": idx(full),
        "ratio_all": idx(ratio),
        "cf": idx(rd("did_counterfactual.csv")),
        "chips": idx(rd("chip_self_sufficiency.csv")),
    }


def prior_year_quarter(q):
    """'2026Q2' -> '2025Q2'."""
    y, n = q.split("Q")
    return f"{int(y) - 1}Q{n}"


def _ratio(c, ctx, ge):
    q, thr = c["criteria"]["quarter"], float(c["criteria"]["threshold"])
    rf = ctx["ratio_full"]
    if rf.empty or q not in rf.index:
        return None
    v = float(rf.loc[q, "ratio"])
    ok = v >= thr if ge else v <= thr
    return ("YES" if ok else "NO", f"ratio {v:.1%} in {q}")


def _us_equip_lte(c, ctx):
    q, thr = c["criteria"]["quarter"], float(c["criteria"]["threshold_bn"])
    cf = ctx["cf"]
    if cf.empty or q not in cf.index:
        return None
    bn = float(cf.loc[q, "us_actual_usd"]) / 1e9
    return ("YES" if bn <= thr else "NO", f"US equipment ${bn:.2f}bn in {q}")


def _chip_share_lte(c, ctx):
    q, thr = c["criteria"]["quarter"], float(c["criteria"]["threshold"])
    ch = ctx["chips"]
    if ch.empty or q not in ch.index:
        return None
    v = float(ch.loc[q, "chip_domestic_share"])
    return ("YES" if v <= thr else "NO", f"chip domestic share {v:.1%} in {q}")


def _domestic_yoy_up(c, ctx):
    q = c["criteria"]["quarter"]
    py = prior_year_quarter(q)
    ra = ctx["ratio_all"]
    if ra.empty or q not in ra.index or py not in ra.index:
        return None
    a = float(ra.loc[q, "domestic_semicap_usd"])
    b = float(ra.loc[py, "domestic_semicap_usd"])
    return ("YES" if a > b else "NO",
            f"domestic ${a / 1e9:.2f}bn ({q}) vs ${b / 1e9:.2f}bn ({py})")


GRADERS = {
    "ratio_gte": lambda c, ctx: _ratio(c, ctx, ge=True),
    "ratio_lte": lambda c, ctx: _ratio(c, ctx, ge=False),
    "us_equip_lte": _us_equip_lte,
    "chip_share_lte": _chip_share_lte,
    "domestic_yoy_up": _domestic_yoy_up,
}


def load():
    with open(LEDGER) as fh:
        return json.load(fh)


def grade(doc=None, ctx=None, write=True, today=None):
    doc = doc if doc is not None else load()
    ctx = ctx if ctx is not None else load_context()
    today = today or dt.date.today().isoformat()
    changed = False
    for c in doc["calls"]:
        if c.get("status") != "open":
            continue
        fn = GRADERS.get(c["criteria"]["type"])
        res = fn(c, ctx) if fn else None
        if res:
            outcome, evidence = res
            c.update(status="resolved", outcome=outcome, evidence=evidence,
                     resolved_at=today)
            changed = True
    if changed and write:
        with open(LEDGER, "w") as fh:
            json.dump(doc, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    return doc


def summary(doc=None):
    doc = doc if doc is not None else load()
    calls = doc["calls"]
    resolved = [c for c in calls if c.get("status") == "resolved"]
    briers = [(float(c["p"]) - (1.0 if c["outcome"] == "YES" else 0.0)) ** 2
              for c in resolved]
    return {
        "n_calls": len(calls),
        "n_open": sum(1 for c in calls if c.get("status") == "open"),
        "n_resolved": len(resolved),
        "brier": (sum(briers) / len(briers)) if briers else None,
        "first_call": min((str(c["made"]) for c in calls), default=None),
    }


def main():
    doc = grade(write=True)
    s = summary(doc)
    line = (f"CALLS LEDGER — {s['n_calls']} calls since {s['first_call']}: "
            f"{s['n_open']} open, {s['n_resolved']} resolved")
    if s["brier"] is not None:
        line += f", Brier {s['brier']:.3f}"
    print(line)
    for c in doc["calls"]:
        flag = {"open": "○", "resolved": "●"}.get(c.get("status"), "?")
        print(f" {flag} [{c['made']}] p={float(c['p']):.0%}  {c['claim'][:76]}")
        if c.get("status") == "resolved":
            print(f"     -> {c['outcome']} ({c.get('evidence', '')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
