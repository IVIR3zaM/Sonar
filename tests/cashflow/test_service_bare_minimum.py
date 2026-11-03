"""Dashboard bare minimum inputs and setup hints (SPEC §13)."""

import sqlite3
from datetime import date

import pytest

from sonar.cashflow.service import load_dashboard
from sonar.cashflow.store import save_settings, set_manual_balance
from sonar.db import MIGRATIONS_DIR, apply_migrations
from sonar.debts.store import add_debt
from tests.cashflow.test_service import (
    CATEGORY_TYPES,
    TODAY,
    _insert_detected,
    _insert_tx,
    _installment,
    _monthly,
    _salary_history,
)


@pytest.fixture
def conn():
    with sqlite3.connect(":memory:") as connection:
        apply_migrations(connection, MIGRATIONS_DIR)
        yield connection


def _history(conn):
    save_settings(conn, 26, -50_000)
    _salary_history(conn)
    _insert_tx(conn, "2026-07-01", -3_100, category="Groceries")
    _insert_tx(conn, "2026-07-15", -6_200, category="Dining")
    _monthly(conn, "Rent", 1, 50_000)


@pytest.mark.parametrize("with_balance", [True, False])
@pytest.mark.parametrize("linked", [True, False])
def test_bare_minimum_counts_debt_schedules_and_current_cycle_drops(conn, with_balance, linked):
    _history(conn)
    if with_balance:
        set_manual_balance(conn, TODAY, 100_000, TODAY)
    if linked:
        _insert_tx(conn, "2026-08-15", -10_000, mandate_ref="plan")
        _insert_detected(conn, "mandate:/plan", "Plan", 15, 10_000)
    add_debt(conn, _installment("Plan", "plan"))
    add_debt(
        conn,
        _installment(
            "Short plan",
            "short",
            total_cents=5_000,
            rate_cents=5_000,
            first_payment_date=date(2026, 9, 15),
            payments_count=1,
        ),
    )

    board = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    minimum = board.bare_minimum
    assert board.bare_minimum_hint is None
    assert minimum is not None
    assert minimum.income_cents == 200_000
    assert minimum.total_cents == max(c.need_cents for c in minimum.cycles)
    costs = {c.start: c.forecast_cents for c in board.fixed_costs.cycles if c.kind == "forecast"}
    assert all(c.fixed_cents == costs[c.start] for c in minimum.cycles)
    assert minimum.cycle.fixed_cents == 60_000
    assert minimum.debt_cents == 10_000
    assert minimum.occasional_cents == 3_100
    assert [(d.name, d.kind, d.end_date) for d in minimum.drops] == [
        ("Short plan", "installment", date(2026, 9, 15)),
        ("Plan", "installment", date(2026, 12, 15)),
    ]
    assert board.estimated_from == (TODAY if with_balance else None)


@pytest.mark.parametrize("hint", ["salary_day", "income", "lights_on"])
def test_bare_minimum_hints_follow_setup_order(conn, hint):
    if hint != "salary_day":
        save_settings(conn, 26, -50_000)
    if hint == "lights_on":
        _insert_tx(conn, "2026-07-24", 200_000, category="Salary")

    board = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    assert board.bare_minimum is None
    assert board.bare_minimum_hint == hint
