"""NOWCAST — current-quarter ESTIMATE of the indigenization ratio.

THIS IS AN ESTIMATE, NOT MEASURED DATA. It exists to bridge the weeks
between high-frequency signals and the quarter's filings, is labeled as a
nowcast in every output, and must never be rendered with the same visual
weight as the measured series.

Model (deterministic arithmetic, every step printed in the driver list):

  Imports side, per origin with missing months in the target quarter:
    observed months are used as-is; each missing month is filled with the
    average of that origin's last 3 observed months (carry-forward), then
    the filled portion is scaled by the VENDOR SIGNAL FACTOR — the ratio of
    the vendor China-revenue panel (AMAT/LRCX/KLAC/ASML, hifreq_signals)
    inside the target quarter vs inside the carry-forward base window,
    capped to [0.7, 1.3]. Uncertainty per origin: the std of its trailing
    12 observed months, times sqrt(missing months).

  Revenue side, if the quarter has no measured/derived rows:
    per company, same-quarter-last-year x that company's trailing YoY
    growth (last two measured quarters vs the same two a year earlier).
    Uncertainty: cross-company dispersion of those growth rates.

  Band: worst-case combination of the two one-sigma dispersions —
  a scenario band, NOT a statistical confidence interval.

Every run inserts a nowcasts row (UNIQUE per day+quarter), and the script
reports the track record: past nowcasts vs the measured value once the
quarter's data completes.

How you'd know it broke: tests pin the arithmetic; the driver list makes a
silly input visible immediately.
"""

import datetime
import sqlite3
import sys
from pathlib import Path
from statistics import mean, pstdev

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import indigenization_ratio as ir  # noqa: E402

DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"
OUT_PATH = REPO_ROOT / "data" / "exports" / "nowcast.md"

NOWCAST_VERSION = "nc-1.0.0"
FULL_COVERAGE_N = len(ir.IMPORT_SERIES)
VENDOR_FACTOR_CAP = (0.7, 1.3)


def connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def quarter_months(quarter):
    year, q = int(quarter[:4]), int(quarter[-1])
    return [f"{year}-{(q - 1) * 3 + i:02d}" for i in (1, 2, 3)]


def prev_quarter(quarter, back=1):
    year, q = int(quarter[:4]), int(quarter[-1])
    idx = year * 4 + (q - 1) - back
    return f"{idx // 4}Q{idx % 4 + 1}"


def monthly_usd_series(df, fx):
    """{origin: sorted [(period, usd_value)]} for every import series."""
    imports = df[df.metric_name.isin(ir.IMPORT_SERIES)].copy()
    imports["origin"] = imports.metric_name.map(lambda m: ir.IMPORT_SERIES[m][0])
    imports["currency"] = imports.metric_name.map(lambda m: ir.IMPORT_SERIES[m][1])
    imports, _ = ir.to_usd(imports, fx)
    out = {}
    for origin, group in imports.groupby("origin"):
        out[origin] = sorted(zip(group.period, group.value_usd))
    return out


def vendor_factor(conn, target_months, base_months):
    """Vendor China-share panel: mean(pct in target) / mean(pct in base),
    capped. Returns (factor, note)."""
    def panel(months):
        rows = conn.execute(
            "SELECT value FROM hifreq_signals"
            " WHERE signal_type = 'vendor_china_revenue' AND value IS NOT NULL"
            " AND substr(signal_date, 1, 7) IN (%s)" % ",".join("?" * len(months)),
            months,
        ).fetchall()
        return [r[0] for r in rows]

    target_panel, base_panel = panel(target_months), panel(base_months)
    if not target_panel or not base_panel:
        return 1.0, "vendor factor 1.00 (no vendor signals in window — unadjusted)"
    raw = mean(target_panel) / mean(base_panel)
    factor = min(max(raw, VENDOR_FACTOR_CAP[0]), VENDOR_FACTOR_CAP[1])
    return factor, (
        f"vendor factor {factor:.2f} (panel mean {mean(target_panel):.1f}% in"
        f" target window vs {mean(base_panel):.1f}% in base;"
        f" {len(target_panel)} vs {len(base_panel)} signals)"
    )


