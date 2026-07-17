"""Chip-layer self-sufficiency (the frontier / Jensen layer), directional.

The equipment ratio (indigenization_ratio.py) has a clean domestic-output
numerator, so it is causally identifiable. The CHIP layer is harder: the clean
national IC-output series (NBS) is geo-blocked from here (collectors/
nbs_ic_output.py records the block), and the leading memory makers (CXMT, YMTC)
are unlisted. So this module builds a DIRECTIONAL proxy from what IS available:

  domestic logic-output proxy = SMIC + Hua Hong quarterly revenue (USD)
  chip imports                = HS 8542 mirror imports, five origins, USD

and reports the domestic proxy's share of (proxy + imports) alongside the
headline equipment ratio, so the two layers can be compared on the same axis.

WHY THIS IS A PROXY, NOT A RATIO (state it loudly, don't bury it):
  - SMIC + Hua Hong are pure-play foundries whose revenue includes chips sold
    to NON-China customers -> overstates domestic supply to China.
  - It EXCLUDES memory (CXMT/YMTC), IDMs, and captive/in-house production
    -> understates domestic output.
  - HS 8542 imports include chips re-exported after assembly and are pulled up
    by booming AI/electronics demand -> the denominator is not clean
    consumption.
  These errors run in opposite directions, so the LEVEL is only indicative.
  The robust signal is the TREND and the CONTRAST with the equipment ratio.

The finding this supports: tools localize (equipment ratio rising fast) while
frontier logic does not keep pace (chip imports rise with demand faster than
domestic output can displace them) — a data-grounded qualifier to "China is
already at the frontier."

Deterministic pandas; no LLM. Outputs:
  data/exports/chip_self_sufficiency.md
  data/exports/chip_self_sufficiency.csv   (for the dashboard)
"""

import sqlite3
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import indigenization_ratio as ir  # noqa: E402

DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"
OUT_MD = REPO_ROOT / "data" / "exports" / "chip_self_sufficiency.md"
OUT_CSV = REPO_ROOT / "data" / "exports" / "chip_self_sufficiency.csv"
RATIO_CSV = REPO_ROOT / "data" / "exports" / "indigenization_ratio.csv"

# Listed domestic foundries used as the logic-output proxy.
FOUNDRY_ENTITIES = ["SMIC", "Hua Hong"]
CHIP_SERIES = {
    "mirror_exports_eu27_hs8542_eur": ("EU27", "EUR"),
    "mirror_exports_jp_hs8542_jpy": ("Japan", "JPY"),
    "mirror_exports_us_hs8542_usd": ("US", "USD"),
    "mirror_exports_kr_hs8542_usd": ("Korea", "USD"),
    "mirror_exports_sg_hs8542_usd": ("Singapore", "USD"),
}
FULL = "+".join(sorted(o for o, _ in CHIP_SERIES.values()))


def quarterly_foundry_usd(df, fx):
    """SMIC + Hua Hong quarterly revenue (CNY) -> USD per quarter, via the
    quarter's average monthly CNY rate (same convention as the numerator in
    indigenization_ratio.quarterly_domestic_usd)."""
    rev = df[(df.metric_name == "quarterly_revenue_cny")
             & (df.layer == "foundry")
             & (df.entity.isin(FOUNDRY_ENTITIES))].copy()
    if rev.empty:
        return pd.Series(dtype=float)
    rev["currency"] = "CNY"
    q_fx = {}
    for period, rate in fx.get("CNY", {}).items():
        q_fx.setdefault(ir.month_to_quarter(period), []).append(rate)
    fx_q = {"CNY": {q: sum(v) / len(v) for q, v in q_fx.items()}}
    rev, dropped = ir.to_usd(rev, fx_q)
    if len(dropped):
        print(f"WARNING: {len(dropped)} foundry rows lacked an FX rate — excluded")
    return rev.groupby("period").value_usd.sum()


def chip_imports_usd(df, fx):
    """Full-coverage (all five origins) quarterly HS 8542 imports, USD."""
    q = ir.quarterly_imports_usd(df, fx, series=CHIP_SERIES)
    q = q[q.coverage_origins == FULL]
    return q.imports_usd


def equipment_ratio():
    """The headline equipment indigenization ratio, full-coverage quarters."""
    if not RATIO_CSV.exists():
        return {}
    r = pd.read_csv(RATIO_CSV).dropna(subset=["ratio"])
    r = r[r.missing_origins.fillna("") == "Taiwan"]
    return dict(zip(r.quarter, r.ratio))


