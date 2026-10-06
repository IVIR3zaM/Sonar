"""Settings endpoints (SPEC §4, §13): salary day, overdraft limit and the manual balance.

Writes go through `cashflow.store`, so validation exists in one place (shared
with the Settings page).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import StrictInt, StrictStr

from sonar.cashflow.store import current_balance, load_settings, save_settings, set_manual_balance
from sonar.db import connect
from sonar.web.api._common import _parse_body, _StrictModel
from sonar.web.forms import friendly

# Which request field a domain ValueError belongs to, by a needle in its text.
_DOMAIN_ERROR_FIELDS = {
    "salary_day": "salary_day",
    "overdraft_limit_cents": "overdraft_limit_cents",
    "as_of": "as_of",
}


class SettingsIn(_StrictModel):
    salary_day: StrictInt | None = None
    overdraft_limit_cents: StrictInt | None = None


class BalanceIn(_StrictModel):
    amount_cents: StrictInt | None = None
    as_of: StrictStr | None = None


def _bad_request(message: str, field: str) -> JSONResponse:
    return JSONResponse({"error": message, "field": field}, status_code=400)


def _domain_error(error: ValueError) -> JSONResponse:
    field = next((f for needle, f in _DOMAIN_ERROR_FIELDS.items() if needle in str(error)), "")
    return _bad_request(friendly(error), field)


def _settings_view(conn) -> dict:
    settings = load_settings(conn)
    balance = current_balance(conn)
    return {
        "salary_day": settings.salary_day,
        "overdraft_limit_cents": settings.overdraft_limit_cents,
        "balance": None
        if balance is None
        else {
            "amount_cents": balance.amount_cents,
            "as_of": balance.as_of.isoformat(),
            "source": balance.source,
        },
    }


def build_router(db_path: Path, today: Callable[[], date]) -> APIRouter:
    router = APIRouter()

    @router.get("/settings")
    async def get_settings() -> JSONResponse:
        conn = connect(db_path)
        try:
            view = _settings_view(conn)
        finally:
            conn.close()
        return JSONResponse(view)

    @router.put("/settings")
    async def put_settings(request: Request) -> JSONResponse:
        body = await _parse_body(request, SettingsIn)
        if isinstance(body, JSONResponse):
            return body
        conn = connect(db_path)
        try:
            stored = load_settings(conn)
            salary_day = body.salary_day if body.salary_day is not None else stored.salary_day
            if salary_day is None:
                return _bad_request("salary_day is required", "salary_day")
            overdraft_limit_cents = (
                body.overdraft_limit_cents
                if body.overdraft_limit_cents is not None
                else stored.overdraft_limit_cents
            )
            try:
                save_settings(conn, salary_day, overdraft_limit_cents)
            except ValueError as error:
                return _domain_error(error)
            view = _settings_view(conn)
        finally:
            conn.close()
        return JSONResponse(view)

    @router.post("/settings/balance")
    async def post_balance(request: Request) -> JSONResponse:
        body = await _parse_body(request, BalanceIn)
        if isinstance(body, JSONResponse):
            return body
        for field in ("amount_cents", "as_of"):
            if getattr(body, field) is None:
                return _bad_request(f"{field} is required", field)
        try:
            as_of = date.fromisoformat(body.as_of)
        except ValueError:
            return _bad_request("as_of must be an ISO date like 2026-09-20", "as_of")
        conn = connect(db_path)
        try:
            try:
                set_manual_balance(conn, as_of, body.amount_cents, today())
            except ValueError as error:
                return _domain_error(error)
            view = _settings_view(conn)
        finally:
            conn.close()
        return JSONResponse(view)

    return router
