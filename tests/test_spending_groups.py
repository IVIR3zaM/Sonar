"""Tests for spending_groups.py: the five category types and group totals."""

from dataclasses import dataclass

import pytest

from sonar.spending_groups import (
    FIXED,
    INCOME,
    LIGHTS_ON,
    OCCASIONAL,
    TRANSFER,
    GroupTotals,
    group_totals,
)


@dataclass(frozen=True)
class _FakeTotal:
    category: str | None
    category_type: str | None
    total_cents: int


def test_group_totals_sums_each_group_and_leaves_out_transfer_and_income():
    totals = [
        _FakeTotal("Housing", FIXED, -1_000),
        _FakeTotal("Groceries", LIGHTS_ON, -2_000),
        _FakeTotal("Dining", OCCASIONAL, -300),
        _FakeTotal("Own transfers", TRANSFER, -5_000),
        _FakeTotal("Salary", INCOME, 300_000),
        _FakeTotal(None, None, -400),
    ]

    assert group_totals(totals) == GroupTotals(
        fixed_cents=-1_000,
        lights_on_cents=-2_000,
        occasional_cents=-300,
        uncategorized_cents=-400,
    )


def test_group_totals_raises_on_unknown_type():
    with pytest.raises(ValueError, match="unknown category type"):
        group_totals([_FakeTotal("Weird", "bogus", -100)])