def estimate_imports(conn, df, fx, quarter):
    """Returns (estimate_usd, sigma_usd, drivers[])."""
    months = quarter_months(quarter)
    series = monthly_usd_series(df, fx)
    total = sigma_sq = 0.0
    drivers = []
    base_months_all = set()
    filled_total = 0.0

    for origin in sorted(series):
        observed = dict(series[origin])
        in_q = {m: observed[m] for m in months if m in observed}
        missing = [m for m in months if m not in observed]
        history = [v for p, v in series[origin] if p < months[0]]
        if not history and not in_q:
            drivers.append(f"{origin}: NO DATA at all — origin omitted (band does not cover this)")
            continue
        carry_base = history[-3:] if history else list(in_q.values())
        base_periods = [p for p, v in series[origin] if p < months[0]][-3:]
        base_months_all.update(base_periods)
        fill_level = mean(carry_base)
        fill = fill_level * len(missing)
        observed_sum = sum(in_q.values())
        total += observed_sum + fill
        filled_total += fill
        if missing:
            trailing = [v for _, v in series[origin][-12:]]
            sigma = (pstdev(trailing) if len(trailing) > 1 else fill_level * 0.3)
            sigma_sq += (sigma ** 2) * len(missing)
            drivers.append(
                f"{origin}: {len(in_q)}/3 months observed"
                f" (${observed_sum/1e9:.2f}bn); {len(missing)} filled at"
                f" carry-forward ${fill_level/1e9:.2f}bn/mo"
            )
        else:
            drivers.append(f"{origin}: fully observed (${observed_sum/1e9:.2f}bn)")

    factor, factor_note = vendor_factor(conn, months, sorted(base_months_all))
    adjustment = filled_total * (factor - 1.0)
    total += adjustment
    drivers.append(factor_note + f" -> applied to filled months: {adjustment/1e9:+.2f}bn")
    return total, sigma_sq ** 0.5, drivers


def estimate_numerator(df, fx, quarter):
    """Returns (estimate_usd, sigma_usd, drivers[], measured: bool)."""
    domestic = ir.quarterly_domestic_usd(df, fx)
    if quarter in domestic.index:
        row = domestic.loc[quarter]
        return (
            row.domestic_semicap_usd, 0.0,
            [f"revenue: measured/derived for {int(row.n_companies)} companies"
             f" ({int(row.n_estimated)} with ESTIMATED share-year flags)"],
            True,
        )
    rev = df[(df.metric_name == ir.NUMERATOR_METRIC) & (df.layer == "equipment")]
    year_ago = prev_quarter(quarter, 4)
    growths, base_total = [], 0.0
    for entity, group in rev.groupby("entity"):
        vals = dict(zip(group.period, group.value))
        recent = sorted(p for p in vals if p < quarter)[-2:]
        prior = [prev_quarter(p, 4) for p in recent]
        if year_ago not in vals or not recent or any(p not in vals for p in prior):
            continue
        g = sum(vals[p] for p in recent) / sum(vals[p] for p in prior)
        growths.append(g)
        base_total += vals[year_ago] * g
    if not growths:
        return None, None, ["revenue: no basis to extrapolate"], False
    fx_dict = ir.load_fx if False else None  # noqa: F841 (clarity only)
    # convert CNY estimate at latest available quarterly-average rate
    cny = sorted(fx["CNY"].items())
    rate = mean(v for _, v in cny[-3:])
    est = base_total * rate
    sigma = (pstdev(growths) if len(growths) > 1 else 0.15) * est
    drivers = [
        f"revenue: EXTRAPOLATED — same quarter last year x per-company trailing"
        f" YoY growth (median g={sorted(growths)[len(growths)//2]:.2f},"
        f" {len(growths)} companies), CNY->USD at {rate:.3f}"
    ]
    return est, sigma, drivers, False


def make_nowcast(conn, quarter):
    df = ir.load_metrics(conn)
    fx = ir.load_fx(conn)
    imports_est, imports_sigma, d1 = estimate_imports(conn, df, fx, quarter)
    num_est, num_sigma, d2, measured = estimate_numerator(df, fx, quarter)
    if num_est is None or imports_est <= 0:
        return None
    ratio = num_est / (num_est + imports_est)
    low = (num_est - num_sigma) / ((num_est - num_sigma) + (imports_est + imports_sigma))
    high = (num_est + num_sigma) / ((num_est + num_sigma) + max(imports_est - imports_sigma, 1e-9))
    return {
        "target_quarter": quarter,
        "ratio": ratio,
        "low": low,
        "high": high,
        "numerator_usd": num_est,
        "imports_usd": imports_est,
        "drivers": d1 + d2,
        "numerator_measured": measured,
    }


