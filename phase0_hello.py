"""Phase 0 end-to-end "hello pipeline".

What this does: runs the two Phase 0 steps in order — (1) the ASML collector,
(2) the China-revenue extraction — then queries the database independently
and prints the resulting metrics row. One command, one visible row:

    .venv/bin/python phase0_hello.py

How you'd know it broke: any step failing stops the run with that step's
error output and a non-zero exit code. If the final query prints no row,
the pipeline did not produce data (check review_queue).
"""

import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

STEPS = [
    "collectors/western_earnings.py",
    "extraction/extract_earnings_region.py",
]


def main():
    for step in STEPS:
        print(f"\n=== running {step} ===", flush=True)
        result = subprocess.run([sys.executable, str(ROOT / step)])
        if result.returncode != 0:
            print(f"\nstep failed: {step} (exit code {result.returncode})")
            return result.returncode

    print("\n=== final check: reading metrics straight from the database ===")
    conn = sqlite3.connect(ROOT / "db" / "tracker.sqlite")
    rows = conn.execute(
        "SELECT m.id, e.name_en, m.metric_name, m.period, m.value, m.unit,"
        "       m.extraction_confidence"
        " FROM metrics m JOIN entities e ON e.id = m.entity_id"
    ).fetchall()
    conn.close()
    if not rows:
        print("no rows in metrics — check review_queue")
        return 1
    for row in rows:
        print("  " + " | ".join(str(v) for v in row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
