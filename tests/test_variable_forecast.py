"""Tests for variable_forecast.py: the variable spending range until payday (SPEC §9)."""

from datetime import date
from fractions import Fraction

import pytest

from sonar.payday import Cycle
from sonar.transactions import ParsedTransaction
from sonar.variable_forecast import (
    CategorySpend,
    VariableForecast,
    percentile,
    variable_forecast,
)

TYPES = {
    "groceries": "lights_on",
    "dining": "lights_on",
    "gifts": "occasional",
    "rent": "fixed",
}

# Four contiguous 30-day cycles, oldest first, so scaling to 15 days halves each total.
C1 = Cycle(date(2026, 5, 1), date(2026, 5, 30))
C2 = Cycle(date(2026, 5, 31), date(2026, 6, 29))
C3 = Cycle(date(2026, 6, 30), date(2026, 7, 29))
C4 = Cycle(date(2026, 7, 30), date(2026, 8, 28))


def _tx(booking_date: date, amount_cents: int) -> ParsedTransaction:
    return ParsedTransaction(
        account="DE00 0000 0000 0000 0000 00",
        booking_date=booking_date,
        value_date=booking_date,
        amount_cents=amount_cents,
        currency="EUR",
        counterparty="Example Shop",
        purpose="",
        raw_row="",
    )


def _spend(cycle: Cycle, category: str | None, cents: int) -> tuple[ParsedTransaction, str | None]:
    # Booked on the cycle's first day so the cycle counts as covered by history.
    return (_tx(cycle.start, -cents), category)


def _groceries_1_to_4() -> list[tuple[ParsedTransaction, str | None]]:
    return [
        _spend(C1, "groceries", 100000),
        _spend(C2, "groceries", 200000),
        _spend(C3, "groceries", 300000),
        _spend(C4, "groceries", 400000),
    ]


def test_percentile_interpolates_between_neighbours():
    values = [Fraction(v) for v in (200000, 50000, 150000, 100000)]
    # P25 sits at position 0.25 * 3 = 0.75: 50000 + 0.75 * 50000.
    assert percentile(values, Fraction(1, 4)) == 87500
    # P75 sits at position 0.75 * 3 = 2.25: 150000 + 0.25 * 50000.
    assert percentile(values, Fraction(3, 4)) == 162500


def test_percentile_on_an_exact_position_is_that_value():
    values = [Fraction(v) for v in (3, 1, 2)]
    assert percentile(values, Fraction(1, 2)) == 2


def test_range_is_p25_to_p75_of_totals_scaled_to_days_remaining():
    # Scaled to 15 of 30 days: 50000, 100000, 150000, 200000. Cycles are passed
    # most recent first, as payday.complete_cycles returns them.
    result = variable_forecast(_groceries_1_to_4(), TYPES, (C4, C3, C2, C1), days_remaining=15)
    assert result is not None
    assert (result.low_cents, result.high_cents) == (87500, 162500)
    assert result.cycles_used == 4


def test_each_cycle_scales_by_its_own_length():
    june = Cycle(date(2026, 6, 1), date(2026, 6, 30))  # 30 days
    july = Cycle(date(2026, 7, 1), date(2026, 7, 31))  # 31 days
    august = Cycle(date(2026, 8, 1), date(2026, 8, 31))  # 31 days
    rows = [
        _spend(june, "groceries", 30000),
        _spend(july, "groceries", 31000),
        _spend(august, "groceries", 62000),
    ]
    # Per 10 days: 10000, 10000, 20000 -> P25 at 0.5 = 10000, P75 at 1.5 = 15000.
    result = variable_forecast(rows, TYPES, (june, july, august), days_remaining=10)
    assert result is not None
    assert (result.low_cents, result.high_cents) == (10000, 15000)


def test_scaled_values_round_to_whole_cents():
    rows = [_spend(c, "groceries", 20) for c in (C1, C2, C3)]
    # 20 cents over 30 days is 2/3 of a cent for 1 day, which rounds to 1.
    result = variable_forecast(rows, TYPES, (C1, C2, C3), days_remaining=1)
    assert result == VariableForecast(1, 1, (CategorySpend("groceries", 1),), 3)


def test_exact_half_cents_round_up():
    h1 = Cycle(date(2026, 5, 1), date(2026, 5, 2))
    h2 = Cycle(date(2026, 5, 3), date(2026, 5, 4))
    h3 = Cycle(date(2026, 5, 5), date(2026, 5, 6))
    rows = [_spend(c, "groceries", 101) for c in (h1, h2, h3)]
    # 101 cents over 2 days is 50.5 for 1 day; half up gives 51, round() would give 50.
    result = variable_forecast(rows, TYPES, (h3, h2, h1), days_remaining=1)
    assert result == VariableForecast(51, 51, (CategorySpend("groceries", 51),), 3)


