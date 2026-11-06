"""Integer geometry for the Monthly income bar (SPEC §13)."""

from dataclasses import FrozenInstanceError

import pytest

from sonar.categorization.groups import GroupTotals
from sonar.web import charts


def test_income_bar_example_widths_labels_and_residual():
    bar = charts.income_bar(GroupTotals(-200_000, -100_000, -50_000, 0), 600_000)

    assert [(s.part, s.cents, s.width, s.label_tier) for s in bar.segments] == [
        ("fixed", 200_000, "23.3", "wide"),
        ("lights_on", 100_000, "11.7", None),
        ("occasional", 50_000, "5.8", None),
        ("residual", 250_000, "29.2", "always"),
    ]
    assert bar.spent_cents == 350_000
    assert bar.over_cents == 0
    with pytest.raises(FrozenInstanceError):
        bar.spent_cents = 0
    with pytest.raises(FrozenInstanceError):
        bar.segments[0].cents = 0


def test_income_bar_overspend_caps_segments_without_discarding_their_cents():
    bar = charts.income_bar(GroupTotals(-100_000, -100_000, -100_000, -50_000), 100_000)

    assert [(s.part, s.cents, s.width) for s in bar.segments] == [
        ("fixed", 100_000, "70.0"),
        ("lights_on", 100_000, "30.0"),
        ("occasional", 100_000, "0.0"),
        ("uncategorized", 50_000, "0.0"),
    ]
    assert bar.spent_cents == 350_000
    assert bar.over_cents == 250_000


@pytest.mark.parametrize(
    "spent, width, tier",
    [(239, "23.9", "wide"), (240, "24.0", "always"), (119, "11.9", None), (120, "12.0", "wide")],
)
def test_income_bar_label_thresholds(spent, width, tier):
    bar = charts.income_bar(GroupTotals(-spent, 0, 0, 0), 700)
    assert (bar.segments[0].width, bar.segments[0].label_tier) == (width, tier)


def test_income_bar_rounds_cumulative_endpoints_exactly():
    bar = charts.income_bar(GroupTotals(-1, -1, -1, 0), 6)
    assert [s.width for s in bar.segments] == ["11.7", "11.6", "11.7", "35.0"]


def test_income_bar_exactly_spent_income_has_no_residual():
    bar = charts.income_bar(GroupTotals(-100, 0, 0, 0), 100)
    assert [s.part for s in bar.segments] == ["fixed"]
    assert bar.over_cents == 0


def test_income_bar_without_spending_is_all_residual():
    bar = charts.income_bar(GroupTotals(0, 0, 0, 0), 100)
    assert [(s.part, s.cents, s.width) for s in bar.segments] == [("residual", 100, "70.0")]


def test_income_bar_without_income_is_absent():
    assert charts.income_bar(GroupTotals(-100, 0, 0, 0), 0) is None
