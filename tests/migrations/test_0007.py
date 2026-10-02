"""Tests for migration 0007: allowed_emails (SPEC §13 Access list)."""

import sqlite3

import pytest

from sonar.db import MIGRATIONS_DIR, apply_migrations


def _connect_migrated() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    return conn


def test_allowed_email_round_trips():
    conn = _connect_migrated()
    conn.execute(
        "INSERT INTO allowed_emails (email, added_at) VALUES (?, ?)",
        ("owner@example.com", "2026-01-01T00:00:00+00:00"),
    )

    assert conn.execute("SELECT email, added_at FROM allowed_emails").fetchall() == [
        ("owner@example.com", "2026-01-01T00:00:00+00:00")
    ]


def test_email_is_the_primary_key():
    conn = _connect_migrated()
    conn.execute("INSERT INTO allowed_emails VALUES ('owner@example.com', 't')")

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO allowed_emails VALUES ('owner@example.com', 't')")


def test_added_at_is_required():
    conn = _connect_migrated()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO allowed_emails (email, added_at) VALUES ('a@example.com', NULL)")


def test_earlier_tables_survive():
    conn = _connect_migrated()

    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    assert {"transactions", "settings", "categories", "allowed_emails"} <= tables
