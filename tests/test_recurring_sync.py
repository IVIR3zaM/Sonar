"""Tests for sync_detected (SPEC §6): my edits and dismissals always win."""

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from sonar.db import apply_migrations
from sonar.recurring import add_manual, dismiss, edit_payment, list_payments, sync_detected
from sonar.schedule import SchedulePeriod

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "sonar" / "migrations"

FITNESS_TYPES = {"Fitness": "fixed"}
VARIABLE_TYPES = {"Fitness": "variable"}


@pytest.fixture
def conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    return conn


def _insert(
    conn: sqlite3.Connection,
    *,
    fingerprint: str,
    booking_date: str,
    counterparty: str = "Gym Inc",
    category: str | None = "Fitness",
    amount_cents: int = -1000,
) -> None:
    """Insert one transaction row directly by SQL (sync_detected reads stored rows)."""
    conn.execute(
        """
        INSERT INTO transactions (
            source, account, booking_date, value_date, amount_cents, currency,
            counterparty, purpose, iban, mandate_ref, creditor_id, raw_row,
            fingerprint, occurrence, category
        ) VALUES (
            'test', 'acc', ?, ?, ?, 'EUR',
            ?, '', NULL, NULL, NULL, 'raw', ?, 1, ?
        )
        """,
        (booking_date, booking_date, amount_cents, counterparty, fingerprint, category),
    )


def _seed_monthly_series(conn: sqlite3.Connection) -> None:
    for i, booking_date in enumerate(["2026-07-01", "2026-08-01", "2026-09-01"]):
        _insert(conn, fingerprint=f"m{i}", booking_date=booking_date)


def test_sync_inserts_new_payment_and_second_sync_changes_nothing(
    conn: sqlite3.Connection,
) -> None:
    _seed_monthly_series(conn)

    changed = sync_detected(conn, FITNESS_TYPES, date(2026, 9, 23))
    assert changed == 1
    [payment] = list_payments(conn)
    assert payment.name == "Gym Inc"
    assert payment.source == "detected"
    assert payment.last_paid_date == date(2026, 9, 1)

    assert sync_detected(conn, FITNESS_TYPES, date(2026, 9, 23)) == 0


def test_dismissed_payment_stays_dismissed_after_resync(conn: sqlite3.Connection) -> None:
    _seed_monthly_series(conn)
    sync_detected(conn, FITNESS_TYPES, date(2026, 9, 23))
    [payment] = list_payments(conn, include_dismissed=True)
    dismiss(conn, payment.id)

    _insert(conn, fingerprint="m3", booking_date="2026-10-01")  # newer payment
    sync_detected(conn, FITNESS_TYPES, date(2026, 10, 23))

    [still_dismissed] = list_payments(conn, include_dismissed=True)
    assert still_dismissed.status == "dismissed"


def test_edited_payment_keeps_edits_but_last_paid_updates(conn: sqlite3.Connection) -> None:
    _seed_monthly_series(conn)
    sync_detected(conn, FITNESS_TYPES, date(2026, 9, 23))
    [payment] = list_payments(conn)
    edit_payment(conn, payment.id, "Gym Plus", 2000, 1, 1)

    _insert(conn, fingerprint="m3", booking_date="2026-10-01", amount_cents=-1500)
    sync_detected(conn, FITNESS_TYPES, date(2026, 10, 23))

    [updated] = list_payments(conn)
    assert updated.name == "Gym Plus"
    assert updated.periods[0].amount_cents == 2000
    assert updated.last_paid_date == date(2026, 10, 1)


def test_unlocked_series_recategorized_as_variable_is_deleted(conn: sqlite3.Connection) -> None:
    _seed_monthly_series(conn)
    sync_detected(conn, FITNESS_TYPES, date(2026, 9, 23))
    assert list_payments(conn) != []

    changed = sync_detected(conn, VARIABLE_TYPES, date(2026, 9, 23))

    assert changed == 1
    assert list_payments(conn) == []


def test_new_amount_and_display_name_update_an_unedited_row(conn: sqlite3.Connection) -> None:
    """A later debit with a new amount/display name/category refreshes the row.

    Only the display text and category change here (fake strings); normalize_text
    still maps "GYM INC" to the same key as "Gym Inc", so this is the same series,
    not a new one (covers recurring.py:219-220, the schedule-changed branch).
    """
    _seed_monthly_series(conn)
    assert sync_detected(conn, FITNESS_TYPES, date(2026, 9, 23)) == 1

    _insert(
        conn,
        fingerprint="m3",
        booking_date="2026-10-01",
        counterparty="GYM INC",
        category="Fitness Plus",
        amount_cents=-1200,
    )
    types = {"Fitness": "fixed", "Fitness Plus": "fixed"}
    changed = sync_detected(conn, types, date(2026, 10, 23))

    assert changed >= 1
    [payment] = list_payments(conn)
    assert payment.periods[0].amount_cents == 1200
    assert payment.name == "GYM INC"
    assert payment.category == "Fitness Plus"
    assert payment.last_paid_date == date(2026, 10, 1)


def test_dismissed_and_edited_rows_survive_recategorization(conn: sqlite3.Connection) -> None:
    """Dismissed/edited rows are kept (not deleted, not duplicated) across re-detection."""
    _seed_monthly_series(conn)  # "Gym Inc", to be dismissed
    for i, booking_date in enumerate(["2026-07-05", "2026-08-05", "2026-09-05"]):
        _insert(conn, fingerprint=f"y{i}", booking_date=booking_date, counterparty="Yoga Studio")

    sync_detected(conn, FITNESS_TYPES, date(2026, 9, 23))
    by_name = {p.name: p for p in list_payments(conn)}
    gym_key = by_name["Gym Inc"].detection_key
    dismiss(conn, by_name["Gym Inc"].id)
    edit_payment(conn, by_name["Yoga Studio"].id, "Yoga Plus", 3000, 1, 5)

    # Recategorize both series as `variable` -> detection no longer sees either key.
    sync_detected(conn, {"Fitness": "variable"}, date(2026, 9, 23))
    by_name = {p.name: p for p in list_payments(conn, include_dismissed=True)}
    assert by_name["Gym Inc"].status == "dismissed"
    assert by_name["Yoga Plus"].name == "Yoga Plus"

    # Switch back to `fixed` and re-sync -> both keys are detected again.
    sync_detected(conn, FITNESS_TYPES, date(2026, 9, 23))

    active_names = [p.name for p in list_payments(conn)]
    assert "Gym Inc" not in active_names
    assert "Yoga Plus" in active_names
    [row_count] = conn.execute(
        "SELECT COUNT(*) FROM recurring_payments WHERE detection_key = ?", (gym_key,)
    ).fetchone()
    assert row_count == 1


def test_manual_row_is_never_touched(conn: sqlite3.Connection) -> None:
    period = SchedulePeriod(
        starts_on=date(2026, 1, 1), until=None, amount_cents=500, interval_months=1, day=1
    )
    manual_id = add_manual(conn, "Streaming", "Subscriptions", period)
    _seed_monthly_series(conn)

    sync_detected(conn, FITNESS_TYPES, date(2026, 9, 23))

    [manual] = [p for p in list_payments(conn) if p.id == manual_id]
    assert manual.name == "Streaming"
    assert manual.source == "manual"
