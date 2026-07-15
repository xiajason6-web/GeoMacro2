"""Surprise model: nowcast vs consensus — the delta a trader actually trades.

Traders don't trade the level, they trade the gap between the incoming print
and what's expected. This reframes the nowcast as a surprise:

  surprise = nowcast(target quarter) − consensus expectation

Two consensus anchors, both honest:
  1. PERSISTENCE (primary): the last fully-measured quarterly ratio — what a
     no-new-information forecaster assumes. This is the default the market
     drifts to between prints.
  2. ANALYST (reference): the nearest published annual estimate for the
     target year from the benchmarks table (Bernstein/UBS/CSIS), annualized
     context — flagged as annual-vs-quarterly.

Catalyst = the dominant driver from the nowcast (the vendor-signal factor or
the largest carry-forward origin), pulled from the stored nowcast drivers.

Deterministic; reads nowcasts + ratio + benchmarks. No LLM, no trade calls.
Output: data/exports/surprise.md, and a dict the trade note consumes.
"""

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import indigenization_ratio as ir  # noqa: E402

DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"
OUT_PATH = REPO_ROOT / "data" / "exports" / "surprise.md"

FULL = "+".join(sorted(o for o, _ in ir.IMPORT_SERIES.values()))


def connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def persistence_baseline(conn):
    """(quarter, ratio) of the last fully-covered measured quarter."""
    out = ir.compute_ratio(conn)
    full = out[(out.coverage_origins == FULL) & out.ratio.notna()]
    if full.empty:
        return None, None
    q = full.index.max()
    return q, float(full.loc[q].ratio)


def nearest_analyst(conn, year):
    """A representative published estimate for the target year, if any."""
    rows = conn.execute(
        "SELECT source, value FROM benchmarks WHERE period = ? ORDER BY source",
        (year,),
    ).fetchall()
    return rows  # list of (source, pct)


def catalyst_from_drivers(drivers):
    """The one line most useful as the 'why it surprises' — prefer the vendor
    factor, else the biggest carry-forward origin."""
    lines = drivers.splitlines()
    for line in lines:
        if "vendor factor" in line:
            return line.strip("- ").strip()
    for line in lines:
        if "filled at carry-forward" in line:
            return line.strip("- ").strip()
    return lines[0].strip("- ").strip() if lines else "n/a"


def build(conn):
    base_q, base = persistence_baseline(conn)
    if base is None:
        return None
    rows = conn.execute(
        "SELECT target_quarter, ratio_nowcast, ratio_low, ratio_high, drivers, made_at"
        " FROM nowcasts WHERE made_at = (SELECT MAX(made_at) FROM nowcasts)"
        " ORDER BY target_quarter"
    ).fetchall()
    out = {"baseline_quarter": base_q, "baseline": base, "made_at": None, "rows": []}
    for quarter, nc, low, high, drivers, made_at in rows:
        out["made_at"] = made_at
        surprise = nc - base
        out["rows"].append(
            {
                "quarter": quarter,
                "nowcast": nc,
                "low": low,
                "high": high,
                "surprise_pp": surprise * 100,
                "direction": "above" if surprise > 0 else "below",
                "catalyst": catalyst_from_drivers(drivers),
                "analyst": nearest_analyst(conn, quarter[:4]),
            }
        )
    return out


def render(data):
    b = data["baseline"]
    lines = [
        "# Surprise model — nowcast vs consensus",
        "",
        f"_Model estimate ({data['made_at']}), not measured data. Consensus"
        f" baseline = persistence: the last fully-measured quarter"
        f" ({data['baseline_quarter']} = {b:.1%}), what the market assumes"
        " absent a new print. Surprise = nowcast − baseline._",
        "",
        "| Quarter | Nowcast | Band | vs persistence | Read |",
        "|---|---|---|---|---|",
    ]
    for r in data["rows"]:
        read = (
            f"{abs(r['surprise_pp']):.1f} pp {r['direction']} the no-change"
            f" baseline"
        )
        lines.append(
            f"| {r['quarter']} | {r['nowcast']:.1%} |"
            f" {r['low']:.1%}–{r['high']:.1%} | {r['surprise_pp']:+.1f} pp | {read} |"
        )
    lines += ["", "Catalyst per quarter (why the nowcast diverges from persistence):", ""]
    for r in data["rows"]:
        lines.append(f"- {r['quarter']}: {r['catalyst']}")
        if r["analyst"]:
            refs = ", ".join(f"{s} {v:.0f}% (annual)" for s, v in r["analyst"])
            lines.append(f"    analyst reference for {r['quarter'][:4]}: {refs}")
    lines += [
        "",
        "The trade is the surprise, not the level: a nowcast materially above"
        " persistence with a named catalyst (here, the vendor China-revenue"
        " roll-off leading the Chinese prints by weeks) is the edge — it says"
        " the next print likely lands away from where the market is anchored.",
    ]
    return "\n".join(lines)


def main():
    conn = connect()
    data = build(conn)
    conn.close()
    if data is None:
        print("no baseline or nowcast yet")
        return 1
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(render(data))
    print(render(data))
    print(f"\nwrote {OUT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
