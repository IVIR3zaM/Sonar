from datetime import date

import pytest

from sonar.recurrence import DetectedPayment, detect_recurring
from sonar.schedule import SchedulePeriod
from sonar.transactions import ParsedTransaction

TODAY = date(2026, 9, 23)
CREDITOR = "DE98ZZZ09999999999"
TYPES = {
    "Utilities": "fixed",
    "Groceries": "lights_on",
    "Dining": "occasional",
    "Own transfers": "transfer",
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
