"""Cumulative payoff steps: pay the smallest debts first and see what monthly fixed cost is freed.

Freed is one amount per month: the sum of the included debts' rates, whatever
their interval. Only the fixed totals are ranges, because fixed payments are not
all monthly: a quarterly or yearly payment makes some months heavier, so the
total has a minimum and a maximum over the horizon.
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
    months: tuple[
        int, ...
    ]  # this debt's own fixed payments per month, aligned with the base series


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
    debts: Sequence[LadderDebt], fixed_months: Sequence[int]
) -> tuple[PayoffStep, ...]:
    for debt in debts:
        if len(debt.months) != len(fixed_months):
            raise ValueError(
                f"{debt.name}: {len(debt.months)} months, expected {len(fixed_months)}"
            )
    ordered = sorted(
        (d for d in debts if d.remaining_cents > 0),
        key=lambda d: (d.remaining_cents, d.name, d.id),
    )
    if not ordered:
        return ()

    before_min, before_max = min(fixed_months), max(fixed_months)
    steps = []
    for k in range(1, len(ordered) + 1):
        included = tuple(ordered[:k])
        after = [fixed - sum(d.months[m] for d in included) for m, fixed in enumerate(fixed_months)]
        steps.append(
            PayoffStep(
                number=k,
                pay_now_cents=sum(d.remaining_cents for d in included),
                debts=included,
                before_min_cents=before_min,
                before_max_cents=before_max,
                after_min_cents=min(after),
                after_max_cents=max(after),
                freed_cents=sum(d.rate_cents for d in included),
            )
        )
    return tuple(steps)
