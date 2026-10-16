"""Utility cost and settlement math (SPEC §13 Utilities).

Pure functions over daily usage in meter units. Everything runs in exact fractions;
each figure that is shown is rounded half up once, at the end.
"""

from __future__ import annotations

import calendar
import math
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from fractions import Fraction

from sonar.utilities.model import BillingPeriod, Charge

DailyUsage = dict[date, Fraction]
Booking = tuple[date, int]  # booking date, signed cents
Advance = tuple[date, int]  # booking date, cents > 0

CALORIFIC_SCALE = 10**8  # state factor and calorific value are both in ten-thousandths
CENTS_PER_MICRO_EURO = Fraction(1, 10**4)  # µ€ per kWh or m³ to cents per kWh or m³
WHOLE_EURO_CENTS = 100
GRACE_DAYS = 14  # a bill settles late: its last advance and the settlement itself fall this far out
ADVANCES_PER_YEAR = 11
SCHEDULE_MATCH_DAYS = 7  # a debit this close to a scheduled date pays it
CHART_MONTHS = 24


@dataclass(frozen=True)
class MonthFigure:
    month: date  # first day of the calendar month
    kwh: int
    cost_cents: int


@dataclass(frozen=True)
class ChartMonth:
    month: date  # first day of the calendar month
    kwh: int
    cost_cents: int
    cycle: str  # "previous" or "current"
    projected: bool


@dataclass(frozen=True)
class ChargeFigure:
    name: str  # "drinking" or "wastewater"
    cost_so_far_cents: int
    projected_cost_cents: int


@dataclass(frozen=True)
class MeterStatus:
    as_of: date | None
    cost_so_far_cents: int | None
    paid_cents: int
    paid_since: date
    advance_count: int
    remaining_advance_count: int
    left_cents: int | None
    projected_cost_cents: int | None
    remaining_advances_cents: int
    settlement_cents: int | None  # positive is a refund
    worst_settlement_cents: int | None
    suggested_advance_cents: int | None  # None for a schedule
    charges: tuple[ChargeFigure, ...]  # water with a projection only
    advance_mode: str
    remaining_advance_dates: tuple[date, ...]  # a schedule's unpaid dates after today
    debit_date: date  # when the bank debits the settlement


def round_half_up(value: Fraction) -> int:
    return math.floor(value + Fraction(1, 2))


def days_in_month(day: date) -> int:
    return calendar.monthrange(day.year, day.month)[1]


def same_day_last_year(day: date) -> date:
    """The same calendar day a year earlier; 29 February maps to 28 February."""
    if day.month == 2 and day.day == 29:
        return date(day.year - 1, 2, 28)
    return date(day.year - 1, day.month, day.day)


def current_period(periods: Iterable[BillingPeriod], today: date) -> BillingPeriod | None:
    return period_on(periods, today)


def period_on(periods: Iterable[BillingPeriod], day: date) -> BillingPeriod | None:
    for period in periods:
        if period.start_date <= day <= period.settlement_date:
            return period
    return None


def daily_kwh(kind: str, periods: Sequence[BillingPeriod], usage: DailyUsage) -> DailyUsage:
    """kWh per day by the period in force; days outside every period are left out."""
    result: DailyUsage = {}
    for day, units in usage.items():
        period = period_on(periods, day)
        if period is not None:
            result[day] = units * _kwh_per_unit(kind, period)
    return result


def cost(
    kind: str,
    periods: Sequence[BillingPeriod],
    usage: DailyUsage,
    first: date,
    last: date,
) -> int:
    """Cents for the days of [first, last] that have usage and a period in force."""
    return round_half_up(_exact_cost(periods, daily_kwh(kind, periods, usage), first, last))


def month_figures(
    kind: str, periods: Sequence[BillingPeriod], usage: DailyUsage
) -> list[MonthFigure]:
    """Usage and cost of every calendar month whose days all have usage and a period."""
    kwh_by_day = daily_kwh(kind, periods, usage)
    figures = []
    for month in _months_touched(kwh_by_day):
        days = list(_days(month, month.replace(day=days_in_month(month))))
        if all(day in kwh_by_day for day in days):
            figures.append(
                MonthFigure(
                    month,
                    kwh=round_half_up(sum(kwh_by_day[day] for day in days)),
                    cost_cents=round_half_up(_exact_cost(periods, kwh_by_day, days[0], days[-1])),
                )
            )
    return figures


