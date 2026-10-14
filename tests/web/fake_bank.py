"""A stand-in for the Enable Banking client so bank page tests never touch the network."""

from __future__ import annotations

from datetime import datetime

from sonar.banking.client import BankApiError

BANK_AUTH_URL = "https://auth.example.com/start"


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
