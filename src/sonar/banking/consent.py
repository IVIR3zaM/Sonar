"""Bank consent rules (SPEC §13 Bank sync): authorization state, session parsing, banners.

Pure but for `new_state`, which draws randomness. Callers pass `now` and `today`.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal

# Asks the bank for slightly less than its maximum so the request is never refused as too long.
_REQUEST_MARGIN = timedelta(minutes=10)
STATE_MAX_AGE = timedelta(minutes=30)
EXPIRING_WITHIN = timedelta(days=14)


@dataclass(frozen=True)
class NewConnection:
    session_id: str
    account_uid: str
    iban_last4: str
    consent_valid_until: datetime
    connected_at: datetime


@dataclass(frozen=True)
class BankConnection:
    session_id: str
    account_uid: str
    iban_last4: str
    consent_valid_until: datetime
    connected_at: datetime
    last_sync_at: datetime | None
    last_sync_status: Literal["ok", "error"] | None
    last_sync_added: int | None
    last_sync_error: str | None


@dataclass(frozen=True)
class Banner:
    kind: Literal["expired", "failed", "expiring"]
    on: date
    error: str | None = None


def consent_seconds(aspsps: list[dict], name: str) -> int:
    """The longest consent, in seconds, that the bank called `name` allows."""
    for aspsp in aspsps:
        if aspsp.get("name") == name:
            return aspsp["maximum_consent_validity"]
    raise ValueError(f"Bank {name} is not offered by Enable Banking")


def requested_valid_until(now: datetime, seconds: int) -> datetime:
    return now + timedelta(seconds=seconds) - _REQUEST_MARGIN


def new_state() -> str:
    return secrets.token_urlsafe(32)


def state_hash(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def state_matches(state: str, stored_hash: str, created_at: datetime, now: datetime) -> bool:
    hashes_equal = hmac.compare_digest(state_hash(state), stored_hash)
    return hashes_equal and now - created_at < STATE_MAX_AGE


def parse_session(session: dict, now: datetime) -> NewConnection:
    """The connection described by an Enable Banking session; ValueError when unusable."""
    try:
        account = _pick_account(session["accounts"])
        return NewConnection(
            session_id=session["session_id"],
            account_uid=account["uid"],
            iban_last4=account["account_id"]["iban"][-4:],
            consent_valid_until=_utc(session["access"]["valid_until"]),
            connected_at=now,
        )
    except (KeyError, TypeError, AttributeError):
        raise ValueError("The bank session lacks a required field") from None


def _pick_account(accounts: list[dict]) -> dict:
    if len(accounts) == 1:
        return accounts[0]
    for account in accounts:
        if account.get("cash_account_type") == "CACC":
            return account
    raise ValueError("The bank session has no usable account")


def _utc(iso: str) -> datetime:
    moment = datetime.fromisoformat(iso)
    if moment.tzinfo is None:
        raise ValueError("The bank session consent end has no timezone")
    return moment.astimezone(UTC)


def banner(connection: BankConnection | None, today: date) -> Banner | None:
    """The one banner to show, first match wins: expired, failed, expiring."""
    if connection is None:
        return None
    ends_on = connection.consent_valid_until.date()
    if today >= ends_on:
        return Banner(kind="expired", on=ends_on)
    if connection.last_sync_status == "error":
        failed_on = connection.last_sync_at.date() if connection.last_sync_at else today
        return Banner(kind="failed", on=failed_on, error=connection.last_sync_error)
    if today >= ends_on - EXPIRING_WITHIN:
        return Banner(kind="expiring", on=ends_on)
    return None


def card_status(connection: BankConnection | None, today: date) -> str:
    if connection is None:
        return "Not connected"
    ends_on = connection.consent_valid_until.date()
    if today >= ends_on:
        return "Expired"
    if today >= ends_on - EXPIRING_WITHIN:
        return "Ends soon"
    return "Connected"
