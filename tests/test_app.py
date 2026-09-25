"""Tests for the FastAPI app factory."""

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from sonar.app import MIGRATIONS_DIR, create_app
from sonar.db import apply_migrations
from sonar.taxonomy_store import add_category, add_rule
from tests.seed import seed

# Never the shipped src/sonar/categories.toml: tests seed their own fake
# taxonomy so they don't depend on (or break from editing) the real rules.
FAKE_TOML = """
[[category]]
name = "Rent"
type = "fixed"

[[rule]]
category = "Rent"
counterparty = "Fake Landlord"
"""


def test_get_index_renders_page_and_migrates_db(tmp_path):
    db_path = tmp_path / "t.db"

    with TestClient(create_app(db_path)) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "<title>Sonar</title>" in response.text
    assert "htmx" in response.text and "<script" in response.text

    conn = sqlite3.connect(db_path)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "schema_migrations" in tables


def _insert_uncategorized_row(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    apply_migrations(conn, MIGRATIONS_DIR)
    conn.execute(
        """
        INSERT INTO transactions (
            source, account, booking_date, value_date, amount_cents, currency,
            counterparty, purpose, iban, mandate_ref, creditor_id, raw_row,
            fingerprint, occurrence
        ) VALUES (
            'test', 'acc', '2026-01-01', '2026-01-01', -1000, 'EUR',
            'Fake Landlord GmbH', 'rent', NULL, NULL, NULL, 'raw', 'fp1', 1
        )
        """
    )
    conn.commit()
    conn.close()


def test_startup_reapplies_the_stored_taxonomy(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path, FAKE_TOML)
    _insert_uncategorized_row(db_path)

    with TestClient(create_app(db_path)):
        pass

    conn = sqlite3.connect(db_path)
    (category,) = conn.execute(
        "SELECT category FROM transactions WHERE fingerprint = 'fp1'"
    ).fetchone()
    conn.close()
    assert category == "Rent"


def test_reapply_categorizes_a_row_after_a_rule_is_added_through_the_store(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)  # generic seed, no rules: the row stays uncategorized until added below
    _insert_uncategorized_row(db_path)

    with TestClient(create_app(db_path)) as client:
        conn = sqlite3.connect(db_path)
        try:
            category_id = add_category(conn, "Rent", "fixed")
            add_rule(conn, {"category": "Rent", "counterparty": "Fake Landlord"})
        finally:
            conn.close()
        assert category_id > 0

        response = client.post("/reapply")

    assert response.status_code == 200
    conn = sqlite3.connect(db_path)
    (category,) = conn.execute(
        "SELECT category FROM transactions WHERE fingerprint = 'fp1'"
    ).fetchone()
    conn.close()
    assert category == "Rent"


def test_index_shows_uncategorized_count_and_link(tmp_path):
    db_path = tmp_path / "t.db"
    # An empty taxonomy: no rule matches, so the seeded row stays uncategorized.
    seed(db_path)
    _insert_uncategorized_row(db_path)

    with TestClient(create_app(db_path)) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert 'href="/uncategorized"' in response.text
    assert ">1<" in response.text
