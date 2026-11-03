from datetime import date, timedelta

import pytest

from sonar.recurring.detect import NAME_LENGTH, detect_recurring, payment_key, series_keys
from sonar.transactions import ParsedTransaction

TODAY = date(2026, 9, 23)


def _card(
    booking_date: date = date(2026, 9, 1),
    merchant: str = "Cloud Lantern",
    amount_cents: int = -1710,
    counterparty: str = "ABRECHNUNG KARTE",
    purpose: str | None = None,
    mandate_ref: str | None = "CARD-001",
    creditor_id: str | None = "TEST-CREDITOR",
) -> ParsedTransaction:
    return ParsedTransaction(
        account="TEST-ACCOUNT",
        booking_date=booking_date,
        value_date=booking_date,
        amount_cents=amount_cents,
        currency="EUR",
        counterparty=counterparty,
        purpose=purpose if purpose is not None else f"{merchant}//EXAMPLE/CITY/XX",
        raw_row="",
        mandate_ref=mandate_ref,
        creditor_id=creditor_id,
    )


def test_card_keys_separate_merchants_despite_shared_creditor_and_distinct_mandates():
    cloud = _card(merchant="Cloud Lantern", mandate_ref="CARD-001")
    market = _card(merchant="Willow Market", mandate_ref="CARD-002")

    assert payment_key(cloud) == "card:cloud lantern"
    assert payment_key(market) == "card:willow market"
    assert payment_key(_card(mandate_ref="OTHER", creditor_id="OTHER-CREDITOR")) == (
        "card:cloud lantern"
    )


@pytest.mark.parametrize("counterparty", ["ABRECHNUNG KARTE", " abrechnung  Karte\t"])
@pytest.mark.parametrize("merchant", ["Cloud Lantern", "  CLOUD \t lantern  "])
def test_card_label_and_merchant_case_and_spacing_share_a_key(counterparty, merchant):
    assert payment_key(_card(counterparty=counterparty, merchant=merchant)) == (
        "card:cloud lantern"
    )


@pytest.mark.parametrize("purpose", ["Cloud Lantern", "  //CITY/XX", "//"])
@pytest.mark.parametrize(
    ("mandate_ref", "creditor_id", "expected"),
    [
        ("CARD-001", "TEST-CREDITOR", "mandate:TEST-CREDITOR/CARD-001"),
        (None, "TEST-CREDITOR", "creditor:TEST-CREDITOR"),
        (None, None, "counterparty:abrechnung karte"),
    ],
)
def test_missing_card_merchant_keeps_existing_key(purpose, mandate_ref, creditor_id, expected):
    assert (
        payment_key(_card(purpose=purpose, mandate_ref=mandate_ref, creditor_id=creditor_id))
        == expected
    )


@pytest.mark.parametrize(
    ("mandate_ref", "creditor_id", "expected"),
    [
        ("CARD-001", "TEST-CREDITOR", "mandate:TEST-CREDITOR/CARD-001"),
        (None, "TEST-CREDITOR", "creditor:TEST-CREDITOR"),
        (None, None, "counterparty:other bank"),
    ],
)
def test_non_card_keys_stay_unchanged(mandate_ref, creditor_id, expected):
    assert (
        payment_key(
            _card(counterparty=" Other  Bank ", mandate_ref=mandate_ref, creditor_id=creditor_id)
        )
        == expected
    )


def test_monthly_card_series_uses_latest_merchant_name_and_amount_among_weekly_rows():
    monthly = [
        _card(date(2026, month, 1), amount_cents=-amount, mandate_ref=f"MONTH-{month}")
        for month, amount in zip(range(6, 10), [1710, 1760, 1800, 1823], strict=True)
    ]
    monthly[-1] = _card(
        date(2026, 9, 1), merchant="  CLOUD  Lantern\t", amount_cents=-1823, mandate_ref="LAST"
    )
    weekly = [
        _card(
            date(2026, 6, 1) + timedelta(weeks=week),
            merchant="Willow Market",
            mandate_ref=f"WEEK-{week}",
        )
        for week in range(17)
    ]

    [series] = detect_recurring([(tx, None) for tx in reversed(monthly + weekly)], {}, TODAY)

    assert series.key == "card:cloud lantern"
    assert series.name == "CLOUD Lantern"
    assert series.schedule.amount_cents == 1823
    assert series.schedule.interval_months == 1


def test_same_day_card_charges_split_into_amount_ranked_series():
    rows = [
        _card(date(2026, month, 1), amount_cents=amount, mandate_ref=f"{month}-{amount}")
        for month in range(6, 10)
        for amount in (-1710, -4000)
    ]

    assert [key for _, key in series_keys(rows)] == [
        "card:cloud lantern#2",
        "card:cloud lantern#1",
    ] * 4
    detected = detect_recurring([(tx, None) for tx in rows], {}, TODAY)
    assert [(series.key, series.schedule.amount_cents) for series in detected] == [
        ("card:cloud lantern#1", 4000),
        ("card:cloud lantern#2", 1710),
    ]


def test_card_series_name_is_limited_to_name_length():
    merchant = "Lantern " * 8
    rows = [(_card(date(2026, month, 1), merchant=merchant), None) for month in range(6, 10)]

    [series] = detect_recurring(rows, {}, TODAY)

    assert series.name == " ".join(merchant.split())[:NAME_LENGTH]
