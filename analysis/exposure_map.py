"""The transmission-mechanism map: event categories -> channels -> entities.

What this does: maintains the `exposure_links` table from SEED_LINKS below —
hand-written, reviewable analyst judgments about how each event CATEGORY
transmits to each listed entity (direction + confidence + rationale). These
are deliberately code, not LLM output: you can read every line, and editing
the map is a git-reviewed change. Run with no arguments to sync the table
and print the current map joined against recent events.

This is research analysis (finding -> mechanism -> exposed entities ->
confidence), never trade advice.

How you'd know it broke: the sync prints how many links exist; the report
joins the last 60 days of events to the map — an event category with no
links prints a NO MAPPING warning so gaps are visible.
"""

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"

# direction: how the event category affects the entity's business
# ('benefit' | 'harm' | 'mixed'), NOT a view on any security's price.
SEED_LINKS = [
    # --- BIS Entity List / US export controls ---------------------------------
    {
        "event_category": "entity_list",
        "entities": ["SMIC", "Hua Hong"],
        "direction": "harm",
        "confidence": "high",
        "channel": (
            "US Entity List / export-control actions restrict listed Chinese"
            " fabs' access to US-origin tools, spares, and services; capacity"
            " expansion at advanced nodes becomes harder and costlier."
        ),
        "rationale": (
            "SMIC has been Entity-Listed since 2020; incremental actions"
            " tighten license policy for suppliers. Visible in mirror trade:"
            " US HS8486 exports to China fell sharply after Oct 2022 and Dec"
            " 2024 rule waves (metrics: mirror_exports_us_hs8486_usd)."
        ),
    },
    {
        "event_category": "entity_list",
        "entities": ["Naura", "AMEC", "ACM Shanghai", "Piotech", "Kingsemi", "Hwatsing"],
        "direction": "benefit",
        "confidence": "high",
        "channel": (
            "Restrictions on foreign tools push Chinese fabs to qualify and"
            " purchase domestic equipment (import substitution demand)."
        ),
        "rationale": (
            "The indigenization ratio rose from ~17% (2023Q3) to ~37% (2026Q1)"
            " while imports fell — substitution is observable in our own"
            " series (metrics: quarterly_revenue_cny vs mirror_exports_*)."
        ),
    },
    {
        "event_category": "export_control",
        "entities": ["SMIC", "Hua Hong"],
        "direction": "harm",
        "confidence": "high",
        "channel": (
            "Broader export-control rules (end-user, affiliate, FDPR"
            " expansions) constrain tool/parts supply to Chinese foundries."
        ),
        "rationale": "Same mechanism as entity_list at rule level; see events actor=BIS.",
    },
    {
        "event_category": "export_control",
        "entities": ["Naura", "AMEC", "ACM Shanghai", "Piotech", "Kingsemi", "Hwatsing"],
        "direction": "benefit",
        "confidence": "high",
        "channel": "Import substitution demand (as with entity_list actions).",
        "rationale": "See indigenization ratio series.",
    },
    # --- Chinese industrial policy --------------------------------------------
    {
        "event_category": "subsidy",
        "entities": ["Naura", "AMEC", "ACM Shanghai", "Piotech", "Kingsemi", "Hwatsing", "SMIC", "Hua Hong"],
        "direction": "benefit",
        "confidence": "medium",
        "channel": (
            "State funds (Big Fund tranches, local funds) and tax incentives"
            " lower capital costs and subsidize fab capex, which is equipment"
            " demand."
        ),
        "rationale": (
            "Directionally clear; magnitude and timing per company are not,"
            " hence medium confidence. Refine per specific policy event."
        ),
    },
    {
        "event_category": "industrial_policy",
        "entities": ["Naura", "AMEC", "ACM Shanghai", "Piotech", "Kingsemi", "Hwatsing"],
        "direction": "benefit",
        "confidence": "medium",
        "channel": (
            "Domestic-content targets and qualification programs prioritize"
            " local toolmakers in fab procurement."
        ),
        "rationale": "Mechanism well documented; per-event strength varies.",
    },
]


def connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def sync_links(conn):
    """Insert seed links that aren't in exposure_links yet (matched on
    category + entity + direction + channel). Never deletes — removing a
    link is a reviewed edit here followed by manual DB cleanup."""
    added = 0
    for link in SEED_LINKS:
        for name_en in link["entities"]:
            row = conn.execute(
                "SELECT id FROM entities WHERE name_en = ?", (name_en,)
            ).fetchone()
            if row is None:
                print(f"WARNING: entity {name_en!r} not in entities table — skipped")
                continue
            entity_id = row[0]
            exists = conn.execute(
                "SELECT 1 FROM exposure_links WHERE event_category = ?"
                " AND entity_id = ? AND direction = ? AND channel_description = ?",
                (link["event_category"], entity_id, link["direction"], link["channel"]),
            ).fetchone()
            if exists:
                continue
            conn.execute(
                "INSERT INTO exposure_links"
                " (event_category, channel_description, entity_id, direction,"
                "  confidence, rationale)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    link["event_category"],
                    link["channel"],
                    entity_id,
                    link["direction"],
                    link["confidence"],
                    link["rationale"],
                ),
            )
            added += 1
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM exposure_links").fetchone()[0]
    print(f"exposure_links synced: +{added} new, {total} total")


def exposure_report(conn, days=60):
    """Join recent events to the map; return list of text lines."""
    lines = []
    events = conn.execute(
        "SELECT id, event_date, category, actor, COALESCE(summary_en, summary_zh)"
        " FROM events WHERE event_date >= date('now', ?) ORDER BY event_date DESC",
        (f"-{days} days",),
    ).fetchall()
    for event_id, date, category, actor, summary in events:
        links = conn.execute(
            "SELECT e.name_en, x.direction, x.confidence, x.channel_description"
            " FROM exposure_links x JOIN entities e ON e.id = x.entity_id"
            " WHERE x.event_category = ? ORDER BY x.direction, e.name_en",
            (category,),
        ).fetchall()
        lines.append(f"[{date}] ({category}, {actor}) event #{event_id}")
        lines.append(f"    {summary[:150]}")
        if not links:
            lines.append(f"    !! NO MAPPING for category {category!r} — add to exposure_map.py")
            continue
        for name, direction, confidence, channel in links:
            lines.append(f"    -> {name}: {direction} ({confidence}) via: {channel[:90]}")
    return lines


def main():
    conn = connect()
    sync_links(conn)
    print()
    for line in exposure_report(conn):
        print(line)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
