"""Utilities endpoints (SPEC §13 Utilities): meters, readings, exchanges and billing periods."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import StrictInt, StrictStr

from sonar.cashflow.service import AdvanceLink, advance_links
from sonar.db import connect
from sonar.utilities.model import BillingPeriod, Charge, Exchange, FieldError, Meter, Reading
from sonar.utilities.service import ConflictCase, MeterView, load_utilities
from sonar.utilities.store import (
    MeterNotEmpty,
    Stored,
    UtilityNotFound,
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
    reading_to_exchange,
    rename_meter,
    update_exchange,
    update_period,
    update_reading,
    zero_garden_interval,
)
from sonar.web.api._common import _jsonable, _parse_body, _StrictModel

Action = Callable[[sqlite3.Connection], object]


class MeterIn(_StrictModel):
    name: StrictStr
    kind: StrictStr
    main_meter_id: StrictInt | None = None


class MeterRenameIn(_StrictModel):
    name: StrictStr


class ReadingIn(_StrictModel):
    date: StrictStr
    value_milli: StrictInt


class ExchangeIn(_StrictModel):
    date: StrictStr
    old_final_milli: StrictInt
    new_start_milli: StrictInt


class ZeroIn(_StrictModel):
    start_date: StrictStr
    end_date: StrictStr


class ExchangeOfReadingIn(_StrictModel):
    old_final_milli: StrictInt


class ChargeIn(_StrictModel):
    unit_price_micro: StrictInt
    base_fee_cents: StrictInt
    vat_percent: StrictInt


class PeriodIn(_StrictModel):
    start_date: StrictStr
    settlement_date: StrictStr
    base_fee_cents: StrictInt | None = None
    unit_price_micro: StrictInt | None = None
    state_factor_e4: StrictInt | None = None
    calorific_value_e4: StrictInt | None = None
    advance_cents: StrictInt
    expected_usage: StrictInt
    category: StrictStr | None = None
    settled_cents: StrictInt | None = None
    drinking: ChargeIn | None = None
    wastewater: ChargeIn | None = None
    advance_mode: StrictStr = "flexible"
    advance_dates: list[StrictStr] = []
    settlement_debit_days: StrictInt = 0
    garden_fee_cents: StrictInt | None = None


def _day(text: str, field: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise FieldError(field, f"{field} must be a date like 2026-01-31") from None


def _reading(body: ReadingIn) -> Reading:
    return Reading(_day(body.date, "date"), body.value_milli)


def _exchange(body: ExchangeIn) -> Exchange:
    return Exchange(_day(body.date, "date"), body.old_final_milli, body.new_start_milli)


def _charge(body: ChargeIn | None) -> Charge | None:
    if body is None:
        return None
    return Charge(body.unit_price_micro, body.base_fee_cents, body.vat_percent)


def _period(body: PeriodIn) -> BillingPeriod:
    return BillingPeriod(
        start_date=_day(body.start_date, "start_date"),
        settlement_date=_day(body.settlement_date, "settlement_date"),
        base_fee_cents=body.base_fee_cents,
        unit_price_micro=body.unit_price_micro,
        state_factor_e4=body.state_factor_e4,
        calorific_value_e4=body.calorific_value_e4,
        advance_cents=body.advance_cents,
        expected_usage=body.expected_usage,
        category=body.category,
        settled_cents=body.settled_cents,
        drinking=_charge(body.drinking),
        wastewater=_charge(body.wastewater),
        advance_mode=body.advance_mode,
        advance_dates=tuple(_day(text, "advance_dates") for text in body.advance_dates),
        settlement_debit_days=body.settlement_debit_days,
        garden_fee_cents=body.garden_fee_cents,
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


def _conflict_item(case: ConflictCase) -> dict:
    return {
        "start_date": case.start_date.isoformat(),
        "end_date": case.end_date.isoformat(),
        "excess_milli": case.excess_milli,
        "reading_id": case.reading_id,
        "exchange_id": case.exchange_id,
        "zeroed": case.zeroed,
    }


def _meter_item(view: MeterView, links: dict[int, AdvanceLink]) -> dict:
    status = _jsonable(view.status)
    if status is not None:
        # The payment that pays a schedule's advances; null when unlinked or flexible.
        status["recurring_payment_id"] = next(
            (payment for payment, link in links.items() if link.meter_id == view.id), None
        )
    return {
        "id": view.id,
        "name": view.meter.name,
        "kind": view.meter.kind,
        "main_meter_id": view.main_meter_id,
        "garden_conflicts": [_conflict_item(case) for case in view.conflicts],
        "status": status,
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
    raise UtilityNotFound(row_id)


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
            except UtilityNotFound:
                return JSONResponse({"error": "No such utility record"}, status_code=404)
            except MeterNotEmpty:
                return JSONResponse(
                    {
                        "error": "Delete the meter's readings, exchanges, periods and "
                        "garden meters first"
                    },
                    status_code=409,
                )
        finally:
            conn.close()
        return JSONResponse(item, status_code=status)

    def meter_item(conn: sqlite3.Connection, meter_id: int) -> dict:
        links = advance_links(conn, today())
        for view in load_utilities(conn, today()):
            if view.id == meter_id:
                return _meter_item(view, links)
        raise UtilityNotFound(meter_id)

    def all_meters(conn: sqlite3.Connection) -> list[dict]:
        links = advance_links(conn, today())
        return [_meter_item(view, links) for view in load_utilities(conn, today())]

    @router.get("/utilities")
    async def get_utilities() -> JSONResponse:
        return respond(lambda conn: {"meters": all_meters(conn)})

    # Meters

    @router.post("/utilities/meters", status_code=201)
    async def post_meter(request: Request) -> JSONResponse:
        body = await _parse_body(request, MeterIn)
        if isinstance(body, JSONResponse):
            return body
        return respond(
            lambda conn: meter_item(
                conn, add_meter(conn, Meter(body.name, body.kind, body.main_meter_id))
            ),
            201,
        )

    @router.put("/utilities/meters/{id}")
    async def put_meter(request: Request, id: int) -> JSONResponse:
        body = await _parse_body(request, MeterRenameIn)
        if isinstance(body, JSONResponse):
            return body

        def action(conn: sqlite3.Connection) -> dict:
            rename_meter(conn, id, body.name)
            return meter_item(conn, id)

        return respond(action)

    @router.delete("/utilities/meters/{id}")
    async def delete_meter_route(id: int) -> JSONResponse:
        def action(conn: sqlite3.Connection) -> dict:
            item = meter_item(conn, id)
            delete_meter(conn, id)
            return item

        return respond(action)

    @router.post("/utilities/meters/{id}/conflicts/zero")
    async def zero_conflict(request: Request, id: int) -> JSONResponse:
        body = await _parse_body(request, ZeroIn)
        if isinstance(body, JSONResponse):
            return body

        def action(conn: sqlite3.Connection) -> dict:
            start = _day(body.start_date, "start_date")
            end = _day(body.end_date, "end_date")
            zero_garden_interval(conn, id, start, end)
            return meter_item(conn, id)

        return respond(action)

    # Readings

    @router.post("/utilities/meters/{id}/readings", status_code=201)
    async def post_reading(request: Request, id: int) -> JSONResponse:
        body = await _parse_body(request, ReadingIn)
        if isinstance(body, JSONResponse):
            return body

        def action(conn: sqlite3.Connection) -> dict:
            reading = _reading(body)
            return _reading_item(Stored(add_reading(conn, id, reading), reading))

        return respond(action, 201)

    @router.put("/utilities/readings/{id}")
    async def put_reading(request: Request, id: int) -> JSONResponse:
        body = await _parse_body(request, ReadingIn)
        if isinstance(body, JSONResponse):
            return body

        def action(conn: sqlite3.Connection) -> dict:
            reading = _reading(body)
            update_reading(conn, id, reading)
            return _reading_item(Stored(id, reading))

        return respond(action)

    @router.delete("/utilities/readings/{id}")
    async def delete_reading_route(id: int) -> JSONResponse:
        def action(conn: sqlite3.Connection) -> dict:
            item = _reading_item(_find(conn, list_readings, id))
            delete_reading(conn, id)
            return item

        return respond(action)

    @router.post("/utilities/readings/{id}/exchange", status_code=201)
    async def post_reading_exchange(request: Request, id: int) -> JSONResponse:
        body = await _parse_body(request, ExchangeOfReadingIn)
        if isinstance(body, JSONResponse):
            return body

        def action(conn: sqlite3.Connection) -> dict:
            exchange_id = reading_to_exchange(conn, id, body.old_final_milli)
            return _exchange_item(_find(conn, list_exchanges, exchange_id))

        return respond(action, 201)

    # Exchanges

    @router.post("/utilities/meters/{id}/exchanges", status_code=201)
    async def post_exchange(request: Request, id: int) -> JSONResponse:
        body = await _parse_body(request, ExchangeIn)
        if isinstance(body, JSONResponse):
            return body

        def action(conn: sqlite3.Connection) -> dict:
            exchange = _exchange(body)
            return _exchange_item(Stored(add_exchange(conn, id, exchange), exchange))

        return respond(action, 201)

    @router.put("/utilities/exchanges/{id}")
    async def put_exchange(request: Request, id: int) -> JSONResponse:
        body = await _parse_body(request, ExchangeIn)
        if isinstance(body, JSONResponse):
            return body

        def action(conn: sqlite3.Connection) -> dict:
            exchange = _exchange(body)
            update_exchange(conn, id, exchange)
            return _exchange_item(Stored(id, exchange))

        return respond(action)

    @router.delete("/utilities/exchanges/{id}")
    async def delete_exchange_route(id: int) -> JSONResponse:
        def action(conn: sqlite3.Connection) -> dict:
            item = _exchange_item(_find(conn, list_exchanges, id))
            delete_exchange(conn, id)
            return item

        return respond(action)

    # Billing periods

    @router.post("/utilities/meters/{id}/periods", status_code=201)
    async def post_period(request: Request, id: int) -> JSONResponse:
        body = await _parse_body(request, PeriodIn)
        if isinstance(body, JSONResponse):
            return body

        def action(conn: sqlite3.Connection) -> dict:
            period = _period(body)
            return _period_item(Stored(add_period(conn, id, period), period))

        return respond(action, 201)

    @router.put("/utilities/periods/{id}")
    async def put_period(request: Request, id: int) -> JSONResponse:
        body = await _parse_body(request, PeriodIn)
        if isinstance(body, JSONResponse):
            return body

        def action(conn: sqlite3.Connection) -> dict:
            period = _period(body)
            update_period(conn, id, period)
            return _period_item(Stored(id, period))

        return respond(action)

    @router.delete("/utilities/periods/{id}")
    async def delete_period_route(id: int) -> JSONResponse:
        def action(conn: sqlite3.Connection) -> dict:
            item = _period_item(_find(conn, list_periods, id))
            delete_period(conn, id)
            return item

        return respond(action)

    return router
