"""Tests for debt_overview (SPEC §7): status plus the recurring-payment link.

A debt links to a recurring payment through the same detection key that
detect.py would have grouped the matching transactions under, so a
dashboard forecast (M5) can skip a fixed payment that is already counted as a
debt instead of counting it twice.
"""

import sqlite3
from datetime import date

import pytest

from sonar.db import MIGRATIONS_DIR, apply_migrations
from sonar.debts.model import Installment, InstallmentStatus, Loan, LoanStatus, MatchRule
from sonar.debts.store import add_debt, debt_overview
from sonar.recurring.schedule import SchedulePeriod
from sonar.recurring.store import add_manual


@pytest.fixture
def conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    return conn


def _insert_tx(
    conn: sqlite3.Connection,
    *,
    fingerprint: str,
    booking_date: str,
    counterparty: str = "",
    purpose: str = "",
    mandate_ref: str | None = None,
    creditor_id: str | None = None,
    amount_cents: int = -10_000,
) -> None:
    """Seed one transaction row directly by SQL (debt_overview reads stored rows)."""
    conn.execute(
        """
        INSERT INTO transactions (
            source, account, booking_date, value_date, amount_cents, currency,
            counterparty, purpose, iban, mandate_ref, creditor_id, raw_row,
            fingerprint, occurrence, category
        ) VALUES (
            'test', 'acc', ?, ?, ?, 'EUR',
            ?, ?, NULL, ?, ?, 'raw', ?, 1, NULL
        )
        """,
        (
            booking_date,
            booking_date,
            amount_cents,
            counterparty,
            purpose,
            mandate_ref,
            creditor_id,
            fingerprint,
        ),
    )


def _insert_recurring(
    conn: sqlite3.Connection,
    *,
    detection_key: str,
    name: str,
    status: str = "active",
) -> None:
    """Seed one detected recurring payment directly by SQL, with one period."""
    cursor = conn.execute(
        """
        INSERT INTO recurring_payments (
            detection_key, name, category, status, source, last_paid_date
        ) VALUES (?, ?, NULL, ?, 'detected', '2026-09-01')
        """,
        (detection_key, name, status),
    )
    conn.execute(
        """
        INSERT INTO schedule_periods (
            payment_id, starts_on, until, amount_cents, interval_months, day
        ) VALUES (?, '2026-01-01', NULL, 10000, 1, 1)
        """,
        (cursor.lastrowid,),
    )


def _installment(name: str = "Sofa", counterparty: str = "Furniture Store") -> Installment:
    return Installment(
        name=name,
        total_cents=120_000,
        rate_cents=10_000,
        interval_months=1,
        first_payment_date=date(2026, 1, 5),
        payments_count=12,
        match=MatchRule("counterparty", counterparty),
    )


def _loan(name: str = "Car loan", mandate: str = "M-1") -> Loan:
    return Loan(
        name=name,
        balance_cents=500_000,
        balance_as_of=date(2026, 6, 30),
        rate_cents=100_000,
        interest_bp=None,
        match=MatchRule("mandate", mandate),
    )


TODAY = date(2026, 9, 23)


def test_installment_matched_by_counterparty_shows_paid_status(conn: sqlite3.Connection) -> None:
    for i, booking_date in enumerate(["2026-01-05", "2026-02-05", "2026-03-05"]):
        _insert_tx(
            conn, fingerprint=f"f{i}", booking_date=booking_date, counterparty="Furniture Store"
        )
    add_debt(conn, _installment())

    [view] = debt_overview(conn, TODAY)

    assert isinstance(view.status, InstallmentStatus)
    assert view.status.paid_cents == 30_000


def test_loan_shows_projected_balance_for_the_pinned_today(conn: sqlite3.Connection) -> None:
    add_debt(conn, _loan())

    [view] = debt_overview(conn, TODAY)

    assert isinstance(view.status, LoanStatus)
    assert view.status.projected_balance_cents == 300_000
    assert view.status.payoff_date == date(2026, 11, 30)


