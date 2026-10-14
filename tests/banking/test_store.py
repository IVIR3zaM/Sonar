"""Tests for banking/store.py: the one connection and the pending authorization state."""

import sqlite3
from datetime import UTC, datetime

from sonar.banking.consent import NewConnection
from sonar.banking.store import (
    load_connection,
    save_connection,
    save_pending_state,
    take_pending_state,
)
from sonar.db import MIGRATIONS_DIR, apply_migrations

NOW = datetime(2026, 10, 14, 8, 0, tzinfo=UTC)
ENDS = datetime(2027, 4, 12, 7, 50, tzinfo=UTC)


def _connect_migrated() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    return conn


def _new(session_id: str = "session-1", uid: str = "uid-1", last4: str = "1234"):
    return NewConnection(session_id, uid, last4, ENDS, NOW)


def test_no_connection_loads_as_none():
    assert load_connection(_connect_migrated()) is None


def test_save_then_load_round_trips():
    conn = _connect_migrated()
    save_connection(conn, _new())
    loaded = load_connection(conn)
    assert (loaded.session_id, loaded.account_uid, loaded.iban_last4) == (
        "session-1",
        "uid-1",
        "1234",
    )
    assert loaded.consent_valid_until == ENDS
    assert loaded.connected_at == NOW
    assert loaded.last_sync_at is None
    assert loaded.last_sync_status is None


def test_second_save_replaces_session_fields_and_keeps_last_sync_fields():
    conn = _connect_migrated()
    save_connection(conn, _new())
    conn.execute(
        "UPDATE bank_connection SET last_sync_at = ?, last_sync_status = 'ok', "
        "last_sync_added = 7, last_sync_error = NULL",
        ("2026-10-15T04:30:00+00:00",),
    )
    save_connection(conn, _new("session-2", "uid-2", "5678"))
    loaded = load_connection(conn)
    assert (loaded.session_id, loaded.account_uid, loaded.iban_last4) == (
        "session-2",
        "uid-2",
        "5678",
    )
    assert loaded.last_sync_at == datetime(2026, 10, 15, 4, 30, tzinfo=UTC)
    assert (loaded.last_sync_status, loaded.last_sync_added) == ("ok", 7)
    assert conn.execute("SELECT COUNT(*) FROM bank_connection").fetchone() == (1,)


def test_take_pending_state_returns_the_saved_hash_once():
    conn = _connect_migrated()
    save_pending_state(conn, "hash-1", NOW)
    assert take_pending_state(conn) == ("hash-1", NOW)
    assert take_pending_state(conn) is None


def test_new_pending_state_replaces_the_old_one():
    conn = _connect_migrated()
    save_pending_state(conn, "hash-1", NOW)
    save_pending_state(conn, "hash-2", NOW)
    assert take_pending_state(conn) == ("hash-2", NOW)
    assert take_pending_state(conn) is None
