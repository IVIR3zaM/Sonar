"""The daily bank sync (SPEC §13 Bank sync): fetch, map, import, record.

Synced rows go through the import pipeline, so they dedupe against earlier syncs and merge
with the CSV rows of the same bookings. The caller passes `today`, `now` and the client.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Protocol

from sonar.banking import mapping
from sonar.banking.client import BankApiError
from sonar.banking.consent import BankConnection
from sonar.banking.store import (
    latest_account,
    load_connection,
    record_sync_error,
    record_sync_ok,
    upsert_balance,
)
from sonar.categorization.store import load_stored_taxonomy
from sonar.importing.importers import deutsche_bank_giro
from sonar.importing.store import import_rows
from sonar.recurring.store import sync_detected
from sonar.transactions import ParsedBalance

FIRST_SYNC_DAYS = 90
# Refetching the last week catches bookings the bank posts late.
OVERLAP_DAYS = 7
_UNREADABLE = "Enable Banking sent an answer Sonar cannot read"


class NotConnectedError(Exception):
    """No bank connection is stored, so there is nothing to sync."""


class SyncClient(Protocol):
    def booked_transactions(
        self, account_uid: str, date_from: date, date_to: date
    ) -> list[dict]: ...

    def balances(self, account_uid: str) -> list[dict]: ...


@dataclass(frozen=True)
class SyncResult:
    added: int
    duplicates: int
    balance: ParsedBalance | None


def sync(conn: sqlite3.Connection, client: SyncClient, today: date, now: datetime) -> SyncResult:
    """Sync the connected account into the DB.

    A `BankApiError` (or an unreadable answer, raised as one) is recorded on the connection and
    re-raised; rows stored by earlier syncs stay.
    """
    connection = load_connection(conn)
    if connection is None:
        raise NotConnectedError("Bank is not connected.")
    try:
        booked = client.booked_transactions(
            connection.account_uid, sync_start(connection, today), today
        )
        listed_balances = client.balances(connection.account_uid)
        account = mapping.sync_account(latest_account(conn, deutsche_bank_giro.NAME), booked)
        transactions = mapping.transactions(booked, account) if account else []
        balance = mapping.balance(listed_balances, account, today) if account else None
    except BankApiError as error:
        record_sync_error(conn, now, error.message)
        raise
    except ValueError:
        record_sync_error(conn, now, _UNREADABLE)
        raise BankApiError(None, _UNREADABLE) from None

    counts = _import(conn, transactions, today)
    if balance is not None:
        upsert_balance(conn, balance)
    record_sync_ok(conn, now, counts.added)
    return SyncResult(added=counts.added, duplicates=counts.duplicates, balance=balance)


def sync_start(connection: BankConnection, today: date) -> date:
    """The first day to fetch: a week before the last successful sync, else 90 days back.

    After a failed sync the last successful date is not stored, so the full first window is
    fetched again; the import pipeline counts the overlap as duplicates.
    """
    if connection.last_sync_status == "ok" and connection.last_sync_at is not None:
        return connection.last_sync_at.date() - timedelta(days=OVERLAP_DAYS)
    return today - timedelta(days=FIRST_SYNC_DAYS)


def _import(conn: sqlite3.Connection, transactions, today: date):
    # Same follow-up as an upload: rules over every row, then recurring detection.
    taxonomy = load_stored_taxonomy(conn)
    counts = import_rows(conn, mapping.SOURCE, transactions, None, taxonomy.rules)
    sync_detected(conn, taxonomy.categories, today)
    return counts
