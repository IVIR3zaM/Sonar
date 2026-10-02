"""Draft debts from recurring payments in debt categories (SPEC §13 Draft debts).

Pure functions only: the store passes in payments and transactions. An open
draft holds no hand-entered data, so its prefill is computed here on every read
and always follows the latest detection and the owner's schedule edits.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from sonar.debts.model import MatchRule
from sonar.recurring.detect import payment_key
from sonar.transactions import ParsedTransaction

if TYPE_CHECKING:
    from sonar.recurring.store import RecurringPayment


@dataclass(frozen=True)
class DraftPrefill:
    name: str
    rate_cents: int
    interval_months: int
    first_payment_date: date
    match: MatchRule


def qualifies(
    payment: RecurringPayment, debt_categories: set[str], debt_keys: frozenset[str]
) -> bool:
    """Whether a payment needs a draft: an existing debt already holds its details."""
    return (
        payment.status == "active"
        and payment.detection_key is not None
        and payment.category in debt_categories
        and payment.detection_key not in debt_keys
    )


def draft_prefill(
    payment: RecurringPayment, txs: Iterable[ParsedTransaction]
) -> DraftPrefill | None:
    """The debt form's starting values, or None when no debit backs the payment."""
    debits = sorted(
        (tx for tx in txs if tx.amount_cents < 0 and payment_key(tx) == payment.detection_key),
        key=lambda tx: tx.booking_date,
    )
    if not debits:
        return None
    match = _match_rule(payment.detection_key or "", debits[-1])
    if match is None:
        return None
    # The latest period carries the owner's edits and any detected price change.
    latest = payment.periods[-1]
    return DraftPrefill(
        name=payment.name,
        rate_cents=latest.amount_cents,
        interval_months=latest.interval_months,
        first_payment_date=debits[0].booking_date,
        match=match,
    )


def _match_rule(detection_key: str, latest: ParsedTransaction) -> MatchRule | None:
    if detection_key.startswith("mandate:") and latest.mandate_ref:
        return MatchRule("mandate", latest.mandate_ref)
    # A debit without a counterparty has nothing a debt could match on.
    if not latest.counterparty.strip():
        return None
    return MatchRule("counterparty", latest.counterparty)
