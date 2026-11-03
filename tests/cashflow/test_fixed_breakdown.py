from datetime import date

from sonar.cashflow.forecast import (
    BreakdownGroup,
    BreakdownPayment,
    FixedBreakdown,
    FixedSource,
    SupplierDates,
    fixed_breakdown,
    fixed_costs,
)
from sonar.recurring.schedule import SchedulePeriod

TODAY = date(2026, 9, 23)


def _source(name: str, cents: int, interval: int = 1) -> FixedSource:
    return FixedSource(name, (SchedulePeriod(date(2026, 9, 1), None, cents, interval, 1),), TODAY)


def test_mixed_schedules_apportion_to_monthly_equivalent_and_sort_groups_and_payments():
    ending = FixedSource(
        "Debt",
        (
            SchedulePeriod(date(2026, 9, 1), date(2026, 10, 31), 10, 1, 1),
            SchedulePeriod(date(2026, 11, 1), date(2026, 11, 30), 5, 1, 1),
        ),
        None,
    )
    paused = FixedSource("Paused", (SchedulePeriod(date(2027, 9, 1), None, 100, 1, 1),), None)
    labelled = (
        ("Utilities", _source("Quarterly", 101, 3)),
        ("Loans", ending),
        ("Insurance", _source("Annual", 31, 12)),
        ("Utilities", _source("Bimonthly", 101, 2)),
        ("Housing", _source("Rent", 1200)),
        ("Paused", paused),
    )

    result = fixed_breakdown(labelled, TODAY)

    assert (
        result.total_cents
        == fixed_costs(tuple(source for _, source in labelled), TODAY).monthly_equivalent_cents
    )
    assert result == FixedBreakdown(
        1289,
        5,
        (
            BreakdownGroup("Housing", 1200, 93, (BreakdownPayment("Rent", 1200),)),
            BreakdownGroup(
                "Utilities",
                84,
                7,
                (BreakdownPayment("Bimonthly", 50), BreakdownPayment("Quarterly", 34)),
            ),
            BreakdownGroup("Insurance", 3, 0, (BreakdownPayment("Annual", 3),)),
            BreakdownGroup("Loans", 2, 0, (BreakdownPayment("Debt", 2),)),
        ),
    )
    assert sum(group.total_cents for group in result.groups) == result.total_cents
    assert all(
        group.total_cents == sum(payment.monthly_cents for payment in group.payments)
        for group in result.groups
    )


def test_equal_remainders_award_the_cent_by_payment_name_independent_of_input_order():
    result = fixed_breakdown(
        (("Other", _source("Beta", 18, 12)), ("Other", _source("Alpha", 18, 12))), TODAY
    )

    assert result == FixedBreakdown(
        3,
        2,
        (
            BreakdownGroup(
                "Other", 3, 100, (BreakdownPayment("Alpha", 2), BreakdownPayment("Beta", 1))
            ),
        ),
    )


def test_equal_totals_sort_groups_and_payments_by_name():
    result = fixed_breakdown(
        (
            ("Zulu", _source("Single", 2)),
            ("Alpha", _source("Zulu", 1)),
            ("Alpha", _source("Alpha", 1)),
        ),
        TODAY,
    )

    assert result.groups == (
        BreakdownGroup("Alpha", 2, 50, (BreakdownPayment("Alpha", 1), BreakdownPayment("Zulu", 1))),
        BreakdownGroup("Zulu", 2, 50, (BreakdownPayment("Single", 2),)),
    )


def test_shares_round_half_up_without_forcing_a_sum_of_100():
    result = fixed_breakdown(
        (("Small", _source("Small", 1)), ("Large", _source("Large", 7))), TODAY
    )

    assert [group.share_percent for group in result.groups] == [88, 13]


def test_empty_breakdown_and_payment_rounding_to_zero_have_zero_share():
    assert fixed_breakdown((), TODAY) == FixedBreakdown(0, 0, ())
    assert fixed_breakdown((("Other", _source("Tiny", 1, 12)),), TODAY) == FixedBreakdown(
        0, 1, (BreakdownGroup("Other", 0, 0, (BreakdownPayment("Tiny", 0),)),)
    )


def test_paused_months_only_count_planned_occurrences():
    source = FixedSource(
        "Paused",
        (
            SchedulePeriod(date(2026, 9, 1), date(2026, 10, 31), 120, 1, 1),
            SchedulePeriod(date(2027, 8, 1), None, 240, 1, 1),
        ),
        TODAY,
    )

    result = fixed_breakdown((("Other", source),), TODAY)

    assert result.total_cents == 40
    assert result.total_cents == fixed_costs((source,), TODAY).monthly_equivalent_cents


def test_supplier_dates_replace_own_occurrences_inside_the_span():
    source = FixedSource(
        "Water",
        _source("Water", 120).periods,
        TODAY,
        SupplierDates(
            date(2026, 9, 1),
            date(2027, 2, 28),
            (date(2026, 9, 1), date(2026, 12, 1)),
            (date(2026, 12, 1),),
            180,
        ),
    )

    result = fixed_breakdown((("Utilities", source),), TODAY)

    assert result.total_cents == 90
    assert result.total_cents == fixed_costs((source,), TODAY).monthly_equivalent_cents
