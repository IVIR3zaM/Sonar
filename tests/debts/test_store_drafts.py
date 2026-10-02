"""Tests for the draft-debt DB shell (SPEC §13 Draft debts): sync and complete."""

import sqlite3
from datetime import date

import pytest

from sonar.categorization.store import list_categories, update_category
from sonar.db import MIGRATIONS_DIR, apply_migrations
from sonar.debts.model import Installment, Loan, MatchRule
from sonar.debts.store import (
    DraftNotFound,
    add_debt,
    complete_draft,
    debt_overview,
    delete_debt,
    list_debts,
    sync_drafts,
)
from sonar.recurring.store import dismiss

LOANS = "Loans & Installments"
CAR_KEY = "mandate:/M-1"
SOFA_KEY = "counterparty:furniture store"
TODAY = date(2026, 9, 23)


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
    counterparty: str,
    mandate_ref: str | None = None,
    category: str | None = LOANS,
) -> None:
    conn.execute(
        """
        INSERT INTO transactions (
            source, account, booking_date, value_date, amount_cents, currency,
            counterparty, purpose, iban, mandate_ref, creditor_id, raw_row,
            fingerprint, occurrence, category
        ) VALUES ('test', 'acc', ?, ?, -10000, 'EUR', ?, '', NULL, ?, NULL, 'raw', ?, 1, ?)
        """,
        (booking_date, booking_date, counterparty, mandate_ref, fingerprint, category),
    )


def _insert_recurring(
    conn: sqlite3.Connection, *, detection_key: str, name: str, category: str | None = LOANS
) -> int:
    payment_id = conn.execute(
        """
        INSERT INTO recurring_payments (
            detection_key, name, category, status, source, last_paid_date
        ) VALUES (?, ?, ?, 'active', 'detected', '2026-03-05')
        """,
        (detection_key, name, category),
    ).lastrowid
    conn.execute(
        """
        INSERT INTO schedule_periods (
            payment_id, starts_on, until, amount_cents, interval_months, day
        ) VALUES (?, '2026-01-05', NULL, 10000, 1, 5)
        """,
        (payment_id,),
    )
    return payment_id


def _seed_car(conn: sqlite3.Connection) -> int:
    for month in (1, 2, 3):
        _insert_tx(
            conn,
            fingerprint=f"car{month}",
            booking_date=f"2026-0{month}-05",
            counterparty="Car Bank",
            mandate_ref="M-1",
        )
    return _insert_recurring(conn, detection_key=CAR_KEY, name="Car Bank")


def _seed_sofa(conn: sqlite3.Connection) -> int:
    for month in (1, 2, 3):
        _insert_tx(
            conn,
            fingerprint=f"sofa{month}",
            booking_date=f"2026-0{month}-10",
            counterparty="Furniture Store",
        )
    return _insert_recurring(conn, detection_key=SOFA_KEY, name="Furniture Store")


def _installment() -> Installment:
    return Installment(
        name="Sofa",
        total_cents=120_000,
        rate_cents=10_000,
        interval_months=1,
        first_payment_date=date(2026, 1, 10),
        payments_count=12,
        match=MatchRule("counterparty", "Furniture Store"),
    )


def _loan() -> Loan:
    return Loan(
        name="Car",
        balance_cents=500_000,
        balance_as_of=date(2026, 6, 30),
        rate_cents=100_000,
        interest_bp=None,
        match=MatchRule("mandate", "M-1"),
    )


def _draft_keys(conn: sqlite3.Connection) -> list[str]:
    return [draft.detection_key for draft in sync_drafts(conn)]


def test_sync_creates_one_draft_per_qualifying_payment_ordered_by_name(conn):
    _seed_sofa(conn)
    _seed_car(conn)

    drafts = sync_drafts(conn)

    assert [d.detection_key for d in drafts] == [CAR_KEY, SOFA_KEY]
    assert drafts[0].prefill.match == MatchRule("mandate", "M-1")
    assert drafts[0].prefill.first_payment_date == date(2026, 1, 5)


def test_second_sync_changes_nothing_and_keeps_the_ids(conn):
    _seed_car(conn)
    _seed_sofa(conn)

    first = sync_drafts(conn)
    second = sync_drafts(conn)

    assert second == first
    assert conn.execute("SELECT COUNT(*) FROM debt_drafts").fetchone() == (2,)


def test_payment_outside_a_debt_category_gets_no_draft(conn):
    _insert_tx(conn, fingerprint="r1", booking_date="2026-01-01", counterparty="Landlord")
    _insert_recurring(conn, detection_key="counterparty:landlord", name="Landlord", category=None)

    assert sync_drafts(conn) == []


def test_payment_without_a_matching_debit_gets_no_draft(conn):
    _insert_recurring(conn, detection_key=CAR_KEY, name="Car Bank")

    assert sync_drafts(conn) == []


def test_draft_is_deleted_when_its_payment_is_dismissed(conn):
    car_id = _seed_car(conn)
    _seed_sofa(conn)
    sync_drafts(conn)

    dismiss(conn, car_id)

    assert _draft_keys(conn) == [SOFA_KEY]
    assert conn.execute("SELECT detection_key FROM debt_drafts").fetchall() == [(SOFA_KEY,)]


def test_draft_is_deleted_when_its_category_is_unflagged(conn):
    _seed_car(conn)
    sync_drafts(conn)
    [loans] = [c for c in list_categories(conn) if c.name == LOANS]

    update_category(conn, loans.id, loans.name, loans.type, debt=False)

    assert sync_drafts(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM debt_drafts").fetchone() == (0,)


def test_draft_is_deleted_when_a_hand_entered_debt_links_its_payment(conn):
    _seed_car(conn)
    _seed_sofa(conn)
    sync_drafts(conn)

    add_debt(conn, _installment())

    assert _draft_keys(conn) == [CAR_KEY]


def test_completing_a_draft_as_an_installment_adds_a_linked_debt(conn):
    _seed_sofa(conn)
    [draft] = sync_drafts(conn)

    debt_id = complete_draft(conn, draft.id, _installment())

    [view] = debt_overview(conn, TODAY)
    assert view.id == debt_id
    assert view.debt == _installment()
    assert [p.detection_key for p in view.linked_payments] == [SOFA_KEY]
    assert sync_drafts(conn) == []


def test_completing_a_draft_as_a_loan_adds_a_debt(conn):
    _seed_car(conn)
    [draft] = sync_drafts(conn)

    debt_id = complete_draft(conn, draft.id, _loan())

    [view] = debt_overview(conn, TODAY)
    assert view.id == debt_id
    assert view.debt == _loan()
    assert sync_drafts(conn) == []


def test_completed_payment_gets_no_draft_after_its_debt_is_deleted(conn):
    _seed_car(conn)
    [draft] = sync_drafts(conn)
    debt_id = complete_draft(conn, draft.id, _loan())

    delete_debt(conn, debt_id)

    assert sync_drafts(conn) == []
    assert conn.execute("SELECT detection_key, status FROM debt_drafts").fetchall() == [
        (CAR_KEY, "completed")
    ]


def test_completing_an_unknown_draft_raises_and_adds_no_debt(conn):
    with pytest.raises(DraftNotFound):
        complete_draft(conn, 999, _loan())

    assert list_debts(conn) == []


def test_completing_a_completed_draft_raises_and_adds_no_debt(conn):
    _seed_car(conn)
    [draft] = sync_drafts(conn)
    complete_draft(conn, draft.id, _loan())

    with pytest.raises(DraftNotFound):
        complete_draft(conn, draft.id, _installment())

    assert [stored.debt for stored in list_debts(conn)] == [_loan()]
