from datetime import date

import pytest

from sonar.recurring.detect import (
    DetectedPayment,
    detect_income,
    detect_recurring,
    payment_key,
    series_keys,
)
from sonar.recurring.schedule import SchedulePeriod
from sonar.transactions import ParsedTransaction

TODAY = date(2026, 9, 23)
CREDITOR = "DE98ZZZ09999999999"
TYPES = {
    "Utilities": "fixed",
    "Groceries": "lights_on",
    "Dining": "occasional",
    "Own transfers": "transfer",
    "Benefits": "income",
}


def _tx(
    booking_date: date,
    amount_cents: int = -5000,
    counterparty: str = "Acme Energy",
    purpose: str = "Abschlag",
    mandate_ref: str | None = None,
    creditor_id: str | None = None,
) -> ParsedTransaction:
    return ParsedTransaction(
        account="DE00 0000 0000 0000 0000 00",
        booking_date=booking_date,
        value_date=booking_date,
        amount_cents=amount_cents,
        currency="EUR",
        counterparty=counterparty,
        purpose=purpose,
        raw_row="",
        mandate_ref=mandate_ref,
        creditor_id=creditor_id,
    )


def _rows(*dates: date, category: str | None = "Utilities", **fields):
    return [(_tx(d, **fields), category) for d in dates]


def _detect(rows, today: date = TODAY) -> list[DetectedPayment]:
    return detect_recurring(rows, TYPES, today)


@pytest.mark.parametrize(
    ("dates", "interval", "day", "next_due"),
    [
        (
            [date(2026, 6, 1), date(2026, 7, 1), date(2026, 8, 1), date(2026, 9, 1)],
            1,
            1,
            date(2026, 10, 1),
        ),
        (
            [date(2026, 3, 15), date(2026, 5, 15), date(2026, 7, 15), date(2026, 9, 15)],
            2,
            15,
            date(2026, 11, 15),
        ),
        (
            [date(2025, 12, 10), date(2026, 3, 10), date(2026, 6, 10), date(2026, 9, 10)],
            3,
            10,
            date(2026, 12, 10),
        ),
        ([date(2025, 10, 20), date(2026, 4, 20)], 6, 20, date(2026, 10, 20)),
        ([date(2024, 11, 5), date(2025, 11, 5)], 12, 5, date(2026, 11, 5)),
    ],
)
def test_each_interval_is_detected_with_its_next_due_date(dates, interval, day, next_due):
    [payment] = _detect(_rows(*dates))

    assert payment == DetectedPayment(
        key="counterparty:acme energy",
        name="Acme Energy",
        category="Utilities",
        schedule=SchedulePeriod(
            starts_on=dates[0], until=None, amount_cents=5000, interval_months=interval, day=day
        ),
        last_paid_date=dates[-1],
        next_due_date=next_due,
    )


def test_weekend_jitter_of_five_days_is_accepted():
    dates = [date(2026, 6, 1), date(2026, 7, 6), date(2026, 8, 1), date(2026, 9, 1)]

    [payment] = _detect(_rows(*dates))

    assert payment.schedule.interval_months == 1
    assert payment.schedule.day == 1
    assert payment.next_due_date == date(2026, 10, 1)


def test_late_first_payment_keeps_the_bimonthly_phase():
    # A first payment after the typical day must not shift the schedule a month.
    dates = [date(2026, 3, 18), date(2026, 5, 15), date(2026, 7, 15), date(2026, 9, 15)]

    [payment] = _detect(_rows(*dates))

    assert payment.schedule.day == 15
    assert payment.next_due_date == date(2026, 11, 15)


def test_ten_day_offset_breaks_the_run():
    dates = [date(2026, 6, 1), date(2026, 7, 11), date(2026, 8, 1), date(2026, 9, 1)]

    assert _detect(_rows(*dates)) == []


def test_two_monthly_payments_are_not_enough_evidence():
    assert _detect(_rows(date(2026, 8, 1), date(2026, 9, 1))) == []


@pytest.mark.parametrize(
    ("dates", "interval"),
    [
        ([date(2026, 7, 15), date(2026, 9, 15)], 2),
        ([date(2026, 6, 10), date(2026, 9, 10)], 3),
    ],
)
def test_two_payments_are_not_enough_for_bimonthly_and_quarterly(dates, interval):
    """MIN_PAYMENTS[2] and MIN_PAYMENTS[3] are both 3, not 2."""
    assert _detect(_rows(*dates)) == []


