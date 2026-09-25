"""Variable spending forecast until payday (SPEC §9, Variable range method).

Each of the last complete salary cycles gives one sample: its total `variable`
spending, scaled to the days left in the current cycle. The range is the 25th
to 75th percentile of those samples and each category shows its median. The
method is deliberately simple so the dashboard tooltip can explain it in one
sentence. Pure functions only; exact `Fraction` arithmetic keeps cents exact
until the final rounding.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from fractions import Fraction

from sonar import spending_groups
from sonar.payday import Cycle
from sonar.transactions import ParsedTransaction

HISTORY_CYCLES = 6
MIN_CYCLES = 3
# Until N07 removes this module: the two groups that replaced the old single type.
VARIABLE = frozenset({spending_groups.LIGHTS_ON, spending_groups.OCCASIONAL})
LOW = Fraction(1, 4)
HIGH = Fraction(3, 4)
MEDIAN = Fraction(1, 2)

Row = tuple[ParsedTransaction, str | None]


@dataclass(frozen=True)
class CategorySpend:
    category: str
    median_cents: int


@dataclass(frozen=True)
class VariableForecast:
    low_cents: int
    high_cents: int
    by_category: tuple[CategorySpend, ...]
    cycles_used: int


def variable_forecast(
    rows: Iterable[Row],
    category_types: dict[str, str],
    cycles: Sequence[Cycle],
    days_remaining: int,
) -> VariableForecast | None:
    """Spending range for the next `days_remaining` days, or None for "not enough data".

    `cycles` are the complete cycles to learn from, usually
    `payday.complete_cycles(today, salary_day, HISTORY_CYCLES)`.
    """
    if days_remaining < 0:
        raise ValueError(f"days_remaining must not be negative, got {days_remaining}")
    rows = list(rows)
    if not rows:
        return None
    # A cycle that starts before the first imported transaction is only partly
    # known, and its low total would drag the range down.
    history_start = min(tx.booking_date for tx, _ in rows)
    covered = [c for c in cycles if c.start >= history_start]
    if len(covered) < MIN_CYCLES:
        return None

    spent = _variable_spending(rows, category_types, covered)
    # Cycles differ in length (28 to 31 days), so each scales by its own days.
    scales = [Fraction(days_remaining, cycle.days) for cycle in covered]
    totals = [sum(per_cycle.values()) * s for per_cycle, s in zip(spent, scales, strict=True)]
    categories = sorted({category for per_cycle in spent for category in per_cycle})
    medians = [
        CategorySpend(category, _cents(percentile(_scaled(spent, scales, category), MEDIAN)))
        for category in categories
    ]
    # A category with a zero median is usually a one-off; listing it as
    # "€0 expected" would only add noise to the breakdown.
    by_category = sorted(
        (m for m in medians if m.median_cents > 0),
        key=lambda m: (-m.median_cents, m.category),
    )
    return VariableForecast(
        low_cents=_cents(percentile(totals, LOW)),
        high_cents=_cents(percentile(totals, HIGH)),
        by_category=tuple(by_category),
        cycles_used=len(covered),
    )


def percentile(values: Sequence[Fraction | int], p: Fraction) -> Fraction:
    """Linear interpolation between closest ranks (the common spreadsheet method).

    Chosen because it is easy to explain and never jumps between samples, so a
    small change in one cycle moves the range only a little.
    """
    ordered = sorted(Fraction(v) for v in values)
    position = p * (len(ordered) - 1)
    lower = math.floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _variable_spending(
    rows: list[Row], category_types: dict[str, str], cycles: list[Cycle]
) -> list[dict[str, int]]:
    """Debit cents per variable category, one dict per cycle in `cycles` order."""
    spent: list[dict[str, int]] = [defaultdict(int) for _ in cycles]
    for tx, category in rows:
        # Refunds are left out: SPEC §9 forecasts spending, and a refund in
        # one cycle would hide real spending instead of predicting future refunds.
        if tx.amount_cents >= 0 or category_types.get(category or "") not in VARIABLE:
            continue
        for index, cycle in enumerate(cycles):
            if cycle.start <= tx.booking_date <= cycle.end:
                spent[index][category] += -tx.amount_cents
    return spent


def _scaled(spent: list[dict[str, int]], scales: list[Fraction], category: str) -> list[Fraction]:
    # A cycle without this category still counts, as zero spending.
    return [per_cycle.get(category, 0) * s for per_cycle, s in zip(spent, scales, strict=True)]


def _cents(amount: Fraction) -> int:
    # Half a cent rounds up, like forecast.py and amortization.py; floor(x + 1/2)
    # is half up because these amounts are never negative.
    return math.floor(amount + Fraction(1, 2))
