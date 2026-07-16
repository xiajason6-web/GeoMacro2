"""Vendor lead: does foreign-vendor China revenue lead the domestic ratio?

Foreign toolmakers (AMAT, LRCX, KLA, ASML) disclose their China revenue
share weeks before the Chinese equipment makers file. If that share FALLING
leads the indigenization ratio RISING, it is a named leading indicator — and
the nowcast already leans on exactly this relationship.

⚠️ SAMPLE HONESTY — the overlap between the vendor panel and the measured
ratio is only a handful of quarters. That is FAR too short for a
statistically valid lead-lag estimate. This module builds the aligned
series and reports the DESCRIPTIVE co-movement and lag-0 / lag-1
correlations, but any correlation on n<8 is illustrative, not inferential.
The value now is the apparatus; the answer sharpens as quarters accumulate.
Do not present the correlation as an established lead.

Deterministic. Output: data/exports/vendor_lead.md.
"""

import sqlite3
import sys
from pathlib import Path
from statistics import mean

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import indigenization_ratio as ir  # noqa: E402

DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"
OUT_PATH = REPO_ROOT / "data" / "exports" / "vendor_lead.md"
FULL = "+".join(sorted(o for o, _ in ir.IMPORT_SERIES.values()))
MIN_N_FOR_INFERENCE = 8


def connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def month_to_quarter(period):
    y, m = period.split("-")
    return f"{y}Q{(int(m) - 1) // 3 + 1}"


def pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx, my = mean(xs), mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    return num / (dx * dy) if dx and dy else None


def vendor_panel_by_quarter(conn):
    """{calendar quarter: mean China-revenue % across vendors reporting}."""
    rows = conn.execute(
        "SELECT period, value FROM metrics WHERE metric_name = 'china_revenue_pct'"
    ).fetchall()
    buckets = {}
    for period, pct in rows:
        # vendor periods are fiscal-period-end 'YYYY-MM' (or already 'YYYYQ#')
        q = period if "Q" in period else month_to_quarter(period)
        buckets.setdefault(q, []).append(pct)
    return {q: mean(v) for q, v in buckets.items()}


def build(conn):
    out = ir.compute_ratio(conn)
    ratio = out[(out.coverage_origins == FULL) & out.ratio.notna()].ratio.to_dict()
    vendor = vendor_panel_by_quarter(conn)

    aligned = sorted(set(ratio) & set(vendor))
    rows = [{"quarter": q, "vendor_china_pct": vendor[q], "ratio": ratio[q]} for q in aligned]

    # lag-0: vendor(T) vs ratio(T); lag-1: vendor(T) vs ratio(T+1)
    def quarters_plus(q):
        y, n = int(q[:4]), int(q[-1])
        idx = y * 4 + (n - 1) + 1
        return f"{idx // 4}Q{idx % 4 + 1}"

    lag0_x = [vendor[q] for q in aligned]
    lag0_y = [ratio[q] for q in aligned]
    lag1_pairs = [(vendor[q], ratio[quarters_plus(q)]) for q in aligned if quarters_plus(q) in ratio]

    return {
        "rows": rows,
        "n": len(aligned),
        "corr_lag0": pearson(lag0_x, lag0_y),
        "corr_lag1": pearson([a for a, _ in lag1_pairs], [b for _, b in lag1_pairs]) if lag1_pairs else None,
        "n_lag1": len(lag1_pairs),
    }


def render(data):
    n = data["n"]
    strong = n >= MIN_N_FOR_INFERENCE
    lines = [
        "# Vendor lead: foreign China revenue vs the domestic ratio",
        "",
        f"⚠️ **Descriptive only — n = {n} overlapping quarters.** This is below"
        f" the {MIN_N_FOR_INFERENCE}-quarter floor for any lead-lag inference."
        " The correlations below are illustrative; do not present them as an"
        " established leading indicator. The point is the apparatus, which"
        " answers this properly as the panel lengthens.",
        "",
        "| Quarter | Vendor China rev % (panel mean) | Domestic ratio |",
        "|---|---|---|",
    ]
    for r in data["rows"]:
        lines.append(f"| {r['quarter']} | {r['vendor_china_pct']:.1f}% | {r['ratio']:.1%} |")
    c0 = data["corr_lag0"]
    c1 = data["corr_lag1"]
    lines += [
        "",
        f"- Contemporaneous correlation (vendor % vs ratio, same quarter):"
        f" {c0:+.2f}" if c0 is not None else "- Contemporaneous correlation: n/a",
        (f"- Lead correlation (vendor % in T vs ratio in T+1, n={data['n_lag1']}):"
         f" {c1:+.2f}") if c1 is not None else "- Lead correlation: n/a",
        "",
        "Expected sign is NEGATIVE: foreign vendors losing China share as the"
        " domestic ratio rises. A negative contemporaneous number is"
        " consistent with substitution; a negative LEAD number (vendor moves"
        " first) is what would make it tradeable — but that claim needs"
        f" {MIN_N_FOR_INFERENCE}+ quarters, not {n}.",
        "",
    ]
    if c0 is not None and c0 > 0:
        lines.append(
            "Observed sign is POSITIVE, not negative — a real finding in"
            " itself: over this short window both series rise and fall with"
            " China's fab-capex CYCLE (up-cycle = foreign vendors AND domestic"
            " makers both grow), which swamps the slower substitution trend."
            " Reading substitution off raw co-movement fails at this horizon;"
            " it needs more quarters or explicit cycle-adjustment (e.g."
            " controlling for total WFE demand)."
        )
        lines.append("")
    lines += [
        ("Status: too few quarters to conclude." if not strong else
         "Status: sample now adequate — treat the lead correlation as evidence."),
    ]
    return "\n".join(lines)


def main():
    conn = connect()
    data = build(conn)
    conn.close()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(render(data))
    print(render(data))
    print(f"\nwrote {OUT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
