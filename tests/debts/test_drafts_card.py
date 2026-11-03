"""Card debt drafts match the merchant purpose rather than the settlement label."""

from datetime import date

from sonar.debts.drafts import draft_prefill, qualifies
from sonar.debts.model import MatchRule, linked_keys
from sonar.recurring.schedule import SchedulePeriod
from sonar.recurring.store import RecurringPayment
from sonar.transactions import ParsedTransaction


def test_card_debt_prefill_matches_only_its_merchant():
    payment = RecurringPayment(
        id=1,
        detection_key="card:streamco .video subscr",
        name="Family video",
        category="Loans & Installments",
        status="active",
        source="detected",
        name_locked=True,
        schedule_locked=False,
        last_paid_date=date(2026, 9, 10),
        periods=(SchedulePeriod(date(2026, 7, 10), None, 1823, 1, 10),),
    )
    transactions = [
        ParsedTransaction(
            account="fixture-account",
            booking_date=booking_date,
            value_date=booking_date,
            amount_cents=amount,
            currency="EUR",
            counterparty="ABRECHNUNG KARTE",
            purpose=f"{merchant}//EXAMPLE CITY/DE 2026-09-10T12:00 Kartennr. XXXX0000",
            mandate_ref=f"FICTION-{index}",
            creditor_id="DE00ZZZ00000000000",
            raw_row="synthetic",
        )
        for index, (booking_date, merchant, amount) in enumerate(
            [
                (date(2026, 7, 10), "STREAMCO .VIDEO SUBSCR", -1710),
                (date(2026, 9, 10), "STREAMCO .VIDEO SUBSCR", -1823),
                (date(2026, 9, 11), "FICTIONAL GROCER", -5000),
                (date(2026, 9, 12), "STREAMCO .VIDEO SUBSCR", 1823),
            ]
        )
    ]
    assert qualifies(payment, {"Loans & Installments"}, frozenset())

    prefill = draft_prefill(payment, transactions)

    assert prefill is not None
    assert prefill.name == "Family video"
    assert prefill.match == MatchRule("purpose", "STREAMCO .VIDEO SUBSCR")
    assert prefill.rate_cents == 1823
    assert prefill.interval_months == 1
    assert prefill.first_payment_date == date(2026, 7, 10)
    assert linked_keys(prefill, transactions) == frozenset({payment.detection_key})
