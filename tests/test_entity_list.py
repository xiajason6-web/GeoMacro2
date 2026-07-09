"""Phase 4 fixture tests: BIS Entity List events from the Federal Register.

Fixture: tests/fixtures/fr_bis_rules.json is the real Federal Register API
response (BIS rules mentioning the Entity List, 2023-07 onward) retrieved
2026-07-09 — 57 rules.
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "collectors"))

import entity_list  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "fr_bis_rules.json"


@pytest.fixture
def rules():
    return json.loads(FIXTURE.read_bytes().splitlines()[0])["results"]


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript((ROOT / "db" / "schema.sql").read_text())
    conn.execute(
        "INSERT INTO sources (name, url, type, language)"
        " VALUES ('Federal Register', 'u', 'regulatory', 'en')"
    )
    yield conn
    conn.close()


def test_categorize():
    assert entity_list.categorize("Additions to the Entity List") == "entity_list"
    assert entity_list.categorize("Revisions to the Unverified List") == "export_control"


def test_fixture_shape(rules):
    assert len(rules) == 57
    titles = [r["title"] for r in rules]
    assert "Additions to the Entity List" in titles
    for r in rules:
        assert r["publication_date"] >= "2023-07-01"


def test_ingest_creates_events_and_dedupes(db, tmp_path, monkeypatch, rules):
    monkeypatch.setattr(entity_list, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(entity_list, "REPO_ROOT", tmp_path)
    raw_pages = [FIXTURE.read_bytes().splitlines()[0]]

    new = entity_list.ingest(db, 1, rules, raw_pages)
    assert new == 57
    count, = db.execute("SELECT COUNT(*) FROM events").fetchone()
    assert count == 57
    # every event traceable to a document
    orphans, = db.execute(
        "SELECT COUNT(*) FROM events e LEFT JOIN documents d ON d.id = e.document_id"
        " WHERE d.id IS NULL"
    ).fetchone()
    assert orphans == 0

    # second ingest of the same data adds nothing
    new2 = entity_list.ingest(db, 1, rules, raw_pages)
    assert new2 == 0
    count2, = db.execute("SELECT COUNT(*) FROM events").fetchone()
    assert count2 == 57


def test_summary_carries_url(rules):
    summary = entity_list.summarize(rules[0])
    assert rules[0]["title"] in summary
    assert "federalregister.gov" in summary
