"""Tests for load_dashboard (SPEC §7, §8, §9): wiring the forecast to the DB.

All data is fake and `today` is pinned. With salary day 26, today 2026-09-10
gives payday Friday 2026-09-25 (the 26th is a Saturday), so a balance as of
today forecasts the window [2026-09-11, 2026-09-24].
"""

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from sonar.dashboard import load_dashboard
from sonar.db import apply_migrations
from sonar.debt_store import add_debt
from sonar.debts import Installment, Loan, MatchRule
from sonar.forecast import DueItem, Projection
from sonar.recurring import add_manual
from sonar.schedule import SchedulePeriod
from sonar.settings_store import save_settings, set_manual_balance
from sonar.variable_forecast import CategorySpend, VariableForecast

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "sonar" / "migrations"
TODAY = date(2026, 9, 10)
PAYDAY = date(2026, 9, 25)
CATEGORY_TYPES = {"Groceries": "variable", "Rent": "fixed"}


@pytest.fixture
def conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    return conn


def _insert_tx(
    conn: sqlite3.Connection,
    booking_date: str,
    amount_cents: int,
    *,
    counterparty: str = "Shop",
    mandate_ref: str | None = None,
    category: str | None = None,
) -> None:
    (count,) = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()
    conn.execute(
        """
        INSERT INTO transactions (
            source, account, booking_date, value_date, amount_cents, currency,
            counterparty, purpose, iban, mandate_ref, creditor_id, raw_row,
            fingerprint, occurrence, category
        ) VALUES ('test', 'acc', ?, ?, ?, 'EUR', ?, '', NULL, ?, NULL, 'raw', ?, 1, ?)
        """,
        (
            booking_date,
            booking_date,
            amount_cents,
            counterparty,
            mandate_ref,
            f"fp{count}",
            category,
        ),
    )
    conn.commit()


def _insert_import_balance(conn: sqlite3.Connection, as_of: str, amount_cents: int) -> None:
    conn.execute(
        "INSERT INTO balances (account, as_of, amount_cents, source)"
        " VALUES ('acc', ?, ?, 'import')",
        (as_of, amount_cents),
    )
    conn.commit()


def _insert_detected(
    conn: sqlite3.Connection, detection_key: str, name: str, day: int, amount_cents: int
) -> None:
    cursor = conn.execute(
        """
        INSERT INTO recurring_payments (
            detection_key, name, category, status, source, last_paid_date
        ) VALUES (?, ?, NULL, 'active', 'detected', '2026-08-15')
        """,
        (detection_key, name),
    )
    conn.execute(
        """
        INSERT INTO schedule_periods (
            payment_id, starts_on, until, amount_cents, interval_months, day
        ) VALUES (?, '2026-01-01', NULL, ?, 1, ?)
        """,
        (cursor.lastrowid, amount_cents, day),
    )
    conn.commit()


def _monthly(conn: sqlite3.Connection, name: str, day: int, amount_cents: int) -> None:
    add_manual(conn, name, None, SchedulePeriod(date(2026, 1, 1), None, amount_cents, 1, day))


def _installment(
    name: str,
    mandate: str,
    *,
    total_cents: int = 120_000,
    first_payment_date: date = date(2026, 1, 15),
    payments_count: int = 12,
) -> Installment:
    return Installment(
        name=name,
        total_cents=total_cents,
        rate_cents=10_000,
        interval_months=1,
        first_payment_date=first_payment_date,
        payments_count=payments_count,
        match=MatchRule("mandate", mandate),
    )


def _configured(conn: sqlite3.Connection, balance_cents: int, as_of: date = TODAY) -> None:
    save_settings(conn, 26, -50_000)
    set_manual_balance(conn, as_of, balance_cents, TODAY)


