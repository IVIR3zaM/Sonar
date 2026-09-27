"""Month-by-month spending: payment list and per-category totals."""

from datetime import date

import pytest

from sonar.monthly import (
    UNCATEGORIZED,
    CategoryTotal,
    Period,
    adjacent_months,
    month_of,
    monthly_spending,
    only_category,
    parse_month,
    payment_months,
    period_for,
    salary_paydays,
)
from sonar.transactions import ParsedTransaction

CATEGORY_TYPES = {
    "Groceries": "lights_on",
    "Housing": "fixed",
    "Own transfers": "transfer",
    "Salary": "income",
}


SEPTEMBER = Period(date(2026, 9, 1), date(2026, 9, 1), date(2026, 9, 30))


def _tx(booking_date: date, amount_cents: int, counterparty: str = "Shop Foo") -> ParsedTransaction:
    return ParsedTransaction(
        account="GiroKonto",
        booking_date=booking_date,
        value_date=booking_date,
        amount_cents=amount_cents,
        currency="EUR",
        counterparty=counterparty,
        purpose="purpose bar",
        raw_row="",
    )


def test_lists_only_the_months_debits_newest_first():
    rows = [
        (_tx(date(2026, 9, 3), -1_000), "Groceries"),
        (_tx(date(2026, 9, 20), -2_000), "Groceries"),
        (_tx(date(2026, 9, 25), 300_000), "Salary"),  # income is not a payment
        (_tx(date(2026, 8, 31), -5_000), "Groceries"),  # another month
        (_tx(date(2026, 10, 1), -7_000), "Groceries"),
    ]

    result = monthly_spending(rows, CATEGORY_TYPES, SEPTEMBER)

    assert [(tx.booking_date, category) for tx, category in result.payments] == [
        (date(2026, 9, 20), "Groceries"),
        (date(2026, 9, 3), "Groceries"),
    ]


def test_totals_per_category_largest_first_with_uncategorized_as_none():
    rows = [
        (_tx(date(2026, 9, 1), -100_000), "Housing"),
        (_tx(date(2026, 9, 2), -3_000), "Groceries"),
        (_tx(date(2026, 9, 9), -4_500), "Groceries"),
        (_tx(date(2026, 9, 5), -2_000), None),
    ]

    result = monthly_spending(rows, CATEGORY_TYPES, SEPTEMBER)

    assert result.by_category == (
        CategoryTotal("Housing", "fixed", -100_000, 1),
        CategoryTotal("Groceries", "lights_on", -7_500, 2),
        CategoryTotal(None, None, -2_000, 1),
    )
    assert result.spent_cents == -109_500
    assert result.transfers_net_cents == 0
    assert result.groups.fixed_cents == -100_000
    assert result.groups.lights_on_cents == -7_500
    assert result.groups.uncategorized_cents == -2_000


def test_transfers_leave_by_category_for_their_own_net_table():
    rows = [
        (_tx(date(2026, 9, 1), -50_000), "Own transfers"),
        (_tx(date(2026, 9, 2), -3_000), "Groceries"),
    ]

    result = monthly_spending(rows, CATEGORY_TYPES, SEPTEMBER)

    assert [c.category for c in result.by_category] == ["Groceries"]
    assert [c.category for c in result.transfer_totals] == ["Own transfers"]
    assert result.spent_cents == -3_000
    assert result.transfers_net_cents == -50_000


def test_transfer_totals_net_debits_and_credits_ordered_ascending():
    category_types = {**CATEGORY_TYPES, "Family transfer": "transfer"}
    rows = [
        (_tx(date(2026, 9, 1), -40_000, "Fake Bank"), "Own transfers"),
        (_tx(date(2026, 9, 10), 34_000, "Fake Bank"), "Own transfers"),
        (_tx(date(2026, 9, 3), -3_600, "Fake Family"), "Family transfer"),
        (_tx(date(2026, 9, 4), -1_000), "Groceries"),
    ]

    result = monthly_spending(rows, category_types, SEPTEMBER)

    assert [(c.category, c.total_cents, c.count) for c in result.transfer_totals] == [
        ("Own transfers", -6_000, 2),
        ("Family transfer", -3_600, 1),
    ]
    assert result.by_category == (CategoryTotal("Groceries", "lights_on", -1_000, 1),)
    assert result.spent_cents == -1_000
    assert result.transfers_net_cents == -9_600


