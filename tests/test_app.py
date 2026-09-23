"""Tests for the FastAPI app factory."""

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from sonar.app import MIGRATIONS_DIR, create_app
from sonar.db import apply_migrations

# Never the shipped src/sonar/categories.toml: tests write their own tmp
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


def test_startup_reapplies_rules_from_categories_path(tmp_path):
    db_path = tmp_path / "t.db"
    categories_path = tmp_path / "categories.toml"
    categories_path.write_text(FAKE_TOML, encoding="utf-8")
    _insert_uncategorized_row(db_path)

    with TestClient(create_app(db_path, categories_path=categories_path)):
        pass

    conn = sqlite3.connect(db_path)
    (category,) = conn.execute(
        "SELECT category FROM transactions WHERE fingerprint = 'fp1'"
    ).fetchone()
    conn.close()
    assert category == "Rent"


def test_index_shows_uncategorized_count_and_link(tmp_path):
    db_path = tmp_path / "t.db"
    # An empty taxonomy: no rule matches, so the seeded row stays uncategorized.
    categories_path = tmp_path / "categories.toml"
    categories_path.write_text("", encoding="utf-8")
    _insert_uncategorized_row(db_path)

    with TestClient(create_app(db_path, categories_path=categories_path)) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert 'href="/uncategorized"' in response.text
    assert ">1<" in response.text
