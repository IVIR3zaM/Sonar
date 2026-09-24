"""DB shell for the dashboard (SPEC §9): gathers every figure the page shows.

The pure pieces (payday, forecast, variable_forecast, debts) do the math; this
module only reads the stored data and wires them together, so the web layer
renders a single `Dashboard` and never repeats a forecast rule.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Literal

from sonar import debts, forecast, payday
from sonar.balance import BalanceEntry
from sonar.categorizing import transactions_with_category, uncategorized_count
from sonar.debt_store import DebtView, debt_overview, remaining_cents
from sonar.forecast import DueItem, FixedCosts, FixedSource, Projection
from sonar.recurring import list_payments
from sonar.settings_store import current_balance, load_settings
from sonar.transactions import ParsedTransaction
from sonar.variable_forecast import HISTORY_CYCLES, VariableForecast, variable_forecast


@dataclass(frozen=True)
class Dashboard:
    salary_day: int | None
    payday: date | None
    days_to_payday: int | None
    balance: BalanceEntry | None
    overdraft_limit_cents: int
    due: list[DueItem]
    due_total_cents: int
    variable: VariableForecast | None
    projection: Projection | None
    light: Literal["green", "yellow", "red"] | None
    fixed_costs: FixedCosts
    debts: list[tuple[str, int]]
    debts_total_cents: int
    uncategorized_count: int


def load_dashboard(
    conn: sqlite3.Connection, category_types: dict[str, str], today: date
) -> Dashboard:
    """Everything the dashboard shows, as of `today`."""
    settings = load_settings(conn)
    balance = current_balance(conn)
    rows = transactions_with_category(conn)
    views = debt_overview(conn, today)
    sources = _fixed_sources(conn, views, [tx for tx, _ in rows])
    remaining = [(view.debt.name, remaining_cents(view)) for view in views]
    board = Dashboard(
        salary_day=settings.salary_day,
        payday=None,
        days_to_payday=None,
        balance=balance,
        overdraft_limit_cents=settings.overdraft_limit_cents,
        due=[],
        due_total_cents=0,
        variable=None,
        projection=None,
        light=None,
        fixed_costs=forecast.fixed_costs(sources, today),
        debts=remaining,
        debts_total_cents=sum(cents for _, cents in remaining),
        uncategorized_count=uncategorized_count(conn),
    )
    if settings.salary_day is None or balance is None:
        # Without both there is nothing to project from; the rest of the page
        # is still useful, so only the forecast part stays empty.
        return board

    next_payday = payday.next_payday(today, settings.salary_day)
    # The balance already contains everything booked up to its own date, so
    # the forecast starts the day after it, even when that is before today.
    start = balance.as_of + timedelta(days=1)
    end = next_payday - timedelta(days=1)
    # An import balance dated past payday would give a negative length; an
    # empty window simply means nothing more is expected.
    window_days = max((end - start).days + 1, 0)
    due = forecast.fixed_due(sources, start, end)
    due_total = sum(item.amount_cents for item in due)
    variable = variable_forecast(
        rows,
        category_types,
        payday.complete_cycles(today, settings.salary_day, HISTORY_CYCLES),
        window_days,
    )
    variable_range = None if variable is None else (variable.low_cents, variable.high_cents)
    projection = forecast.project(balance.amount_cents, due_total, variable_range)
    return replace(
        board,
        payday=next_payday,
        days_to_payday=(next_payday - today).days,
        due=due,
        due_total_cents=due_total,
        variable=variable,
        projection=projection,
        light=forecast.traffic_light(projection, settings.overdraft_limit_cents),
    )


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
