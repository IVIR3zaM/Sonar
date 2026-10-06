"""DB shell for the dashboard (SPEC §9): gathers every figure the page shows.

The pure pieces (payday, forecast, lights_on, debts) do the math; this
module only reads the stored data and wires them together, so the web layer
renders a single `Dashboard` and never repeats a forecast rule.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Literal

from sonar.cashflow import forecast, lights_on, payday
from sonar.cashflow.balance import BalanceEntry
from sonar.cashflow.forecast import DueItem, FixedCosts, FixedSource, Projection
from sonar.cashflow.lights_on import LightsOnForecast
from sonar.cashflow.monthly import (
    MonthlySpending,
    adjacent_months,
    monthly_spending,
    payment_months,
    period_for,
    salary_paydays,
)
from sonar.cashflow.store import current_balance, load_settings
from sonar.categorization import groups
from sonar.categorization.store import transactions_with_category, uncategorized_count
from sonar.debts import model
from sonar.debts.store import DebtView, debt_overview, remaining_cents
from sonar.recurring.detect import Row, detect_income
from sonar.recurring.store import list_payments
from sonar.transactions import ParsedTransaction


@dataclass(frozen=True)
class Dashboard:
    salary_day: int | None
    payday: date | None
    days_to_payday: int | None
    balance: BalanceEntry | None
    # The balance's as-of date: every estimate starts from it (SPEC §13).
    estimated_from: date | None
    overdraft_limit_cents: int
    due: list[DueItem]
    due_total_cents: int
    # Recurring income expected before payday, named by category (SPEC §13).
    inflows: list[DueItem]
    inflow_total_cents: int
    window_days: int | None
    lights_on_categories: tuple[str, ...]
    occasional_categories: tuple[str, ...]
    lights_on: LightsOnForecast | None
    # The same months' figures for a single day: what `lights_on` multiplies
    # by `window_days`, and what the Keep the lights on page shows.
    lights_on_daily: LightsOnForecast | None
    # Balance + inflows - due - expected lights-on spending: the margin (or, negative,
    # the shortfall) against 0 at payday.
    expected_cents: int | None
    projection: Projection | None
    light: Literal["green", "yellow", "red"] | None
    fixed_costs: FixedCosts
    debts: list[tuple[str, int]]
    debts_total_cents: int
    uncategorized_count: int


def load_dashboard(
    conn: sqlite3.Connection, category_types: dict[str, str], today: date
) -> Dashboard:
    """Everything the dashboard shows, estimated from the balance's date.

    `today` only counts the calendar days to payday; the estimates follow the
    data, which may end before today.
    """
    settings = load_settings(conn)
    balance = current_balance(conn)
    estimate_date = today if balance is None else balance.as_of
    rows = transactions_with_category(conn)
    views = debt_overview(conn, estimate_date)
    sources = _fixed_sources(conn, views, [tx for tx, _ in rows])
    remaining = [(view.debt.name, remaining_cents(view)) for view in views]
    board = Dashboard(
        salary_day=settings.salary_day,
        payday=None,
        days_to_payday=None,
        balance=balance,
        estimated_from=None if balance is None else balance.as_of,
        overdraft_limit_cents=settings.overdraft_limit_cents,
        due=[],
        due_total_cents=0,
        inflows=[],
        inflow_total_cents=0,
        window_days=None,
        lights_on_categories=_names_of_type(category_types, groups.LIGHTS_ON),
        occasional_categories=_names_of_type(category_types, groups.OCCASIONAL),
        lights_on=None,
        lights_on_daily=None,
        expected_cents=None,
        projection=None,
        light=None,
        fixed_costs=forecast.fixed_costs(sources, estimate_date),
        debts=remaining,
        debts_total_cents=sum(cents for _, cents in remaining),
        uncategorized_count=uncategorized_count(conn),
    )
    if settings.salary_day is None or balance is None:
        # Without both there is nothing to project from; the rest of the page
        # is still useful, so only the forecast part stays empty.
        return board

    # The balance already contains everything booked up to its own date, so
    # the forecast covers the cycle that date is in, even when that cycle's
    # payday is already behind today.
    next_payday = payday.next_payday(estimate_date, settings.salary_day)
    start = estimate_date + timedelta(days=1)
    end = next_payday - timedelta(days=1)
    window_days = (end - start).days + 1
    due = forecast.fixed_due(sources, start, end)
    due_total = sum(item.amount_cents for item in due)
    inflows = _inflows(rows, category_types, settings.salary_day, estimate_date, start, end)
    inflow_total = sum(item.amount_cents for item in inflows)
    until = lights_on.last_known_day(rows, balance.as_of)
    months = (
        []
        if until is None
        else lights_on.month_spends(rows, category_types, settings.salary_day, until)
    )
    lights = lights_on.lights_on_forecast(months, window_days)
    lights_range = None if lights is None else (lights.low_cents, lights.high_cents)
    projection = forecast.project(balance.amount_cents, due_total, lights_range, inflow_total)
    lights_expected = 0 if lights is None else lights.expected_cents
    return replace(
        board,
        payday=next_payday,
        days_to_payday=(next_payday - today).days,
        due=due,
        due_total_cents=due_total,
        inflows=inflows,
        inflow_total_cents=inflow_total,
        window_days=window_days,
        lights_on=lights,
        lights_on_daily=lights_on.lights_on_forecast(months, 1),
        expected_cents=balance.amount_cents + inflow_total - due_total - lights_expected,
        projection=projection,
        light=forecast.traffic_light(projection, settings.overdraft_limit_cents),
    )


@dataclass(frozen=True)
class LightsOnView:
    """What the Keep the lights on page shows: the latest months and their daily average."""

    categories: tuple[str, ...]
    months: list[lights_on.MonthSpend]
    daily: LightsOnForecast | None
    salary_months: bool


def load_lights_on(conn: sqlite3.Connection, category_types: dict[str, str]) -> LightsOnView:
    """The last 24 complete months and the daily average learned from the latest ones."""
    rows = transactions_with_category(conn)
    salary_day = load_settings(conn).salary_day
    balance = current_balance(conn)
    until = lights_on.last_known_day(rows, balance.as_of if balance else None)
    months = (
        [] if until is None else lights_on.month_spends(rows, category_types, salary_day, until)
    )
    return LightsOnView(
        categories=_names_of_type(category_types, groups.LIGHTS_ON),
        months=months[-24:],
        daily=lights_on.lights_on_forecast(months, 1),
        salary_months=salary_day is not None,
    )


@dataclass(frozen=True)
class MonthlyView:
    """What the Monthly page shows: one month's spending and the months around it."""

    spending: MonthlySpending
    months: list[date]  # every month with a payment, newest first
    selected: date
    older: date | None
    newer: date | None
    salary_months: bool


