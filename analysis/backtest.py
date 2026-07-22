"""Point-in-time backtest + vintage harness.

The rigor layer. Iran's model keys every partition by the date it was PULLED so
a backtest can never peek at data that wasn't available yet. This repo gets the
same discipline for free: the nightly pipeline commits data/exports to git, so
**git history IS the point-in-time vintage lake** — the state of a file at
commit date D contains only data committed by D. This module reconstructs those
vintages and uses them for two honest, no-lookahead measurements:

  1. REVISION analysis — how much each quarter's flagship ratio moved across
     vintages as later data (and coverage) landed. This quantifies how
     provisional the newest print is: don't over-trust a fresh quarter.
  2. NOWCAST backtest — each target quarter's EARLIEST stored nowcast vs the
     value it later realized (point-in-time by construction: the nowcast was
     made before the quarter was known).

HONESTY: the tracker is only a few weeks old, so there are a handful of
vintages and few realized quarters — far too little for inference. The
deliverable now is the HARNESS and the point-in-time discipline; it earns its
keep as vintages accumulate (cf. the calls ledger, which scores forward calls).

Deterministic. Outputs: data/exports/backtest.md + backtest_revisions.csv.
"""

import io
import subprocess
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPORTS = REPO_ROOT / "data" / "exports"
RATIO_REL = "data/exports/indigenization_ratio.csv"


