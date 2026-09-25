"""The five category types and their spending groups (SPEC §5, §13 Groups).

Design decision (N02): `variable` splits into `lights_on` (spending we can
reduce but not bring to zero, e.g. groceries, transport, shopping) and
`occasional` (fees, education, donations, health, dining and similar
one-offs). This module is the single source for the five type values, their
display labels, the ordered spending groups, and the set excluded from
recurring detection, so categorize.py, recurrence.py and lights_on.py
never repeat the literals.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

INCOME = "income"
TRANSFER = "transfer"
FIXED = "fixed"
LIGHTS_ON = "lights_on"
OCCASIONAL = "occasional"

TYPES = frozenset({INCOME, TRANSFER, FIXED, LIGHTS_ON, OCCASIONAL})

LABELS = {
    INCOME: "Income",
    TRANSFER: "Transfers",
    FIXED: "Fixed payments",
    LIGHTS_ON: "Keep the lights on",
    OCCASIONAL: "Occasional payments",
}

# Shown in this order on the Monthly page stats.
SPENDING_GROUPS = (FIXED, LIGHTS_ON, OCCASIONAL)

# Irregular or already tracked elsewhere; kept out of recurring detection.
EXCLUDED_FROM_RECURRENCE = frozenset({LIGHTS_ON, OCCASIONAL, TRANSFER})


class CategoryTotalLike(Protocol):
    """Duck-typed shape of monthly.CategoryTotal; avoids importing sonar.monthly."""

    category: str | None
    category_type: str | None
    total_cents: int


@dataclass(frozen=True)
class GroupTotals:
    fixed_cents: int
    lights_on_cents: int
    occasional_cents: int
    uncategorized_cents: int


def group_totals(totals: Iterable[CategoryTotalLike]) -> GroupTotals:
    """Sum debit totals (negative cents, like the inputs) per spending group.

    Transfer and income totals are money moved or earned, not spent, and are
    left out. An item with no category (`category_type` None) counts toward
    uncategorized. Any other type raises ValueError.
    """
    fixed = lights_on = occasional = uncategorized = 0
    for total in totals:
        category_type = total.category_type
        if category_type is None:
            uncategorized += total.total_cents
        elif category_type == FIXED:
            fixed += total.total_cents
        elif category_type == LIGHTS_ON:
            lights_on += total.total_cents
        elif category_type == OCCASIONAL:
            occasional += total.total_cents
        elif category_type in (INCOME, TRANSFER):
            continue
        else:
            raise ValueError(f"unknown category type {category_type!r}")
    return GroupTotals(
        fixed_cents=fixed,
        lights_on_cents=lights_on,
        occasional_cents=occasional,
        uncategorized_cents=uncategorized,
    )