def cycle_months(
    kind: str, periods: Sequence[BillingPeriod], usage: DailyUsage, today: date
) -> list[ChartMonth]:
    """The previous and the current billing cycle month by month, the latest 24.

    A month belongs to the period in force on its 1st. The current cycle is the period in
    force today (none: the latest, without a projection); its months after the last full
    one are projected through the settlement month.
    """
    in_force = current_period(periods, today)
    current = in_force or max(periods, key=lambda p: p.settlement_date, default=None)
    if current is None:
        return []
    previous = _previous_period(periods, current)
    cycles = {"previous": previous, "current": current}
    actual = [
        ChartMonth(figure.month, figure.kwh, figure.cost_cents, cycle, projected=False)
        for figure in month_figures(kind, periods, usage)
        for cycle, period in cycles.items()
        if period is not None and period_on([period], figure.month) is not None
    ]
    projected = _projected_months(kind, periods, current, usage, actual) if in_force else []
    return (actual + projected)[-CHART_MONTHS:]


def _projected_months(
    kind: str,
    periods: Sequence[BillingPeriod],
    period: BillingPeriod,
    usage: DailyUsage,
    actual: list[ChartMonth],
) -> list[ChartMonth]:
    """Measured days before `as_of` plus the seasonal days after, priced by the period."""
    as_of = _usage_end(period, usage)
    if as_of is None:
        return []
    kwh_by_day = {
        **daily_kwh(kind, periods, usage),
        **seasonal_daily_kwh(kind, period, usage, as_of),
    }
    last_actual = max((m.month for m in actual if m.cycle == "current"), default=None)
    months = []
    for month in _cycle_month_starts(period):
        if last_actual is not None and month <= last_actual:
            continue
        last = min(month.replace(day=days_in_month(month)), period.settlement_date)
        days = {day: kwh_by_day[day] for day in _days(month, last) if day in kwh_by_day}
        total = sum(days.values(), start=Fraction(0))
        cost_cents = round_half_up(_rest_cost(period, days))
        months.append(ChartMonth(month, round_half_up(total), cost_cents, "current", True))
    return months


def _usage_end(period: BillingPeriod, usage: DailyUsage) -> date | None:
    """The day after the last measured day of the period; None without usage in it.

    Usage covers [first point, last point), so the last point ends the days so far.
    """
    first_day = max(period.start_date, min(usage, default=date.max))
    end = min(
        max(usage, default=date.min) + timedelta(days=1), period.settlement_date + timedelta(days=1)
    )
    return end if first_day < end else None


def _cycle_month_starts(period: BillingPeriod) -> Iterator[date]:
    """First days of the months whose 1st falls in the period."""
    month = period.start_date.replace(day=1)
    while month <= period.settlement_date:
        if month >= period.start_date:
            yield month
        month = (month + timedelta(days=31)).replace(day=1)