def test_unsaved_settings_leave_the_forecast_empty_but_fill_the_rest(
    conn: sqlite3.Connection,
) -> None:
    set_manual_balance(conn, TODAY, 100_000, TODAY)
    _monthly(conn, "Rent", 1, 50_000)
    add_debt(conn, _installment("Sofa", "M-1"))
    _insert_tx(conn, "2026-09-01", -2_000)
    _insert_tx(conn, "2026-09-02", -3_000, category="Groceries")

    board = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    assert board.salary_day is None
    assert board.overdraft_limit_cents == -50_000
    assert board.balance is not None and board.balance.amount_cents == 100_000
    assert (board.payday, board.days_to_payday) == (None, None)
    assert (board.projection, board.light, board.variable) == (None, None, None)
    assert (board.due, board.due_total_cents) == ([], 0)
    assert [row.name for row in board.fixed_costs.rows] == ["Rent", "Sofa"]
    assert board.debts == [("Sofa", 120_000)]
    assert board.debts_total_cents == 120_000
    assert board.uncategorized_count == 1


def test_salary_day_without_a_balance_has_no_light(conn: sqlite3.Connection) -> None:
    save_settings(conn, 26, -50_000)
    _monthly(conn, "Rent", 1, 50_000)

    board = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    assert board.salary_day == 26
    assert board.balance is None
    assert (board.payday, board.projection, board.light) == (None, None, None)
    assert board.fixed_costs.monthly_equivalent_cents == 50_000


def test_overdrawn_balance_is_green_at_the_default_limit_and_red_at_zero(
    conn: sqlite3.Connection,
) -> None:
    _configured(conn, -40_000)

    board = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    assert (board.payday, board.days_to_payday) == (PAYDAY, 15)
    assert board.projection == Projection(-40_000, -40_000)
    assert board.light == "green"

    save_settings(conn, 26, 0)
    board = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    assert board.overdraft_limit_cents == 0
    assert board.light == "red"


def test_due_covers_the_day_after_the_balance_date_up_to_the_day_before_payday(
    conn: sqlite3.Connection,
) -> None:
    # The balance is two days old: a payment on the 9th is not in it yet,
    # even though it falls before today.
    _configured(conn, 100_000, as_of=date(2026, 9, 8))
    _monthly(conn, "On balance day", 8, 1_000)
    _monthly(conn, "Day after balance", 9, 2_000)
    _monthly(conn, "Day before payday", 24, 4_000)
    _monthly(conn, "On payday", 25, 8_000)

    board = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    assert board.due == [
        DueItem("Day after balance", date(2026, 9, 9), 2_000),
        DueItem("Day before payday", date(2026, 9, 24), 4_000),
    ]
    assert board.due_total_cents == 6_000
    assert board.projection == Projection(94_000, 94_000)


@pytest.mark.parametrize("as_of", ["2026-09-24", "2026-09-30"])
def test_balance_on_or_after_the_day_before_payday_leaves_nothing_due(
    conn: sqlite3.Connection, as_of: str
) -> None:
    save_settings(conn, 26, -50_000)
    _insert_import_balance(conn, as_of, 10_000)
    _monthly(conn, "Day before payday", 24, 4_000)

    board = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    assert board.due == []
    assert board.projection == Projection(10_000, 10_000)


def test_debt_linked_to_a_recurring_payment_is_counted_once(conn: sqlite3.Connection) -> None:
    _configured(conn, 100_000)
    for month in range(1, 9):
        _insert_tx(conn, f"2026-{month:02d}-15", -10_000, mandate_ref="M-1")
    # recurrence.payment_key for a mandate without a creditor id.
    _insert_detected(conn, "mandate:/M-1", "Sofa rate", day=15, amount_cents=10_000)
    add_debt(conn, _installment("Sofa", "M-1"))

    board = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    assert board.due == [DueItem("Sofa", date(2026, 9, 15), 10_000)]
    assert [row.name for row in board.fixed_costs.rows] == ["Sofa"]
    assert board.debts == [("Sofa", 40_000)]


def test_unlinked_detected_payment_stays_a_fixed_cost(conn: sqlite3.Connection) -> None:
    _configured(conn, 100_000)
    _insert_detected(conn, "mandate:/OTHER", "Gym", day=15, amount_cents=3_000)
    add_debt(conn, _installment("Sofa", "M-1", first_payment_date=date(2026, 9, 20)))

    board = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    assert board.due == [
        DueItem("Gym", date(2026, 9, 15), 3_000),
        DueItem("Sofa", date(2026, 9, 20), 10_000),
    ]


