"""Usage from meter readings (SPEC §13 Energy): the continuous series and daily usage."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from fractions import Fraction

from sonar.utilities.model import Exchange, FieldError, Reading

Series = list[tuple[date, int]]

MILLI = 1000


def continuous_series(readings: Iterable[Reading], exchanges: Iterable[Exchange]) -> Series:
    """Points (date, value_milli) that never reset: each exchange carries its offset forward.

    A reading counts the offsets of exchanges dated before it; the exchange itself is
    the point (date, old_final + earlier offsets), so the swap day closes the old meter.
    """
    ordered_exchanges = sorted(exchanges, key=lambda exchange: exchange.exchange_date)
    points: Series = []
    offset = 0
    for exchange in ordered_exchanges:
        points.append((exchange.exchange_date, exchange.old_final_milli + offset))
        offset += exchange.old_final_milli - exchange.new_start_milli
    for reading in readings:
        before = sum(
            exchange.old_final_milli - exchange.new_start_milli
            for exchange in ordered_exchanges
            if exchange.exchange_date < reading.reading_date
        )
        points.append((reading.reading_date, reading.value_milli + before))
    return sorted(points)


def check_series(readings: Iterable[Reading], exchanges: Iterable[Exchange]) -> None:
    """Raise FieldError for a shared date ("date") or a series that drops ("value")."""
    readings = list(readings)
    exchanges = list(exchanges)
    dates = [reading.reading_date for reading in readings]
    exchange_dates = [exchange.exchange_date for exchange in exchanges]
    for day in sorted(set(dates + exchange_dates)):
        if dates.count(day) + exchange_dates.count(day) > 1:
            raise FieldError("date", f"only one reading or exchange on {day.isoformat()}")
    previous = None
    for day, value in continuous_series(readings, exchanges):
        if previous is not None and value < previous:
            raise FieldError("value", f"the meter value drops on {day.isoformat()}")
        previous = value


def daily_usage(series: Series) -> dict[date, Fraction]:
    """Meter units used on each day of [first point, last point), each interval spread evenly."""
    usage: dict[date, Fraction] = {}
    for (start, start_value), (end, end_value) in zip(series, series[1:], strict=False):
        days = (end - start).days
        if days <= 0:
            continue
        per_day = Fraction(end_value - start_value, MILLI * days)
        for offset in range(days):
            usage[start + timedelta(days=offset)] = per_day
    return usage
