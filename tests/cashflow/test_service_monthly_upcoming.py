"""Monthly estimates share the dashboard's balance-date forecasting rules."""

import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient
from jinja2 import DictLoader, Environment

from sonar.cashflow.monthly import Upcoming, ledger
from sonar.cashflow.service import load_dashboard, load_monthly
from sonar.cashflow.store import save_settings, set_manual_balance
from sonar.db import MIGRATIONS_DIR, apply_migrations
from sonar.debts.model import Installment, MatchRule
from sonar.debts.store import add_debt
from sonar.recurring.schedule import SchedulePeriod
from sonar.recurring.store import add_manual
from sonar.utilities.model import BillingPeriod, Charge, Meter
from sonar.utilities.store import add_meter, add_period
from sonar.web.pages.monthly import build_router

TODAY = date(2026, 11, 7)
ESTIMATE_DATE = date(2026, 9, 10)
MONTH = date(2026, 9, 1)
CATEGORIES = {"Rent": "fixed", "Groceries": "lights_on", "Benefit": "income"}


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(":memory:")
    apply_migrations(connection, MIGRATIONS_DIR)
    yield connection
    connection.close()


def _booking(
    conn: sqlite3.Connection,
    day: date,
    cents: int,
    category: str,
    counterparty: str = "Shop",
) -> None:
    (count,) = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()
    conn.execute(
        """INSERT INTO transactions (
            source, account, booking_date, value_date, amount_cents, currency,
            counterparty, purpose, raw_row, fingerprint, occurrence, category
        ) VALUES ('test', 'acc', ?, ?, ?, 'EUR', ?, '', 'raw', ?, 1, ?)""",
        (day.isoformat(), day.isoformat(), cents, counterparty, f"fp{count}", category),
    )
    conn.commit()


def _configure(conn: sqlite3.Connection, as_of: date = ESTIMATE_DATE) -> None:
    save_settings(conn, 26, -50_000)
    set_manual_balance(conn, as_of, 100_000, TODAY)
    add_manual(conn, "Rent", "Rent", SchedulePeriod(date(2026, 1, 1), None, 30_000, 1, 15))


def test_current_period_forecasts_due_lights_on_and_income_by_category(
    conn: sqlite3.Connection,
) -> None:
    _configure(conn)
    # Complete salary periods have an exact daily cost of 100 cents.
    day = date(2026, 5, 26)
    while day <= ESTIMATE_DATE:
        _booking(conn, day, -100, "Groceries")
        day += timedelta(days=1)
    for month in (6, 7, 8):
        for counterparty, cents in (("Family Office", 20_000), ("Other Office", 5_000)):
            _booking(conn, date(2026, month, 18), cents, "Benefit", counterparty)

    view = load_monthly(conn, CATEGORIES, TODAY, MONTH)

    assert view.upcoming == Upcoming(
        date(2026, 9, 11), date(2026, 9, 24), -30_000, -1_400, (("Benefit", 25_000),)
    )
    assert view.ledger == ledger(view.spending, view.upcoming)


@pytest.mark.parametrize(
    ("salary_day", "balance_date", "month"),
    [
        (26, ESTIMATE_DATE, date(2026, 8, 1)),
        (26, ESTIMATE_DATE, date(2026, 10, 1)),
        (26, None, MONTH),
        (None, ESTIMATE_DATE, MONTH),
        (26, date(2026, 9, 24), MONTH),
        (26, date(2026, 8, 25), MONTH),
    ],
)
def test_upcoming_requires_setup_estimate_inside_period_and_remaining_days(
    conn: sqlite3.Connection, salary_day: int | None, balance_date: date | None, month: date
) -> None:
    if salary_day is not None:
        save_settings(conn, salary_day, -50_000)
    if balance_date is not None:
        set_manual_balance(conn, balance_date, 100_000, TODAY)

    view = load_monthly(conn, CATEGORIES, TODAY, month)

    assert view.upcoming is None
    assert view.ledger == ledger(view.spending)


def test_booking_fixed_payment_preserves_fixed_total_and_actual_residual(
    conn: sqlite3.Connection,
) -> None:
    _configure(conn)
    before = load_monthly(conn, CATEGORIES, TODAY, MONTH)

    _booking(conn, date(2026, 9, 15), -30_000, "Rent")
    set_manual_balance(conn, date(2026, 9, 16), 70_000, TODAY)
    after = load_monthly(conn, CATEGORIES, TODAY, MONTH)

    assert before.upcoming is not None and after.upcoming is not None
    assert before.upcoming.lights_on_cents == after.upcoming.lights_on_cents == 0
    assert before.ledger.fixed.paid_cents == 0
    assert before.ledger.fixed.upcoming_cents == -30_000
    assert after.ledger.fixed.paid_cents == -30_000
    assert after.ledger.fixed.upcoming_cents == 0
    assert before.ledger.fixed.total_cents == after.ledger.fixed.total_cents == -30_000
    assert before.ledger.actual_residual_cents == after.ledger.actual_residual_cents == -30_000


@pytest.mark.parametrize("settled_cents", [-3_500, 4_000])
def test_fixed_forecast_includes_debts_advances_and_settlement_debits_but_no_refunds(
    conn: sqlite3.Connection, settled_cents: int
) -> None:
    _configure(conn)
    add_debt(
        conn,
        Installment(
            name="Sofa",
            total_cents=120_000,
            rate_cents=10_000,
            interval_months=1,
            first_payment_date=date(2026, 1, 15),
            payments_count=12,
            match=MatchRule("mandate", "fake-mandate"),
        ),
    )
    conn.execute("INSERT INTO categories (name, type) VALUES ('Water', 'fixed')")
    meter_id = add_meter(conn, Meter("Water", "water"))
    ended = BillingPeriod(
        date(2026, 1, 1),
        date(2026, 7, 20),
        None,
        None,
        None,
        None,
        24_000,
        150,
        "Water",
        drinking=Charge(1_140_000, 3600, 7),
        wastewater=Charge(3_690_000, 9600, 0),
        settled_cents=settled_cents,
        settlement_debit_days=55,
    )
    add_period(conn, meter_id, ended)
    add_period(
        conn,
        meter_id,
        replace(
            ended,
            start_date=date(2026, 7, 21),
            settlement_date=date(2026, 12, 31),
            settled_cents=None,
            advance_mode="schedule",
            advance_dates=(date(2026, 9, 18),),
        ),
    )

    view = load_monthly(conn, CATEGORIES, TODAY, MONTH)
    board = load_dashboard(conn, CATEGORIES, TODAY)

    assert view.upcoming is not None
    assert view.upcoming.fixed_cents == -(64_000 + max(0, -settled_cents))
    assert view.upcoming.fixed_cents == -board.due_total_cents
    assert view.upcoming.income_by_category == ()
    assert board.inflow_total_cents == max(0, settled_cents)


def test_monthly_page_passes_ledger_to_template(tmp_path: Path) -> None:
    db_path = tmp_path / "monthly.db"
    with sqlite3.connect(db_path) as conn:
        apply_migrations(conn, MIGRATIONS_DIR)
        _configure(conn)
    templates = Jinja2Templates(
        env=Environment(loader=DictLoader({"monthly.html": "{{ ledger.fixed.total_cents }}"}))
    )
    app = FastAPI()
    app.include_router(build_router(db_path, lambda: TODAY, templates))

    response = TestClient(app).get("/monthly?month=2026-09")

    assert response.status_code == 200
    assert response.text == "-30000"
