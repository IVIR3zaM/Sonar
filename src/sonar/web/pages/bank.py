"""Connecting the bank (SPEC §13 Bank sync): the authorization redirect and its callback."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from sonar.banking.client import BankApiError
from sonar.banking.consent import (
    consent_seconds,
    new_state,
    parse_session,
    requested_valid_until,
    state_hash,
    state_matches,
)
from sonar.banking.settings import ASPSP_COUNTRY, ASPSP_NAME, BankSettings
from sonar.banking.store import save_connection, save_pending_state, take_pending_state
from sonar.db import connect
from sonar.web.pages.settings import render_settings_page

# One message for every failure: the page must not tell an attacker which check failed.
FAILURE_MESSAGE = "The bank connection did not complete. Start again with Connect bank."


class BankClient(Protocol):
    def aspsps(self, country: str) -> list[dict]: ...

    def start_authorization(self, valid_until: datetime, state: str, redirect_url: str) -> dict: ...

    def create_session(self, code: str) -> dict: ...


def build_router(
    db_path: Path,
    today: Callable[[], date],
    now: Callable[[], datetime],
    bank: BankSettings,
    client: BankClient,
    templates: Jinja2Templates,
) -> APIRouter:
    router = APIRouter()

    def failed(request: Request) -> HTMLResponse:
        return render_settings_page(
            request,
            db_path,
            today,
            templates,
            status_code=400,
            error={"form": "bank", "message": FAILURE_MESSAGE},
        )

    # Plain `def` routes: the bank client blocks on the network, so FastAPI runs them in a thread.
    @router.post("/bank/connect")
    def connect_bank(request: Request) -> Response:
        moment = now()
        state = new_state()
        try:
            seconds = consent_seconds(client.aspsps(ASPSP_COUNTRY), ASPSP_NAME)
            conn = connect(db_path)
            try:
                save_pending_state(conn, state_hash(state), moment)
            finally:
                conn.close()
            answer = client.start_authorization(
                requested_valid_until(moment, seconds), state, bank.redirect_url
            )
            return RedirectResponse(answer["url"], status_code=303)
        except (BankApiError, ValueError, KeyError):
            return failed(request)

    @router.get("/bank/callback")
    def bank_callback(
        request: Request,
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
    ) -> Response:
        conn = connect(db_path)
        try:
            # Taken first, on every call, so a state is single use whatever the outcome.
            pending = take_pending_state(conn)
            moment = now()
            if error or not code or not state or pending is None:
                return failed(request)
            stored_hash, created_at = pending
            if not state_matches(state, stored_hash, created_at, moment):
                return failed(request)
            try:
                save_connection(conn, parse_session(client.create_session(code), moment))
            except (BankApiError, ValueError):
                return failed(request)
        finally:
            conn.close()
        return RedirectResponse("/settings", status_code=303)

    return router
