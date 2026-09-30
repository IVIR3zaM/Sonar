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

from sonar import debts, forecast, lights_on, payday, spending_groups
from sonar.balance import BalanceEntry
from sonar.categorizing import transactions_with_category, uncategorized_count
from sonar.debt_store import DebtView, debt_overview, remaining_cents
from sonar.forecast import DueItem, FixedCosts, FixedSource, Projection
from sonar.lights_on import LightsOnForecast
from sonar.recurring import list_payments
from sonar.settings_store import current_balance, load_settings
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
    window_days: int | None
    lights_on_categories: tuple[str, ...]
    occasional_categories: tuple[str, ...]
    lights_on: LightsOnForecast | None
    # The same months' figures for a single day: what `lights_on` multiplies
    # by `window_days`, and what the Keep the lights on page shows.
    lights_on_daily: LightsOnForecast | None
    # Balance - due - expected lights-on spending: the margin (or, negative,
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
        window_days=None,
        lights_on_categories=_names_of_type(category_types, spending_groups.LIGHTS_ON),
        occasional_categories=_names_of_type(category_types, spending_groups.OCCASIONAL),
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
    until = lights_on.last_known_day(rows, balance.as_of)
    months = (
        []
        if until is None
        else lights_on.month_spends(rows, category_types, settings.salary_day, until)
    )
    lights = lights_on.lights_on_forecast(months, window_days)
    lights_range = None if lights is None else (lights.low_cents, lights.high_cents)
    projection = forecast.project(balance.amount_cents, due_total, lights_range)
    lights_expected = 0 if lights is None else lights.expected_cents
    return replace(
        board,
        payday=next_payday,
        days_to_payday=(next_payday - today).days,
        due=due,
        due_total_cents=due_total,
        window_days=window_days,
        lights_on=lights,
        lights_on_daily=lights_on.lights_on_forecast(months, 1),
        expected_cents=balance.amount_cents - due_total - lights_expected,
        projection=projection,
        light=forecast.traffic_light(projection, settings.overdraft_limit_cents),
    )


def _names_of_type(category_types: dict[str, str], category_type: str) -> tuple[str, ...]:
    return tuple(sorted(name for name, type_ in category_types.items() if type_ == category_type))


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
            debts.debt_schedule(view.debt, view.status),
            debts.last_payment_date(view.debt, txs),
        )
        for view in views
    ]
    # A paid-off debt's schedule is empty, which is how it drops out (SPEC §7).
    return tuple(recurring + owed)
