"""Tests for draft debts (SPEC §13 Draft debts): which payments qualify, and their prefill."""

from datetime import date

from sonar.debts.drafts import DraftPrefill, draft_prefill, qualifies
from sonar.debts.model import MatchRule, linked_keys
from sonar.recurring.schedule import SchedulePeriod
from sonar.recurring.store import RecurringPayment
from sonar.transactions import ParsedTransaction

LOANS = "Loans & Installments"
MANDATE_KEY = "mandate:DE00ZZZ0000000001/M-1"
COUNTERPARTY_KEY = "counterparty:furniture store"


def _tx(
    booking_date: date,
    *,
    amount_cents: int = -10_000,
    counterparty: str = "Furniture Store",
    mandate_ref: str | None = None,
    creditor_id: str | None = None,
) -> ParsedTransaction:
    return ParsedTransaction(
        account="acc",
        booking_date=booking_date,
        value_date=booking_date,
        amount_cents=amount_cents,
        currency="EUR",
        counterparty=counterparty,
        purpose="",
        raw_row="raw",
        mandate_ref=mandate_ref,
        creditor_id=creditor_id,
    )


def _period(starts_on: date, amount_cents: int = 10_000, interval: int = 1) -> SchedulePeriod:
    return SchedulePeriod(
        starts_on=starts_on,
        until=None,
        amount_cents=amount_cents,
        interval_months=interval,
        day=starts_on.day,
    )


def _payment(
    detection_key: str | None = MANDATE_KEY,
    *,
    name: str = "Car Bank",
    category: str | None = LOANS,
    status: str = "active",
    periods: tuple[SchedulePeriod, ...] = (),
) -> RecurringPayment:
    return RecurringPayment(
        id=1,
        detection_key=detection_key,
        name=name,
        category=category,
        status=status,
        source="detected",
        name_locked=False,
        schedule_locked=False,
        last_paid_date=None,
        periods=periods or (_period(date(2026, 1, 5)),),
    )


def _mandate_tx(booking_date: date, counterparty: str = "Car Bank") -> ParsedTransaction:
    return _tx(
        booking_date,
        counterparty=counterparty,
        mandate_ref="M-1",
        creditor_id="DE00ZZZ0000000001",
    )


# Qualifying


def test_active_keyed_payment_in_a_flagged_category_qualifies():
    assert qualifies(_payment(), {LOANS}, frozenset())


def test_dismissed_payment_does_not_qualify():
    assert not qualifies(_payment(status="dismissed"), {LOANS}, frozenset())


def test_manual_payment_without_a_key_does_not_qualify():
    assert not qualifies(_payment(None), {LOANS}, frozenset())


def test_payment_in_an_unflagged_category_does_not_qualify():
    assert not qualifies(_payment(category="Rent"), {LOANS}, frozenset())
    assert not qualifies(_payment(category=None), {LOANS}, frozenset())


def test_payment_a_debt_already_links_does_not_qualify():
    assert not qualifies(_payment(), {LOANS}, frozenset({MANDATE_KEY}))


# Prefill


def test_mandate_payment_prefill_uses_the_mandate_and_the_earliest_debit():
    txs = [
        _mandate_tx(date(2026, 3, 5)),
        _mandate_tx(date(2026, 1, 5)),
        _mandate_tx(date(2026, 2, 5)),
    ]

    prefill = draft_prefill(_payment(), txs)

    assert prefill == DraftPrefill(
        name="Car Bank",
        rate_cents=10_000,
        interval_months=1,
        first_payment_date=date(2026, 1, 5),
        match=MatchRule("mandate", "M-1"),
    )


def test_prefill_takes_rate_and_interval_from_the_latest_period():
    periods = (
        _period(date(2026, 1, 5), amount_cents=10_000, interval=1),
        _period(date(2026, 6, 5), amount_cents=12_500, interval=3),
    )
    txs = [_mandate_tx(date(2026, 1, 5))]

    prefill = draft_prefill(_payment(periods=periods), txs)

    assert prefill is not None
    assert prefill.rate_cents == 12_500
    assert prefill.interval_months == 3


