"""Plain data shapes produced by importers, before any storage decisions.

Importers turn raw bank export bytes into these frozen dataclasses. Money is
integer cents, never float, and dates are `datetime.date` per SPEC §2.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ParsedTransaction:
    """One transaction row as read from a bank export, before fingerprinting."""

    account: str
    booking_date: date
    value_date: date
    amount_cents: int
    currency: str
    counterparty: str
    purpose: str
    raw_row: str
    iban: str | None = None
    mandate_ref: str | None = None
    creditor_id: str | None = None


@dataclass(frozen=True)
class ParsedBalance:
    """An account balance as of a date, as reported by an export."""

    account: str
    as_of: date
    amount_cents: int
