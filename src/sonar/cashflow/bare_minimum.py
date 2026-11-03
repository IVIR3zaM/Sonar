"""Income needed to cover a full pay cycle (SPEC §13 Bare minimum)."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from sonar.cashflow.forecast import CycleCost, DueItem
from sonar.cashflow.lights_on import LOOKBACK_MONTHS, MonthSpend
from sonar.cashflow.payday import complete_cycles
from sonar.categorization.groups import INCOME
from sonar.recurring.detect import SALARY_DAY_DISTANCE, Row


@dataclass(frozen=True)
class CycleNeed:
    start: date
    end: date
    days: int
    fixed_cents: int
    lights_on_cents: int
    need_cents: int
    residual_cents: int


@dataclass(frozen=True)
class DebtEnd:
    name: str
    kind: str
    end_date: date
    rate_cents: int


@dataclass(frozen=True)
class BareMinimum:
    total_cents: int
    cycle: CycleNeed
    income_cents: int
    residual_cents: int
    debt_cents: int
    debt_share_percent: int
    occasional_cents: int
    occasional_margin_cents: int
    cycles: tuple[CycleNeed, ...]
    drops: tuple[DebtEnd, ...]


def cycle_income(
    rows: Iterable[Row], category_types: dict[str, str], salary_day: int, estimate_date: date
) -> int | None:
    """Lowest positive income total across three complete, salary-shifted cycles."""
    credits = [
        (tx.booking_date, tx.amount_cents)
        for tx, category in rows
        if tx.amount_cents > 0 and category_types.get(category or "") == INCOME
    ]
    shift = timedelta(days=SALARY_DAY_DISTANCE)
    totals = (
        sum(
            cents for booked, cents in credits if cycle.start - shift <= booked <= cycle.end - shift
        )
        for cycle in complete_cycles(estimate_date, salary_day, 3)
    )
    return min((total for total in totals if total > 0), default=None)


def occasional_per_month(months: Sequence[MonthSpend]) -> int:
    """Average occasional spend over the latest three complete months, half up."""
    recent = months[-LOOKBACK_MONTHS:]
    if not recent:
        return 0
    total = sum(month.occasional_cents for month in recent)
    return (2 * total + len(recent)) // (2 * len(recent))


def bare_minimum(
    cycles: Sequence[CycleCost],
    lights_on_daily_cents: int,
    debt_due: Iterable[DueItem],
    debt_ends: Iterable[DebtEnd],
    income_cents: int,
    occasional_cents: int,
    estimate_date: date,
) -> BareMinimum | None:
    needs = []
    for cycle in sorted(cycles, key=lambda cycle: cycle.start):
        if cycle.kind != "forecast":
            continue
        days = (cycle.end - cycle.start).days + 1
        lights_on = lights_on_daily_cents * days
        need = cycle.forecast_cents + lights_on
        needs.append(
            CycleNeed(
                cycle.start,
                cycle.end,
                days,
                cycle.forecast_cents,
                lights_on,
                need,
                income_cents - need,
            )
        )
    if not needs:
        return None
    peak = max(needs, key=lambda cycle: cycle.need_cents)
    debt = sum(item.amount_cents for item in debt_due if peak.start <= item.due_date <= peak.end)
    share = (200 * debt + peak.fixed_cents) // (2 * peak.fixed_cents) if peak.fixed_cents else 0
    last_end = max(cycle.end for cycle in needs)
    drops = tuple(
        sorted(
            (debt for debt in debt_ends if estimate_date < debt.end_date <= last_end),
            key=lambda debt: (debt.end_date, debt.name),
        )
    )
    return BareMinimum(
        total_cents=peak.need_cents,
        cycle=peak,
        income_cents=income_cents,
        residual_cents=peak.residual_cents,
        debt_cents=debt,
        debt_share_percent=share,
        occasional_cents=occasional_cents,
        occasional_margin_cents=peak.residual_cents - occasional_cents,
        cycles=tuple(needs),
        drops=drops,
    )
