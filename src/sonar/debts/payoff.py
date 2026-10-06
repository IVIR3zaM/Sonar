"""Cumulative payoff steps: pay the smallest debts first and see what monthly fixed cost is freed.

Freed is one amount per month: the sum of the included debts' rates, whatever
their interval. The fixed totals are ranges because not every payment is
monthly: a quarterly or yearly payment only falls due in some months. The
minimum counts the monthly payments alone, the maximum counts every payment at
full amount, so paying off a non-monthly debt lowers the maximum only.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal


@dataclass(frozen=True)
class LadderDebt:
    id: int
    kind: Literal["installment", "loan"]
    name: str
    remaining_cents: int
    rate_cents: int
    interval_months: int
    end_date: date | None


@dataclass(frozen=True)
class PayoffStep:
    number: int
    pay_now_cents: int
    debts: tuple[LadderDebt, ...]
    before_min_cents: int
    before_max_cents: int
    after_min_cents: int
    after_max_cents: int
    freed_cents: int


def payoff_ladder(
    debts: Sequence[LadderDebt], now_min_cents: int, now_max_cents: int
) -> tuple[PayoffStep, ...]:
    ordered = sorted(
        (d for d in debts if d.remaining_cents > 0),
        key=lambda d: (d.remaining_cents, d.name, d.id),
    )
    steps = []
    for k in range(1, len(ordered) + 1):
        included = tuple(ordered[:k])
        freed = sum(d.rate_cents for d in included)
        freed_monthly = sum(d.rate_cents for d in included if d.interval_months <= 1)
        steps.append(
            PayoffStep(
                number=k,
                pay_now_cents=sum(d.remaining_cents for d in included),
                debts=included,
                before_min_cents=now_min_cents,
                before_max_cents=now_max_cents,
                after_min_cents=now_min_cents - freed_monthly,
                after_max_cents=now_max_cents - freed,
                freed_cents=freed,
            )
        )
    return tuple(steps)
