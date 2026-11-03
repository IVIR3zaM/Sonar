"""Manual payment category updates preserve the rest of the payment."""

import sqlite3
from dataclasses import replace
from datetime import date

import pytest

from sonar.db import MIGRATIONS_DIR, apply_migrations
from sonar.recurring.schedule import SchedulePeriod
from sonar.recurring.store import (
    NotManual,
    PaymentNotFound,
    add_manual,
    get_payment,
    set_category,
)


@pytest.fixture
def conn():
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    yield conn
    conn.close()


@pytest.mark.parametrize("category", ["Subscriptions", None])
def test_set_category_only_changes_category(conn, category):
    period = SchedulePeriod(date(2026, 11, 1), None, 1000, 1, 5)
    payment_id = add_manual(conn, "Magazine", "Reading", period, "Print")
    before = get_payment(conn, payment_id)
    set_category(conn, payment_id, category)
    assert get_payment(conn, payment_id) == replace(before, category=category)


def test_set_category_missing_payment_raises(conn):
    with pytest.raises(PaymentNotFound):
        set_category(conn, 999, "Subscriptions")


def test_set_category_detected_payment_raises_and_changes_nothing(conn):
    period = SchedulePeriod(date(2026, 11, 1), None, 1000, 1, 5)
    payment_id = add_manual(conn, "Magazine", "Reading", period)
    with conn:
        conn.execute(
            "UPDATE recurring_payments SET source = 'detected', detection_key = 'test' "
            "WHERE id = ?",
            (payment_id,),
        )
    before = get_payment(conn, payment_id)
    with pytest.raises(NotManual):
        set_category(conn, payment_id, "Subscriptions")
    assert get_payment(conn, payment_id) == before
