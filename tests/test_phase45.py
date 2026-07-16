"""Phase 4/5 tests: policy collector parsing, exposure map, digest assembly,
red-team validation.

Fixture: tests/fixtures/govcn_search_ic.json is a real gov.cn policy-library
search response (keyword 集成电路, titles only, since 2023-07) retrieved
2026-07-09 — 6 documents.
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for sub in ("collectors", "analysis", "review", "extraction"):
    sys.path.insert(0, str(ROOT / sub))

import exposure_map  # noqa: E402
import policy_monitor  # noqa: E402
import translate_classify_policy as tcp  # noqa: E402

GOVCN_FIXTURE = Path(__file__).parent / "fixtures" / "govcn_search_ic.json"


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript((ROOT / "db" / "schema.sql").read_text())
    conn.execute("INSERT INTO sources (name, url, type, language) VALUES ('t','u','policy','zh')")
    conn.execute(
        "INSERT INTO documents (source_id,url,retrieved_at,raw_path,sha256,title,language)"
        " VALUES (1,'u','t','p','s1','t','zh')"
    )
    for name, layer in [("Naura", "equipment"), ("SMIC", "foundry")]:
        conn.execute(
            "INSERT INTO entities (name_en, entity_type, supply_chain_layer)"
            " VALUES (?, 'company', ?)",
            (name, layer),
        )
    yield conn
    conn.close()


# ---- policy monitor parsing ---------------------------------------------------

def test_govcn_parse_returns_dated_titles():
    payload = json.loads(GOVCN_FIXTURE.read_text())
    results = policy_monitor.parse_results(payload)
    assert len(results) == 6
    for item in results:
        assert item["title"]
        assert "<em>" not in item["title"]          # highlight markup stripped
        assert len(item["date"].split("-")) == 3     # YYYY-MM-DD


# ---- classification validator ---------------------------------------------------

def test_classify_validator():
    good = {"summary_en": "x", "category": "subsidy", "relevance": "high"}
    assert tcp.validate(good) == []
    assert tcp.validate(dict(good, category="nonsense")) != []
    assert tcp.validate(dict(good, relevance="extreme")) != []
    assert tcp.validate({}) != []


# ---- exposure map --------------------------------------------------------------

def test_exposure_sync_inserts_only_known_entities(db):
    exposure_map.sync_links(db)
    count, = db.execute("SELECT COUNT(*) FROM exposure_links").fetchone()
    # Seeds reference 8 entities but only Naura and SMIC exist in this DB.
    names = {
        r[0]
        for r in db.execute(
            "SELECT DISTINCT e.name_en FROM exposure_links x"
            " JOIN entities e ON e.id = x.entity_id"
        )
    }
    assert names == {"Naura", "SMIC"}
    assert count > 0

    # Re-sync is idempotent.
    exposure_map.sync_links(db)
    count2, = db.execute("SELECT COUNT(*) FROM exposure_links").fetchone()
    assert count2 == count


def test_exposure_report_flags_unmapped_categories(db):
    exposure_map.sync_links(db)
    db.execute(
        "INSERT INTO events (event_date, category, actor, summary_en, document_id)"
        " VALUES (date('now'), 'mystery_category', 'X', 'test event', 1)"
    )
    report = "\n".join(exposure_map.exposure_report(db, days=7))
    assert "NO MAPPING" in report


def test_unreviewed_links_never_publish(db):
    exposure_map.sync_links(db)
    db.execute(
        "INSERT INTO events (event_date, category, actor, summary_en, document_id)"
        " VALUES (date('now'), 'entity_list', 'BIS', 'additions', 1)"
    )
    report = "\n".join(exposure_map.exposure_report(db, days=7))
    assert "Naura: benefit" not in report          # gate holds
    assert "pending human review" in report        # but the gap is visible

    exposure_map.approve(db, "all")
    report = "\n".join(exposure_map.exposure_report(db, days=7))
    assert "Naura: benefit" in report
    assert "SMIC: harm" in report
    assert "via:" in report                        # concrete channel shown


def test_directions_vocabulary_enforced(db):
    import sqlite3 as sq
    with pytest.raises(sq.IntegrityError):
        db.execute(
            "INSERT INTO exposure_links (event_category, channel_description,"
            " entity_id, direction, confidence, rationale)"
            " VALUES ('x', 'c', 1, 'buy', 'high', 'r')"
        )