def test_detected_payment_with_matching_key_is_linked(conn: sqlite3.Connection) -> None:
    # payment_key for a mandate ref with no creditor_id is "mandate:/<ref>".
    _insert_tx(conn, fingerprint="m1", booking_date="2026-07-30", mandate_ref="M-1")
    _insert_recurring(conn, detection_key="mandate:/M-1", name="Car Loan Payment")
    add_debt(conn, _loan())

    [view] = debt_overview(conn, TODAY)

    assert [p.name for p in view.linked_payments] == ["Car Loan Payment"]


def test_payment_kept_under_the_unsplit_key_stays_linked(conn: sqlite3.Connection) -> None:
    # The mandate also carries purchases, one on a monthly debit's day, so detection
    # splits the group into "#1", "#2"; a payment kept under the bare key must still link.
    for i, booking_date in enumerate(["2026-06-05", "2026-07-05", "2026-08-05"]):
        _insert_tx(conn, fingerprint=f"d{i}", booking_date=booking_date, mandate_ref="M-1")
    _insert_tx(
        conn, fingerprint="p1", booking_date="2026-07-05", mandate_ref="M-1", amount_cents=-2_500
    )
    _insert_tx(
        conn, fingerprint="p2", booking_date="2026-07-20", mandate_ref="M-1", amount_cents=-4_000
    )
    _insert_recurring(conn, detection_key="mandate:/M-1", name="Car Loan Payment")
    add_debt(conn, _loan())

    [view] = debt_overview(conn, TODAY)

    assert [p.name for p in view.linked_payments] == ["Car Loan Payment"]


def test_dismissed_payment_with_matching_key_is_not_linked(conn: sqlite3.Connection) -> None:
    _insert_tx(conn, fingerprint="m1", booking_date="2026-07-30", mandate_ref="M-1")
    _insert_recurring(
        conn, detection_key="mandate:/M-1", name="Car Loan Payment", status="dismissed"
    )
    add_debt(conn, _loan())

    [view] = debt_overview(conn, TODAY)

    assert view.linked_payments == ()


def test_manual_recurring_payment_is_never_linked(conn: sqlite3.Connection) -> None:
    _insert_tx(conn, fingerprint="m1", booking_date="2026-07-30", mandate_ref="M-1")
    period = SchedulePeriod(
        starts_on=date(2026, 1, 1), until=None, amount_cents=10_000, interval_months=1, day=1
    )
    add_manual(conn, "Streaming", "Subscriptions", period)
    add_debt(conn, _loan())

    [view] = debt_overview(conn, TODAY)

    assert view.linked_payments == ()


def test_debt_with_no_matching_transactions_has_empty_links_and_zero_paid(
    conn: sqlite3.Connection,
) -> None:
    _insert_tx(conn, fingerprint="other", booking_date="2026-01-05", counterparty="Other Shop")
    add_debt(conn, _installment())

    [view] = debt_overview(conn, TODAY)

    assert view.status.paid_cents == 0
    assert view.linked_payments == ()


def test_purpose_debt_counts_only_its_debit_and_skips_the_shared_key(
    conn: sqlite3.Connection,
) -> None:
    _insert_tx(
        conn, fingerprint="a", booking_date="2026-07-30", mandate_ref="M-1", purpose="Rate 111"
    )
    _insert_tx(
        conn, fingerprint="b", booking_date="2026-07-30", mandate_ref="M-1", purpose="Rate 222"
    )
    _insert_recurring(conn, detection_key="mandate:/M-1", name="Shared Mandate")
    debt = Installment(
        name="Order 111",
        total_cents=120_000,
        rate_cents=10_000,
        interval_months=1,
        first_payment_date=date(2026, 1, 5),
        payments_count=12,
        match=MatchRule("purpose", "Rate 111"),
    )
    add_debt(conn, debt)

    [view] = debt_overview(conn, TODAY)

    assert view.status.paid_cents == 10_000
    assert view.linked_payments == ()