def test_two_annual_payments_are_enough_evidence():
    [payment] = _detect(_rows(date(2024, 11, 5), date(2025, 11, 5)))

    assert payment.schedule.interval_months == 12


MONTHLY = (date(2026, 7, 1), date(2026, 8, 1), date(2026, 9, 1))


@pytest.mark.parametrize("category", ["Groceries", "Dining", "Own transfers"])
def test_lights_on_occasional_and_transfer_categories_are_excluded(category):
    assert _detect(_rows(*MONTHLY, category=category)) == []


def test_credits_are_excluded():
    assert _detect(_rows(*MONTHLY, amount_cents=5000)) == []


@pytest.mark.parametrize("category", [None, "Not in taxonomy"])
def test_uncategorized_and_unknown_categories_are_included(category):
    [payment] = _detect(_rows(*MONTHLY, category=category))

    assert payment.category == category


def test_two_mandates_from_one_creditor_give_two_payments():
    rows = _rows(*MONTHLY, mandate_ref="M-1", creditor_id=CREDITOR) + _rows(
        *MONTHLY, mandate_ref="M-2", creditor_id=CREDITOR
    )

    keys = [p.key for p in _detect(rows)]

    assert keys == [f"mandate:{CREDITOR}/M-1", f"mandate:{CREDITOR}/M-2"]


def test_creditor_id_merges_counterparty_name_variants():
    rows = [
        (_tx(date(2026, 7, 1), counterparty="ACME Energy GmbH", creditor_id=CREDITOR), None),
        (_tx(date(2026, 8, 1), counterparty="Acme Energie", creditor_id=CREDITOR), None),
        (_tx(date(2026, 9, 1), counterparty="Acme Energy AG", creditor_id=CREDITOR), None),
    ]

    [payment] = _detect(rows)

    assert payment.key == f"creditor:{CREDITOR}"
    assert payment.name == "Acme Energy AG"


def test_case_and_space_counterparty_variants_merge():
    rows = [
        (_tx(date(2026, 7, 1), counterparty="Acme  Energy"), None),
        (_tx(date(2026, 8, 1), counterparty="ACME ENERGY"), None),
        (_tx(date(2026, 9, 1), counterparty=" acme energy "), None),
    ]

    [payment] = _detect(rows)

    assert payment.key == "counterparty:acme energy"


def test_varying_amounts_use_the_latest_amount():
    rows = [
        (_tx(date(2026, 7, 1), amount_cents=-4800), None),
        (_tx(date(2026, 9, 1), amount_cents=-5250), None),
        (_tx(date(2026, 8, 1), amount_cents=-5100), None),
    ]

    [payment] = _detect(rows)

    assert payment.schedule.amount_cents == 5250


def test_typical_day_is_the_low_median_of_the_run():
    dates = [date(2026, 6, 4), date(2026, 7, 1), date(2026, 8, 3), date(2026, 9, 2)]

    [payment] = _detect(_rows(*dates))

    assert payment.schedule.day == 2


def test_category_comes_from_the_latest_row():
    rows = _rows(date(2026, 7, 1), date(2026, 8, 1), category=None) + _rows(date(2026, 9, 1))

    [payment] = _detect(rows)

    assert payment.category == "Utilities"


def test_name_falls_back_to_purpose_cut_to_40_chars():
    purpose = "SEPA Lastschrift Stadtwerke Beispielstadt Kundennummer 123"

    [payment] = _detect(_rows(*MONTHLY, counterparty="", purpose=purpose))

    assert payment.name == purpose[:40]
    assert payment.key == "counterparty:"


def test_stale_series_is_dropped_against_the_latest_booking_date():
    series = _rows(date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1))
    # last paid 2026-03-01 + 1 month + 7 days = 2026-04-08
    still_due = [(_tx(date(2026, 4, 8), amount_cents=300000, counterparty="Employer"), None)]
    overdue = [(_tx(date(2026, 4, 9), amount_cents=300000, counterparty="Employer"), None)]

    assert len(_detect(series + still_due)) == 1
    assert _detect(series + overdue) == []


