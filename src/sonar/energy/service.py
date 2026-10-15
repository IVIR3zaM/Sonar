"""Energy service (SPEC §13 Energy): coordinates the energy store, the transactions and the math."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from sonar.categorization.store import transactions_with_category
from sonar.energy.model import BillingPeriod, Exchange, Meter, Reading
from sonar.energy.settlement import (
    Booking,
    ChartMonth,
    MeterStatus,
    current_period,
    cycle_months,
    meter_status,
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
    chart_months: list[ChartMonth]  # the previous and the current cycle


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
        status=meter_status(kind, billing, usage, _bookings(transactions, in_force), today),
        chart_months=cycle_months(kind, billing, usage, today),
    )


def _bookings(transactions: list, period: BillingPeriod | None) -> list[Booking]:
    """Signed amounts filed under the period's category; the math picks the advances."""
    if period is None or period.category is None:
        return []
    return [
        (transaction.booking_date, transaction.amount_cents)
        for transaction, category in transactions
        if category == period.category
    ]


@dataclass(frozen=True)
class SettlementSummary:
    """One meter's projected settlement, as the dashboard shows and forecasts it."""

    meter_name: str
    settlement_date: date
    settlement_cents: int  # positive is a refund
    worst_settlement_cents: int
    suggested_advance_cents: int | None  # None without a projection


def settlement_summaries(conn: sqlite3.Connection, today: date) -> list[SettlementSummary]:
    """The meters with a period in force on `today` and usage to project from."""
    summaries = []
    for view in load_energy(conn, today):
        status = view.status
        if status is None or status.settlement_cents is None:
            continue
        period = current_period([p.item for p in view.periods], today)
        assert period is not None  # a status exists only for a period in force
        summaries.append(
            SettlementSummary(
                meter_name=view.meter.name,
                settlement_date=period.settlement_date,
                settlement_cents=status.settlement_cents,
                worst_settlement_cents=status.worst_settlement_cents,
                suggested_advance_cents=status.suggested_advance_cents,
            )
        )
    return summaries
