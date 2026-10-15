"""Energy endpoints (SPEC §13 Energy): meters, readings, exchanges and billing periods."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import StrictInt, StrictStr

from sonar.db import connect
from sonar.energy.model import BillingPeriod, Exchange, FieldError, Meter, Reading
from sonar.energy.service import MeterView, load_energy
from sonar.energy.store import (
    EnergyNotFound,
    MeterNotEmpty,
    Stored,
    add_exchange,
    add_meter,
    add_period,
    add_reading,
    delete_exchange,
    delete_meter,
    delete_period,
    delete_reading,
    list_exchanges,
    list_meters,
    list_periods,
    list_readings,
    rename_meter,
    update_exchange,
    update_period,
    update_reading,
)
from sonar.web.api._common import _jsonable, _parse_body, _StrictModel

Action = Callable[[sqlite3.Connection], object]


class MeterIn(_StrictModel):
    name: StrictStr
    kind: StrictStr


class MeterRenameIn(_StrictModel):
    name: StrictStr


class ReadingIn(_StrictModel):
    date: StrictStr
    value_milli: StrictInt


class ExchangeIn(_StrictModel):
    date: StrictStr
    old_final_milli: StrictInt
    new_start_milli: StrictInt


class PeriodIn(_StrictModel):
    start_date: StrictStr
    settlement_date: StrictStr
    base_fee_cents: StrictInt
    unit_price_micro: StrictInt
    state_factor_e4: StrictInt | None = None
    calorific_value_e4: StrictInt | None = None
    advance_cents: StrictInt
    expected_kwh: StrictInt
    category: StrictStr | None = None


def _day(text: str, field: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise FieldError(field, f"{field} must be a date like 2026-01-31") from None


def _reading(body: ReadingIn) -> Reading:
    return Reading(_day(body.date, "date"), body.value_milli)


def _exchange(body: ExchangeIn) -> Exchange:
    return Exchange(_day(body.date, "date"), body.old_final_milli, body.new_start_milli)


def _period(body: PeriodIn) -> BillingPeriod:
    return BillingPeriod(
        start_date=_day(body.start_date, "start_date"),
        settlement_date=_day(body.settlement_date, "settlement_date"),
        base_fee_cents=body.base_fee_cents,
        unit_price_micro=body.unit_price_micro,
        state_factor_e4=body.state_factor_e4,
        calorific_value_e4=body.calorific_value_e4,
        advance_cents=body.advance_cents,
        expected_kwh=body.expected_kwh,
        category=body.category,
    )


def _reading_item(stored: Stored[Reading]) -> dict:
    return {
        "id": stored.id,
        "date": stored.item.reading_date.isoformat(),
        "value_milli": stored.item.value_milli,
    }


def _exchange_item(stored: Stored[Exchange]) -> dict:
    exchange = stored.item
    return {
        "id": stored.id,
        "date": exchange.exchange_date.isoformat(),
        "old_final_milli": exchange.old_final_milli,
        "new_start_milli": exchange.new_start_milli,
    }


def _period_item(stored: Stored[BillingPeriod]) -> dict:
    return {"id": stored.id, **_jsonable(stored.item)}


def _meter_item(view: MeterView) -> dict:
    return {
        "id": view.id,
        "name": view.meter.name,
        "kind": view.meter.kind,
        "status": _jsonable(view.status),
        "periods": [_period_item(period) for period in view.periods],
        "exchanges": [_exchange_item(exchange) for exchange in view.exchanges],
        "readings": [_reading_item(reading) for reading in view.readings],
    }


def _find[T](conn: sqlite3.Connection, lister: Callable, row_id: int) -> Stored[T]:
    """The stored reading, exchange or period with `row_id`, whichever meter owns it."""
    for meter in list_meters(conn):
        for stored in lister(conn, meter.id):
            if stored.id == row_id:
                return stored
    raise EnergyNotFound(row_id)


def build_router(db_path: Path, today: Callable[[], date]) -> APIRouter:
    router = APIRouter()

    def respond(action: Action, status: int = 200) -> JSONResponse:
        """Run `action` on a fresh connection; a domain error becomes its 400, 404 or 409."""
        conn = connect(db_path)
        try:
            try:
                item = action(conn)
            except FieldError as error:
                return JSONResponse({"error": str(error), "field": error.field}, status_code=400)
            except EnergyNotFound:
                return JSONResponse({"error": "No such energy record"}, status_code=404)
            except MeterNotEmpty:
                return JSONResponse(
                    {"error": "Delete the meter's readings, exchanges and periods first"},
                    status_code=409,
                )
        finally:
            conn.close()
        return JSONResponse(item, status_code=status)

    def meter_item(conn: sqlite3.Connection, meter_id: int) -> dict:
        for view in load_energy(conn, today()):
            if view.id == meter_id:
                return _meter_item(view)
        raise EnergyNotFound(meter_id)

    @router.get("/energy")
    async def get_energy() -> JSONResponse:
        return respond(
            lambda conn: {"meters": [_meter_item(v) for v in load_energy(conn, today())]}
        )

    # Meters

    @router.post("/energy/meters", status_code=201)
    async def post_meter(request: Request) -> JSONResponse:
        body = await _parse_body(request, MeterIn)
        if isinstance(body, JSONResponse):
            return body
        return respond(
            lambda conn: meter_item(conn, add_meter(conn, Meter(body.name, body.kind))), 201
        )

    @router.put("/energy/meters/{id}")
    async def put_meter(request: Request, id: int) -> JSONResponse:
        body = await _parse_body(request, MeterRenameIn)
        if isinstance(body, JSONResponse):
            return body

        def action(conn: sqlite3.Connection) -> dict:
            rename_meter(conn, id, body.name)
            return meter_item(conn, id)

        return respond(action)

    @router.delete("/energy/meters/{id}")
    async def delete_meter_route(id: int) -> JSONResponse:
        def action(conn: sqlite3.Connection) -> dict:
            item = meter_item(conn, id)
            delete_meter(conn, id)
            return item

        return respond(action)

    # Readings

    @router.post("/energy/meters/{id}/readings", status_code=201)
    async def post_reading(request: Request, id: int) -> JSONResponse:
        body = await _parse_body(request, ReadingIn)
        if isinstance(body, JSONResponse):
            return body

        def action(conn: sqlite3.Connection) -> dict:
            reading = _reading(body)
            return _reading_item(Stored(add_reading(conn, id, reading), reading))

        return respond(action, 201)

    @router.put("/energy/readings/{id}")
    async def put_reading(request: Request, id: int) -> JSONResponse:
        body = await _parse_body(request, ReadingIn)
        if isinstance(body, JSONResponse):
            return body

        def action(conn: sqlite3.Connection) -> dict:
            reading = _reading(body)
            update_reading(conn, id, reading)
            return _reading_item(Stored(id, reading))

        return respond(action)

    @router.delete("/energy/readings/{id}")
    async def delete_reading_route(id: int) -> JSONResponse:
        def action(conn: sqlite3.Connection) -> dict:
            item = _reading_item(_find(conn, list_readings, id))
            delete_reading(conn, id)
            return item

        return respond(action)

    # Exchanges

    @router.post("/energy/meters/{id}/exchanges", status_code=201)
    async def post_exchange(request: Request, id: int) -> JSONResponse:
        body = await _parse_body(request, ExchangeIn)
        if isinstance(body, JSONResponse):
            return body

        def action(conn: sqlite3.Connection) -> dict:
            exchange = _exchange(body)
            return _exchange_item(Stored(add_exchange(conn, id, exchange), exchange))

        return respond(action, 201)

    @router.put("/energy/exchanges/{id}")
    async def put_exchange(request: Request, id: int) -> JSONResponse:
        body = await _parse_body(request, ExchangeIn)
        if isinstance(body, JSONResponse):
            return body

        def action(conn: sqlite3.Connection) -> dict:
            exchange = _exchange(body)
            update_exchange(conn, id, exchange)
            return _exchange_item(Stored(id, exchange))

        return respond(action)

    @router.delete("/energy/exchanges/{id}")
    async def delete_exchange_route(id: int) -> JSONResponse:
        def action(conn: sqlite3.Connection) -> dict:
            item = _exchange_item(_find(conn, list_exchanges, id))
            delete_exchange(conn, id)
            return item

        return respond(action)

    # Billing periods

    @router.post("/energy/meters/{id}/periods", status_code=201)
    async def post_period(request: Request, id: int) -> JSONResponse:
        body = await _parse_body(request, PeriodIn)
        if isinstance(body, JSONResponse):
            return body

        def action(conn: sqlite3.Connection) -> dict:
            period = _period(body)
            return _period_item(Stored(add_period(conn, id, period), period))

        return respond(action, 201)

    @router.put("/energy/periods/{id}")
    async def put_period(request: Request, id: int) -> JSONResponse:
        body = await _parse_body(request, PeriodIn)
        if isinstance(body, JSONResponse):
            return body

        def action(conn: sqlite3.Connection) -> dict:
            period = _period(body)
            update_period(conn, id, period)
            return _period_item(Stored(id, period))

        return respond(action)

    @router.delete("/energy/periods/{id}")
    async def delete_period_route(id: int) -> JSONResponse:
        def action(conn: sqlite3.Connection) -> dict:
            item = _period_item(_find(conn, list_periods, id))
            delete_period(conn, id)
            return item

        return respond(action)

    return router