def test_transfers_net_cents_nets_a_transfer_credit_against_a_transfer_debit():
    rows = [
        (_tx(date(2026, 9, 1), -100_000, "Own account"), "Own transfers"),
        (_tx(date(2026, 9, 10), 90_000, "Own account"), "Own transfers"),
        (_tx(date(2026, 9, 5), -1_000), "Groceries"),
        (_tx(date(2026, 8, 20), 90_000, "Own account"), "Own transfers"),  # outside the period
        (_tx(date(2026, 9, 25), 300_000), "Salary"),  # income, not a transfer
    ]

    result = monthly_spending(rows, CATEGORY_TYPES, SEPTEMBER)

    assert result.transfers_net_cents == -10_000
    assert result.spent_cents == -1_000
    assert result.groups.lights_on_cents == -1_000
    assert result.groups.fixed_cents == 0
    assert result.groups.occasional_cents == 0
    assert result.groups.uncategorized_cents == 0


def test_a_month_without_payments_is_empty():
    result = monthly_spending([], CATEGORY_TYPES, SEPTEMBER)

    assert result.payments == ()
    assert result.by_category == ()
    assert result.spent_cents == 0


def test_spending_covers_the_whole_period_across_calendar_months():
    rows = [
        (_tx(date(2026, 8, 25), -1_000), "Groceries"),  # before the period
        (_tx(date(2026, 8, 26), -2_000), "Groceries"),
        (_tx(date(2026, 9, 24), -3_000), "Groceries"),
        (_tx(date(2026, 9, 25), -4_000), "Groceries"),  # after it
    ]
    period = Period(date(2026, 9, 1), date(2026, 8, 26), date(2026, 9, 24))

    result = monthly_spending(rows, CATEGORY_TYPES, period)

    assert [tx.amount_cents for tx, _ in result.payments] == [-3_000, -2_000]
    assert result.period == period


def test_payment_months_are_first_of_month_newest_first_and_ignore_income():
    rows = [
        (_tx(date(2026, 7, 15), -1_000), "Groceries"),
        (_tx(date(2026, 9, 3), -1_000), "Groceries"),
        (_tx(date(2026, 9, 28), -1_000), None),
        (_tx(date(2026, 10, 1), 300_000), "Salary"),
    ]

    assert payment_months(rows, None, []) == [date(2026, 9, 1), date(2026, 7, 1)]


def test_payment_months_follow_salary_months_when_a_salary_day_is_set():
    rows = [
        (_tx(date(2026, 8, 20), -1_000), "Groceries"),  # August salary month
        (_tx(date(2026, 8, 27), -1_000), "Groceries"),  # September: after the 26 Aug salary
    ]

    assert payment_months(rows, 26, []) == [date(2026, 9, 1), date(2026, 8, 1)]


def test_without_a_salary_day_a_month_is_the_calendar_month():
    assert period_for(date(2026, 2, 1), None, []) == Period(
        date(2026, 2, 1), date(2026, 2, 1), date(2026, 2, 28)
    )
    assert month_of(date(2026, 8, 27), None, []) == date(2026, 8, 1)


def test_a_salary_month_runs_from_the_real_payday_to_the_day_before_the_next():
    # Promised on the 26th; August's salary came on time, September's
    # arrived 3 days early on 23 Sep.
    paydays = [date(2026, 8, 26), date(2026, 9, 23)]

    assert period_for(date(2026, 9, 1), 26, paydays) == Period(
        date(2026, 9, 1), date(2026, 8, 26), date(2026, 9, 22)
    )


