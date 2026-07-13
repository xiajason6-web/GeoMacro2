"""Weekly digest DRAFT assembler — for human review, never auto-published.

What this does: assembles data/exports/digest_YYYY-MM-DD.md from the
database, deterministically:
  (a) what changed in the data in the last 7 days (documents, metrics, with
      row-id citations),
  (b) the current indigenization series,
  (c) recent events mapped through exposure_links (channel + direction +
      confidence per entity),
  (d) the latest red-team memo (from review/red_team.py, if present today),
  (e) open review_queue items.
The only LLM content is the red-team section, which is generated separately
and clearly attributed. Everything else is queries.

How you'd know it broke: it prints the output path; each section states its
row counts, so an empty section is visible, not silent.
"""

import datetime
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "analysis"))

import exposure_map  # noqa: E402

DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"
OUT_DIR = REPO_ROOT / "data" / "exports"


def connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def section_data_changes(conn, days=7):
    lines = [f"## What changed in the data (last {days} days)", ""]
    docs = conn.execute(
        "SELECT s.name, COUNT(*), MIN(d.id), MAX(d.id) FROM documents d"
        " JOIN sources s ON s.id = d.source_id"
        " WHERE d.retrieved_at >= datetime('now', ?) GROUP BY s.name",
        (f"-{days} days",),
    ).fetchall()
    if not docs:
        lines.append("No new documents.")
    for name, n, lo, hi in docs:
        lines.append(f"- {name}: {n} new documents (ids {lo}-{hi})")
    metrics = conn.execute(
        "SELECT m.metric_name, COUNT(*), MIN(m.period), MAX(m.period)"
        " FROM metrics m JOIN documents d ON d.id = m.document_id"
        " WHERE d.retrieved_at >= datetime('now', ?)"
        " GROUP BY m.metric_name ORDER BY m.metric_name",
        (f"-{days} days",),
    ).fetchall()
    if metrics:
        lines.append("")
        for name, n, lo, hi in metrics:
            lines.append(f"- metric `{name}`: {n} rows ({lo} .. {hi})")
    return lines


def section_ratio(conn):
    lines = ["## Indigenization series (working)", ""]
    csv_path = OUT_DIR / "indigenization_ratio.csv"
    if not csv_path.exists():
        return lines + ["Not computed — run analysis/indigenization_ratio.py."]
    rows = csv_path.read_text().splitlines()
    header = rows[0].split(",")
    q_i = header.index("quarter")
    r_i = header.index("ratio")
    c_i = header.index("coverage_origins")
    m_i = header.index("missing_origins")
    v_i = header.index("methodology_version")
    lines.append("| Quarter | Ratio | Origins included | Missing |")
    lines.append("|---|---|---|---|")
    version = ""
    for row in rows[1:]:
        cells = row.split(",")
        if cells[r_i]:
            version = cells[v_i]
            lines.append(
                f"| {cells[q_i]} | {float(cells[r_i]):.1%} | {cells[c_i]} | {cells[m_i]} |"
            )
    lines.append("")
    lines.append(
        f"_Methodology v{version} (USD): numerator = domestic semicap revenue;"
        " quarters with missing origins are not comparable to fully-covered"
        " ones — see analysis/methodology.md._"
    )
    return lines


def section_events(conn, days=30):
    lines = [f"## Events and exposure (last {days} days)", ""]
    report = exposure_map.exposure_report(conn, days=days)
    if not report:
        lines.append("No events in window.")
    return lines + report


def section_red_team():
    today = datetime.date.today().isoformat()
    path = OUT_DIR / f"red_team_{today}.md"
    if path.exists():
        return path.read_text().splitlines()
    return [
        "## Red team: the case against",
        "",
        "_No red-team memo for today — run review/red_team.py._",
    ]


def section_review_queue(conn):
    lines = ["## Open questions / review queue", ""]
    items = conn.execute(
        "SELECT id, item_type, reason FROM review_queue WHERE status = 'open'"
        " ORDER BY id DESC"
    ).fetchall()
    if not items:
        lines.append("Queue is empty.")
    for item_id, item_type, reason in items:
        lines.append(f"- [#{item_id}] ({item_type}) {reason[:200]}")
    return lines


def main():
    conn = connect()
    today = datetime.date.today().isoformat()
    parts = [
        f"# China Tech Flows — weekly digest DRAFT ({today})",
        "",
        "_Draft for human review and editing. Research analysis only —"
        " transmission mechanisms and exposure, not investment advice._",
        "",
    ]
    for section in (
        section_data_changes(conn),
        [""],
        section_ratio(conn),
        [""],
        section_events(conn),
        [""],
        section_red_team(),
        [""],
        section_review_queue(conn),
    ):
        parts.extend(section)
    conn.close()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"digest_{today}.md"
    out_path.write_text("\n".join(parts))
    print(f"wrote {out_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
