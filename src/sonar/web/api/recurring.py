"""Recurring payment endpoints (SPEC §6, §13)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import StrictInt, StrictStr

from sonar.db import connect
from sonar.debts.store import debt_overview
from sonar.recurring.schedule import SchedulePeriod, next_due_date
from sonar.recurring.store import (
    NotDismissed,
    PaymentNotFound,
    RecurringPayment,
    add_manual,
    dismiss,
    edit_payment,
    get_payment,
    list_payments,
    pause_payment,
    restore,
    resume_payment,
    update_details,
)
from sonar.web.api._common import _parse_body, _StrictModel
from sonar.web.forms import friendly

# Which request field a SchedulePeriod error belongs to, found by its message text.
_SCHEDULE_ERROR_FIELDS = {
    "amount must be positive": "amount_cents",
    "interval must be at least": "interval_months",
    "day must be within": "day",
}


class RecurringIn(_StrictModel):
    name: StrictStr | None = None
    description: StrictStr | None = None
    amount_cents: StrictInt | None = None
    interval_months: StrictInt | None = None
    day: StrictInt | None = None


class RecurringAddIn(_StrictModel):
    name: StrictStr | None = None
    description: StrictStr | None = None
    amount_cents: StrictInt | None = None
    interval_months: StrictInt | None = None
    day: StrictInt | None = None
    starts_on: StrictStr | None = None


class PauseIn(_StrictModel):
    last_date: StrictStr | None = None


class ResumeIn(_StrictModel):
    starts_on: StrictStr | None = None
    amount_cents: StrictInt | None = None
    interval_months: StrictInt | None = None
    day: StrictInt | None = None


def _iso(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _recurring_item(payment: RecurringPayment, today: date, debt_ids: dict[int, int]) -> dict:
    # periods come back ordered by starts_on, so [-1] is the latest.
    latest = payment.periods[-1]
    return {
        "id": payment.id,
        "detection_key": payment.detection_key,
        "name": payment.name,
        "description": payment.description,
        "category": payment.category,
        "status": payment.status,
        "source": payment.source,
        "amount_cents": latest.amount_cents,
        "interval_months": latest.interval_months,
        "day": latest.day,
        "last_paid_date": _iso(payment.last_paid_date),
        "next_due": _iso(next_due_date(payment.periods, payment.last_paid_date, today)),
        "until": _iso(latest.until),
        "periods": [
            {
                "starts_on": _iso(period.starts_on),
                "until": _iso(period.until),
                "amount_cents": period.amount_cents,
                "interval_months": period.interval_months,
                "day": period.day,
            }
            for period in payment.periods
        ],
        "debt_id": debt_ids.get(payment.id),
    }


def _bad(error: str, field: str) -> JSONResponse:
    return JSONResponse({"error": error, "field": field}, status_code=400)


def _missing(body: _StrictModel, keys: tuple[str, ...]) -> JSONResponse | None:
    """The 400 naming the first required key that is absent or null."""
    for key in keys:
        if getattr(body, key) is None:
            return _bad(f"{key} is required", key)
    return None


def _parse_date(text: str, field: str) -> date | JSONResponse:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return _bad(f"{field} must be a date like 2026-01-31", field)


def _check_schedule(
    starts_on: date, amount_cents: int, interval_months: int, day: int
) -> JSONResponse | None:
    """The 400 for a schedule SchedulePeriod rejects, else None."""
    try:
        SchedulePeriod(starts_on, None, amount_cents, interval_months, day)
    except ValueError as error:
        field = next(
            (f for needle, f in _SCHEDULE_ERROR_FIELDS.items() if needle in str(error)), ""
        )
        return _bad(friendly(error), field)
    return None


def _kept(value: int | None, current: int) -> int:
    return current if value is None else value


def _not_found(id: int) -> JSONResponse:
    return JSONResponse({"error": f"No such recurring payment: {id}"}, status_code=404)


def build_router(db_path: Path, today: Callable[[], date]) -> APIRouter:
    router = APIRouter()

    def _debt_ids(conn) -> dict[int, int]:
        # Inverted from debt_overview's debt -> payments, built once per request.
        return {
            payment.id: view.id
            for view in debt_overview(conn, today())
            for payment in view.linked_payments
        }

    def _item(conn, id: int) -> dict:
        return _recurring_item(get_payment(conn, id), today(), _debt_ids(conn))

    @router.get("/recurring")
    async def get_recurring() -> JSONResponse:
        conn = connect(db_path)
        try:
            debt_ids = _debt_ids(conn)
            items = [
                _recurring_item(p, today(), debt_ids)
                for p in list_payments(conn, include_dismissed=True)
            ]
        finally:
            conn.close()
        return JSONResponse(items)

    @router.post("/recurring")
    async def post_recurring(request: Request) -> JSONResponse:
        body = await _parse_body(request, RecurringAddIn)
        if isinstance(body, JSONResponse):
            return body
        required = ("name", "amount_cents", "interval_months", "day", "starts_on")
        if (error := _missing(body, required)) is not None:
            return error
        name = body.name.strip()
        if not name:
            return _bad("name is required", "name")
        starts_on = _parse_date(body.starts_on, "starts_on")
        if isinstance(starts_on, JSONResponse):
            return starts_on
        if (
            error := _check_schedule(starts_on, body.amount_cents, body.interval_months, body.day)
        ) is not None:
            return error
        period = SchedulePeriod(starts_on, None, body.amount_cents, body.interval_months, body.day)
        conn = connect(db_path)
        try:
            payment_id = add_manual(conn, name, None, period, body.description)
            item = _item(conn, payment_id)
        finally:
            conn.close()
        return JSONResponse(item, status_code=201)

    @router.put("/recurring/{id}")
    async def put_recurring(id: int, request: Request) -> JSONResponse:
        body = await _parse_body(request, RecurringIn)
        if isinstance(body, JSONResponse):
            return body
        conn = connect(db_path)
        try:
            try:
                current = get_payment(conn, id)
            except PaymentNotFound:
                return _not_found(id)
            name = (body.name or "").strip() if "name" in body.model_fields_set else current.name
            if not name:
                return JSONResponse(
                    {"error": "Name must not be blank", "field": "name"}, status_code=400
                )
            description = (
                body.description if "description" in body.model_fields_set else current.description
            )
            latest = current.periods[-1]
            schedule = (body.amount_cents, body.interval_months, body.day)
            if any(value is not None for value in schedule):
                amount_cents = _kept(body.amount_cents, latest.amount_cents)
                interval_months = _kept(body.interval_months, latest.interval_months)
                day = _kept(body.day, latest.day)
                if (
                    error := _check_schedule(latest.starts_on, amount_cents, interval_months, day)
                ) is not None:
                    return error
                edit_payment(conn, id, name, amount_cents, interval_months, day, description)
            else:
                update_details(conn, id, name, description)
            item = _item(conn, id)
        finally:
            conn.close()
        return JSONResponse(item)

    @router.post("/recurring/{id}/dismiss")
    async def dismiss_recurring(id: int) -> JSONResponse:
        conn = connect(db_path)
        try:
            try:
                dismiss(conn, id)
            except PaymentNotFound:
                return _not_found(id)
            item = _item(conn, id)
        finally:
            conn.close()
        return JSONResponse(item)

    @router.post("/recurring/{id}/restore")
    async def restore_recurring(id: int) -> JSONResponse:
        conn = connect(db_path)
        try:
            try:
                restore(conn, id)
            except PaymentNotFound:
                return _not_found(id)
            except NotDismissed:
                return JSONResponse(
                    {"error": f"Recurring payment {id} is not dismissed"}, status_code=409
                )
            item = _item(conn, id)
        finally:
            conn.close()
        return JSONResponse(item)

    @router.post("/recurring/{id}/pause")
    async def pause_recurring(id: int, request: Request) -> JSONResponse:
        body = await _parse_body(request, PauseIn)
        if isinstance(body, JSONResponse):
            return body
        if (error := _missing(body, ("last_date",))) is not None:
            return error
        last_date = _parse_date(body.last_date, "last_date")
        if isinstance(last_date, JSONResponse):
            return last_date
        conn = connect(db_path)
        try:
            try:
                pause_payment(conn, id, last_date)
            except PaymentNotFound:
                return _not_found(id)
            item = _item(conn, id)
        finally:
            conn.close()
        return JSONResponse(item)

    @router.post("/recurring/{id}/resume")
    async def resume_recurring(id: int, request: Request) -> JSONResponse:
        body = await _parse_body(request, ResumeIn)
        if isinstance(body, JSONResponse):
            return body
        if (error := _missing(body, ("starts_on", "amount_cents", "interval_months"))) is not None:
            return error
        starts_on = _parse_date(body.starts_on, "starts_on")
        if isinstance(starts_on, JSONResponse):
            return starts_on
        # Day defaults to the resume date's own day, same as the page.
        day = starts_on.day if body.day is None else body.day
        if (
            error := _check_schedule(starts_on, body.amount_cents, body.interval_months, day)
        ) is not None:
            return error
        conn = connect(db_path)
        try:
            try:
                resume_payment(conn, id, starts_on, body.amount_cents, body.interval_months, day)
            except PaymentNotFound:
                return _not_found(id)
            item = _item(conn, id)
        finally:
            conn.close()
        return JSONResponse(item)

    return router