def build(conn):
    df = ir.load_metrics(conn)
    fx = ir.load_fx(conn)
    foundry = quarterly_foundry_usd(df, fx)
    chips = chip_imports_usd(df, fx)
    equip = equipment_ratio()
    quarters = sorted(set(foundry.index) & set(chips.index))
    if not quarters:
        return None
    base = quarters[0]
    rows = []
    for q in quarters:
        dom, imp = foundry[q], chips[q]
        rows.append({
            "quarter": q,
            "domestic_logic_usd": dom,
            "chip_imports_usd": imp,
            "domestic_logic_bn": dom / 1e9,
            "chip_imports_bn": imp / 1e9,
            "domestic_logic_idx": 100 * dom / foundry[base],
            "chip_imports_idx": 100 * chips[q] / chips[base],
            "chip_domestic_share": dom / (dom + imp),
            "equipment_ratio": equip.get(q, float("nan")),
        })
    return {"base": base, "rows": pd.DataFrame(rows).set_index("quarter")}


def render(data):
    b = data["base"]
    t = data["rows"]
    first, last = t.iloc[0], t.iloc[-1]
    dom_chg = last.domestic_logic_idx - 100
    imp_chg = last.chip_imports_idx - 100
    chip_share_chg = (last.chip_domestic_share - first.chip_domestic_share) * 100
    equip_chg = (last.equipment_ratio - first.equipment_ratio) * 100

    lines = [
        "# Chip-layer self-sufficiency (frontier logic) — directional proxy",
        "",
        "_Domestic logic-output PROXY = SMIC + Hua Hong quarterly revenue (USD)."
        " Chip imports = HS 8542 mirror trade, five origins, USD, full-coverage"
        " quarters. This is the frontier/Jensen layer. It is a DIRECTIONAL proxy,"
        " not a clean self-sufficiency ratio — see the limits below._",
        "",
        f"| Quarter | Domestic logic $bn | Chip imports $bn | Domestic idx ({b}=100)"
        f" | Imports idx ({b}=100) | Chip domestic share | Equipment ratio |",
        "|---|---|---|---|---|---|---|",
    ]
    for q, r in t.iterrows():
        eq = "—" if pd.isna(r.equipment_ratio) else f"{r.equipment_ratio:.1%}"
        lines.append(
            f"| {q} | {r.domestic_logic_bn:.2f} | {r.chip_imports_bn:.1f} |"
            f" {r.domestic_logic_idx:.0f} | {r.chip_imports_idx:.0f} |"
            f" {r.chip_domestic_share:.1%} | {eq} |"
        )
    lines += [
        "",
        f"Over {b} → {last.name}: domestic logic output {dom_chg:+.0f}%, chip"
        f" imports {imp_chg:+.0f}%. The chip domestic share moved"
        f" {chip_share_chg:+.1f}pp (to {last.chip_domestic_share:.1%}) while the"
        f" equipment ratio moved {equip_chg:+.1f}pp (to {last.equipment_ratio:.1%}).",
        "",
        "## Read",
        "",
        "- **Tools localize; frontier logic lags.** Domestic logic output roughly"
        " doubled, yet chip imports ALSO rose — AI/electronics demand outran"
        " substitution, so the domestic share crept up only a few points while"
        " the equipment ratio surged. China is localizing the *factory* faster"
        " than the *frontier product* the factory makes.",
        "- **The two 'self-sufficiency' numbers are on different paths.** Reading"
        " them as one figure (as the debate often does) hides that the chip"
        " layer — the one AI accelerators live in — is the laggard.",
        "",
        "## Limits (why this is a proxy, not a ratio)",
        "",
        "- **Numerator overstates**: SMIC + Hua Hong sell to non-China customers"
        " too; their revenue is not chips-consumed-in-China.",
        "- **Numerator understates**: excludes memory (CXMT/YMTC, unlisted),"
        " IDMs, and captive production — no domestic series exists for these.",
        "- **Denominator is not clean consumption**: HS 8542 imports include"
        " chips re-exported after assembly and are inflated by demand growth.",
        "- **The clean series is blocked**: NBS national IC-output is geo-blocked"
        " from here (collectors/nbs_ic_output.py records it in `review_queue`)."
        " The TREND and the CONTRAST with equipment are the robust parts, not"
        " the level.",
        "",
        "_Research output — finding → mechanism → exposed entities → confidence →"
        " sources. Not investment advice._",
    ]
    return "\n".join(lines)


def main():
    conn = sqlite3.connect(DB_PATH)
    data = build(conn)
    conn.close()
    if data is None:
        print("no overlapping quarters for foundry output and chip imports yet")
        return 1
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    data["rows"].reset_index().to_csv(OUT_CSV, index=False)
    md = render(data)
    OUT_MD.write_text(md)
    print(md)
    print(f"\nwrote {OUT_MD.relative_to(REPO_ROOT)} and {OUT_CSV.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