def test_debt_payment_booked_early_is_not_due_again(conn: sqlite3.Connection) -> None:
    _configured(conn, 100_000)
    for booking_date in ["2026-08-15", "2026-09-09"]:
        _insert_tx(conn, booking_date, -10_000, mandate_ref="M-1")
    add_debt(conn, _installment("Sofa", "M-1", first_payment_date=date(2026, 8, 15)))

    board = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    assert board.due == []


def test_paid_off_debt_is_absent_from_due_but_listed_with_nothing_left(
    conn: sqlite3.Connection,
) -> None:
    _configured(conn, 100_000)
    for booking_date in ["2026-08-15", "2026-09-05"]:
        _insert_tx(conn, booking_date, -10_000, mandate_ref="M-2")
    add_debt(
        conn,
        _installment(
            "Lamp",
            "M-2",
            total_cents=20_000,
            first_payment_date=date(2026, 8, 15),
            payments_count=2,
        ),
    )
    add_debt(
        conn,
        Loan(
            name="Car",
            balance_cents=500_000,
            balance_as_of=date(2026, 6, 30),
            rate_cents=100_000,
            interest_bp=None,
            match=MatchRule("mandate", "M-3"),
        ),
    )

    board = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    # Without the paid-off check the Lamp's last rate would be due on 09-15,
    # since its latest payment (09-05) is outside the early-payment tolerance.
    assert board.due == []
    assert [row.name for row in board.fixed_costs.rows] == ["Car"]
    assert board.debts == [("Lamp", 0), ("Car", 300_000)]
    assert board.debts_total_cents == 300_000


def test_variable_range_is_scaled_to_the_window_days(conn: sqlite3.Connection) -> None:
    # _configured pins the balance to 2026-09-08, so the window
    # [2026-09-09, 2026-09-24] up to payday is 16 days long.
    _configured(conn, 100_000, as_of=date(2026, 9, 8))
    # The 6 most recent complete salary cycles before TODAY (2026-09-10) are,
    # oldest to newest: 03-01 [02-26,03-25] 28d, 04-01 [03-26,04-23] 29d,
    # 05-01 [04-24,05-25] 32d, 06-01 [05-26,06-25] 31d, 07-01 [06-26,07-23]
    # 28d, 08-01 [07-24,08-25] 33d. One Groceries debit per cycle, each sized
    # cycle length x 100 x m (m = 1..6, newest to oldest), scales to 16 days
    # as 1600*m: 1600, 3200, 4800, 6400, 8000, 9600.
    _insert_tx(conn, "2026-08-01", -3_300, category="Groceries")
    _insert_tx(conn, "2026-07-01", -5_600, category="Groceries")
    _insert_tx(conn, "2026-06-01", -9_300, category="Groceries")
    _insert_tx(conn, "2026-05-01", -12_800, category="Groceries")
    _insert_tx(conn, "2026-04-01", -14_500, category="Groceries")
    _insert_tx(conn, "2026-03-01", -16_800, category="Groceries")
    # A 7th, older debit sitting in the cycle before the 6-cycle history
    # window (HISTORY_CYCLES = 6): it must be ignored, not just clamped.
    _insert_tx(conn, "2026-01-26", -310_000, category="Groceries")

    board = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    assert board.variable == VariableForecast(3_600, 7_600, (CategorySpend("Groceries", 5_600),), 6)
    assert board.projection == Projection(92_400, 96_400)


def test_fewer_than_three_cycles_give_no_variable_range(conn: sqlite3.Connection) -> None:
    _configured(conn, 100_000)
    _monthly(conn, "Gym", 15, 3_000)
    _insert_tx(conn, "2026-07-27", -5_000, category="Groceries")

    board = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    assert board.variable is None
    assert board.projection == Projection(97_000, 97_000)
