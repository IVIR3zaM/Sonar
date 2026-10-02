"""Tests for migration 0009: debt_drafts (SPEC §13 Draft debts)."""

import sqlite3

import pytest

from sonar.db import MIGRATIONS_DIR, apply_migrations


@pytest.fixture
def conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    return conn


def test_table_has_exactly_the_three_columns(conn):
    columns = [row[1] for row in conn.execute("PRAGMA table_info(debt_drafts)")]

    assert columns == ["id", "detection_key", "status"]


def test_status_defaults_to_open(conn):
    conn.execute("INSERT INTO debt_drafts (detection_key) VALUES ('mandate:/M-1')")

    assert conn.execute("SELECT status FROM debt_drafts").fetchone() == ("open",)


def test_duplicate_detection_key_is_rejected(conn):
    conn.execute("INSERT INTO debt_drafts (detection_key) VALUES ('mandate:/M-1')")

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO debt_drafts (detection_key, status) VALUES ('mandate:/M-1', 'completed')"
        )


def test_missing_detection_key_is_rejected(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO debt_drafts (detection_key) VALUES (NULL)")


def test_status_outside_open_and_completed_is_rejected(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO debt_drafts (detection_key, status) VALUES ('mandate:/M-1', 'dismissed')"
        )
