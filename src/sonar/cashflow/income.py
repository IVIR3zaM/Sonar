"""Expected monthly income (SPEC §13 Recurring income).

Expected income is the best salary of the last 3 complete pay cycles plus the
monthly equivalent of the detected recurring income (benefits and similar).

The salary is matched by distance to payday, not by the cycle a credit is booked
in: employers often pay a day or two early, so a credit at payday - 2 belongs to
that payday's cycle. A credit is the salary when it is booked within
`SALARY_DAY_DISTANCE` days of the payday, the same rule that keeps the salary
out of recurring income. Pure functions only: `estimate_date` is passed in.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from sonar.cashflow.payday import complete_cycles
from sonar.categorization.groups import INCOME
from sonar.recurring.detect import SALARY_DAY_DISTANCE, Row, detect_income

_CYCLES_LOOKED_AT = 3
_MONTHS_PER_YEAR = 12


@dataclass(frozen=True)
class ExpectedIncome:
    salary_cents: int
    recurring_cents: int
    total_cents: int


def expected_income(
    rows: Iterable[Row], category_types: dict[str, str], salary_day: int, estimate_date: date
) -> ExpectedIncome | None:
    """None without salary history: recurring income alone is no income estimate."""
    rows = list(rows)
    salary = _best_salary(rows, category_types, salary_day, estimate_date)
    if salary == 0:
        return None
    recurring = _recurring_monthly(rows, category_types, salary_day, estimate_date)
    return ExpectedIncome(salary, recurring, salary + recurring)


def _best_salary(
    rows: list[Row], category_types: dict[str, str], salary_day: int, estimate_date: date
) -> int:
    credits = [
        (tx.booking_date, tx.amount_cents)
        for tx, category in rows
        if tx.amount_cents > 0 and category_types.get(category or "") == INCOME
    ]
    paydays = [
        cycle.start for cycle in complete_cycles(estimate_date, salary_day, _CYCLES_LOOKED_AT)
    ]
    return max(
        (
            sum(
                cents
                for booked, cents in credits
                if abs((booked - payday).days) <= SALARY_DAY_DISTANCE
            )
            for payday in paydays
        ),
        default=0,
    )


def _recurring_monthly(
    rows: list[Row], category_types: dict[str, str], salary_day: int, estimate_date: date
) -> int:
    series = detect_income(rows, category_types, salary_day, estimate_date)
    yearly = sum(
        p.schedule.amount_cents * _MONTHS_PER_YEAR // p.schedule.interval_months for p in series
    )
    # Integer round half up; the total is never negative, so this is exact.
    return (yearly * 2 + _MONTHS_PER_YEAR) // (_MONTHS_PER_YEAR * 2)
