"""The transmission-mechanism map v2: differentiated per-entity exposure.

Every link below is hand-written, entity-specific, and states the concrete
channel through the entity's actual tool categories or node position —
never a uniform 'benefit/medium'. Rationales cite this pipeline's own data
(segment extractions, the vendor China-revenue panel, Big Fund signals,
the Bernstein category-localization benchmark) wherever possible.

PUBLICATION GATE: every seeded link starts human_reviewed=0. The digest and
dashboard only surface links with human_reviewed=1. Review flow:
    python analysis/exposure_map.py            # sync seeds + show pending
    python analysis/exposure_map.py approve 3 7 12   # approve by id
    python analysis/exposure_map.py approve-all      # after reading them
Direction vocabulary is {benefit, harm, mixed, neutral} — business-exposure
direction with a written mechanism, never trade advice.

How you'd know it broke: sync prints link counts; the report prints a
NO MAPPING warning for event categories without links and a pending count.
"""

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"

# Tool-category / node profiles (from our segment extractions + filings).
# These are context for the links below and printed with pending reviews.
PROFILES = {
    "Naura": "broadest domestic portfolio: etch, thin-film dep, thermal, clean (FY2025 semicap 93% of revenue per our segment extraction)",
    "AMEC": "etch specialist (CCP/ICP; ~98-100% semicap per segments); etch is the most-localized category (~31%, Bernstein benchmark)",
    "Piotech": "PECVD/ALD deposition pure-play; deposition localization ~27% (Bernstein)",
    "ACM Shanghai": "cleaning/plating; cleaning already >50% localized in sub-segments (Bernstein) — least substitution headroom",
    "Kingsemi": "coater-developer (track) — demand coupled to lithography availability, which remains <10% localized",
    "Hwatsing": "CMP polishing (+ thinning); competes primarily with Applied Materials CMP",
    "SMIC": "largest domestic foundry; Entity-Listed since 2020; advanced-node expansion is the constrained margin",
    "Hua Hong": "specialty mature-node foundry (power/analog/MCU) — less dependent on leading-edge US tools",
    "Applied Materials": "US vendor; China 27% of revenue latest vs 35% peak (our panel)",
    "Lam Research": "US vendor; China 34% latest vs 43% peak (our panel)",
    "KLA": "US vendor (metrology/inspection — least localized category); China 24% latest vs 40% peak (our panel)",
    "ASML": "EU litho vendor; EUV already embargoed, DUV restricted; China 19% of 2026Q1 revenue vs 36% in 2025Q4 (our extraction)",
}

L = lambda cat, entity, direction, conf, channel, rationale: {  # noqa: E731
    "event_category": cat, "entity": entity, "direction": direction,
    "confidence": conf, "channel": channel, "rationale": rationale,
}

