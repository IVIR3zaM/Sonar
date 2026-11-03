"""Card merchants remain separate recurring series through import and sync."""

import sqlite3
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest

from sonar.db import MIGRATIONS_DIR, apply_migrations
from sonar.importing.store import import_file, import_rows
from sonar.recurring.store import edit_payment, list_payments, sync_detected
from sonar.transactions import ParsedTransaction

FIXTURE = Path(__file__).parents[1] / "fixtures" / "db_girokonto_cards.csv"
TODAY = date(2026, 9, 23)


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    with sqlite3.connect(":memory:") as conn:
        apply_migrations(conn, MIGRATIONS_DIR)
        yield conn


def test_import_and_sync_detect_only_the_monthly_card_merchant(conn):
    result = import_file(conn, FIXTURE.read_bytes(), FIXTURE.name)
    assert result.added == 14

    assert sync_detected(conn, {}, TODAY) == 1

    [payment] = list_payments(conn)
    assert payment.status == "active"
    assert payment.source == "detected"
    assert payment.name == "STREAMCO .VIDEO SUBSCR"
    assert payment.detection_key == "card:streamco .video subscr"
    assert payment.periods[-1].interval_months == 1
    assert payment.periods[-1].amount_cents == 1823
    assert payment.last_paid_date == date(2026, 9, 10)


@pytest.mark.parametrize("rename", [False, True])
def test_card_name_and_description_survive_resync(conn, rename):
    import_file(conn, FIXTURE.read_bytes(), FIXTURE.name)
    sync_detected(conn, {}, TODAY)
    [payment] = list_payments(conn)
    if rename:
        edit_payment(conn, payment.id, "Family video", 1823, 1, 10)
    conn.execute(
        "UPDATE recurring_payments SET description = ? WHERE id = ?",
        ("Shared household subscription", payment.id),
    )

    sync_detected(conn, {}, TODAY)

    [updated] = list_payments(conn)
    assert updated.id == payment.id
    assert updated.name == ("Family video" if rename else "STREAMCO .VIDEO SUBSCR")
    assert updated.name_locked == rename
    assert conn.execute(
        "SELECT description FROM recurring_payments WHERE id = ?", (payment.id,)
    ).fetchone() == ("Shared household subscription",)


def test_locked_non_card_series_survives_card_import(conn):
    rows = [
        ParsedTransaction(
            account="fixture-account",
            booking_date=date(2026, month, 1),
            value_date=date(2026, month, 1),
            amount_cents=-2500,
            currency="EUR",
            counterparty="Fictional Fitness",
            purpose="Monthly membership",
            raw_row="synthetic",
        )
        for month in (7, 8, 9)
    ]
    import_rows(conn, "fixture", rows)
    sync_detected(conn, {}, TODAY)
    [existing] = list_payments(conn)
    assert existing.detection_key == "counterparty:fictional fitness"
    edit_payment(conn, existing.id, "My fitness", 2500, 1, 1)

    import_file(conn, FIXTURE.read_bytes(), FIXTURE.name)
    sync_detected(conn, {}, TODAY)

    payments = list_payments(conn)
    assert len(payments) == 2
    updated = next(payment for payment in payments if payment.id == existing.id)
    assert updated.name == "My fitness"
    assert updated.name_locked
    assert updated.detection_key == existing.detection_key
    assert updated.periods == existing.periods