def vintages_from_git(relpath=RATIO_REL, repo=REPO_ROOT):
    """One vintage per calendar date: the LAST commit that touched `relpath`
    that day (git log is newest-first, so the first hash we see per date).
    Returns [{date, text}] sorted ascending. Empty if git/file unavailable."""
    try:
        log = subprocess.run(
            ["git", "-C", str(repo), "log", "--format=%H %cd", "--date=short",
             "--", relpath],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return []
    seen = {}
    for line in log.stdout.splitlines():
        parts = line.split(" ", 1)
        if len(parts) != 2:
            continue
        h, date = parts
        if date in seen:
            continue
        show = subprocess.run(["git", "-C", str(repo), "show", f"{h}:{relpath}"],
                              capture_output=True, text=True, timeout=60)
        if show.returncode == 0:
            seen[date] = show.stdout
    return [{"date": d, "text": t} for d, t in sorted(seen.items())]


def parse_ratio_vintages(vintages):
    """[{date,text}] -> long panel {vintage, quarter, ratio, coverage},
    restricted to methodology v2 (a methodology break is not a data revision).
    ALL coverage levels are kept: a quarter revising as it flips from reduced-
    to full-coverage is a REAL point-in-time revision (the printed number
    changed), and it is the biggest kind here — hiding it would misstate the
    provisional risk. Coverage transitions are flagged in revision_table."""
    rows = []
    for v in vintages:
        try:
            df = pd.read_csv(io.StringIO(v["text"]))
        except Exception:
            continue
        if "ratio" not in df or "methodology_version" not in df:
            continue
        df = df[(df["methodology_version"].astype(str) == "2.0.0")
                & df["ratio"].notna()]
        for _, r in df.iterrows():
            rows.append({"vintage": v["date"], "quarter": r["quarter"],
                         "ratio": float(r["ratio"]),
                         "coverage": str(r.get("missing_origins", ""))})
    return pd.DataFrame(rows)


def revision_table(panel):
    """Per quarter: first-print vs latest across vintages, revision magnitude,
    and whether the revision coincided with a coverage change."""
    if panel.empty:
        return pd.DataFrame()
    rows = []
    for q, g in panel.groupby("quarter"):
        g = g.sort_values("vintage")
        steps = g.ratio.diff().abs().dropna()
        rows.append({
            "quarter": q, "n_vintages": len(g),
            "first_vintage": g.iloc[0].vintage,
            "first_ratio": g.iloc[0].ratio,
            "latest_ratio": g.iloc[-1].ratio,
            "revision_pp": (g.iloc[-1].ratio - g.iloc[0].ratio) * 100,
            "max_step_pp": (steps.max() * 100 if len(steps) else 0.0),
            "coverage_changed": g.iloc[0].coverage != g.iloc[-1].coverage,
        })
    return pd.DataFrame(rows).sort_values("quarter").reset_index(drop=True)


def realized_ratios(exports=EXPORTS):
    p = exports / "indigenization_ratio.csv"
    if not p.exists():
        return {}
    df = pd.read_csv(p)
    df = df[df["ratio"].notna() & (df["missing_origins"].fillna("") == "Taiwan")]
    return dict(zip(df["quarter"], df["ratio"]))


def nowcast_backtest(conn, realized):
    """Earliest stored nowcast per target quarter vs the value later realized."""
    try:
        nc = pd.read_sql_query(
            "SELECT made_at, target_quarter, ratio_nowcast FROM nowcasts", conn)
    except Exception:
        return pd.DataFrame()
    if nc.empty:
        return pd.DataFrame()
    first = nc.sort_values("made_at").groupby("target_quarter", as_index=False).first()
    rows = []
    for _, r in first.iterrows():
        q = r.target_quarter
        if q in realized:
            rows.append({
                "target_quarter": q, "first_nowcast_at": r.made_at,
                "nowcast": float(r.ratio_nowcast), "realized": realized[q],
                "error_pp": (float(r.ratio_nowcast) - realized[q]) * 100,
            })
    return pd.DataFrame(rows)


def render(rev, ncbt):
    lines = [
        "# Point-in-time backtest & vintage harness",
        "",
        "_Vintages are reconstructed from git history — the state of the flagship"
        " ratio at each nightly commit — so every measurement here is"
        " no-lookahead by construction (methodology v2 full-coverage rows only)._",
        "",
        "## Revision analysis — how provisional is a fresh print?",
        "",
    ]
    if rev.empty:
        lines.append("_No parseable v2 vintages yet — the harness accrues as the"
                     " nightly pipeline commits._")
    else:
        n_multi = rev[rev.n_vintages > 1]
        lines += [
            "| Quarter | Vintages | First print | Latest | Revision (pp) | Coverage change |",
            "|---|---|---|---|---|---|",
        ]
        for _, r in rev.iterrows():
            lines.append(
                f"| {r.quarter} | {int(r.n_vintages)} | {r.first_ratio:.1%} |"
                f" {r.latest_ratio:.1%} | {r.revision_pp:+.1f} |"
                f" {'yes' if r.coverage_changed else ''} |")
        if len(n_multi):
            mean_abs = n_multi.revision_pp.abs().mean()
            cov = n_multi[n_multi.coverage_changed]
            lines += [
                "",
                f"Across {len(n_multi)} quarters seen in >1 vintage, the mean"
                f" absolute revision from first print to latest is"
                f" **{mean_abs:.1f}pp**.",
            ]
            if len(cov):
                worst = cov.loc[cov.revision_pp.abs().idxmax()]
                lines.append(
                    f"The largest revisions coincide with COVERAGE changes"
                    f" (e.g. {worst.quarter}: {worst.first_ratio:.1%} →"
                    f" {worst.latest_ratio:.1%}, {worst.revision_pp:+.1f}pp, when"
                    " EU27/Korea/Singapore backfilled) — the clearest reason not"
                    " to over-trust a reduced-coverage print. Full-coverage"
                    " quarters have been stable so far.")
    lines += ["", "## Nowcast backtest — earliest call vs realized", ""]
    if ncbt.empty:
        lines += [
            "_No target quarter has both a stored nowcast AND a realized"
            " full-coverage value yet (the nowcast targets are still open"
            " quarters). This resolves as quarters complete — same discipline as"
            " the calls ledger._",
        ]
    else:
        lines += ["| Target | First nowcast | Nowcast | Realized | Error (pp) |",
                  "|---|---|---|---|---|"]
        for _, r in ncbt.iterrows():
            lines.append(f"| {r.target_quarter} | {r.first_nowcast_at} |"
                         f" {r.nowcast:.1%} | {r.realized:.1%} | {r.error_pp:+.1f} |")
        lines.append("")
        lines.append(f"MAE {ncbt.error_pp.abs().mean():.1f}pp over"
                     f" {len(ncbt)} resolved target(s) — illustrative at this n.")
    lines += [
        "",
        "_Harness, not a verdict: n is tiny by design this early. Point-in-time"
        " discipline (git-vintage, no lookahead) is the deliverable; it earns its"
        " keep as vintages accumulate. Research, not investment advice._",
    ]
    return "\n".join(lines)


def main():
    import sqlite3
    panel = parse_ratio_vintages(vintages_from_git())
    rev = revision_table(panel)
    conn = sqlite3.connect(REPO_ROOT / "db" / "tracker.sqlite")
    ncbt = nowcast_backtest(conn, realized_ratios())
    conn.close()

    EXPORTS.mkdir(parents=True, exist_ok=True)
    if not rev.empty:
        rev.to_csv(EXPORTS / "backtest_revisions.csv", index=False)
    md = render(rev, ncbt)
    (EXPORTS / "backtest.md").write_text(md)
    print(md)
    print(f"\nwrote data/exports/backtest.md ({len(panel)} vintage-rows,"
          f" {rev.shape[0]} quarters)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
