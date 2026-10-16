"""Utilities service (SPEC §13 Utilities): coordinates the store, the transactions and the math."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

from sonar.categorization.store import transactions_with_category
from sonar.utilities.garden import (
    GardenShare,
    garden_conflicts,
    garden_cycle_months,
    garden_usage,
)
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
    list_zeroed,
)
from sonar.utilities.usage import Series, continuous_series, daily_usage


@dataclass(frozen=True)
class ConflictEntry:
    """A garden interval named in a case, with the point that closes it."""

    meter_id: int
    start_date: date
    end_date: date  # the interval's closing reading or exchange, exclusive
    used_milli: int  # the garden's m³ on the case's days
    reading_id: int | None  # the closing point is a reading ...
    exchange_id: int | None  # ... or an exchange


@dataclass(frozen=True)
class ConflictCase:
    """A run of days the gardens measured more than their main meter, for the owner to resolve."""

    main_meter_id: int
    start_date: date
    end_date: date  # the day after the run's last day
    excess_milli: int
    zeroed: bool
    gardens: tuple[ConflictEntry, ...]


@dataclass(frozen=True)
class MeterView:
    id: int
    meter: Meter
    periods: list[Stored[BillingPeriod]]
    exchanges: list[Stored[Exchange]]
    readings: list[Stored[Reading]]
    status: MeterStatus | None  # None without a period in force today
    chart_months: list[ChartMonth]  # the previous and the current cycle
    main_meter_id: int | None  # set on a garden meter
    garden_ids: tuple[int, ...]  # the garden meters of a main meter
    conflicts: tuple[ConflictCase, ...]  # a main meter's cases, or those naming a garden


def load_utilities(conn: sqlite3.Connection, today: date) -> list[MeterView]:
    transactions = transactions_with_category(conn)
    meters = list_meters(conn)
    return [_meter_view(conn, stored, meters, transactions, today) for stored in meters]


def _meter_view(
    conn: sqlite3.Connection,
    stored: Stored[Meter],
    meters: list[Stored[Meter]],
    transactions: list,
    today: date,
) -> MeterView:
    periods = list_periods(conn, stored.id)
    exchanges = list_exchanges(conn, stored.id)
    readings = list_readings(conn, stored.id)
    kind = stored.item.kind
    billing = [period.item for period in periods]
    usage = _usage(readings, exchanges)
    main_id = stored.item.main_meter_id
    garden_ids = _garden_ids(meters, stored.id)
    garden = _garden_usage(conn, garden_ids, billing)
    in_force = current_period(billing, today)
    if main_id is None:
        chart = cycle_months(kind, billing, usage, today, garden=garden)
        cases = _conflict_cases(conn, stored.id, garden_ids)
    else:
        main_periods = [period.item for period in list_periods(conn, main_id)]
        chart = garden_cycle_months(main_periods, usage, today)
        cases = [
            case
            for case in _conflict_cases(conn, main_id, _garden_ids(meters, main_id))
            if any(entry.meter_id == stored.id for entry in case.gardens)
        ]
    return MeterView(
        id=stored.id,
        meter=stored.item,
        periods=periods,
        exchanges=exchanges,
        readings=readings,
        status=meter_status(
            kind, billing, usage, _bookings(transactions, in_force), today, garden=garden
        ),
        chart_months=chart,
        main_meter_id=main_id,
        garden_ids=garden_ids,
        conflicts=tuple(cases),
    )


def _garden_series(conn: sqlite3.Connection, garden_ids: tuple[int, ...]) -> dict[int, Series]:
    return {
        garden_id: continuous_series(
            [r.item for r in list_readings(conn, garden_id)],
            [e.item for e in list_exchanges(conn, garden_id)],
        )
        for garden_id in garden_ids
    }


def _garden_usage(
    conn: sqlite3.Connection, garden_ids: tuple[int, ...], periods: list[BillingPeriod]
) -> DailyUsage | None:
    """The gardens' m³ per day behind a main meter; None for a meter without garden meters."""
    if not garden_ids:
        return None
    series = _garden_series(conn, garden_ids).values()
    return garden_usage(periods, [daily_usage(points) for points in series])


def _garden_ids(meters: list[Stored[Meter]], main_id: int) -> tuple[int, ...]:
    return tuple(other.id for other in meters if other.item.main_meter_id == main_id)


def _conflict_cases(
    conn: sqlite3.Connection, main_id: int, garden_ids: tuple[int, ...]
) -> list[ConflictCase]:
    if not garden_ids:
        return []
    main = continuous_series(
        [r.item for r in list_readings(conn, main_id)],
        [e.item for e in list_exchanges(conn, main_id)],
    )
    zeroed = set(list_zeroed(conn, main_id))
    return [
        ConflictCase(
            main_id,
            conflict.start_date,
            conflict.end_date,
            conflict.excess_milli,
            (conflict.start_date, conflict.end_date) in zeroed,
            tuple(_conflict_entry(conn, share) for share in conflict.gardens),
        )
        for conflict in garden_conflicts(main, _garden_series(conn, garden_ids))
    ]


def _conflict_entry(conn: sqlite3.Connection, share: GardenShare) -> ConflictEntry:
    closing = share.end_date
    reading_id = next(
        (r.id for r in list_readings(conn, share.meter_id) if r.item.reading_date == closing),
        None,
    )
    exchange_id = next(
        (e.id for e in list_exchanges(conn, share.meter_id) if e.item.exchange_date == closing),
        None,
    )
    return ConflictEntry(
        share.meter_id,
        share.start_date,
        share.end_date,
        share.used_milli,
        reading_id,
        exchange_id,
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

    meter_id: int
    meter_name: str
    period: BillingPeriod | None  # the one in force
    category: str | None  # of the period in force; a recurring payment in it can take the advances
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
        garden = _garden_usage(conn, view.garden_ids, periods)
        ended = _ended_settlement(view, periods, transactions, garden, today)
        if current is None and ended is None:
            continue
        schedule = view.status.remaining_advance_dates if view.status else ()
        flows.append(
            MeterCashflow(
                meter_id=view.id,
                meter_name=view.meter.name,
                period=current,
                category=current.category if current else None,
                advance_cents=current.advance_cents if current else 0,
                advance_dates=schedule,
                ended_debit_date=ended[0] if ended else None,
                ended_settlement_cents=ended[1] if ended else None,
            )
        )
    return flows


def _ended_settlement(
    view: MeterView,
    periods: list[BillingPeriod],
    transactions: list,
    garden: DailyUsage | None,
    today: date,
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
            garden=garden,
        )
        cents = None if status is None else status.settlement_cents
    if cents is None:
        return None
    return period.settlement_date + timedelta(days=period.settlement_debit_days), cents