def test_payments_are_sorted_by_key():
    rows = _rows(*MONTHLY, counterparty="Zeta Mobile") + _rows(*MONTHLY, counterparty="Acme")

    keys = [p.key for p in _detect(rows)]

    assert keys == ["counterparty:acme", "counterparty:zeta mobile"]


SALARY_DAY = 28


def _income(rows, salary_day: int = SALARY_DAY, today: date = TODAY) -> list[DetectedPayment]:
    return detect_income(rows, TYPES, salary_day, today)


def _benefit_rows(*dates: date, category: str | None = "Benefits", amount_cents: int = 25000):
    return _rows(
        *dates, category=category, amount_cents=amount_cents, counterparty="Family Benefits Office"
    )


def _monthly_on(day: int) -> list[date]:
    return [date(2026, 7, day), date(2026, 8, day), date(2026, 9, day)]


def test_monthly_benefit_credit_is_detected_as_income():
    rows = _benefit_rows(*_monthly_on(15))

    [payment] = _income(rows)

    assert payment == DetectedPayment(
        key="counterparty:family benefits office",
        name="Family Benefits Office",
        category="Benefits",
        schedule=SchedulePeriod(
            starts_on=date(2026, 7, 15),
            until=None,
            amount_cents=25000,
            interval_months=1,
            day=15,
        ),
        last_paid_date=date(2026, 9, 15),
        next_due_date=date(2026, 10, 15),
    )


def test_income_uses_the_latest_amount():
    rows = _benefit_rows(date(2026, 7, 15), date(2026, 8, 15), amount_cents=25000)
    rows += _benefit_rows(date(2026, 9, 15), amount_cents=26000)

    [payment] = _income(rows)

    assert payment.schedule.amount_cents == 26000


@pytest.mark.parametrize(
    ("day", "kept"),
    [(21, False), (20, True), (28, False), (3, False)],
)
def test_series_within_seven_days_of_the_salary_day_is_the_salary(day, kept):
    # day 21 is exactly 7 from 28 (salary); day 20 is 8 away and kept.
    assert bool(_income(_benefit_rows(*_monthly_on(day)))) is kept


def test_salary_distance_counts_across_the_month_end():
    # day 2 vs salary day 28: |2 - 28| = 26, 31 - 26 = 5, so it is the salary.
    assert _income(_benefit_rows(*_monthly_on(2))) == []


def test_salary_distance_across_the_month_end_of_eight_is_kept():
    # day 5 vs salary day 28: |5 - 28| = 23, 31 - 23 = 8.
    assert len(_income(_benefit_rows(*_monthly_on(5)))) == 1


def test_debits_in_an_income_category_are_ignored():
    assert _income(_benefit_rows(*_monthly_on(15), amount_cents=-25000)) == []


@pytest.mark.parametrize("category", ["Utilities", "Own transfers", "Groceries", "Dining", None])
def test_credits_outside_income_categories_are_ignored(category):
    assert _income(_benefit_rows(*_monthly_on(15), category=category)) == []


def test_stopped_income_series_is_dropped():
    series = _benefit_rows(date(2026, 1, 15), date(2026, 2, 15), date(2026, 3, 15))
    # last paid 2026-03-15 + 1 month + 7 days = 2026-04-22
    later = [(_tx(date(2026, 4, 23), counterparty="Other"), None)]

    assert _income(series + later) == []


def test_quarterly_income_with_three_payments_is_detected():
    rows = _benefit_rows(date(2026, 3, 10), date(2026, 6, 10), date(2026, 9, 10))

    [payment] = _income(rows)

    assert payment.schedule.interval_months == 3
    assert payment.next_due_date == date(2026, 12, 10)


def test_no_income_rows_give_no_series():
    assert _income([]) == []


QUARTERLY = [date(2026, 3, 10), date(2026, 6, 10), date(2026, 9, 10)]
MANDATE_KEY = f"mandate:{CREDITOR}/M-0001"


def _shared_mandate_rows(dates: list[date], amounts: tuple[int, ...], **fields):
    return [
        (_tx(d, amount_cents=a, mandate_ref="M-0001", creditor_id=CREDITOR, **fields), "Utilities")
        for d in dates
        for a in amounts
    ]


