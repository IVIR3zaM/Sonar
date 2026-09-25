"""Tests for the `sonar import-categories` CLI (SPEC §5)."""

import sqlite3
from pathlib import Path

import pytest

from sonar.__main__ import import_categories, main
from sonar.db import apply_migrations
from tests.seed import MIGRATIONS_DIR

FAKE_TOML = """
[[category]]
name = "Rent"
type = "fixed"

[[rule]]
category = "Rent"
counterparty = "Fake Landlord"
"""

UNKNOWN_RULE_CATEGORY_TOML = """
[[category]]
name = "Rent"
type = "fixed"

[[rule]]
category = "Nonexistent"
counterparty = "Fake Landlord"
"""


def _insert_uncategorized_row(db_path) -> None:
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


def _stored_taxonomy(db_path) -> tuple[dict, int]:
    conn = sqlite3.connect(db_path)
    try:
        categories = dict(conn.execute("SELECT name, type FROM categories").fetchall())
        (rule_count,) = conn.execute("SELECT COUNT(*) FROM category_rules").fetchone()
        return categories, rule_count
    finally:
        conn.close()


def test_import_categories_replaces_seed_and_categorizes_a_row(tmp_path, capsys):
    db_path = tmp_path / "t.db"
    toml_path = tmp_path / "categories.toml"
    toml_path.write_text(FAKE_TOML, encoding="utf-8")
    _insert_uncategorized_row(db_path)

    import_categories(toml_path, db_path)

    categories, rule_count = _stored_taxonomy(db_path)
    assert categories == {"Rent": "fixed"}
    assert rule_count == 1
    conn = sqlite3.connect(db_path)
    (category,) = conn.execute(
        "SELECT category FROM transactions WHERE fingerprint = 'fp1'"
    ).fetchone()
    conn.close()
    assert category == "Rent"

    printed = capsys.readouterr().out
    assert "1 categor" in printed and "1 rule" in printed and "0 uncategorized" in printed


def test_import_categories_is_idempotent(tmp_path):
    db_path = tmp_path / "t.db"
    toml_path = tmp_path / "categories.toml"
    toml_path.write_text(FAKE_TOML, encoding="utf-8")
    _insert_uncategorized_row(db_path)

    import_categories(toml_path, db_path)
    first = _stored_taxonomy(db_path)
    import_categories(toml_path, db_path)
    second = _stored_taxonomy(db_path)

    assert first == second


def test_missing_file_exits_1_and_leaves_the_db_unchanged(tmp_path):
    db_path = tmp_path / "t.db"
    apply_migrations(sqlite3.connect(db_path), MIGRATIONS_DIR)
    before = _stored_taxonomy(db_path)

    with pytest.raises(SystemExit) as excinfo:
        import_categories(tmp_path / "nope.toml", db_path)

    assert excinfo.value.code == 1
    assert _stored_taxonomy(db_path) == before


def test_unknown_rule_category_exits_1_and_leaves_the_seed_intact(tmp_path):
    db_path = tmp_path / "t.db"
    apply_migrations(sqlite3.connect(db_path), MIGRATIONS_DIR)
    before = _stored_taxonomy(db_path)
    toml_path = tmp_path / "categories.toml"
    toml_path.write_text(UNKNOWN_RULE_CATEGORY_TOML, encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        import_categories(toml_path, db_path)

    assert excinfo.value.code == 1
    assert _stored_taxonomy(db_path) == before


def test_main_dispatches_import_categories_from_argv(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "sonar.__main__.import_categories", lambda path, db: calls.append((path, db))
    )
    monkeypatch.setattr(
        "sys.argv", ["sonar", "import-categories", "cats.toml", "--db", "data/x.db"]
    )

    main()

    assert calls == [(Path("cats.toml"), Path("data/x.db"))]