def load_monthly(
    conn: sqlite3.Connection, category_types: dict[str, str], today: date, month: date | None
) -> MonthlyView:
    """The spending of `month`, or of the latest month with payments when it is None."""
    rows = transactions_with_category(conn)
    salary_day = load_settings(conn).salary_day
    paydays = salary_paydays(rows)
    months = payment_months(rows, salary_day, paydays)
    if month is None:
        # The latest month with data rather than the clock's: exports are
        # often weeks old, and an empty current month would open the page.
        selected = months[0] if months else today.replace(day=1)
    else:
        selected = month
    older, newer = adjacent_months(months, selected)
    spending = monthly_spending(rows, category_types, period_for(selected, salary_day, paydays))
    return MonthlyView(spending, months, selected, older, newer, salary_day is not None)


def _names_of_type(category_types: dict[str, str], category_type: str) -> tuple[str, ...]:
    return tuple(sorted(name for name, type_ in category_types.items() if type_ == category_type))


def _inflows(
    rows: list[Row],
    category_types: dict[str, str],
    salary_day: int,
    estimate_date: date,
    start: date,
    end: date,
) -> list[DueItem]:
    """Recurring income still expected within [start, end], named by category.

    Same occurrence and already-booked rule as the fixed payments, so one
    income series is treated exactly like one fixed source.
    """
    series = detect_income(rows, category_types, salary_day, estimate_date)
    sources = tuple(
        FixedSource(p.category or p.name, (p.schedule,), p.last_paid_date) for p in series
    )
    return forecast.fixed_due(sources, start, end)


def _fixed_sources(
    conn: sqlite3.Connection, views: list[DebtView], txs: list[ParsedTransaction]
) -> tuple[FixedSource, ...]:
    """Recurring payments plus debt schedules, with each real payment counted once.

    A recurring payment linked to a debt is the same money (SPEC §7), and the
    debt's own schedule knows its end and final rate, so the debt wins.
    """
    linked_ids = {payment.id for view in views for payment in view.linked_payments}
    recurring = [
        FixedSource(payment.name, payment.periods, payment.last_paid_date)
        for payment in list_payments(conn)
        if payment.id not in linked_ids
    ]
    owed = [
        FixedSource(
            view.debt.name,
            model.debt_schedule(view.debt, view.status),
            model.last_payment_date(view.debt, txs),
        )
        for view in views
    ]
    # A paid-off debt's schedule is empty, which is how it drops out (SPEC §7).
    return tuple(recurring + owed)