def meter_status(
    kind: str,
    periods: Sequence[BillingPeriod],
    usage: DailyUsage,
    bookings: Iterable[Booking],
    today: date,
) -> MeterStatus | None:
    """The outlook of the period in force today, or None without one."""
    period = current_period(periods, today)
    if period is None:
        return None
    previous = _previous_period(periods, period)
    paid_since = _paid_since(period, previous)
    paid_advances = _paid_advances(bookings, previous, paid_since, _paid_until(period, today))
    paid = sum(cents for _, cents in paid_advances)
    advance_count, remaining_dates, due_count = _advance_plan(
        period, paid_since, paid_advances, today
    )
    remaining_advances = period.advance_cents * due_count
    debit_date = period.settlement_date + timedelta(days=period.settlement_debit_days)

    end = _usage_end(period, usage)
    if end is None:
        return MeterStatus(
            as_of=None,
            cost_so_far_cents=None,
            paid_cents=paid,
            paid_since=paid_since,
            advance_count=advance_count,
            remaining_advance_count=due_count,
            left_cents=None,
            projected_cost_cents=None,
            remaining_advances_cents=remaining_advances,
            settlement_cents=None,
            worst_settlement_cents=None,
            suggested_advance_cents=None,
            charges=(),
            advance_mode=period.advance_mode,
            remaining_advance_dates=remaining_dates,
            debit_date=debit_date,
        )

    first_day = max(period.start_date, min(usage))
    kwh_by_day = daily_kwh(kind, periods, usage)
    so_far = _exact_costs(periods, kwh_by_day, first_day, end - timedelta(days=1))
    rest = _rest_costs(period, seasonal_daily_kwh(kind, period, usage, end))
    cost_so_far = _total(so_far)
    projected = cost_so_far + _total(rest)
    worst = cost_so_far + _rest_cost(period, worst_daily_kwh(kind, period, usage, end))
    projected_cents = round_half_up(projected)
    cost_so_far_cents = round_half_up(cost_so_far)
    flexible = period.advance_mode == "flexible"
    return MeterStatus(
        as_of=end,
        cost_so_far_cents=cost_so_far_cents,
        paid_cents=paid,
        paid_since=paid_since,
        advance_count=advance_count,
        remaining_advance_count=due_count,
        left_cents=paid - cost_so_far_cents,
        projected_cost_cents=projected_cents,
        remaining_advances_cents=remaining_advances,
        settlement_cents=paid + remaining_advances - projected_cents,
        worst_settlement_cents=paid + remaining_advances - round_half_up(worst),
        suggested_advance_cents=suggested_advance(projected, paid, due_count) if flexible else None,
        charges=_charge_figures(kind, so_far, rest),
        advance_mode=period.advance_mode,
        remaining_advance_dates=remaining_dates,
        debit_date=debit_date,
    )


def _charge_figures(
    kind: str, so_far: dict[str, Fraction], rest: dict[str, Fraction]
) -> tuple[ChargeFigure, ...]:
    if kind != "water":
        return ()
    return tuple(
        ChargeFigure(
            name,
            cost_so_far_cents=round_half_up(so_far.get(name, Fraction(0))),
            projected_cost_cents=round_half_up(
                so_far.get(name, Fraction(0)) + rest.get(name, Fraction(0))
            ),
        )
        for name in ("drinking", "wastewater")
    )


def seasonal_daily_kwh(
    kind: str, period: BillingPeriod, usage: DailyUsage, as_of: date
) -> DailyUsage:
    """Projected kWh for each day of [as_of, settlement date].

    A day follows last year's usage on the same day, moved halfway towards this year's
    trend (this year's units over last year's in the latest full month). Without a trend
    or a last-year day it falls back to the period's expected kWh per day.
    """
    ratio = _seasonal_ratio(period, usage, as_of)
    per_unit = _kwh_per_unit(kind, period)
    projection: DailyUsage = {}
    for day in _days(as_of, period.settlement_date):
        previous = usage.get(same_day_last_year(day))
        if ratio is None or previous is None:
            projection[day] = _expected_usage_per_day(period)
        else:
            projection[day] = previous * (1 + ratio) / 2 * per_unit
    return projection


def worst_daily_kwh(kind: str, period: BillingPeriod, usage: DailyUsage, as_of: date) -> DailyUsage:
    """Per day of [as_of, settlement date] the highest of the seasonal kWh, the expected kWh
    per day and last year's kWh on that day."""
    per_unit = _kwh_per_unit(kind, period)
    worst: DailyUsage = {}
    for day, seasonal in seasonal_daily_kwh(kind, period, usage, as_of).items():
        candidates = [seasonal, _expected_usage_per_day(period)]
        previous = usage.get(same_day_last_year(day))
        if previous is not None:
            candidates.append(previous * per_unit)
        worst[day] = max(candidates)
    return worst


def _expected_usage_per_day(period: BillingPeriod) -> Fraction:
    return Fraction(period.expected_usage, 365)


