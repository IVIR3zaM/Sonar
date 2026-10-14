"""A stand-in for the Enable Banking client so bank page tests never touch the network."""

from __future__ import annotations

from datetime import date, datetime

from sonar.banking.client import BankApiError

BANK_AUTH_URL = "https://auth.example.com/start"
OWN_IBAN = "DE00000000000000001234"


def booked_debit(
    reference: str,
    amount: str = "12.34",
    booking_date: str = "2026-10-12",
    creditor: str = "Grocer Example",
    purpose: str = "Card payment",
) -> dict:
    """An anonymized Enable Banking booked debit from the owner's account."""
    return {
        "entry_reference": reference,
        "transaction_amount": {"currency": "EUR", "amount": amount},
        "credit_debit_indicator": "DBIT",
        "creditor": {"name": creditor},
        "creditor_account": {"iban": "DE99000000000000000001"},
        "debtor": {"name": "Owner Example"},
        "debtor_account": {"iban": OWN_IBAN},
        "remittance_information": [purpose],
        "booking_date": booking_date,
        "value_date": booking_date,
    }


def listed_balance(amount: str, balance_type: str = "ITAV") -> dict:
    return {
        "name": balance_type,
        "balance_type": balance_type,
        "balance_amount": {"currency": "EUR", "amount": amount},
    }


class FakeBank:
    def __init__(self) -> None:
        self.error: BankApiError | None = None
        self.states: list[str] = []
        self.valid_untils: list[datetime] = []
        self.redirect_urls: list[str] = []
        self.codes: list[str] = []
        self.iban = "DE00000000000000001234"
        self.session_id = "session-1"
        self.accounts: list[dict] | None = None
        self.booked: list[dict] = []
        self.balance_list: list[dict] = []
        self.windows: list[tuple[str, date, date]] = []

    def booked_transactions(self, account_uid: str, date_from: date, date_to: date) -> list[dict]:
        if self.error is not None:
            raise self.error
        self.windows.append((account_uid, date_from, date_to))
        return list(self.booked)

    def balances(self, account_uid: str) -> list[dict]:
        if self.error is not None:
            raise self.error
        return list(self.balance_list)

    def aspsps(self, country: str) -> list[dict]:
        return [
            {"name": "Other Bank", "country": country, "maximum_consent_validity": 100},
            {"name": "Deutsche Bank", "country": country, "maximum_consent_validity": 15552000},
        ]

    def start_authorization(self, valid_until: datetime, state: str, redirect_url: str) -> dict:
        if self.error is not None:
            raise self.error
        self.valid_untils.append(valid_until)
        self.states.append(state)
        self.redirect_urls.append(redirect_url)
        return {"url": BANK_AUTH_URL}

    def create_session(self, code: str) -> dict:
        if self.error is not None:
            raise self.error
        self.codes.append(code)
        return {
            "session_id": self.session_id,
            "accounts": self._accounts(),
            "access": {"valid_until": "2027-03-01T00:00:00+00:00"},
        }

    def _accounts(self) -> list[dict]:
        if self.accounts is not None:
            return self.accounts
        return [
            {"uid": "account-1", "account_id": {"iban": self.iban}, "cash_account_type": "CACC"}
        ]
