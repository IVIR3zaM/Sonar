"""Energy service (SPEC §13 Energy): coordinates the energy store, the transactions and the math."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from sonar.categorization.store import transactions_with_category
from sonar.energy.model import BillingPeriod, Exchange, Meter, Reading
from sonar.energy.settlement import (
    Advance,
    MeterStatus,
    MonthFigure,
    current_period,
    meter_status,
    month_figures,
)
from sonar.energy.store import (
    Stored,
    list_exchanges,
    list_meters,
    list_periods,
    list_readings,
)
from sonar.energy.usage import continuous_series, daily_usage


@dataclass(frozen=True)
class MeterView:
    id: int
    meter: Meter
    periods: list[Stored[BillingPeriod]]
    exchanges: list[Stored[Exchange]]
    readings: list[Stored[Reading]]
    status: MeterStatus | None  # None without a period in force today
    month_figures: list[MonthFigure]


def load_energy(conn: sqlite3.Connection, today: date) -> list[MeterView]:
    transactions = transactions_with_category(conn)
    return [_meter_view(conn, stored, transactions, today) for stored in list_meters(conn)]


def _meter_view(
    conn: sqlite3.Connection,
    stored: Stored[Meter],
    transactions: list,
    today: date,
) -> MeterView:
    periods = list_periods(conn, stored.id)
    exchanges = list_exchanges(conn, stored.id)
    readings = list_readings(conn, stored.id)
    kind = stored.item.kind
    billing = [period.item for period in periods]
    usage = daily_usage(continuous_series([r.item for r in readings], [e.item for e in exchanges]))
    in_force = current_period(billing, today)
    return MeterView(
        id=stored.id,
        meter=stored.item,
        periods=periods,
        exchanges=exchanges,
        readings=readings,
        status=meter_status(kind, billing, usage, _advances(transactions, in_force), today),
        month_figures=month_figures(kind, billing, usage),
    )


def _advances(transactions: list, period: BillingPeriod | None) -> list[Advance]:
    """Debits filed under the period's category, as positive cents; credits are ignored."""
    if period is None or period.category is None:
        return []
    return [
        (transaction.booking_date, -transaction.amount_cents)
        for transaction, category in transactions
        if category == period.category and transaction.amount_cents < 0
    ]