def _seasonal_ratio(period: BillingPeriod, usage: DailyUsage, as_of: date) -> Fraction | None:
    """Units of the latest full month over the same month a year earlier; None if unknown."""
    month = _latest_full_month(period, usage, as_of)
    if month is None:
        return None
    this_year = _month_units(usage, month)
    last_year = _month_units(usage, month.replace(year=month.year - 1))
    if this_year is None or not last_year:
        return None
    return this_year / last_year


def _latest_full_month(period: BillingPeriod, usage: DailyUsage, as_of: date) -> date | None:
    """First day of the latest month inside the period with usage on all its days before `as_of`."""
    latest_day = min(as_of - timedelta(days=1), period.settlement_date)
    month = latest_day.replace(day=1)
    while month >= period.start_date:
        last = month.replace(day=days_in_month(month))
        if last <= latest_day and _month_units(usage, month) is not None:
            return month
        month = (month - timedelta(days=1)).replace(day=1)
    return None


def _month_units(usage: DailyUsage, month: date) -> Fraction | None:
    days = list(_days(month, month.replace(day=days_in_month(month))))
    if any(day not in usage for day in days):
        return None
    return sum((usage[day] for day in days), start=Fraction(0))


def _kwh_per_unit(kind: str, period: BillingPeriod) -> Fraction:
    if kind != "gas":
        return Fraction(1)
    assert period.state_factor_e4 is not None and period.calorific_value_e4 is not None
    return Fraction(period.state_factor_e4 * period.calorific_value_e4, CALORIFIC_SCALE)


def _days(first: date, last: date) -> Iterator[date]:
    for offset in range((last - first).days + 1):
        yield first + timedelta(days=offset)


def _months_touched(kwh_by_day: DailyUsage) -> list[date]:
    months = sorted({day.replace(day=1) for day in kwh_by_day})
    return months


def _fee_per_day(period: BillingPeriod, day: date) -> Fraction:
    return Fraction(period.base_fee_cents, days_in_month(day))


def _day_costs(period: BillingPeriod, day: date, units: Fraction) -> dict[str, Fraction]:
    """A day's cents by part: each water charge with its VAT, else the energy with its fee."""
    if period.drinking is None or period.wastewater is None:
        return {"energy": _energy_cents(period, units) + _fee_per_day(period, day)}
    return {
        "drinking": _charge_cents(period.drinking, day, units),
        "wastewater": _charge_cents(period.wastewater, day, units),
    }


def _charge_cents(charge: Charge, day: date, units: Fraction) -> Fraction:
    """The m³ at the net price plus the day's share of a twelfth of the yearly fee, then VAT."""
    net = units * charge.unit_price_micro * CENTS_PER_MICRO_EURO + Fraction(
        charge.base_fee_cents, 12 * days_in_month(day)
    )
    return net * (100 + charge.vat_percent) / 100


def _add_costs(totals: dict[str, Fraction], costs: dict[str, Fraction]) -> None:
    for part, cents in costs.items():
        totals[part] = totals.get(part, Fraction(0)) + cents


def _total(costs: dict[str, Fraction]) -> Fraction:
    return sum(costs.values(), start=Fraction(0))


def _exact_costs(
    periods: Sequence[BillingPeriod], kwh_by_day: DailyUsage, first: date, last: date
) -> dict[str, Fraction]:
    """Cents by part for the days of [first, last] that have usage and a period in force."""
    totals: dict[str, Fraction] = {}
    for day in _days(first, last):
        period = period_on(periods, day)
        if period is not None and day in kwh_by_day:
            _add_costs(totals, _day_costs(period, day, kwh_by_day[day]))
    return totals


def _exact_cost(
    periods: Sequence[BillingPeriod], kwh_by_day: DailyUsage, first: date, last: date
) -> Fraction:
    return _total(_exact_costs(periods, kwh_by_day, first, last))


def _energy_cents(period: BillingPeriod, kwh: Fraction) -> Fraction:
    return kwh * period.unit_price_micro * CENTS_PER_MICRO_EURO


def _rest_costs(period: BillingPeriod, kwh_by_day: DailyUsage) -> dict[str, Fraction]:
    """Cents by part for the projected days, all priced by the current period."""
    totals: dict[str, Fraction] = {}
    for day, kwh in kwh_by_day.items():
        _add_costs(totals, _day_costs(period, day, kwh))
    return totals


