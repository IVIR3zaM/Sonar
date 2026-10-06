"""Tests for a recurring payment's free-text description (SPEC §6)."""

import sqlite3
from datetime import date

import pytest

from sonar.db import MIGRATIONS_DIR, apply_migrations
from sonar.recurring.schedule import SchedulePeriod
from sonar.recurring.store import (
    PaymentNotFound,
    add_manual,
    edit_payment,
    get_payment,
    list_payments,
    sync_detected,
    update_details,
)

FITNESS_TYPES = {"Fitness": "fixed"}
PERIOD = SchedulePeriod(
    starts_on=date(2026, 1, 1), until=None, amount_cents=1000, interval_months=1, day=1
)


@pytest.fixture
def conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    return conn


def _unlock(conn: sqlite3.Connection, payment_id: int) -> None:
    conn.execute(
        "UPDATE recurring_payments SET name_locked = 0, schedule_locked = 0 WHERE id = ?",
        (payment_id,),
    )


def _insert(conn: sqlite3.Connection, fingerprint: str, booking_date: str) -> None:
    conn.execute(
        """
        INSERT INTO transactions (
            source, account, booking_date, value_date, amount_cents, currency,
            counterparty, purpose, iban, mandate_ref, creditor_id, raw_row,
            fingerprint, occurrence, category
        ) VALUES (
            'test', 'acc', ?, ?, -1000, 'EUR',
            'Gym Inc', '', NULL, NULL, NULL, 'raw', ?, 1, 'Fitness'
        )
        """,
        (booking_date, booking_date, fingerprint),
    )


def _seed_series(conn: sqlite3.Connection) -> None:
    for i, booking_date in enumerate(["2026-07-01", "2026-08-01", "2026-09-01"]):
        _insert(conn, f"m{i}", booking_date)


def test_update_details_sets_description_without_locking_or_touching_periods(
    conn: sqlite3.Connection,
) -> None:
    payment_id = add_manual(conn, "Gym", "Fitness", PERIOD)
    _unlock(conn, payment_id)

    update_details(conn, payment_id, "Gym", "Pays the main studio")

    payment = get_payment(conn, payment_id)
    assert payment.description == "Pays the main studio"
    assert payment.name_locked is False
    assert payment.periods == (PERIOD,)


def test_update_details_locks_the_name_only_when_it_changes(conn: sqlite3.Connection) -> None:
    payment_id = add_manual(conn, "Gym", "Fitness", PERIOD)
    _unlock(conn, payment_id)

    update_details(conn, payment_id, "Fitness Studio", None)

    payment = get_payment(conn, payment_id)
    assert payment.name == "Fitness Studio"
    assert payment.name_locked is True
    assert payment.periods == (PERIOD,)


def test_update_details_unknown_id_raises(conn: sqlite3.Connection) -> None:
    with pytest.raises(PaymentNotFound):
        update_details(conn, 999, "Name", "Text")


def test_get_payment_returns_the_payment_or_raises(conn: sqlite3.Connection) -> None:
    payment_id = add_manual(conn, "Gym", "Fitness", PERIOD)

    assert get_payment(conn, payment_id).name == "Gym"
    with pytest.raises(PaymentNotFound):
        get_payment(conn, 999)


def test_add_manual_stores_a_stripped_description_and_blank_becomes_null(
    conn: sqlite3.Connection,
) -> None:
    with_text = add_manual(conn, "Gym", None, PERIOD, "  Monthly fee  ")
    blank = add_manual(conn, "Water", None, PERIOD, "   ")
    omitted = add_manual(conn, "Power", None, PERIOD)

    assert get_payment(conn, with_text).description == "Monthly fee"
    assert get_payment(conn, blank).description is None
    assert get_payment(conn, omitted).description is None


def test_edit_payment_stores_and_clears_a_description(conn: sqlite3.Connection) -> None:
    payment_id = add_manual(conn, "Gym", None, PERIOD)
    _unlock(conn, payment_id)

    edit_payment(conn, payment_id, "Gym", 1000, 1, 1, " Studio fee ")
    stored = get_payment(conn, payment_id)
    assert stored.description == "Studio fee"
    assert stored.name_locked is False  # a description change locks nothing
    assert stored.schedule_locked is False

    edit_payment(conn, payment_id, "Gym", 1000, 1, 1, "  ")
    assert get_payment(conn, payment_id).description is None


def test_update_details_blank_description_clears_it(conn: sqlite3.Connection) -> None:
    payment_id = add_manual(conn, "Gym", None, PERIOD, "Old")

    update_details(conn, payment_id, "Gym", "  ")

    assert get_payment(conn, payment_id).description is None


def test_redetection_keeps_a_description(conn: sqlite3.Connection) -> None:
    _seed_series(conn)
    sync_detected(conn, FITNESS_TYPES, date(2026, 9, 23))
    [payment] = list_payments(conn)
    update_details(conn, payment.id, payment.name, "Rent for the studio")
    _unlock(conn, payment.id)

    _insert(conn, "m3", "2026-10-01")
    sync_detected(conn, FITNESS_TYPES, date(2026, 10, 23))

    [after] = list_payments(conn)
    assert after.description == "Rent for the studio"


def test_vanished_row_with_a_description_is_kept_and_without_is_deleted(
    conn: sqlite3.Connection,
) -> None:
    _seed_series(conn)
    sync_detected(conn, FITNESS_TYPES, date(2026, 9, 23))
    [_] = list_payments(conn)

    # Unlocked, active, no description: a vanished row is deleted.
    sync_detected(conn, {"Fitness": "lights_on"}, date(2026, 9, 23))
    assert list_payments(conn) == []

    sync_detected(conn, FITNESS_TYPES, date(2026, 9, 23))
    [again] = list_payments(conn)
    update_details(conn, again.id, again.name, "Keep me")
    assert get_payment(conn, again.id).name_locked is False

    sync_detected(conn, {"Fitness": "lights_on"}, date(2026, 9, 23))
    [kept] = list_payments(conn)
    assert kept.description == "Keep me"
