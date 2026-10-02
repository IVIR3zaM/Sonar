"""Tests for the allow-list store (SPEC §13 Access list)."""

import sqlite3
from datetime import UTC, datetime

import pytest

from sonar.auth.store import allow_email, is_allowed, list_emails, revoke_email, sync_emails
from sonar.db import MIGRATIONS_DIR, apply_migrations

NOW = datetime(2026, 1, 1, tzinfo=UTC)
LATER = datetime(2026, 2, 1, tzinfo=UTC)


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    apply_migrations(connection, MIGRATIONS_DIR)
    return connection


def test_allow_stores_the_normalized_form(conn):
    allow_email(conn, "  Owner@Example.COM ", NOW)

    assert list_emails(conn) == ["owner@example.com"]


def test_allow_is_idempotent(conn):
    allow_email(conn, "owner@example.com", NOW)
    allow_email(conn, "OWNER@example.com", LATER)

    assert list_emails(conn) == ["owner@example.com"]
    (added_at,) = conn.execute("SELECT added_at FROM allowed_emails").fetchone()
    assert added_at == NOW.isoformat()


def test_allow_rejects_an_invalid_email(conn):
    with pytest.raises(ValueError):
        allow_email(conn, "nobody", NOW)

    assert list_emails(conn) == []


def test_revoke_returns_true_then_false(conn):
    allow_email(conn, "owner@example.com", NOW)

    assert revoke_email(conn, " Owner@example.com") is True
    assert revoke_email(conn, "owner@example.com") is False
    assert list_emails(conn) == []


def test_list_is_sorted(conn):
    for email in ("b@example.com", "c@example.com", "a@example.com"):
        allow_email(conn, email, NOW)

    assert list_emails(conn) == ["a@example.com", "b@example.com", "c@example.com"]


def test_sync_replaces_the_set_and_keeps_listed_ones(conn):
    allow_email(conn, "keep@example.com", NOW)
    allow_email(conn, "drop@example.com", NOW)

    sync_emails(conn, ["Keep@example.com", "new@example.com"], LATER)

    assert list_emails(conn) == ["keep@example.com", "new@example.com"]
    added = dict(conn.execute("SELECT email, added_at FROM allowed_emails"))
    assert added["keep@example.com"] == NOW.isoformat()
    assert added["new@example.com"] == LATER.isoformat()


def test_sync_rejects_an_empty_list_without_changing_the_table(conn):
    allow_email(conn, "keep@example.com", NOW)

    with pytest.raises(ValueError):
        sync_emails(conn, [], LATER)

    assert list_emails(conn) == ["keep@example.com"]


def test_sync_rejects_an_invalid_email_without_changing_the_table(conn):
    allow_email(conn, "keep@example.com", NOW)

    with pytest.raises(ValueError):
        sync_emails(conn, ["new@example.com", "a@b@example.com"], LATER)

    assert list_emails(conn) == ["keep@example.com"]


def test_is_allowed_matches_case_insensitively(conn):
    allow_email(conn, "owner@example.com", NOW)

    assert is_allowed(conn, "Owner@Example.com ") is True
    assert is_allowed(conn, "other@example.com") is False
    assert is_allowed(conn, "not an email") is False
