"""Bank sync endpoints (SPEC §13 Bank sync): the connection's status and a manual sync.

They exist only when bank sync is on, so the bank pages router mounts them under `/api`.
Neither ever returns the session id or the account uid.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from sonar.banking.client import BankApiError
from sonar.banking.consent import BankConnection, card_status
from sonar.banking.service import NotConnectedError, SyncClient, sync
from sonar.banking.store import load_connection
from sonar.db import connect


def bank_view(connection: BankConnection | None, today: date) -> dict:
    """What the Settings card shows, as JSON."""
    if connection is None:
        return {
            "status": card_status(None, today),
            "iban_last4": None,
            "consent_valid_until": None,
            "last_sync": None,
        }
    last_sync = None
    if connection.last_sync_at is not None:
        last_sync = {
            "at": connection.last_sync_at.isoformat(),
            "status": connection.last_sync_status,
            "added": connection.last_sync_added,
            "error": connection.last_sync_error,
        }
    return {
        "status": card_status(connection, today),
        "iban_last4": connection.iban_last4,
        "consent_valid_until": connection.consent_valid_until.isoformat(),
        "last_sync": last_sync,
    }


def build_router(
    db_path: Path,
    today: Callable[[], date],
    now: Callable[[], datetime],
    client: SyncClient,
) -> APIRouter:
    router = APIRouter()

    @router.get("/bank")
    async def get_bank() -> JSONResponse:
        conn = connect(db_path)
        try:
            view = bank_view(load_connection(conn), today())
        finally:
            conn.close()
        return JSONResponse(view)

    # Plain `def`: the bank client blocks on the network, so FastAPI runs it in a thread.
    @router.post("/bank/sync")
    def post_sync() -> JSONResponse:
        day = today()
        conn = connect(db_path)
        try:
            try:
                result = sync(conn, client, day, now())
            except NotConnectedError as error:
                return JSONResponse({"error": str(error)}, status_code=409)
            except BankApiError as error:
                return JSONResponse({"error": error.message}, status_code=502)
            view = bank_view(load_connection(conn), day)
        finally:
            conn.close()
        balance = result.balance
        return JSONResponse(
            {
                "added": result.added,
                "duplicates": result.duplicates,
                "balance": None
                if balance is None
                else {"amount_cents": balance.amount_cents, "as_of": balance.as_of.isoformat()},
                "bank": view,
            }
        )

    return router
