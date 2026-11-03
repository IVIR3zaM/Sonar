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
    paused = FixedSource("Paused", (SchedulePeriod(date(2027, 9, 24), None, 100, 1, 1),), None)
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
        1297,
        5,
        (
            BreakdownGroup("Housing", 1200, 93, (BreakdownPayment("Rent", 1200),)),
            BreakdownGroup(
                "Utilities",
                84,
                6,
                (BreakdownPayment("Bimonthly", 50), BreakdownPayment("Quarterly", 34)),
            ),
            BreakdownGroup("Loans", 10, 1, (BreakdownPayment("Debt", 10, date(2026, 11, 30)),)),
            BreakdownGroup("Insurance", 3, 0, (BreakdownPayment("Annual", 3),)),
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


def test_future_pause_does_not_dilute_current_rate():
    source = FixedSource(
        "Paused",
        (
            SchedulePeriod(date(2026, 9, 1), date(2026, 10, 31), 120, 1, 1),
            SchedulePeriod(date(2027, 8, 1), None, 240, 1, 1),
        ),
        TODAY,
    )

    result = fixed_breakdown((("Other", source),), TODAY)

    assert result.total_cents == 120
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


def test_installment_keeps_current_rate_and_reports_final_payment_date():
    last_date = date(2027, 3, 1)
    source = FixedSource(
        "Installment",
        (
            SchedulePeriod(date(2026, 9, 1), date(2027, 2, 28), 5518, 1, 1),
            SchedulePeriod(last_date, last_date, 2000, 1, 1),
        ),
        TODAY,
    )

    result = fixed_breakdown((("Loans", source),), TODAY)

    assert result.groups[0].payments == (BreakdownPayment("Installment", 5518, last_date),)
    assert result.total_cents == fixed_costs((source,), TODAY).monthly_equivalent_cents == 5518


def test_current_rate_uses_latest_started_valid_period_and_ignores_future_changes():
    source = FixedSource(
        "Changing",
        (
            SchedulePeriod(date(2026, 1, 1), None, 100, 1, 1),
            SchedulePeriod(date(2026, 9, 1), None, 300, 1, 1),
            SchedulePeriod(date(2026, 10, 1), None, 900, 1, 1),
        ),
        None,
    )

    assert fixed_breakdown((("Other", source),), TODAY).total_cents == 300
    assert fixed_costs((source,), TODAY).monthly_equivalent_cents == 300


def test_paused_ended_and_far_future_sources_are_omitted():
    sources = (
        FixedSource(
            "Paused",
            (
                SchedulePeriod(date(2026, 1, 1), date(2026, 8, 31), 100, 1, 1),
                SchedulePeriod(date(2026, 10, 1), None, 200, 1, 1),
            ),
            None,
        ),
        FixedSource(
            "Ended", (SchedulePeriod(date(2026, 1, 1), date(2026, 9, 1), 100, 1, 1),), None
        ),
        FixedSource("Far future", (SchedulePeriod(date(2027, 9, 24), None, 100, 1, 1),), None),
        FixedSource("Paid off", (), None),
    )

    assert fixed_breakdown(tuple(("Other", s) for s in sources), TODAY) == FixedBreakdown(0, 0, ())
    assert fixed_costs(sources, TODAY).monthly_equivalent_cents == 0


def test_first_future_period_counts_at_the_twelve_month_boundary():
    source = FixedSource(
        "Future",
        (
            SchedulePeriod(date(2027, 9, 23), date(2027, 9, 23), 3001, 3, 23),
            SchedulePeriod(date(2027, 10, 23), None, 9000, 3, 23),
        ),
        None,
    )

    assert fixed_breakdown((("Other", source),), TODAY).total_cents == 1000
    assert fixed_costs((source,), TODAY).monthly_equivalent_cents == 1000


def test_exact_mixed_intervals_round_once_and_apportion_largest_remainders():
    sources = (
        _source("Quarterly", 3001, 3),
        _source("Five months", 4, 5),
        _source("Annual", 5, 12),
    )

    result = fixed_breakdown(tuple(("Other", s) for s in sources), TODAY)

    # 3001/3 + 4/5 + 5/12 = 1001.55, rounded once to 1002.
    assert result.total_cents == fixed_costs(sources, TODAY).monthly_equivalent_cents == 1002
    assert result.groups[0].payments == (
        BreakdownPayment("Quarterly", 1000),
        BreakdownPayment("Annual", 1),
        BreakdownPayment("Five months", 1),
    )


def test_end_note_includes_boundary_but_omits_thirteen_months_and_open_ended():
    sources = tuple(
        FixedSource(name, (SchedulePeriod(date(2026, 1, 1), until, 100, 1, 1),), None)
        for name, until in (
            ("Boundary", date(2027, 9, 23)),
            ("Later", date(2027, 10, 23)),
            ("Open", None),
        )
    )

    result = fixed_breakdown(tuple(("Other", s) for s in sources), TODAY)

    assert result.groups[0].payments == (
        BreakdownPayment("Boundary", 100, date(2027, 9, 23)),
        BreakdownPayment("Later", 100),
        BreakdownPayment("Open", 100),
    )
