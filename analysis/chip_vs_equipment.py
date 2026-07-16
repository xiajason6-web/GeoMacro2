"""Chips vs equipment: do China's two import dependencies move together?

The debate conflates "chip self-sufficiency" and "tool self-sufficiency."
This compares China's IMPORT trajectories for the two — HS 8486 (wafer-fab
equipment) and HS 8542 (integrated circuits) — both mirror trade, same five
origins, USD-normalized, full-coverage quarters only.

HONEST SCOPE — this is an import-DEPENDENCE comparison, NOT two
self-sufficiency ratios. The equipment ratio has a domestic-output
numerator (six listed toolmakers); the chip side does NOT — this pipeline
collects no domestic Chinese IC-output series, so a chip self-sufficiency
ratio is not built here (flagged as future work). What the data supports is
whether the two import flows are diverging in level and trend.

Deterministic; reads the same metrics + fx as the ratio. Output:
data/exports/chip_vs_equipment.md.
"""

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import indigenization_ratio as ir  # noqa: E402

DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"
OUT_PATH = REPO_ROOT / "data" / "exports" / "chip_vs_equipment.md"

EQUIPMENT_SERIES = ir.IMPORT_SERIES
CHIP_SERIES = {
    "mirror_exports_eu27_hs8542_eur": ("EU27", "EUR"),
    "mirror_exports_jp_hs8542_jpy": ("Japan", "JPY"),
    "mirror_exports_us_hs8542_usd": ("US", "USD"),
    "mirror_exports_kr_hs8542_usd": ("Korea", "USD"),
    "mirror_exports_sg_hs8542_usd": ("Singapore", "USD"),
}
FULL = "+".join(sorted(o for o, _ in EQUIPMENT_SERIES.values()))


def connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def full_coverage_usd(df, fx, series):
    """Quarterly USD import total, full-coverage quarters only (all 5 origins,
    3 months each). Returns {quarter: usd}."""
    q = ir.quarterly_imports_usd(df, fx, series=series)
    q = q[q.coverage_origins == FULL]
    return q.imports_usd.to_dict()


def build(conn):
    df = ir.load_metrics(conn)
    fx = ir.load_fx(conn)
    equip = full_coverage_usd(df, fx, EQUIPMENT_SERIES)
    chips = full_coverage_usd(df, fx, CHIP_SERIES)
    quarters = sorted(set(equip) & set(chips))
    if not quarters:
        return None
    base = quarters[0]
    rows = []
    for q in quarters:
        rows.append(
            {
                "quarter": q,
                "equip_bn": equip[q] / 1e9,
                "chip_bn": chips[q] / 1e9,
                "equip_idx": 100 * equip[q] / equip[base],
                "chip_idx": 100 * chips[q] / chips[base],
                "chip_to_equip": chips[q] / equip[q],
            }
        )
    return {"base": base, "rows": rows}


def render(data):
    b = data["base"]
    first, last = data["rows"][0], data["rows"][-1]
    equip_chg = last["equip_idx"] - 100
    chip_chg = last["chip_idx"] - 100
    lines = [
        "# Chips vs equipment: China's two import dependencies",
        "",
        "_Mirror imports to China, HS 8486 (equipment) vs HS 8542 (chips),"
        " five origins, USD, full-coverage quarters. This is an import-"
        "DEPENDENCE comparison, not two self-sufficiency ratios — there is no"
        " domestic chip-output series here, so the chip side has no numerator._",
        "",
        f"| Quarter | Equipment $bn | Chips $bn | Equip (idx {b}=100) | Chips (idx {b}=100) | Chips÷Equip |",
        "|---|---|---|---|---|---|",
    ]
    for r in data["rows"]:
        lines.append(
            f"| {r['quarter']} | {r['equip_bn']:.1f} | {r['chip_bn']:.1f} |"
            f" {r['equip_idx']:.0f} | {r['chip_idx']:.0f} | {r['chip_to_equip']:.1f}x |"
        )
    lines += [
        "",
        f"Over {b} → {last['quarter']}: equipment imports {equip_chg:+.0f}%,"
        f" chip imports {chip_chg:+.0f}% (both indexed).",
        "",
        "Read: if the two indices diverge, China's tool-import and chip-import"
        " dependencies are on different paths — the 'self-sufficiency' the"
        " debate treats as one number is at least two. Chips run ~2x the"
        " dollar value of equipment, so a country can localize tools while"
        " staying import-dependent on chips (or vice versa); the trajectories"
        " here show which.",
        "",
        "Limit: chip imports (HS 8542) are dominated by advanced logic/memory"
        " China cannot yet make and by re-export/assembly demand, so the level"
        " is not a clean 'consumption' proxy. The TREND comparison is the"
        " robust part; a true chip self-sufficiency ratio needs a domestic"
        " IC-output series this pipeline does not yet collect.",
    ]
    return "\n".join(lines)


def main():
    conn = connect()
    data = build(conn)
    conn.close()
    if data is None:
        print("no overlapping full-coverage quarters for both series yet")
        return 1
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(render(data))
    print(render(data))
    print(f"\nwrote {OUT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
