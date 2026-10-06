"""Tests for the recurring-payments DB shell (SPEC §6): storage and corrections."""

import sqlite3
from datetime import date

import pytest

from sonar.db import MIGRATIONS_DIR, apply_migrations
from sonar.recurring.schedule import SchedulePeriod, occurrences
from sonar.recurring.store import (
    NotDismissed,
    PaymentNotFound,
    add_manual,
    dismiss,
    edit_payment,
    list_payments,
    pause_payment,
    restore,
    resume_payment,
)


@pytest.fixture
def conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    return conn


def test_water_example_end_to_end(conn: sqlite3.Connection) -> None:
    """SPEC §6 water example, driven through the DB shell instead of schedule.py directly."""
    period = SchedulePeriod(
        starts_on=date(2025, 11, 15),
        until=None,
        amount_cents=24000,
        interval_months=2,
        day=15,
    )
    payment_id = add_manual(conn, "Water", "Utilities", period)

    pause_payment(conn, payment_id, date(2026, 11, 30))
    resume_payment(conn, payment_id, date(2027, 2, 1), 26000, 2, day=15)

    [payment] = list_payments(conn)
    assert payment.id == payment_id
    assert payment.name == "Water"
    assert payment.source == "manual"
    assert payment.name_locked is True
    assert payment.schedule_locked is True

    found = occurrences(payment.periods, date(2026, 9, 1), date(2027, 5, 31))
    due_dates = [o.due_date for o in found]
    assert due_dates == [
        date(2026, 9, 15),
        date(2026, 11, 15),
        date(2027, 2, 15),
        date(2027, 4, 15),
    ]
    assert [o.amount_cents for o in found] == [24000, 24000, 26000, 26000]
    assert all(d.month not in (12, 1) for d in due_dates)


def test_edit_payment_sets_only_the_matching_lock(conn: sqlite3.Connection) -> None:
    period = SchedulePeriod(
        starts_on=date(2026, 1, 1), until=None, amount_cents=1000, interval_months=1, day=1
    )
    payment_id = add_manual(conn, "Gym", "Fitness", period)

    # add_manual already locks both, so use SQL to start from an unlocked, detected-style row.
    conn.execute(
        "UPDATE recurring_payments SET name_locked = 0, schedule_locked = 0 WHERE id = ?",
        (payment_id,),
    )

    edit_payment(conn, payment_id, "Gym", 1000, 1, 1)  # nothing actually changes
    [unchanged] = list_payments(conn)
    assert unchanged.name_locked is False
    assert unchanged.schedule_locked is False

    edit_payment(conn, payment_id, "Fitness Studio", 1000, 1, 1)  # name only
    [name_edited] = list_payments(conn)
    assert name_edited.name == "Fitness Studio"
    assert name_edited.name_locked is True
    assert name_edited.schedule_locked is False

    edit_payment(conn, payment_id, "Fitness Studio", 1500, 1, 1)  # amount only
    [schedule_edited] = list_payments(conn)
    assert schedule_edited.name_locked is True
    assert schedule_edited.schedule_locked is True
    assert schedule_edited.periods[0].amount_cents == 1500


def _table_counts(conn: sqlite3.Connection) -> tuple[int, int]:
    payments = conn.execute("SELECT COUNT(*) FROM recurring_payments").fetchone()[0]
    periods = conn.execute("SELECT COUNT(*) FROM schedule_periods").fetchone()[0]
    return payments, periods


def test_unknown_id_raises_payment_not_found_without_writing(conn: sqlite3.Connection) -> None:
    """store.py:79 used to crash on fetchone() None instead of raising a clear error."""
    before = _table_counts(conn)

    with pytest.raises(PaymentNotFound):
        edit_payment(conn, 999, "Name", 1000, 1, 1)
    with pytest.raises(PaymentNotFound):
        dismiss(conn, 999)
    with pytest.raises(PaymentNotFound):
        pause_payment(conn, 999, date(2026, 1, 1))
    with pytest.raises(PaymentNotFound):
        resume_payment(conn, 999, date(2026, 2, 1), 1000, 1, 1)

    assert _table_counts(conn) == before


def test_dismissed_payment_hidden_unless_included(conn: sqlite3.Connection) -> None:
    period = SchedulePeriod(
        starts_on=date(2026, 1, 1), until=None, amount_cents=500, interval_months=1, day=1
    )
    payment_id = add_manual(conn, "Streaming", "Subscriptions", period)

    dismiss(conn, payment_id)

    assert list_payments(conn) == []
    [dismissed] = list_payments(conn, include_dismissed=True)
    assert dismissed.status == "dismissed"
    assert dismissed.id == payment_id


def test_restore_makes_a_dismissed_payment_active_and_listed_again(
    conn: sqlite3.Connection,
) -> None:
    period = SchedulePeriod(
        starts_on=date(2026, 1, 1), until=None, amount_cents=500, interval_months=1, day=1
    )
    payment_id = add_manual(conn, "Streaming", None, period)
    dismiss(conn, payment_id)

    restore(conn, payment_id)

    assert [p.id for p in list_payments(conn)] == [payment_id]


def test_restore_raises_not_dismissed_for_an_active_payment(conn: sqlite3.Connection) -> None:
    period = SchedulePeriod(
        starts_on=date(2026, 1, 1), until=None, amount_cents=500, interval_months=1, day=1
    )
    payment_id = add_manual(conn, "Streaming", None, period)

    with pytest.raises(NotDismissed):
        restore(conn, payment_id)


def test_restore_unknown_id_raises_payment_not_found(conn: sqlite3.Connection) -> None:
    with pytest.raises(PaymentNotFound):
        restore(conn, 999)