def target_quarters(conn):
    """Quarters needing a nowcast: after the last quarter with full origin
    coverage AND revenue, up to the current calendar quarter."""
    out = ir.compute_ratio(conn)
    solid = out[
        (out.coverage_origins == "+".join(sorted(o for o, _ in ir.IMPORT_SERIES.values())))
        & out.domestic_semicap_usd.notna()
    ]
    last_solid = solid.index.max() if len(solid) else "2023Q2"
    today = datetime.date.today()
    current = f"{today.year}Q{(today.month - 1) // 3 + 1}"
    targets = []
    q = last_solid
    while q < current:
        q = prev_quarter(q, -1)
        targets.append(q)
    return targets, last_solid


def store(conn, nc):
    conn.execute(
        "INSERT OR REPLACE INTO nowcasts"
        " (made_at, target_quarter, ratio_nowcast, ratio_low, ratio_high,"
        "  numerator_usd, imports_usd, drivers, methodology_version)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            datetime.date.today().isoformat(), nc["target_quarter"], nc["ratio"],
            nc["low"], nc["high"], nc["numerator_usd"], nc["imports_usd"],
            "\n".join(nc["drivers"]), NOWCAST_VERSION,
        ),
    )
    conn.commit()


def track_record(conn):
    """Past nowcasts whose target quarter is now fully measured -> errors."""
    measured = ir.compute_ratio(conn)
    full = measured[
        (measured.coverage_origins == "+".join(sorted(o for o, _ in ir.IMPORT_SERIES.values())))
        & measured.ratio.notna()
    ]
    rows = conn.execute(
        "SELECT made_at, target_quarter, ratio_nowcast, ratio_low, ratio_high"
        " FROM nowcasts ORDER BY target_quarter, made_at"
    ).fetchall()
    lines = []
    for made_at, quarter, nc, low, high in rows:
        if quarter in full.index:
            actual = full.loc[quarter].ratio
            hit = "within band" if low <= actual <= high else "OUTSIDE band"
            lines.append(
                f"{quarter} (nowcast {made_at}): {nc:.1%} [{low:.1%}-{high:.1%}]"
                f" vs actual {actual:.1%} -> error {nc - actual:+.1%}, {hit}"
            )
    return lines


def main():
    conn = connect()
    targets, last_solid = target_quarters(conn)
    lines = [
        "# NOWCAST — model estimate, NOT measured data",
        "",
        f"_Produced {datetime.date.today().isoformat()}; nowcast model"
        f" {NOWCAST_VERSION}. Last fully-measured quarter: {last_solid}._",
        "",
    ]
    print("=" * 74)
    print("NOWCAST — model estimate, NOT measured data")
    print("=" * 74)
    made_any = False
    for quarter in targets:
        nc = make_nowcast(conn, quarter)
        if nc is None:
            print(f"{quarter}: not enough signal to nowcast")
            continue
        store(conn, nc)
        made_any = True
        print(
            f"{quarter}: {nc['ratio']:.1%}  band [{nc['low']:.1%} – {nc['high']:.1%}]"
            f"  (numerator {'measured' if nc['numerator_measured'] else 'extrapolated'})"
        )
        lines += [
            f"## {quarter}: **{nc['ratio']:.1%}** (band {nc['low']:.1%} – {nc['high']:.1%})",
            "",
            "Drivers:",
            *[f"- {d}" for d in nc["drivers"]],
            "",
        ]
    record = track_record(conn)
    lines += ["## Nowcast track record vs measured", ""]
    lines += [f"- {r}" for r in record] if record else [
        "- No nowcasted quarter has fully-measured data yet."
    ]
    if record:
        print("\nTrack record:")
        for r in record:
            print(" ", r)
    OUT_PATH.write_text("\n".join(lines))
    print(f"\nwrote {OUT_PATH.relative_to(REPO_ROOT)}")
    conn.close()
    return 0 if made_any else 1


if __name__ == "__main__":
    sys.exit(main())