def _rest_cost(period: BillingPeriod, kwh_by_day: DailyUsage) -> Fraction:
    return _total(_rest_costs(period, kwh_by_day))


def _previous_period(
    periods: Sequence[BillingPeriod], period: BillingPeriod
) -> BillingPeriod | None:
    earlier = [other for other in periods if other.settlement_date < period.start_date]
    return max(earlier, key=lambda other: other.settlement_date, default=None)


def _paid_since(period: BillingPeriod, previous: BillingPeriod | None) -> date:
    """The previous bill's own settlement payment lands in the days right after it."""
    if previous is None:
        return period.start_date
    return max(period.start_date, previous.settlement_date + timedelta(days=GRACE_DAYS + 1))


def _paid_until(period: BillingPeriod, today: date) -> date:
    return min(today, period.settlement_date + timedelta(days=GRACE_DAYS))


def _paid_advances(
    bookings: Iterable[Booking], previous: BillingPeriod | None, since: date, until: date
) -> list[Advance]:
    """Debits in the paid window as positive cents, oldest first.

    A debit equal to the previous bill's settled amount is that bill's settlement, not an advance.
    """
    settled = previous.settled_cents if previous else None
    return sorted(
        (booked, -cents)
        for booked, cents in bookings
        if cents < 0
        and since <= booked <= until
        and not (previous and cents == settled and booked > previous.settlement_date)
    )


def _advance_plan(
    period: BillingPeriod, paid_since: date, paid_advances: list[Advance], today: date
) -> tuple[int, tuple[date, ...], int]:
    """Advance count, a schedule's remaining dates and the number of advances still due."""
    if period.advance_mode == "schedule":
        remaining = _remaining_advance_dates(period, paid_advances, today)
        return len(period.advance_dates), remaining, len(remaining)
    count = _advance_count(period)
    latest_advance = paid_advances[-1][0] if paid_advances else None
    due = _advances_due(period, paid_since, latest_advance, count - len(paid_advances))
    return count, (), due


def _remaining_advance_dates(
    period: BillingPeriod, paid_advances: list[Advance], today: date
) -> tuple[date, ...]:
    """Scheduled dates after today with no counted debit within a week before or after."""
    window = timedelta(days=SCHEDULE_MATCH_DAYS)
    return tuple(
        due
        for due in sorted(period.advance_dates)
        if due > today and not any(abs(booked - due) <= window for booked, _ in paid_advances)
    )


def _advance_count(period: BillingPeriod) -> int:
    """Eleven advances a year, pro rata by the months the period covers."""
    months = sum(
        (
            Fraction(1, days_in_month(day))
            for day in _days(period.start_date, period.settlement_date)
        ),
        start=Fraction(0),
    )
    return max(1, round_half_up(months * ADVANCES_PER_YEAR / 12))


def _advances_due(
    period: BillingPeriod, paid_since: date, latest_advance: date | None, advances_left: int
) -> int:
    """Advance days after the latest advance (none: from `paid_since`) capped by `advances_left`."""
    advance_day = (latest_advance or paid_since).day
    first = latest_advance + timedelta(days=1) if latest_advance else paid_since
    last = period.settlement_date + timedelta(days=GRACE_DAYS)
    count = 0
    year, month = first.year, first.month
    while date(year, month, 1) <= last:
        due = date(year, month, min(advance_day, calendar.monthrange(year, month)[1]))
        if first <= due <= last:
            count += 1
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return min(count, max(0, advances_left))


def suggested_advance(projected_cost: Fraction, paid_cents: int, remaining_advances: int) -> int:
    """What to pay per advance from now on to cover the projected cost, in whole euros.

    The unpaid rest is spread over the remaining advances and the settlement, which is
    why the divisor is one more.
    """
    unpaid = max(Fraction(0), projected_cost - paid_cents)
    return math.ceil(unpaid / (remaining_advances + 1) / WHOLE_EURO_CENTS) * WHOLE_EURO_CENTS
