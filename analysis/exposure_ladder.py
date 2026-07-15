"""Exposure ladder: the indigenization THEME → liquid instruments.

Each row is a hand-written, reviewable mapping from *rising China WFE
indigenization* to a tradeable instrument, stating the business-exposure
SIGN (benefit / harm / mixed / neutral) and the concrete mechanism. This is
research — direction and channel, backed by this pipeline's own data. It is
NOT investment advice: no sizing, no entry, no price target, no long/short.
A PM reads the mechanism and sizes their own trade.

The point of a ladder (vs a flat list) is discernment: some links are clean
(ACMR benefits, AMAT is harmed), some are genuinely mixed (foundries), and
some are too weak to trade (USDCNH) — saying so is the credible move.

human_reviewed gates client-facing output, exactly like exposure_links.
    python analysis/exposure_ladder.py                # sync + show pending
    python analysis/exposure_ladder.py approve-all    # after reading them
"""

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"
OUT_PATH = REPO_ROOT / "data" / "exports" / "exposure_ladder.md"

I = lambda instr, venue, typ, sign, conf, mech, ev: {  # noqa: E731
    "instrument": instr, "venue": venue, "instrument_type": typ,
    "exposure_sign": sign, "confidence": conf, "mechanism": mech, "our_evidence": ev,
}

# Ordered clean-winner -> clean-loser -> mixed -> too-weak-to-trade.
LADDER = [
    I("ACMR", "NASDAQ", "equity", "benefit", "high",
      "US-listed parent of ACM Shanghai (盛美上海), a direct domestic cleaning/plating winner; rising indigenization = rising domestic tool orders it captures. Caveat: ACMR consolidates but is not identical to the A-share entity.",
      "our domestic_semicap_revenue for ACM Shanghai; ~100% semicap segment"),
    I("AMAT", "NASDAQ", "equity", "harm", "high",
      "Domestic etch/deposition/CMP substitution (Naura, AMEC, Piotech, Hwatsing) directly displaces Applied Materials' China tool sales.",
      "vendor panel: AMAT China revenue 35% (mid-25) -> 27% (latest)"),
    I("LRCX", "NASDAQ", "equity", "harm", "high",
      "Etch/deposition substitution plus NAND-heavy China exposure; Lam loses the most localized categories first.",
      "vendor panel: Lam China revenue 43% peak -> 34% latest"),
    I("ASML", "NASDAQ", "equity", "harm", "medium",
      "Rising indigenization erodes ASML's China DUV revenue (EUV already embargoed); China normalizing from a 2023-24 stockpiling peak toward ~20% of revenue.",
      "our extraction: ASML China 19% of 2026Q1 revenue vs 36% in 2025Q4"),
    I("KLAC", "NASDAQ", "equity", "mixed", "medium",
      "Metrology/inspection is the least-localized category (slower substitution), but KLA's China share fell steepest — that erosion is more export-control denial than domestic substitution, so it is not a clean indigenization play.",
      "vendor panel: KLA China revenue 40% -> 24%, steepest of the three"),
    I("0981.HK", "HKEX", "equity", "mixed", "medium",
      "SMIC is a foundry (equipment BUYER): domestic tool availability eases its sanctioned tool-access constraint (benefit), but it is the primary sanctions target and advanced-node-constrained (harm). Net mixed.",
      "our SMIC foundry classification; Big Fund stake-change signal 2026-06"),
    I("1347.HK", "HKEX", "equity", "mixed", "low",
      "Hua Hong is a mature-node foundry, less sanction-exposed; domestic tools serve mature nodes well, so modest benefit — but the link to the WFE ratio is indirect.",
      "our Hua Hong mature-node (power/analog/MCU) classification"),
    I("SMH", "ETF", "etf", "neutral", "low",
      "Broad semis ETF dominated by Nvidia / TSMC / Broadcom; the WFE-indigenization losers (AMAT+LRCX+KLA) are ~10-12% combined weight, so the theme is a minor, partially self-cancelling factor. SOXX behaves similarly.",
      "denominator/vendor exposure vs ETF constituent weights"),
    I("EWY", "ETF", "etf", "mixed", "low",
      "Korea equipment exporters lose China share (our KR mirror data), but EWY is dominated by Samsung / SK Hynix (memory makers with different exposure). Weak, mixed.",
      "our mirror_exports_kr_hs8486 falling into China"),
    I("EWT", "ETF", "etf", "mixed", "low",
      "TSMC-dominated; Taiwanese tool exporters lose China share, but index exposure is fab-driven, not tool-driven. Weak — and our Taiwan trade data is the one origin we cannot source.",
      "Taiwan permanently in the ratio's missing_origins"),
    I("USDCNH", "FX", "fx", "neutral", "low",
      "Import substitution marginally lowers China's WFE import bill (~$40bn/yr market), a third-order CNH positive at most. Not a primary driver — flagged as too weak to trade on this theme alone.",
      "ratio denominator size vs China's external accounts"),
]


def connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def sync(conn):
    added = 0
    for row in LADDER:
        exists = conn.execute(
            "SELECT 1 FROM instrument_exposure WHERE instrument = ?",
            (row["instrument"],),
        ).fetchone()
        if exists:
            continue
        conn.execute(
            "INSERT INTO instrument_exposure"
            " (instrument, venue, instrument_type, exposure_sign, confidence,"
            "  mechanism, our_evidence, human_reviewed)"
            " VALUES (:instrument, :venue, :instrument_type, :exposure_sign,"
            "  :confidence, :mechanism, :our_evidence, 0)",
            row,
        )
        added += 1
    conn.commit()
    total, reviewed = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(human_reviewed), 0) FROM instrument_exposure"
    ).fetchone()
    print(f"instrument_exposure synced: +{added}, {total} total, {reviewed} reviewed"
          f" ({total - reviewed} pending)")


def rows_for_output(conn, include_unreviewed=False):
    gate = "" if include_unreviewed else " WHERE human_reviewed = 1"
    order = (
        " ORDER BY CASE exposure_sign WHEN 'benefit' THEN 0 WHEN 'harm' THEN 1"
        " WHEN 'mixed' THEN 2 ELSE 3 END,"
        " CASE confidence WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END"
    )
    return conn.execute(
        "SELECT instrument, venue, instrument_type, exposure_sign, confidence,"
        " mechanism, our_evidence, human_reviewed FROM instrument_exposure"
        + gate + order
    ).fetchall()


def render_markdown(conn):
    reviewed = conn.execute(
        "SELECT COUNT(*) FROM instrument_exposure WHERE human_reviewed = 1"
    ).fetchone()[0]
    stamp = "reviewed" if reviewed else "DRAFT — analyst review pending"
    lines = [
        "# Exposure ladder — rising China WFE indigenization",
        "",
        f"_Research only ({stamp}). Business-exposure direction and mechanism,"
        " not investment advice: no sizing, entries, or price targets._",
        "",
        "| Instrument | Venue | Exposure to rising indigenization | Conf. | Mechanism |",
        "|---|---|---|---|---|",
    ]
    for instr, venue, _typ, sign, conf, mech, _ev, _hr in rows_for_output(
        conn, include_unreviewed=True
    ):
        lines.append(f"| {instr} | {venue} | {sign} | {conf} | {mech} |")
    lines += [
        "",
        "Exposure sign = how the instrument's business is affected if the"
        " indigenization ratio keeps rising, not a recommendation. 'mixed'"
        " and 'neutral' rows are included deliberately — not every instrument"
        " is a clean expression of the theme, and saying so is the point.",
    ]
    return "\n".join(lines)


def approve(conn, ids):
    if ids == "all":
        cur = conn.execute("UPDATE instrument_exposure SET human_reviewed = 1 WHERE human_reviewed = 0")
    else:
        cur = conn.execute(
            "UPDATE instrument_exposure SET human_reviewed = 1 WHERE id IN"
            " (%s)" % ",".join("?" * len(ids)), ids,
        )
    conn.commit()
    print(f"approved {cur.rowcount} instrument(s)")


def main(argv):
    conn = connect()
    if argv[:1] == ["approve-all"]:
        approve(conn, "all")
    elif argv[:1] == ["approve"]:
        approve(conn, [int(x) for x in argv[1:]])
    else:
        sync(conn)
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(render_markdown(conn))
        print(f"wrote {OUT_PATH.relative_to(REPO_ROOT)}")
        print()
        print(render_markdown(conn))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
