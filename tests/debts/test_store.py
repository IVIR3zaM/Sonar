"""Tests for the debt-storage DB shell (SPEC §7): round-trip, order, delete."""

import sqlite3
from datetime import date

import pytest

from sonar.db import MIGRATIONS_DIR, apply_migrations
from sonar.debts.model import Installment, Loan, MatchRule
from sonar.debts.store import DebtNotFound, add_debt, delete_debt, list_debts, update_debt


@pytest.fixture
def conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    return conn


def _installment(name: str = "Sofa") -> Installment:
    return Installment(
        name=name,
        total_cents=120_000,
        rate_cents=10_000,
        interval_months=1,
        first_payment_date=date(2026, 1, 5),
        payments_count=12,
        match=MatchRule("counterparty", "Furniture Store"),
    )


def _loan(name: str = "Car", interest_bp: int | None = None) -> Loan:
    return Loan(
        name=name,
        balance_cents=500_000,
        balance_as_of=date(2026, 6, 30),
        rate_cents=100_000,
        interest_bp=interest_bp,
        match=MatchRule("mandate", "M-1"),
    )


def test_installment_round_trips(conn: sqlite3.Connection) -> None:
    inst = _installment()
    debt_id = add_debt(conn, inst)

    [stored] = list_debts(conn)
    assert stored.id == debt_id
    assert stored.debt == inst


def test_loan_round_trips_with_and_without_interest(conn: sqlite3.Connection) -> None:
    with_interest = _loan("Car", interest_bp=600)
    without_interest = _loan("Mortgage", interest_bp=None)
    add_debt(conn, with_interest)
    add_debt(conn, without_interest)

    stored = list_debts(conn)
    assert [s.debt for s in stored] == [with_interest, without_interest]


def test_list_debts_orders_installments_before_loans_each_by_name(
    conn: sqlite3.Connection,
) -> None:
    sofa = _installment("Sofa")
    bike = _installment("Bike")
    car = _loan("Car")
    mortgage = _loan("Mortgage")
    # Insert out of the expected output order to prove list_debts, not insertion, sorts.
    add_debt(conn, mortgage)
    add_debt(conn, sofa)
    add_debt(conn, car)
    add_debt(conn, bike)

    names_and_kinds = [
        (isinstance(stored.debt, Loan), stored.debt.name) for stored in list_debts(conn)
    ]
    assert names_and_kinds == [
        (False, "Bike"),
        (False, "Sofa"),
        (True, "Car"),
        (True, "Mortgage"),
    ]


def test_delete_removes_only_that_row(conn: sqlite3.Connection) -> None:
    keep_id = add_debt(conn, _installment("Sofa"))
    remove_id = add_debt(conn, _loan("Car"))

    delete_debt(conn, remove_id)

    [stored] = list_debts(conn)
    assert stored.id == keep_id


def test_delete_unknown_id_raises_and_leaves_table_unchanged(conn: sqlite3.Connection) -> None:
    add_debt(conn, _installment())
    before = list_debts(conn)

    with pytest.raises(DebtNotFound):
        delete_debt(conn, 999)

    assert list_debts(conn) == before


def test_update_edits_an_installment_in_place_and_keeps_its_id(conn: sqlite3.Connection) -> None:
    debt_id = add_debt(conn, _installment("Sofa"))
    edited = Installment(
        name="Couch",
        total_cents=90_000,
        rate_cents=15_000,
        interval_months=3,
        first_payment_date=date(2026, 2, 1),
        payments_count=6,
        match=MatchRule("purpose", "couch"),
    )

    update_debt(conn, debt_id, edited)

    [stored] = list_debts(conn)
    assert stored.id == debt_id
    assert stored.debt == edited


def test_update_changing_an_installment_to_a_loan_nulls_the_installment_columns(
    conn: sqlite3.Connection,
) -> None:
    debt_id = add_debt(conn, _installment("Sofa"))
    loan = _loan("Sofa loan", interest_bp=450)

    update_debt(conn, debt_id, loan)

    [stored] = list_debts(conn)
    assert stored.id == debt_id
    assert stored.debt == loan
    row = conn.execute(
        "SELECT kind, total_cents, interval_months, first_payment_date, payments_count "
        "FROM debts WHERE id = ?",
        (debt_id,),
    ).fetchone()
    assert row == ("loan", None, None, None, None)


def test_update_changing_a_loan_to_an_installment_nulls_the_loan_columns(
    conn: sqlite3.Connection,
) -> None:
    debt_id = add_debt(conn, _loan("Car", interest_bp=450))

    update_debt(conn, debt_id, _installment("Car"))

    row = conn.execute(
        "SELECT kind, balance_cents, balance_as_of, interest_bp FROM debts WHERE id = ?",
        (debt_id,),
    ).fetchone()
    assert row == ("installment", None, None, None)


def test_update_unknown_id_raises_debt_not_found(conn: sqlite3.Connection) -> None:
    with pytest.raises(DebtNotFound):
        update_debt(conn, 99, _installment())