def test_counterparty_payment_prefill_uses_the_latest_debits_counterparty():
    txs = [
        _tx(date(2026, 1, 5), counterparty="FURNITURE STORE"),
        _tx(date(2026, 2, 5), counterparty="Furniture  Store"),
        _tx(date(2026, 3, 5), counterparty="Furniture Store"),
    ]

    prefill = draft_prefill(_payment(COUNTERPARTY_KEY, name="Furniture Store"), txs)

    assert prefill is not None
    assert prefill.name == "Furniture Store"
    assert prefill.match == MatchRule("counterparty", "Furniture Store")
    assert prefill.first_payment_date == date(2026, 1, 5)


def test_mandate_rule_comes_from_the_latest_debit():
    txs = [
        _tx(date(2026, 1, 5), mandate_ref="M-OLD", creditor_id="DE00ZZZ0000000001"),
        _tx(date(2026, 2, 5), mandate_ref="M-NEW", creditor_id="DE00ZZZ0000000001"),
    ]
    key = "mandate:DE00ZZZ0000000001/M-NEW"

    prefill = draft_prefill(_payment(key), txs)

    assert prefill is not None
    assert prefill.match == MatchRule("mandate", "M-NEW")
    assert prefill.first_payment_date == date(2026, 2, 5)


def test_credits_and_other_keys_are_ignored():
    txs = [
        _mandate_tx(date(2026, 3, 5)),
        _tx(
            date(2026, 1, 5), amount_cents=5_000, mandate_ref="M-1", creditor_id="DE00ZZZ0000000001"
        ),
        _tx(date(2026, 2, 5), counterparty="Other Bank", mandate_ref="M-2"),
    ]

    prefill = draft_prefill(_payment(), txs)

    assert prefill is not None
    assert prefill.first_payment_date == date(2026, 3, 5)
    assert prefill.match == MatchRule("mandate", "M-1")


def test_payment_without_a_matching_debit_has_no_prefill():
    txs = [
        _tx(
            date(2026, 1, 5),
            amount_cents=10_000,
            mandate_ref="M-1",
            creditor_id="DE00ZZZ0000000001",
        )
    ]

    assert draft_prefill(_payment(), txs) is None


def test_prefilled_rule_links_back_to_the_payment():
    txs = [_mandate_tx(date(2026, 1, 5)), _tx(date(2026, 2, 5), counterparty="Furniture Store")]
    for payment in (_payment(), _payment(COUNTERPARTY_KEY, name="Furniture Store")):
        prefill = draft_prefill(payment, txs)

        assert prefill is not None
        assert payment.detection_key in linked_keys(prefill, txs)


def test_split_series_prefill_uses_only_the_smaller_same_day_debits():
    txs = []
    for booking_date in (date(2026, 1, 5), date(2026, 4, 5), date(2026, 7, 5)):
        txs.append(_mandate_tx_amount(booking_date, -30_000))
        txs.append(_mandate_tx_amount(booking_date, -5_000))
    txs.insert(0, _mandate_tx_amount(date(2025, 10, 5), -30_000))

    prefill = draft_prefill(_payment(MANDATE_KEY + "#2"), txs)

    assert prefill is not None
    assert prefill.first_payment_date == date(2026, 1, 5)
    assert prefill.match == MatchRule("mandate", "M-1")


def test_split_series_prefill_ignores_larger_debits_on_earlier_days():
    txs = [
        _mandate_tx_amount(date(2025, 12, 5), -30_000),
        _mandate_tx_amount(date(2026, 1, 5), -30_000),
        _mandate_tx_amount(date(2026, 1, 5), -5_000),
    ]

    prefill = draft_prefill(_payment(MANDATE_KEY + "#2"), txs)

    assert prefill is not None
    assert prefill.first_payment_date == date(2026, 1, 5)


def test_split_series_prefill_starts_at_the_first_lone_small_debit():
    txs = [_mandate_tx_amount(date(2026, m, 1), -3_300) for m in range(1, 10)]
    txs += [
        _mandate_tx_amount(date(2026, 3, 3), -67_000),
        _mandate_tx_amount(date(2026, 6, 2), -170_000),
        _mandate_tx_amount(date(2026, 9, 1), -120_000),
    ]

    prefill = draft_prefill(_payment(MANDATE_KEY + "#2"), txs)

    assert prefill is not None
    assert prefill.first_payment_date == date(2026, 1, 1)


def _mandate_tx_amount(booking_date: date, amount_cents: int) -> ParsedTransaction:
    return _tx(
        booking_date,
        amount_cents=amount_cents,
        counterparty="Car Bank",
        mandate_ref="M-1",
        creditor_id="DE00ZZZ0000000001",
    )
