"""Recurring payment endpoints (SPEC §6, §13)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from sonar.db import connect
from sonar.recurring.store import (
    PaymentNotFound,
    RecurringPayment,
    dismiss,
    get_payment,
    list_payments,
    update_details,
)
from sonar.web.api._common import _parse_body, _StrictModel


class RecurringIn(_StrictModel):
    name: str | None = None
    description: str | None = None


def _recurring_item(payment: RecurringPayment) -> dict:
    latest = payment.periods[-1]
    return {
        "id": payment.id,
        "detection_key": payment.detection_key,
        "name": payment.name,
        "description": payment.description,
        "category": payment.category,
        "status": payment.status,
        "amount_cents": latest.amount_cents,
        "interval_months": latest.interval_months,
        "day": latest.day,
    }


def build_router(db_path: Path, today: Callable[[], date]) -> APIRouter:
    router = APIRouter()

    @router.get("/recurring")
    async def get_recurring() -> JSONResponse:
        conn = connect(db_path)
        try:
            items = [_recurring_item(p) for p in list_payments(conn, include_dismissed=True)]
        finally:
            conn.close()
        return JSONResponse(items)

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
                return JSONResponse({"error": f"No such recurring payment: {id}"}, status_code=404)
            name = (body.name or "").strip() if "name" in body.model_fields_set else current.name
            if not name:
                return JSONResponse(
                    {"error": "Name must not be blank", "field": "name"}, status_code=400
                )
            description = (
                body.description if "description" in body.model_fields_set else current.description
            )
            update_details(conn, id, name, description)
            item = _recurring_item(get_payment(conn, id))
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
                return JSONResponse({"error": f"No such recurring payment: {id}"}, status_code=404)
            item = _recurring_item(get_payment(conn, id))
        finally:
            conn.close()
        return JSONResponse(item)

    return router
