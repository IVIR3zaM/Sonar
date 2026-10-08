"""Tests for load_dashboard (SPEC §7, §8, §9): wiring the forecast to the DB.

All data is fake and `today` is pinned. With salary day 26, today 2026-09-10
gives payday Friday 2026-09-25 (the 26th is a Saturday), so a balance as of
today forecasts the window [2026-09-11, 2026-09-24].
"""

import sqlite3
from datetime import date, timedelta

import pytest

from sonar.cashflow.forecast import DueItem, Projection
from sonar.cashflow.lights_on import CategoryExpected
from sonar.cashflow.service import load_dashboard, load_lights_on, load_monthly, load_payoff
from sonar.cashflow.store import save_settings, set_manual_balance
from sonar.db import MIGRATIONS_DIR, apply_migrations
from sonar.debts.model import Installment, Loan, MatchRule
from sonar.debts.store import add_debt
from sonar.recurring.schedule import SchedulePeriod
from sonar.recurring.store import add_manual

TODAY = date(2026, 9, 10)
PAYDAY = date(2026, 9, 25)
CATEGORY_TYPES = {
    "Groceries": "lights_on",
    "Dining": "occasional",
    "Rent": "fixed",
    "Child benefit": "income",
    "Salary": "income",
}


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
    rate_cents: int = 10_000,
    first_payment_date: date = date(2026, 1, 15),
    payments_count: int = 12,
) -> Installment:
    return Installment(
        name=name,
        total_cents=total_cents,
        rate_cents=rate_cents,
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


def test_balance_on_the_day_before_payday_leaves_nothing_due(
    conn: sqlite3.Connection,
) -> None:
    save_settings(conn, 26, -50_000)
    _insert_import_balance(conn, "2026-09-24", 10_000)
    _monthly(conn, "Day before payday", 24, 4_000)

    board = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    assert board.due == []
    assert board.projection == Projection(10_000, 10_000)


def test_balance_after_a_payday_forecasts_to_the_following_one(
    conn: sqlite3.Connection,
) -> None:
    save_settings(conn, 26, -50_000)
    _insert_import_balance(conn, "2026-09-30", 10_000)

    board = load_dashboard(conn, CATEGORY_TYPES, date(2026, 10, 1))

    assert board.payday == date(2026, 10, 26)
    assert board.window_days == 25


def test_estimated_from_is_the_balance_date(conn: sqlite3.Connection) -> None:
    _configured(conn, 100_000, as_of=date(2026, 9, 8))

    board = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    assert board.estimated_from == date(2026, 9, 8)


def test_no_balance_has_no_estimate_date(conn: sqlite3.Connection) -> None:
    save_settings(conn, 26, -50_000)

    board = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    assert board.estimated_from is None


def test_data_from_before_a_passed_payday_forecasts_the_cycle_it_is_in(
    conn: sqlite3.Connection,
) -> None:
    # Paydays are 2026-09-25 and 2026-10-26; the data ends before the first.
    save_settings(conn, 26, -50_000)
    _insert_import_balance(conn, "2026-09-20", 100_000)
    _monthly(conn, "Before payday", 22, 2_000)
    _monthly(conn, "After payday", 1, 4_000)

    board = load_dashboard(conn, CATEGORY_TYPES, date(2026, 9, 28))

    assert board.payday == date(2026, 9, 25)
    assert board.window_days == 4
    assert board.days_to_payday == -3
    assert board.due == [DueItem("Before payday", date(2026, 9, 22), 2_000)]


def test_one_day_old_balance_counts_days_to_payday_from_today(
    conn: sqlite3.Connection,
) -> None:
    _configured(conn, 100_000, as_of=date(2026, 9, 9))

    board = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    assert board.payday == PAYDAY
    assert board.window_days == 15
    assert board.days_to_payday == 15


def test_fixed_cost_next_due_is_counted_from_the_estimate_date(
    conn: sqlite3.Connection,
) -> None:
    save_settings(conn, 26, -50_000)
    _insert_import_balance(conn, "2026-09-20", 100_000)
    _monthly(conn, "Rent", 22, 2_000)

    board = load_dashboard(conn, CATEGORY_TYPES, date(2026, 9, 28))

    (row,) = board.fixed_costs.rows
    assert row.next_due == date(2026, 9, 22)


def test_debt_remainder_is_projected_to_the_estimate_date(
    conn: sqlite3.Connection,
) -> None:
    save_settings(conn, 26, -50_000)
    _insert_import_balance(conn, "2026-09-20", 100_000)
    # The first rate falls on 2026-09-24: after the balance date, before today.
    add_debt(
        conn,
        Loan(
            name="Car",
            balance_cents=100_000,
            balance_as_of=date(2026, 8, 24),
            rate_cents=60_000,
            interest_bp=None,
            match=MatchRule("mandate", "M-3"),
        ),
    )

    board = load_dashboard(conn, CATEGORY_TYPES, date(2026, 9, 28))

    assert board.debts == [("Car", 100_000)]


def test_debt_linked_to_a_recurring_payment_is_counted_once(conn: sqlite3.Connection) -> None:
    _configured(conn, 100_000)
    for month in range(1, 9):
        _insert_tx(conn, f"2026-{month:02d}-15", -10_000, mandate_ref="M-1")
    # detect.payment_key for a mandate without a creditor id.
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


def _income(
    conn: sqlite3.Connection,
    dates: list[str],
    amount_cents: int = 25_000,
    *,
    category: str = "Child benefit",
) -> None:
    for booking_date in dates:
        _insert_tx(
            conn,
            booking_date,
            amount_cents,
            counterparty="Family Benefits Office",
            category=category,
        )


def test_income_inside_the_window_raises_projection_and_expected_and_is_listed(
    conn: sqlite3.Connection,
) -> None:
    _configured(conn, 100_000)
    _income(conn, ["2026-06-15", "2026-07-15"], 20_000)
    _income(conn, ["2026-08-15"], 25_000)
    _monthly(conn, "Gym", 20, 3_000)

    board = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    assert board.inflows == [DueItem("Child benefit", date(2026, 9, 15), 25_000)]
    assert board.inflow_total_cents == 25_000
    assert board.projection == Projection(122_000, 122_000)
    assert board.expected_cents == 122_000


def test_income_adds_to_the_projection_range_and_expected_with_lights_on_history(
    conn: sqlite3.Connection,
) -> None:
    _configured(conn, 100_000, as_of=date(2026, 9, 10))
    for month, cents in ((6, -3_000), (7, -6_000), (8, -9_000)):
        _insert_tx(conn, f"2026-{month:02d}-10", cents, category="Groceries")
    without = load_dashboard(conn, CATEGORY_TYPES, TODAY)
    assert without.projection is not None and without.expected_cents is not None

    _income(conn, ["2026-06-15", "2026-07-15", "2026-08-15"])
    board = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    assert board.projection == Projection(
        without.projection.worst_cents + 25_000, without.projection.best_cents + 25_000
    )
    assert board.expected_cents == without.expected_cents + 25_000


def test_income_series_due_on_or_after_payday_adds_nothing(conn: sqlite3.Connection) -> None:
    _configured(conn, 100_000)
    # Every second month on the 5th: next due 2026-10-05.
    _income(conn, ["2026-04-05", "2026-06-05", "2026-08-05"])

    board = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    assert (board.inflows, board.inflow_total_cents) == ([], 0)
    assert board.projection == Projection(100_000, 100_000)


def test_income_already_booked_within_seven_days_adds_nothing(conn: sqlite3.Connection) -> None:
    _configured(conn, 100_000)
    _income(conn, ["2026-06-15", "2026-07-15", "2026-08-15", "2026-09-10"])

    board = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    assert (board.inflows, board.inflow_total_cents) == ([], 0)
    assert board.projection == Projection(100_000, 100_000)


def test_salary_series_is_never_an_inflow(conn: sqlite3.Connection) -> None:
    _configured(conn, 100_000)
    # Typical day 20 is within 7 days of salary day 26, and due inside the window.
    _income(conn, ["2026-06-20", "2026-07-20", "2026-08-20"], 300_000, category="Salary")

    board = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    assert (board.inflows, board.inflow_total_cents) == ([], 0)
    assert board.projection == Projection(100_000, 100_000)


def test_without_income_series_there_are_no_inflows(conn: sqlite3.Connection) -> None:
    _configured(conn, 100_000)
    _insert_tx(conn, "2026-09-01", 5_000, category="Child benefit")

    board = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    assert (board.inflows, board.inflow_total_cents) == ([], 0)


def test_inflows_are_empty_without_salary_day_or_balance(conn: sqlite3.Connection) -> None:
    _income(conn, ["2026-06-15", "2026-07-15", "2026-08-15"])
    set_manual_balance(conn, TODAY, 100_000, TODAY)

    no_salary_day = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    assert (no_salary_day.inflows, no_salary_day.inflow_total_cents) == ([], 0)

    conn.execute("DELETE FROM balances")
    save_settings(conn, 26, -50_000)

    no_balance = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    assert (no_balance.inflows, no_balance.inflow_total_cents) == ([], 0)


def test_income_leaves_due_and_fixed_costs_unchanged(conn: sqlite3.Connection) -> None:
    _configured(conn, 100_000)
    _monthly(conn, "Rent", 20, 50_000)
    before = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    _income(conn, ["2026-06-15", "2026-07-15", "2026-08-15"])
    after = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    assert after.inflow_total_cents == 25_000
    assert after.due == before.due
    assert after.due_total_cents == before.due_total_cents
    assert after.fixed_costs == before.fixed_costs


def test_load_lights_on_without_transactions_has_no_months_and_no_daily(conn):
    view = load_lights_on(conn, CATEGORY_TYPES)

    assert view.categories == ("Groceries",)
    assert view.months == []
    assert view.daily is None
    assert view.salary_months is False


def test_load_lights_on_reports_complete_months_and_daily_average(conn):
    _insert_tx(conn, "2026-01-01", -3100, category="Groceries")
    # A later booking makes January a complete month.
    _insert_tx(conn, "2026-02-01", 100)

    view = load_lights_on(conn, CATEGORY_TYPES)

    assert [m.lights_on_cents for m in view.months] == [3100]
    assert view.daily is not None
    assert view.daily.months_used == tuple(m.period for m in view.months)


def test_load_lights_on_flags_salary_months_once_a_salary_day_is_set(conn):
    save_settings(conn, 26, -50_000)

    assert load_lights_on(conn, CATEGORY_TYPES).salary_months is True


def test_load_monthly_without_a_month_opens_the_latest_month_with_payments(conn):
    _insert_tx(conn, "2026-06-10", -1000, category="Groceries")
    _insert_tx(conn, "2026-07-10", -2000, category="Groceries")

    view = load_monthly(conn, CATEGORY_TYPES, TODAY, None)

    assert view.selected == date(2026, 7, 1)
    assert view.months == [date(2026, 7, 1), date(2026, 6, 1)]
    assert (view.older, view.newer) == (date(2026, 6, 1), None)
    assert view.spending.spent_cents == -2000
    assert view.salary_months is False


def test_load_monthly_without_a_month_or_data_falls_back_to_the_clock_month(conn):
    view = load_monthly(conn, CATEGORY_TYPES, TODAY, None)

    assert view.selected == date(2026, 9, 1)
    assert view.months == []
    assert view.spending.payments == ()


def test_load_monthly_with_a_month_selects_it_and_its_neighbours(conn):
    _insert_tx(conn, "2026-06-10", -1000, category="Groceries")
    _insert_tx(conn, "2026-07-10", -2000, category="Groceries")
    _insert_tx(conn, "2026-08-10", -4000, category="Groceries")

    view = load_monthly(conn, CATEGORY_TYPES, TODAY, date(2026, 7, 1))

    assert view.selected == date(2026, 7, 1)
    assert (view.older, view.newer) == (date(2026, 6, 1), date(2026, 8, 1))
    assert view.spending.spent_cents == -2000


def test_load_monthly_flags_salary_months_once_a_salary_day_is_set(conn):
    save_settings(conn, 26, -50_000)

    assert load_monthly(conn, CATEGORY_TYPES, TODAY, None).salary_months is True


def _loan(name: str, mandate: str, balance_cents: int = 100_000) -> Loan:
    return Loan(
        name=name,
        balance_cents=balance_cents,
        balance_as_of=date(2026, 8, 24),
        rate_cents=20_000,
        interest_bp=None,
        match=MatchRule("mandate", mandate),
    )


def test_payoff_frees_the_installment_rate_from_the_dashboard_fixed_costs(
    conn: sqlite3.Connection,
) -> None:
    _monthly(conn, "Rent", 1, 50_000)
    add_debt(conn, _installment("Sofa", "M-1", first_payment_date=date(2026, 10, 15)))

    payoff = load_payoff(conn, TODAY)

    (step,) = payoff.steps
    assert payoff.estimate_date == TODAY
    assert (payoff.before_min_cents, payoff.before_max_cents) == (60_000, 60_000)
    assert (step.before_min_cents, step.before_max_cents) == (60_000, 60_000)
    assert (step.after_min_cents, step.after_max_cents) == (50_000, 50_000)
    assert step.freed_cents == 10_000
    assert step.pay_now_cents == 120_000
    assert [d.name for d in step.debts] == ["Sofa"]
    assert step.debts[0].kind == "installment"


def test_payoff_counts_a_quarterly_fixed_row_in_the_maximum_only(
    conn: sqlite3.Connection,
) -> None:
    _monthly(conn, "Rent", 1, 50_000)
    add_manual(conn, "Insurance", None, SchedulePeriod(date(2026, 1, 1), None, 30_000, 3, 20))
    add_debt(conn, _installment("Sofa", "M-1", first_payment_date=date(2026, 10, 15)))

    payoff = load_payoff(conn, TODAY)

    (step,) = payoff.steps
    assert (step.before_min_cents, step.before_max_cents) == (60_000, 90_000)
    assert (step.after_min_cents, step.after_max_cents) == (50_000, 80_000)
    assert step.freed_cents == 10_000


def test_payoff_reads_the_fixed_rows_at_the_balance_date_not_today(
    conn: sqlite3.Connection,
) -> None:
    _insert_import_balance(conn, "2026-09-23", 100_000)
    _monthly(conn, "Rent", 1, 50_000)
    add_manual(conn, "Gym", None, SchedulePeriod(date(2026, 1, 1), date(2026, 9, 30), 7_000, 1, 25))

    payoff = load_payoff(conn, date(2026, 10, 5))

    assert payoff.estimate_date == date(2026, 9, 23)
    assert (payoff.before_min_cents, payoff.before_max_cents) == (57_000, 57_000)


def test_payoff_without_debts_has_no_steps_but_the_before_range(
    conn: sqlite3.Connection,
) -> None:
    _monthly(conn, "Rent", 1, 50_000)

    payoff = load_payoff(conn, TODAY)

    assert payoff.steps == ()
    assert (payoff.before_min_cents, payoff.before_max_cents) == (50_000, 50_000)


def test_payoff_leaves_a_paid_off_installment_off_the_ladder(conn: sqlite3.Connection) -> None:
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
    add_debt(conn, _installment("Sofa", "M-1", first_payment_date=date(2026, 9, 15)))

    payoff = load_payoff(conn, TODAY)

    (step,) = payoff.steps
    assert [d.name for d in step.debts] == ["Sofa"]


def test_payoff_estimates_from_the_balance_date_and_projects_a_loan_to_it(
    conn: sqlite3.Connection,
) -> None:
    _insert_import_balance(conn, "2026-09-20", 100_000)
    add_debt(conn, _loan("Car", "M-3"))

    payoff = load_payoff(conn, date(2026, 9, 28))

    (step,) = payoff.steps
    (car,) = step.debts
    assert payoff.estimate_date == date(2026, 9, 20)
    assert car.kind == "loan"
    assert car.interval_months == 1
    # The first rate falls on 2026-09-24: after the balance date, before today.
    assert car.remaining_cents == 100_000
    assert load_payoff(conn, date(2026, 9, 28)).steps == load_payoff(conn, date(2026, 9, 21)).steps
    assert step.pay_now_cents == car.remaining_cents


def test_payoff_counts_a_debt_linked_recurring_payment_once(conn: sqlite3.Connection) -> None:
    for month in range(1, 9):
        _insert_tx(conn, f"2026-{month:02d}-15", -10_000, mandate_ref="M-1")
    _insert_detected(conn, "mandate:/M-1", "Sofa rate", day=15, amount_cents=10_000)
    add_debt(conn, _installment("Sofa", "M-1"))

    payoff = load_payoff(conn, TODAY)

    (step,) = payoff.steps
    # The debt owns the payment; paying it off leaves nothing of "Sofa rate".
    assert step.after_min_cents == 0
    assert step.after_max_cents == 0
    assert step.freed_cents == 10_000


def _salary_history(conn: sqlite3.Connection) -> None:
    for booked, cents in (
        ("2026-06-25", 200_000),
        ("2026-07-24", 250_000),
        ("2026-08-25", 230_000),
    ):
        _insert_tx(conn, booked, cents, counterparty="Employer", category="Salary")


def test_salary_day_gives_expected_income_and_thirteen_fixed_cost_cycles(
    conn: sqlite3.Connection,
) -> None:
    today = date(2026, 10, 7)
    save_settings(conn, 25, -50_000)
    set_manual_balance(conn, today, 100_000, today)
    _salary_history(conn)
    _monthly(conn, "Rent", 1, 50_000)

    board = load_dashboard(conn, CATEGORY_TYPES, today)

    assert board.expected_income is not None
    assert board.expected_income.salary_cents == 200_000
    assert board.expected_income.total_cents == (
        board.expected_income.salary_cents + board.expected_income.recurring_cents
    )
    cycles = board.fixed_costs.cycles
    assert [c.kind for c in cycles] == ["actual"] * 6 + ["current"] + ["forecast"] * 6
    assert cycles[6].start == date(2026, 9, 25)
    assert cycles[-1].forecast_cents == 50_000


def test_without_a_salary_day_there_are_no_cycles_and_no_expected_income(
    conn: sqlite3.Connection,
) -> None:
    set_manual_balance(conn, TODAY, 100_000, TODAY)
    _salary_history(conn)
    _monthly(conn, "Rent", 1, 50_000)

    board = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    assert board.fixed_costs.cycles == ()
    assert board.expected_income is None


def test_without_income_credits_there_is_no_expected_income(conn: sqlite3.Connection) -> None:
    _configured(conn, 100_000)
    _monthly(conn, "Rent", 1, 50_000)

    board = load_dashboard(conn, CATEGORY_TYPES, TODAY)

    assert board.expected_income is None
    assert len(board.fixed_costs.cycles) == 13