def test_same_day_charges_under_one_mandate_split_into_series_by_amount_rank():
    rows = _shared_mandate_rows(QUARTERLY, (-1205, -7612))

    large, small = _detect(rows)

    assert (large.key, large.schedule.amount_cents, large.schedule.interval_months) == (
        f"{MANDATE_KEY}#1",
        7612,
        3,
    )
    assert (small.key, small.schedule.amount_cents, small.schedule.interval_months) == (
        f"{MANDATE_KEY}#2",
        1205,
        3,
    )


def test_a_quarter_with_only_the_larger_charge_still_detects_the_first_series():
    rows = _shared_mandate_rows(QUARTERLY[:2], (-1205, -7612))
    rows += _shared_mandate_rows(QUARTERLY[2:], (-7612,))

    [large] = _detect(rows)

    assert (large.key, large.schedule.amount_cents) == (f"{MANDATE_KEY}#1", 7612)
    assert large.last_paid_date == QUARTERLY[2]


def test_series_keys_keep_the_bare_key_when_each_date_has_one_payment():
    txs = [row[0] for row in _shared_mandate_rows(QUARTERLY, (-1205,))]

    assert [key for _, key in series_keys(txs)] == [payment_key(txs[0])] * 3


def test_series_keys_rank_by_absolute_amount_and_break_ties_by_input_order():
    small, large, tie_a, tie_b = (
        _tx(QUARTERLY[0], amount_cents=a, mandate_ref="M-0001", creditor_id=CREDITOR)
        for a in (-1205, -7612, -300, -300)
    )

    pairs = series_keys([small, large, tie_a, tie_b])

    assert [tx for tx, _ in pairs] == [small, large, tie_a, tie_b]
    assert [key for _, key in pairs] == [
        f"{MANDATE_KEY}#2",
        f"{MANDATE_KEY}#1",
        f"{MANDATE_KEY}#3",
        f"{MANDATE_KEY}#4",
    ]


MONTHLY_FIRSTS = [date(2026, m, 1) for m in range(1, 10)]
QUARTERLY_LONE = [
    (date(2026, 3, 3), -67000),
    (date(2026, 6, 2), -170000),
    (date(2026, 9, 1), -120000),
]


def _mandate_tx(booking_date: date, amount_cents: int) -> ParsedTransaction:
    return _tx(booking_date, amount_cents=amount_cents, mandate_ref="M-0001", creditor_id=CREDITOR)


def test_lone_payments_join_the_series_with_the_nearest_amount():
    rows = [(_mandate_tx(d, -3300), "Utilities") for d in MONTHLY_FIRSTS]
    rows += [(_mandate_tx(d, a), "Utilities") for d, a in QUARTERLY_LONE]

    quarterly, monthly = _detect(rows)

    assert (quarterly.key, quarterly.schedule.amount_cents, quarterly.schedule.interval_months) == (
        f"{MANDATE_KEY}#1",
        120000,
        3,
    )
    assert (monthly.key, monthly.schedule.amount_cents, monthly.schedule.interval_months) == (
        f"{MANDATE_KEY}#2",
        3300,
        1,
    )


def test_series_keys_assign_a_short_date_to_the_nearest_ranks():
    full = [_mandate_tx(QUARTERLY[0], a) for a in (-9000, -5000, -1000)]
    short = [_mandate_tx(QUARTERLY[1], a) for a in (-5100, -950)]

    pairs = series_keys(full + short)

    assert [key for _, key in pairs[3:]] == [f"{MANDATE_KEY}#2", f"{MANDATE_KEY}#3"]


def test_series_keys_give_an_equidistant_lone_payment_the_lower_rank():
    full = [_mandate_tx(QUARTERLY[0], a) for a in (-9000, -1000)]
    lone = _mandate_tx(QUARTERLY[1], -5000)

    pairs = series_keys([*full, lone])

    assert pairs[2][1] == f"{MANDATE_KEY}#1"


def test_same_day_income_credits_split_through_detect_income():
    rows = [
        (_tx(d, amount_cents=a, counterparty="Family Benefits Office"), "Benefits")
        for d in _monthly_on(15)
        for a in (10000, 25000)
    ]

    large, small = _income(rows)

    assert (large.key, large.schedule.amount_cents) == (
        "counterparty:family benefits office#1",
        25000,
    )
    assert (small.key, small.schedule.amount_cents) == (
        "counterparty:family benefits office#2",
        10000,
    )