def test_only_variable_debits_count():
    rows = [_spend(c, "groceries", 30000) for c in (C1, C2, C3)]
    rows += [
        _spend(C1, "rent", 100000),
        _spend(C2, None, 5000),
        _spend(C2, "mystery", 7000),  # a category missing from the taxonomy
        (_tx(C3.start, 10000), "groceries"),  # a refund is not spending
    ]
    result = variable_forecast(rows, TYPES, (C1, C2, C3), days_remaining=30)
    assert result == VariableForecast(30000, 30000, (CategorySpend("groceries", 30000),), 3)


def test_spending_outside_the_cycles_is_ignored():
    rows = [_spend(c, "groceries", 30000) for c in (C1, C2, C3)]
    rows.append((_tx(date(2026, 9, 1), -99999), "groceries"))  # the current cycle
    result = variable_forecast(rows, TYPES, (C1, C2, C3), days_remaining=30)
    assert result is not None
    assert (result.low_cents, result.high_cents) == (30000, 30000)


def test_a_covered_cycle_without_variable_spending_counts_as_zero():
    rows = [
        _spend(C1, "rent", 100000),
        _spend(C2, "groceries", 30000),
        _spend(C3, "groceries", 30000),
    ]
    # Values 0, 30000, 30000 -> P25 at 0.5 = 15000, P75 at 1.5 = 30000.
    result = variable_forecast(rows, TYPES, (C1, C2, C3), days_remaining=30)
    assert result is not None
    assert (result.low_cents, result.high_cents) == (15000, 30000)


def test_breakdown_is_the_median_per_category_largest_first():
    rows = _groceries_1_to_4() + [_spend(C1, "dining", 20000), _spend(C2, "dining", 20000)]
    result = variable_forecast(rows, TYPES, (C1, C2, C3, C4), days_remaining=15)
    assert result is not None
    # Groceries scaled 50000..200000 -> median (100000 + 150000) / 2.
    # Dining scaled 10000, 10000, 0, 0 -> median (0 + 10000) / 2.
    assert result.by_category == (
        CategorySpend("groceries", 125000),
        CategorySpend("dining", 5000),
    )
    # Totals scaled 60000, 110000, 150000, 200000.
    assert (result.low_cents, result.high_cents) == (97500, 162500)


def test_breakdown_drops_categories_with_a_zero_median():
    rows = _groceries_1_to_4() + [_spend(C1, "gifts", 50000)]
    # Gifts scaled 25000, 0, 0, 0 -> median 0, nothing to expect this cycle.
    result = variable_forecast(rows, TYPES, (C1, C2, C3, C4), days_remaining=15)
    assert result is not None
    assert [c.category for c in result.by_category] == ["groceries"]


def test_breakdown_ties_are_ordered_by_name():
    rows = [_spend(c, cat, 30000) for c in (C1, C2, C3) for cat in ("groceries", "dining")]
    result = variable_forecast(rows, TYPES, (C1, C2, C3), days_remaining=30)
    assert result is not None
    assert result.by_category == (
        CategorySpend("dining", 30000),
        CategorySpend("groceries", 30000),
    )


def test_three_covered_cycles_are_enough_but_two_are_not():
    covered = [_spend(c, "groceries", 30000) for c in (C1, C2, C3)]
    assert variable_forecast(covered, TYPES, (C1, C2, C3), days_remaining=30) is not None

    # History starts mid-C1, so C1 is incomplete and only C2 and C3 count.
    late_start = [(_tx(date(2026, 5, 2), -30000), "groceries")] + covered[1:]
    assert variable_forecast(late_start, TYPES, (C1, C2, C3), days_remaining=30) is None


def test_no_transactions_is_not_enough_data():
    assert variable_forecast([], TYPES, (C1, C2, C3), days_remaining=30) is None


def test_no_days_remaining_forecasts_nothing():
    result = variable_forecast(_groceries_1_to_4(), TYPES, (C1, C2, C3, C4), days_remaining=0)
    assert result == VariableForecast(0, 0, (), 4)


def test_negative_days_remaining_is_rejected():
    with pytest.raises(ValueError, match="days_remaining"):
        variable_forecast(_groceries_1_to_4(), TYPES, (C1, C2, C3, C4), days_remaining=-1)
