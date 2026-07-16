"""Trade note DRAFT — the thematic-pod audition document.

Assembles data/exports/trade_note.md from the pipeline: thesis, the measured
picture, the surprise (nowcast vs consensus), the mechanism, the exposure
ladder, the leading indicators, and — most important — the falsifiers.

STRICTLY RESEARCH. It states a directional VIEW on a theme and maps business
exposure to instruments with mechanisms and disconfirming conditions. It
contains no position sizing, no entry/exit, no price targets, no long/short
instructions. The disclaimer is emitted top and bottom. A PM sizes the trade.

Deterministic assembly — no LLM. How you'd know it broke: it prints the
output path; each section states its inputs.
"""

import datetime
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for sub in ("analysis",):
    sys.path.insert(0, str(REPO_ROOT / sub))

import exposure_ladder  # noqa: E402
import indigenization_ratio as ir  # noqa: E402
import consensus_gap as gap_mod  # noqa: E402

DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"
OUT_PATH = REPO_ROOT / "data" / "exports" / "trade_note.md"

DISCLAIMER = (
    "Research and educational analysis only — NOT investment advice, NOT a"
    " recommendation, and NOT an offer to buy or sell any security. No"
    " position sizing, entry/exit levels, or price targets are expressed or"
    " implied. Exposure directions describe how an instrument's business is"
    " affected by the theme, not what any person should do. Do your own"
    " diligence."
)


def connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def measured_picture(conn):
    out = ir.compute_ratio(conn)
    full = out[(out.coverage_origins == gap_mod.FULL) & out.ratio.notna()]
    if full.empty:
        return None
    latest_q = full.index.max()
    latest = full.loc[latest_q].ratio
    first_q = full.index.min()
    first = full.loc[first_q].ratio
    return {
        "latest_q": latest_q, "latest": latest,
        "first_q": first_q, "first": first,
        "quarters": len(full),
    }


def vendor_panel(conn):
    """Latest China-revenue reading per foreign vendor (the leading signal)."""
    rows = conn.execute(
        "SELECT e.name_en, m.period, m.value FROM metrics m"
        " JOIN entities e ON e.id = m.entity_id"
        " WHERE m.metric_name = 'china_revenue_pct'"
        " AND m.period = (SELECT MAX(m2.period) FROM metrics m2"
        "   WHERE m2.entity_id = m.entity_id AND m2.metric_name = 'china_revenue_pct')"
        " ORDER BY e.name_en"
    ).fetchall()
    return rows


def render(conn):
    today = datetime.date.today().isoformat()
    mp = measured_picture(conn)
    sur = gap_mod.build(conn)
    ladder = exposure_ladder.rows_for_output(conn, include_unreviewed=True)
    ladder_reviewed = conn.execute(
        "SELECT COUNT(*) FROM instrument_exposure WHERE human_reviewed = 1"
    ).fetchone()[0]

    L = [
        f"# Research note: China semiconductor-equipment indigenization ({today})",
        "",
        f"> {DISCLAIMER}",
        "",
        "_DRAFT for human review. Nothing here is published until a person"
        " approves it._",
        "",
        "## Thesis",
        "",
    ]
    if mp:
        direction = "rising" if mp["latest"] > mp["first"] else "falling"
        L.append(
            f"China's domestic share of wafer-fab-equipment spending is"
            f" structurally {direction}: measured at {mp['latest']:.1%} in"
            f" {mp['latest_q']} (full-coverage), up from {mp['first']:.1%} in"
            f" {mp['first_q']}. The trajectory is a slow, policy-driven"
            f" substitution of foreign tools by domestic ones — durable, not"
            f" a blip. It is a market-SHARE shift, not necessarily a"
            f" capability parity, and the two should not be conflated."
        )
    L += ["", "## Nowcast vs consensus — the gap you'd trade", ""]
    if sur and sur["rows"]:
        r = sur["rows"][0]
        L.append(
            f"Consensus drifts to persistence ({sur['baseline_quarter']} ="
            f" {sur['baseline']:.1%}) between quarterly prints. The nowcast"
            f" model puts {r['quarter']} at {r['nowcast']:.1%}"
            f" ({r['surprise_pp']:+.1f} pp {r['direction']} that baseline),"
            f" band {r['low']:.1%}–{r['high']:.1%}. Catalyst: {r['catalyst']}."
            f" This is an estimate, not measured data."
        )
    L += [
        "",
        "## Mechanism",
        "",
        "Export controls (US Entity List, allied DUV/EUV limits) remove or"
        " raise the cost of the foreign alternative; Chinese fabs qualify"
        " domestic tools to keep expanding; state capital (Big Fund, tax"
        " lists) subsidizes the capex that becomes domestic tool orders. The"
        " ratio rising and foreign vendors' China revenue falling are two"
        " sides of the same flow — and this pipeline measures both.",
        "",
        "## Exposure ladder",
        "",
        f"_({'reviewed' if ladder_reviewed else 'DRAFT — pending review'};"
        " business-exposure direction, not a trade call.)_",
        "",
        "| Instrument | Venue | Exposure to rising indigenization | Conf. | Mechanism |",
        "|---|---|---|---|---|",
    ]
    for instr, venue, _t, sign, conf, mech, _ev, _hr in ladder:
        L.append(f"| {instr} | {venue} | {sign} | {conf} | {mech[:150]} |")

    L += ["", "## Leading indicators to watch (this pipeline updates them)", ""]
    for name, period, pct in vendor_panel(conn):
        L.append(f"- {name} China revenue: {pct:.0f}% (as of {period}) — leads Chinese prints by weeks")
    L += [
        "- Next Chinese quarterly filings (cninfo) — extend the measured numerator",
        "- UN Comtrade Korea/Singapore releases — complete the newest quarter's denominator",
        "- BIS Entity List / MOFCOM export-control diffs — step-changes in the mechanism",
        "",
        "## What would prove this wrong (falsifiers)",
        "",
        "- Foreign vendors' China revenue share STOPS falling or re-accelerates"
        " for two+ consecutive quarters (substitution stalling).",
        "- The measured ratio rolls over on FULL-coverage quarters (not the"
        " partial-data artifacts) — i.e. domestic revenue growth decelerates"
        " faster than imports.",
        "- Export controls loosen materially (the mechanism's driver reverses).",
        "- Segment/region disclosures reveal the domestic-semicap numerator was"
        " overstated (our own adjustment proves too generous).",
        "",
        "## Method and limits",
        "",
        "Numerator: six listed Chinese equipment makers' revenue, scaled to"
        " disclosed semicap-segment and domestic shares. Denominator: mirror"
        " exports to China (EU27+Japan+US+Korea+Singapore; Taiwan unavailable),"
        " USD-normalized. Every figure traces to an archived filing or trade"
        " release. Full methodology: analysis/methodology.md; the consensus"
        " reconciliation accompanies this note. The falsifiers above are the"
        " standing case against this thesis.",
        "",
        f"> {DISCLAIMER}",
    ]
    return "\n".join(L)


def main():
    conn = connect()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(render(conn))
    conn.close()
    print(f"wrote {OUT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