def test_a_salary_month_falls_back_to_the_promised_payday_without_a_payment():
    # 26 Sep 2026 is a Saturday, so the promised payday is Friday the 25th.
    assert period_for(date(2026, 9, 1), 26, [date(2026, 8, 26)]) == Period(
        date(2026, 9, 1), date(2026, 8, 26), date(2026, 9, 24)
    )


def test_a_salary_far_from_the_promised_day_is_not_taken_as_payday():
    # 11 days early is too far to be the promised salary (e.g. a bonus).
    assert period_for(date(2026, 9, 1), 26, [date(2026, 8, 15)]).start == date(2026, 8, 26)


def test_an_early_salary_in_the_first_half_of_the_month_names_its_own_month():
    # Paid around the 1st: the salary that arrives on 30 Aug is for September.
    assert period_for(date(2026, 9, 1), 1, [date(2026, 8, 30)]) == Period(
        date(2026, 9, 1), date(2026, 8, 30), date(2026, 9, 30)
    )


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 8, 25), date(2026, 8, 1)),
        (date(2026, 8, 26), date(2026, 9, 1)),
        (date(2026, 9, 22), date(2026, 9, 1)),
        (date(2026, 9, 23), date(2026, 10, 1)),
    ],
)
def test_month_of_finds_the_salary_month_a_day_belongs_to(day, expected):
    assert month_of(day, 26, [date(2026, 8, 26), date(2026, 9, 23)]) == expected


def test_salary_paydays_are_the_salary_credits_oldest_first():
    rows = [
        (_tx(date(2026, 9, 23), 300_000), "Salary"),
        (_tx(date(2026, 8, 26), 300_000), "Salary"),
        (_tx(date(2026, 9, 1), -5_000), "Salary"),  # a debit is not a salary payment
        (_tx(date(2026, 9, 16), 50_000), "Other income"),
    ]

    assert salary_paydays(rows) == [date(2026, 8, 26), date(2026, 9, 23)]


def test_adjacent_months_skip_months_without_payments():
    months = [date(2026, 9, 1), date(2026, 7, 1), date(2026, 6, 1)]

    assert adjacent_months(months, date(2026, 7, 1)) == (date(2026, 6, 1), date(2026, 9, 1))
    assert adjacent_months(months, date(2026, 9, 1)) == (date(2026, 7, 1), None)
    assert adjacent_months(months, date(2026, 6, 1)) == (None, date(2026, 7, 1))
    # A month with no payments of its own still links to its neighbours.
    assert adjacent_months(months, date(2026, 8, 1)) == (date(2026, 7, 1), date(2026, 9, 1))


def test_parse_month_reads_year_and_month():
    assert parse_month("2026-09") == date(2026, 9, 1)


@pytest.mark.parametrize("text", ["", "2026", "2026-13", "2026-9", "2026-09-01", "Sep 2026"])
def test_parse_month_rejects_anything_else(text):
    with pytest.raises(ValueError):
        parse_month(text)


def test_a_category_total_has_a_filter_key_even_when_uncategorized():
    assert CategoryTotal("Groceries", "lights_on", -1_000, 1).key == "Groceries"
    assert CategoryTotal(None, None, -1_000, 1).key == UNCATEGORIZED


def test_only_category_keeps_the_payments_of_one_category_in_order():
    payments = (
        (_tx(date(2026, 9, 20), -2_000), "Groceries"),
        (_tx(date(2026, 9, 10), -9_000), None),
        (_tx(date(2026, 9, 3), -1_000), "Groceries"),
    )

    assert only_category(payments, "Groceries") == (payments[0], payments[2])
    assert only_category(payments, UNCATEGORIZED) == (payments[1],)
    assert only_category(payments, "Housing") == ()