SEED_LINKS = [
    # ============ US Entity List actions ======================================
    L("entity_list", "SMIC", "harm", "high",
      "Designations tighten US-origin tool/spares/service licensing to named fabs; SMIC's advanced-node capacity is the constrained margin.",
      "SMIC Entity-Listed since 2020; each wave narrows licensable scope. Mature-node expansion continues — harm concentrates at advanced nodes."),
    L("entity_list", "Hua Hong", "harm", "low",
      "Mature-node tools largely fall below control thresholds; listings add compliance friction more than hard denial.",
      "Specialty/mature process portfolio (28nm+) — most required tools remain licensable or have domestic substitutes."),
    L("entity_list", "Naura", "benefit", "high",
      "Each tightening pushes Chinese fabs to qualify domestic etch/deposition/thermal/clean — Naura carries the broadest substitute portfolio.",
      "Our series: Naura semicap revenue nearly tripled 2023->2025 while equipment imports fell ~45% from peak — substitution is observable, not theoretical."),
    L("entity_list", "AMEC", "benefit", "high",
      "Etch is the most mature substitution category; constrained Lam/TEL/AMAT etch supply accrues to AMEC first.",
      "Etch localization ~31% (Bernstein benchmark row), highest of all categories; AMEC is the domestic etch flagship."),
    L("entity_list", "Piotech", "benefit", "high",
      "Deposition (PECVD/ALD) is the second-most substituted category; restrictions on AMAT/Lam deposition push qualification to Piotech.",
      "Deposition localization ~27% (Bernstein); Piotech revenue grew fastest among the six in our panel (2.6bn->6.3bn CNY FY2023->FY2025)."),
    L("entity_list", "ACM Shanghai", "benefit", "medium",
      "Cleaning substitution demand rises, but the category is already >50% localized — headroom is smaller than etch/deposition.",
      "Bernstein: cleaning >50% in sub-segments; ACM's marginal win-rate gain per new restriction is lower than AMEC/Piotech's."),
    L("entity_list", "Hwatsing", "benefit", "medium",
      "CMP substitution vs Applied Materials; a mid-sized category with one dominant foreign incumbent.",
      "Hwatsing is the domestic CMP monopolist (FY2025 semicap ~100% per segments); category size caps the effect."),
    L("entity_list", "Kingsemi", "mixed", "medium",
      "Track tools pair 1:1 with lithography: substitution demand rises, but litho itself (<10% localized) stays import-dependent — constrained litho supply also caps new track demand.",
      "Coater-developer demand derives from scanner installations; export controls cut both the competing track imports AND the litho installations tracks attach to."),
    L("entity_list", "Applied Materials", "harm", "high",
      "License requirements directly remove Chinese fab revenue across dep/etch/CMP/implant lines.",
      "Our panel: AMAT China share 35% (mid-2025) -> 27% (latest 10-Q) across the 2024-25 rule waves."),
    L("entity_list", "Lam Research", "harm", "high",
      "Etch/deposition license denials to listed fabs; NAND-heavy China exposure concentrates the hit.",
      "Our panel: Lam China share 43% peak -> 34% latest."),
    L("entity_list", "KLA", "harm", "high",
      "Metrology/inspection is the least-localized category — losses are pure revenue loss, but with no domestic substitution offset China fabs also can't walk away easily (partial stickiness).",
      "Our panel: KLA China share 40% -> 24%, the steepest fall among the three US vendors."),
    L("entity_list", "ASML", "harm", "medium",
      "Incremental US listings matter less for ASML directly — EUV is already embargoed and DUV immersion restricted via Dutch alignment; residual harm via US-content parts thresholds.",
      "Our extraction: ASML China 19% of 2026Q1 revenue, normalizing to ~20% per guidance after the 2023-24 stockpiling wave — most of the adjustment predates new listings."),

    # ============ Broader export-control rules (BIS FDPR/affiliate/etc.) =====
    L("export_control", "SMIC", "harm", "high",
      "FDPR and affiliate-rule expansions capture tools and parts otherwise outside US jurisdiction — tightens the same advanced-node constraint.",
      "Same mechanism as entity_list at rule level; severity scales with each rule's scope."),
    L("export_control", "Hua Hong", "harm", "low",
      "Mature-node scope mostly unaffected; compliance/documentation costs rise.",
      "As with listings: specialty node position insulates."),
    L("export_control", "Naura", "benefit", "high",
      "Rule-level tightening = the same domestic qualification push across Naura's four tool categories.",
      "See entity_list rationale; rule waves (Oct 2022, Oct 2023, Dec 2024) each preceded visible import declines in our mirror series."),
    L("export_control", "AMEC", "benefit", "high",
      "As entity_list: etch substitution accelerates with each rule wave.",
      "Etch localization trajectory (4%->31% since 2018 per Bernstein) tracks the rule timeline."),
    L("export_control", "Piotech", "benefit", "high",
      "As entity_list: deposition substitution.", "See deposition localization evidence."),
    L("export_control", "ACM Shanghai", "benefit", "medium",
      "As entity_list: cleaning substitution with limited headroom.", "See cleaning localization evidence."),
    L("export_control", "Hwatsing", "benefit", "medium",
      "As entity_list: CMP substitution.", "Category-size capped."),
    L("export_control", "Kingsemi", "mixed", "medium",
      "As entity_list: track demand up on substitution, down on litho constraint.", "Litho coupling — see entity_list rationale."),
    L("export_control", "Applied Materials", "harm", "high",
      "Each rule wave removes licensable China revenue.", "Panel evidence as entity_list."),
    L("export_control", "Lam Research", "harm", "high",
      "Each rule wave removes licensable China revenue.", "Panel evidence as entity_list."),
    L("export_control", "KLA", "harm", "high",
      "Each rule wave removes licensable China revenue.", "Panel evidence as entity_list."),
    L("export_control", "ASML", "harm", "medium",
      "US-content thresholds and allied alignment extend restrictions to DUV service/parts.",
      "China share normalization already largely in guidance."),

    # ============ Chinese subsidies (Big Fund, tax lists) =====================
    L("subsidy", "SMIC", "benefit", "high",
      "Direct state-capital channel: Big Fund equity plus subsidized fab capex lowers SMIC's cost of expansion.",
      "Our Big Fund signal 2026-06-25: the Fund and concert parties changed their SMIC A-share position — the ownership channel is live, not historical."),
    L("subsidy", "Hua Hong", "benefit", "high",
      "Same direct channel: Big Fund holds Hua Hong positions; mature-node expansion is subsidy-favored.",
      "Big Fund II participated in Hua Hong's A-share raise; specialty capacity is a stated policy priority."),
    L("subsidy", "Naura", "benefit", "medium",
      "Indirect: subsidized fab capex becomes tool orders; enterprise-list tax breaks cut Naura's own costs.",
      "Magnitude per document varies — the 2023-25 IC enterprise tax lists (our policy events 58-62) set the eligibility channel."),
    L("subsidy", "AMEC", "benefit", "medium",
      "As Naura: capex pass-through plus enterprise tax eligibility.", "Same policy-event basis."),
    L("subsidy", "Piotech", "benefit", "medium",
      "As Naura.", "Same policy-event basis."),
    L("subsidy", "ACM Shanghai", "benefit", "medium",
      "As Naura.", "Same policy-event basis."),
    L("subsidy", "Kingsemi", "benefit", "medium",
      "As Naura.", "Same policy-event basis."),
    L("subsidy", "Hwatsing", "benefit", "medium",
      "As Naura.", "Same policy-event basis."),
    L("subsidy", "Applied Materials", "neutral", "medium",
      "Chinese fab subsidies expand total tool demand (helps) while funding substitution (hurts) — net direction unclear at vendor level.",
      "Subsidized capacity still buys foreign tools where no domestic option exists (esp. metrology, litho-adjacent)."),
    L("subsidy", "Lam Research", "neutral", "medium",
      "As AMAT: demand expansion vs substitution funding — offsetting.", "Same reasoning."),
    L("subsidy", "KLA", "neutral", "medium",
      "As AMAT; inspection has no domestic substitute yet, so subsidy-funded fabs remain KLA customers near-term.", "Least-localized category."),
    L("subsidy", "ASML", "neutral", "low",
      "Chinese subsidies neither expand ASML's licensable scope nor fund a litho substitute at scale yet.", "SMEE remains sub-scale (unlisted, no filings)."),

    # ============ Chinese industrial policy (plans, catalogs, self-reliance) ==
    L("industrial_policy", "Naura", "benefit", "medium",
      "Qualification programs and domestic-content preferences prioritize the broadest-portfolio local vendor in fab procurement.",
      "Mechanism documented in policy events (e.g. 2025-11 self-reliance guidance, our event 63); per-document strength varies."),
    L("industrial_policy", "AMEC", "benefit", "medium",
      "As Naura, concentrated in etch procurement.", "Same policy basis."),
    L("industrial_policy", "Piotech", "benefit", "medium",
      "As Naura, deposition procurement.", "Same policy basis."),
    L("industrial_policy", "ACM Shanghai", "benefit", "medium",
      "As Naura, cleaning procurement.", "Same policy basis."),
    L("industrial_policy", "Kingsemi", "benefit", "medium",
      "Domestic-content preference applies to track tools; the litho coupling matters less here because policy drives share shift within existing demand.",
      "Procurement-preference channel, not supply-constraint channel."),
    L("industrial_policy", "Hwatsing", "benefit", "medium",
      "As Naura, CMP procurement.", "Same policy basis."),
    L("industrial_policy", "SMIC", "benefit", "medium",
      "Self-reliance programs guarantee demand for domestic foundry capacity and priority access to state resources.",
      "Policy events basis; offset partially by pressure to buy less-mature domestic tools."),
    L("industrial_policy", "Hua Hong", "benefit", "medium",
      "As SMIC for specialty capacity.", "Same."),
    L("industrial_policy", "Applied Materials", "harm", "low",
      "Domestic-content preferences displace foreign tools at the margin in covered procurement.",
      "Effect visible only over multi-year horizons; near-term demand still exceeds domestic supply."),
    L("industrial_policy", "Lam Research", "harm", "low",
      "As AMAT.", "Same."),
    L("industrial_policy", "KLA", "harm", "low",
      "As AMAT, least exposed near-term (no domestic metrology substitute).", "Same."),
    L("industrial_policy", "ASML", "neutral", "low",
      "Policy cannot currently substitute lithography; procurement preference has nothing to prefer.",
      "Litho localization <10% (Bernstein)."),
]


def connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def sync_links(conn):
    """Insert seed links not yet present (matched on category+entity+channel).
    New links arrive with human_reviewed=0 — unreviewed links never publish."""
    added = skipped = 0
    for link in SEED_LINKS:
        row = conn.execute(
            "SELECT id FROM entities WHERE name_en = ?", (link["entity"],)
        ).fetchone()
        if row is None:
            print(f"WARNING: entity {link['entity']!r} not in entities table — skipped")
            skipped += 1
            continue
        entity_id = row[0]
        exists = conn.execute(
            "SELECT 1 FROM exposure_links WHERE event_category = ?"
            " AND entity_id = ? AND channel_description = ?",
            (link["event_category"], entity_id, link["channel"]),
        ).fetchone()
        if exists:
            continue
        conn.execute(
            "INSERT INTO exposure_links"
            " (event_category, channel_description, entity_id, direction,"
            "  confidence, rationale, human_reviewed)"
            " VALUES (?, ?, ?, ?, ?, ?, 0)",
            (
                link["event_category"], link["channel"], entity_id,
                link["direction"], link["confidence"], link["rationale"],
            ),
        )
        added += 1
    conn.commit()
    total, reviewed = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(human_reviewed), 0) FROM exposure_links"
    ).fetchone()
    print(f"exposure_links synced: +{added} new, {total} total,"
          f" {reviewed} human-reviewed ({total - reviewed} pending)")


