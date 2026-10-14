"""Enable Banking HTTP client (SPEC §13 Bank sync): signs requests, returns raw payload dicts.

A thin shell: mapping payloads to domain objects happens elsewhere. Errors carry only a status
and a short fixed-shape text, never the request, the credentials or the bank's body.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

import httpx
from authlib.jose import jwt

from sonar.banking.settings import ASPSP_COUNTRY, ASPSP_NAME

BASE_URL = "https://api.enablebanking.com"
_JWT_LIFETIME_SECONDS = 3600
_ERROR_CODE = re.compile(r"[A-Z_]{1,40}")


class BankApiError(Exception):
    def __init__(self, status: int | None, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def default_http() -> httpx.Client:
    return httpx.Client(timeout=30.0, verify=True)


class EnableBankingClient:
    def __init__(
        self,
        app_id: str,
        private_key_pem: bytes,
        http: httpx.Client,
        now: Callable[[], datetime],
    ) -> None:
        self._app_id = app_id
        self._private_key_pem = private_key_pem
        self._http = http
        self._now = now

    def aspsps(self, country: str) -> list[dict]:
        return self._request("GET", "/aspsps", params={"country": country})["aspsps"]

    def start_authorization(self, valid_until: datetime, state: str, redirect_url: str) -> dict:
        body = {
            "access": {"valid_until": valid_until.isoformat()},
            "aspsp": {"name": ASPSP_NAME, "country": ASPSP_COUNTRY},
            "state": state,
            "redirect_url": redirect_url,
            "psu_type": "personal",
        }
        return self._request("POST", "/auth", json=body)

    def create_session(self, code: str) -> dict:
        return self._request("POST", "/sessions", json={"code": code})

    def booked_transactions(self, account_uid: str, date_from: date, date_to: date) -> list[dict]:
        params = {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "transaction_status": "BOOK",
        }
        transactions: list[dict] = []
        while True:
            answer = self._request("GET", f"/accounts/{account_uid}/transactions", params=params)
            transactions.extend(answer["transactions"])
            continuation_key = answer.get("continuation_key")
            if not continuation_key:
                return transactions
            params = {**params, "continuation_key": continuation_key}

    def balances(self, account_uid: str) -> list[dict]:
        return self._request("GET", f"/accounts/{account_uid}/balances")["balances"]

    def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        headers = {"Authorization": f"Bearer {self._token()}"}
        try:
            response = self._http.request(method, BASE_URL + path, headers=headers, **kwargs)
        except httpx.HTTPError:
            raise BankApiError(None, "Enable Banking could not be reached") from None
        if not response.is_success:
            raise BankApiError(response.status_code, _error_text(response))
        return response.json()

    def _token(self) -> str:
        issued_at = int(self._now().timestamp())
        header = {"alg": "RS256", "typ": "JWT", "kid": self._app_id}
        claims = {
            "iss": "enablebanking.com",
            "aud": "api.enablebanking.com",
            "iat": issued_at,
            "exp": issued_at + _JWT_LIFETIME_SECONDS,
        }
        return jwt.encode(header, claims, self._private_key_pem).decode("ascii")


def _error_text(response: httpx.Response) -> str:
    text = f"Enable Banking answered {response.status_code}"
    try:
        error = response.json().get("error")
    except (ValueError, AttributeError):
        return text
    if isinstance(error, str) and _ERROR_CODE.fullmatch(error):
        text += f" ({error})"
    return text
