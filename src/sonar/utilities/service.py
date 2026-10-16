"""Utilities service (SPEC §13 Utilities): coordinates the store, the transactions and the math."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

from sonar.categorization.store import transactions_with_category
from sonar.utilities.model import BillingPeriod, Exchange, Meter, Reading
from sonar.utilities.settlement import (
    Booking,
    ChartMonth,
    DailyUsage,
    MeterStatus,
    current_period,
    cycle_months,
    meter_status,
)
from sonar.utilities.store import (
    Stored,
    list_exchanges,
    list_meters,
    list_periods,
    list_readings,
)
from sonar.utilities.usage import continuous_series, daily_usage


@dataclass(frozen=True)
class MeterView:
    id: int
    meter: Meter
    periods: list[Stored[BillingPeriod]]
    exchanges: list[Stored[Exchange]]
    readings: list[Stored[Reading]]
    status: MeterStatus | None  # None without a period in force today
    chart_months: list[ChartMonth]  # the previous and the current cycle


def load_utilities(conn: sqlite3.Connection, today: date) -> list[MeterView]:
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
    usage = _usage(readings, exchanges)
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


def _usage(readings: list[Stored[Reading]], exchanges: list[Stored[Exchange]]) -> DailyUsage:
    return daily_usage(continuous_series([r.item for r in readings], [e.item for e in exchanges]))


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
    debit_date: date  # when the bank debits the settlement
    settlement_cents: int  # positive is a refund
    worst_settlement_cents: int
    suggested_advance_cents: int | None  # None for a schedule
    advance_mode: str
    remaining_advance_dates: tuple[date, ...]  # a schedule's unpaid dates after the estimate date
    remaining_advances_cents: int


def settlement_summaries(conn: sqlite3.Connection, today: date) -> list[SettlementSummary]:
    """The meters with a period in force on `today` and usage to project from."""
    summaries = []
    for view in load_utilities(conn, today):
        status = view.status
        if status is None or status.settlement_cents is None:
            continue
        period = current_period([p.item for p in view.periods], today)
        assert period is not None  # a status exists only for a period in force
        summaries.append(
            SettlementSummary(
                meter_name=view.meter.name,
                settlement_date=period.settlement_date,
                debit_date=status.debit_date,
                settlement_cents=status.settlement_cents,
                worst_settlement_cents=status.worst_settlement_cents,
                suggested_advance_cents=status.suggested_advance_cents,
                advance_mode=status.advance_mode,
                remaining_advance_dates=status.remaining_advance_dates,
                remaining_advances_cents=status.remaining_advances_cents,
            )
        )
    return summaries


@dataclass(frozen=True)
class MeterCashflow:
    """What a meter still moves at the bank beyond the current settlement (SPEC §13 Utilities)."""

    meter_name: str
    category: str | None  # of the period in force; recurring payments in it cover the advances
    advance_cents: int
    advance_dates: tuple[date, ...]  # a schedule's unpaid dates after `today`; flexible has none
    ended_debit_date: date | None
    ended_settlement_cents: int | None  # positive is a refund


def meter_cashflows(conn: sqlite3.Connection, today: date) -> list[MeterCashflow]:
    """Per meter: the scheduled advances still due and the latest ended period's settlement."""
    transactions = transactions_with_category(conn)
    flows = []
    for view in load_utilities(conn, today):
        periods = [p.item for p in view.periods]
        current = current_period(periods, today)
        ended = _ended_settlement(view, periods, transactions, today)
        if current is None and ended is None:
            continue
        schedule = view.status.remaining_advance_dates if view.status else ()
        flows.append(
            MeterCashflow(
                meter_name=view.meter.name,
                category=current.category if current else None,
                advance_cents=current.advance_cents if current else 0,
                advance_dates=schedule,
                ended_debit_date=ended[0] if ended else None,
                ended_settlement_cents=ended[1] if ended else None,
            )
        )
    return flows


def _ended_settlement(
    view: MeterView, periods: list[BillingPeriod], transactions: list, today: date
) -> tuple[date, int] | None:
    """Debit date and signed amount of the latest period ended before `today`.

    The amount is the settled one when entered, else the projection as of its settlement date.
    """
    ended = [period for period in periods if period.settlement_date < today]
    if not ended:
        return None
    period = max(ended, key=lambda other: other.settlement_date)
    cents = period.settled_cents
    if cents is None:
        usage = _usage(view.readings, view.exchanges)
        status = meter_status(
            view.meter.kind,
            periods,
            usage,
            _bookings(transactions, period),
            period.settlement_date,
        )
        cents = None if status is None else status.settlement_cents
    if cents is None:
        return None
    return period.settlement_date + timedelta(days=period.settlement_debit_days), cents