def exposure_report(conn, days=60, include_unreviewed=False):
    """Join recent events to the map. PUBLISHABLE output shows only
    human_reviewed links; pending ones appear only as a count."""
    lines = []
    gate = "" if include_unreviewed else " AND x.human_reviewed = 1"
    events = conn.execute(
        "SELECT id, event_date, category, actor, COALESCE(NULLIF(summary_en,"
        " 'PENDING_TRANSLATION'), summary_zh)"
        " FROM events WHERE event_date >= date('now', ?) ORDER BY event_date DESC",
        (f"-{days} days",),
    ).fetchall()
    for event_id, date, category, actor, summary in events:
        links = conn.execute(
            f"SELECT e.name_en, x.direction, x.confidence, x.channel_description"
            f" FROM exposure_links x JOIN entities e ON e.id = x.entity_id"
            f" WHERE x.event_category = ?{gate} ORDER BY x.direction, e.name_en",
            (category,),
        ).fetchall()
        pending, = conn.execute(
            "SELECT COUNT(*) FROM exposure_links WHERE event_category = ?"
            " AND human_reviewed = 0",
            (category,),
        ).fetchone()
        lines.append(f"[{date}] ({category}, {actor}) event #{event_id}")
        lines.append(f"    {summary[:150]}")
        if not links and not pending:
            lines.append(f"    !! NO MAPPING for category {category!r} — add to exposure_map.py")
            continue
        for name, direction, confidence, channel in links:
            lines.append(f"    -> {name}: {direction} ({confidence}) via: {channel[:110]}")
        if pending:
            lines.append(f"    ({pending} link(s) pending human review — not shown)")
    return lines


def show_pending(conn):
    rows = conn.execute(
        "SELECT x.id, x.event_category, e.name_en, x.direction, x.confidence,"
        " x.channel_description, x.rationale"
        " FROM exposure_links x JOIN entities e ON e.id = x.entity_id"
        " WHERE x.human_reviewed = 0 ORDER BY x.event_category, e.name_en"
    ).fetchall()
    if not rows:
        print("no links pending review")
        return
    print(f"\n{len(rows)} links PENDING HUMAN REVIEW"
          " (approve: python analysis/exposure_map.py approve <ids>|approve-all):\n")
    for link_id, cat, name, direction, conf, channel, rationale in rows:
        profile = PROFILES.get(name, "")
        print(f"[{link_id}] {cat} -> {name}: {direction} ({conf})")
        if profile:
            print(f"     profile: {profile[:110]}")
        print(f"     channel: {channel}")
        print(f"     rationale: {rationale}\n")


def approve(conn, ids):
    if ids == "all":
        cur = conn.execute("UPDATE exposure_links SET human_reviewed = 1 WHERE human_reviewed = 0")
    else:
        cur = conn.execute(
            "UPDATE exposure_links SET human_reviewed = 1 WHERE id IN"
            " (%s)" % ",".join("?" * len(ids)),
            ids,
        )
    conn.commit()
    print(f"approved {cur.rowcount} link(s)")


def main(argv):
    conn = connect()
    if argv[:1] == ["approve-all"]:
        approve(conn, "all")
    elif argv[:1] == ["approve"]:
        approve(conn, [int(x) for x in argv[1:]])
    else:
        sync_links(conn)
        show_pending(conn)
        print()
        for line in exposure_report(conn):
            print(line)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
