"""Tests for load_dashboard (SPEC §7, §8, §9): wiring the forecast to the DB.

All data is fake and `today` is pinned. With salary day 26, today 2026-09-10
gives payday Friday 2026-09-25 (the 26th is a Saturday), so a balance as of
today forecasts the window [2026-09-11, 2026-09-24].
"""

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from sonar.dashboard import load_dashboard
from sonar.db import apply_migrations
from sonar.debt_store import add_debt
from sonar.debts import Installment, Loan, MatchRule
from sonar.forecast import DueItem, Projection
from sonar.lights_on import CategoryExpected
from sonar.recurring import add_manual
from sonar.schedule import SchedulePeriod
from sonar.settings_store import save_settings, set_manual_balance

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "sonar" / "migrations"
TODAY = date(2026, 9, 10)
PAYDAY = date(2026, 9, 25)
CATEGORY_TYPES = {"Groceries": "lights_on", "Dining": "occasional", "Rent": "fixed"}


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
    assert (board.projection, board.light, board.lights_on) == (None, None, None)
    assert (board.window_days, board.expected_cents) == (None, None)
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


def _three_months_of_spending(conn: sqlite3.Connection) -> None:
    # Salary months for day 26 (as on the Monthly page), all complete by the
    # balance date: [05-26,06-25] 31d, [06-26,07-23] 28d, [07-24,08-25] 33d.
    # Groceries spends 300, 100 and 200 cents a day in them; Dining is
    # `occasional`, so its debits must not move the forecast.
    _insert_tx(conn, "2026-05-26", -9_300, category="Groceries")
    _insert_tx(conn, "2026-07-01", -2_800, category="Groceries")
    _insert_tx(conn, "2026-08-01", -6_600, category="Groceries")
    _insert_tx(conn, "2026-06-10", -50_000, category="Dining")
    _insert_tx(conn, "2026-08-10", -40_000, category="Dining")
    # A booking after the last month keeps that month fully known (SPEC §13).
    _insert_tx(conn, "2026-09-01", -1_000, category="Dining")


def test_lights_on_forecast_is_scaled_to_the_window_days(conn: sqlite3.Connection) -> None:
    # _configured pins the balance to 2026-09-08, so the window
    # [2026-09-09, 2026-09-24] up to payday is 16 days long.
    _configured(conn, 100_000, as_of=date(2026, 9, 8))
    _monthly(conn, "Gym", 15, 3_000)
    _three_months_of_spending(conn)

    board = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    # Expected: 18,700 cents over 92 days x 16 days = 3,252.17 -> 3,252.
    # Range: the lowest and highest daily average (100, 300) x 16 days.
    assert board.window_days == 16
    assert board.lights_on is not None
    assert (board.lights_on.expected_cents, board.lights_on.low_cents) == (3_252, 1_600)
    assert board.lights_on.high_cents == 4_800
    assert board.lights_on.by_category == (CategoryExpected("Groceries", 3_252),)
    assert len(board.lights_on.months_used) == 3
    # 100,000 balance - 3,000 due - the lights-on range.
    assert board.projection == Projection(92_200, 95_400)
    assert board.expected_cents == 100_000 - 3_000 - 3_252
    assert board.lights_on_categories == ("Groceries",)
    assert board.occasional_categories == ("Dining",)


def test_no_lights_on_category_forecasts_nothing(conn: sqlite3.Connection) -> None:
    _configured(conn, 100_000, as_of=date(2026, 9, 8))
    _monthly(conn, "Gym", 15, 3_000)
    _three_months_of_spending(conn)

    board = load_dashboard(conn, {"Dining": "occasional", "Groceries": "fixed"}, TODAY)

    assert board.lights_on_categories == ()
    assert board.projection == Projection(97_000, 97_000)
    assert board.expected_cents == 97_000


def test_no_complete_month_gives_no_lights_on_forecast(conn: sqlite3.Connection) -> None:
    _configured(conn, 100_000)
    _monthly(conn, "Gym", 15, 3_000)
    # The first booking falls inside [07-24, 08-25], so no month is complete.
    _insert_tx(conn, "2026-07-27", -5_000, category="Groceries")

    board = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    assert board.lights_on is None
    assert board.projection == Projection(97_000, 97_000)
    assert board.expected_cents == 97_000


def test_lights_on_learns_only_from_months_the_bookings_fully_cover(
    conn: sqlite3.Connection,
) -> None:
    save_settings(conn, 1, -50_000)
    set_manual_balance(conn, date(2026, 4, 30), 100_000, date(2026, 4, 30))
    for month in range(1, 5):
        _insert_tx(conn, f"2026-{month:02}-01", 300_000, category="Salary")
    day = date(2026, 1, 1)
    while day <= date(2026, 4, 10):
        _insert_tx(conn, day.isoformat(), -2_000, category="Groceries")
        day += timedelta(days=7)

    board = load_dashboard(conn, CATEGORY_TYPES, date(2026, 4, 30))

    # April ends on the balance date but was only booked up to 04-10.
    assert board.lights_on is not None
    assert board.lights_on.months_used[-1].end == date(2026, 3, 31)
    assert board.lights_on_daily is not None
    assert board.lights_on_daily.months_used == board.lights_on.months_used
