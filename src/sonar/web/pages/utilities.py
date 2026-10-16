"""The energy pages (SPEC §13 Energy): the meters overview and one meter's history."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from sonar.categorization.store import list_categories
from sonar.db import connect
from sonar.utilities.model import BillingPeriod, Exchange, Meter, Reading
from sonar.utilities.service import MeterView, load_utilities
from sonar.utilities.settlement import current_period, daily_kwh, round_half_up
from sonar.utilities.store import (
    UtilityNotFound,
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
    meter_of_exchange,
    meter_of_period,
    meter_of_reading,
    update_exchange,
    update_period,
    update_reading,
)
from sonar.utilities.usage import continuous_series, daily_usage
from sonar.money import parse_signed_cents
from sonar.web import forms

METER_FIELDS = ("name", "kind")
READING_FIELDS = ("date", "value")
EXCHANGE_FIELDS = ("date", "old_final", "new_start")
PERIOD_FIELDS = (
    "start_date",
    "settlement_date",
    "base_fee",
    "unit_price",
    "state_factor",
    "calorific_value",
    "advance",
    "expected_usage",
    "category",
    "settled",
)
UNITS = {"gas": "m³", "electricity": "kWh"}


@dataclass(frozen=True)
class ReadingRow:
    stored: Stored[Reading]
    usage_milli: int | None  # since the previous point of the continuous series
    kwh_per_day: int | None


@dataclass(frozen=True)
class MeterCard:
    view: MeterView
    unit: str
    readings: list[ReadingRow]  # newest first
    current: BillingPeriod | None
    latest: Stored[BillingPeriod] | None
    new_period: dict[str, str]  # the "Start new period" form's prefill
    last_settlement: tuple[int, date] | None  # signed cents and date of the previous bill

    @property
    def is_empty(self) -> bool:
        return not (self.view.readings or self.view.exchanges or self.view.periods)


async def _form_values(request: Request, names: tuple[str, ...]) -> dict[str, str]:
    # A missing field becomes "" so it reaches our own ValueError -> 400, not FastAPI's 422.
    form = await request.form()
    return {name: str(form.get(name, "")) for name in names}


def _scaled(places: int) -> Callable[[str], int]:
    return lambda text: forms.parse_scaled(text, places)


def _optional(label: str, raw: str, kind: str, parser: Callable[[str], object]) -> object:
    return forms.field(label, raw, kind, parser) if raw.strip() else None


def _reading_from(values: dict[str, str]) -> Reading:
    return Reading(
        reading_date=forms.field("Date", values["date"], "date", date.fromisoformat),
        value_milli=forms.field("Reading", values["value"], "decimal3", _scaled(3)),
    )


def _exchange_from(values: dict[str, str]) -> Exchange:
    return Exchange(
        exchange_date=forms.field("Date", values["date"], "date", date.fromisoformat),
        old_final_milli=forms.field("Old meter final", values["old_final"], "decimal3", _scaled(3)),
        new_start_milli=forms.field("New meter start", values["new_start"], "decimal3", _scaled(3)),
    )


def _period_from(values: dict[str, str]) -> BillingPeriod:
    return BillingPeriod(
        start_date=forms.field("Start", values["start_date"], "date", date.fromisoformat),
        settlement_date=forms.field(
            "Settlement date", values["settlement_date"], "date", date.fromisoformat
        ),
        base_fee_cents=forms.field("Base fee", values["base_fee"], "amount", parse_signed_cents),
        unit_price_micro=forms.field("Unit price", values["unit_price"], "decimal4", _scaled(4)),
        state_factor_e4=_optional("State factor", values["state_factor"], "decimal4", _scaled(4)),
        calorific_value_e4=_optional(
            "Calorific value", values["calorific_value"], "decimal4", _scaled(4)
        ),
        advance_cents=forms.field("Advance", values["advance"], "amount", parse_signed_cents),
        expected_usage=forms.field("Expected kWh", values["expected_usage"], "int", int),
        category=values["category"].strip() or None,
        settled_cents=_optional("Settled amount", values["settled"], "amount", parse_signed_cents),
    )


def _reading_values(reading: Reading) -> dict[str, str]:
    return {
        "date": reading.reading_date.isoformat(),
        "value": forms.format_scaled(reading.value_milli, 3),
    }


def _exchange_values(exchange: Exchange) -> dict[str, str]:
    return {
        "date": exchange.exchange_date.isoformat(),
        "old_final": forms.format_scaled(exchange.old_final_milli, 3),
        "new_start": forms.format_scaled(exchange.new_start_milli, 3),
    }


def _period_values(period: BillingPeriod | None) -> dict[str, str]:
    if period is None:
        return dict.fromkeys(PERIOD_FIELDS, "")
    return {
        "start_date": period.start_date.isoformat(),
        "settlement_date": period.settlement_date.isoformat(),
        "base_fee": forms.format_scaled(period.base_fee_cents, 2),
        "unit_price": forms.format_scaled(period.unit_price_micro, 4),
        "state_factor": _optional_scaled(period.state_factor_e4),
        "calorific_value": _optional_scaled(period.calorific_value_e4),
        "advance": forms.format_scaled(period.advance_cents, 2),
        "expected_usage": str(period.expected_usage),
        "category": period.category or "",
        "settled": ""
        if period.settled_cents is None
        else forms.format_scaled(period.settled_cents, 2),
    }


def _optional_scaled(value: int | None) -> str:
    return "" if value is None else forms.format_scaled(value, 4)


def _one_year_later(day: date) -> date:
    try:
        return day.replace(year=day.year + 1)
    except ValueError:  # 29 February
        return day.replace(year=day.year + 1, day=28)


def _next_period_values(latest: Stored[BillingPeriod] | None) -> dict[str, str]:
    """The latest period again, starting the day after it settles and running a year longer."""
    if latest is None:
        return _period_values(None)
    settles = latest.item.settlement_date
    return {
        **_period_values(latest.item),
        "start_date": (settles + timedelta(days=1)).isoformat(),
        "settlement_date": _one_year_later(settles).isoformat(),
        "settled": "",  # the new bill is not in yet
    }


def _reading_rows(view: MeterView) -> list[ReadingRow]:
    """Newest first, each with the usage since the previous point and its kWh per day."""
    series = continuous_series(
        [stored.item for stored in view.readings], [stored.item for stored in view.exchanges]
    )
    value_on = dict(series)
    previous = {day: point for point, (day, _) in zip(series, series[1:], strict=False)}
    kwh = daily_kwh(view.meter.kind, [stored.item for stored in view.periods], daily_usage(series))
    rows = []
    for stored in view.readings:
        day = stored.item.reading_date
        before = previous.get(day)
        if before is None:
            rows.append(ReadingRow(stored, None, None))
            continue
        before_day, before_value = before
        days = [before_day + timedelta(days=n) for n in range((day - before_day).days)]
        known = all(each in kwh for each in days)
        rows.append(
            ReadingRow(
                stored,
                usage_milli=value_on[day] - before_value,
                kwh_per_day=round_half_up(sum(kwh[each] for each in days) / len(days))
                if known
                else None,
            )
        )
    return list(reversed(rows))


def _last_settlement(
    periods: list[BillingPeriod], current: BillingPeriod | None
) -> tuple[int, date] | None:
    """The bill of the period right before the current one, when its amount is known."""
    if current is None:
        return None
    earlier = [period for period in periods if period.settlement_date < current.start_date]
    if not earlier:
        return None
    previous = max(earlier, key=lambda period: period.settlement_date)
    if previous.settled_cents is None:
        return None
    return previous.settled_cents, previous.settlement_date


def _card(view: MeterView, today: date) -> MeterCard:
    periods = [stored.item for stored in view.periods]
    latest = view.periods[-1] if view.periods else None
    current = current_period(periods, today)
    return MeterCard(
        view=view,
        unit=UNITS[view.meter.kind],
        readings=_reading_rows(view),
        current=current,
        latest=latest,
        new_period=_next_period_values(latest),
        last_settlement=_last_settlement(periods, current),
    )


def build_router(db_path: Path, today: Callable[[], date], templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    def _render_energy_page(
        request: Request, status_code: int = 200, error: dict | None = None
    ) -> HTMLResponse:
        # Shared by the GET route and every POST error path, so a 400 re-render
        # shows the page a fresh GET would, plus the one form that failed.
        views, _ = _load()
        return templates.TemplateResponse(
            request,
            "utilities.html",
            {
                "cards": [_card(view, today()) for view in views],
                "error": error,
            },
            status_code=status_code,
        )

    def _render_meter_page(
        request: Request, meter_id: int, status_code: int = 200, error: dict | None = None
    ) -> HTMLResponse:
        views, categories = _load()
        view = next((view for view in views if view.id == meter_id), None)
        if view is None:
            return _not_found(request)
        return templates.TemplateResponse(
            request,
            "utility_meter.html",
            {
                "meter_card": _card(view, today()),
                "category_options": [("", "None"), *((name, name) for name in categories)],
                "error": error,
                "values": {
                    "reading": _reading_values,
                    "exchange": _exchange_values,
                    "period": _period_values,
                },
            },
            status_code=status_code,
        )

    def _load() -> tuple[list[MeterView], list[str]]:
        conn = connect(db_path)
        try:
            return load_utilities(conn, today()), [c.name for c in list_categories(conn)]
        finally:
            conn.close()

    def _not_found(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "error.html", {"message": "No such energy record"}, status_code=404
        )

    def _run[T](action: Callable[[sqlite3.Connection], T]) -> T:
        conn = connect(db_path)
        try:
            return action(conn)
        finally:
            conn.close()

    def _back_to(meter_id: int | None) -> str:
        return "/utilities" if meter_id is None else f"/utilities/meters/{meter_id}"

    def _render_back(request: Request, meter_id: int | None, error: dict) -> HTMLResponse:
        if meter_id is None:
            return _render_energy_page(request, status_code=400, error=error)
        return _render_meter_page(request, meter_id, status_code=400, error=error)

    async def _submit(
        request: Request,
        form: str,
        field_names: tuple[str, ...],
        build: Callable[[dict[str, str]], object],
        write: Callable[[sqlite3.Connection, object], object],
        meter_of: Callable[[sqlite3.Connection], int] | None = None,
    ) -> HTMLResponse | RedirectResponse:
        """Parse, write and redirect; a bad entry re-renders with 400 and `form` open.

        With `meter_of` the page is that meter's page, otherwise the overview.
        """
        values = await _form_values(request, field_names)
        meter_id = None
        try:
            meter_id = _run(meter_of) if meter_of else None
            item = build(values)
            _run(lambda conn: write(conn, item))
        except UtilityNotFound:
            return _not_found(request)
        except ValueError as error:  # a parse error or a FieldError
            failure = {"form": form, "message": forms.friendly(error), "fields": values}
            return _render_back(request, meter_id, failure)
        return RedirectResponse(_back_to(meter_id), status_code=303)

    def _delete(
        request: Request,
        remove: Callable[[sqlite3.Connection], object],
        meter_of: Callable[[sqlite3.Connection], int] | None = None,
    ) -> HTMLResponse | RedirectResponse:
        meter_id = None
        try:
            meter_id = _run(meter_of) if meter_of else None
            _run(remove)
        except UtilityNotFound:
            return _not_found(request)
        except MeterNotEmpty:
            message = "Delete the meter's readings, exchanges and periods first."
            return _render_energy_page(
                request, status_code=400, error={"form": "page", "message": message, "fields": {}}
            )
        except ValueError as error:  # the store rejected a delete that breaks the series
            failure = {"form": "page", "message": forms.friendly(error), "fields": {}}
            return _render_back(request, meter_id, failure)
        return RedirectResponse(_back_to(meter_id), status_code=303)

    @router.get("/utilities", response_class=HTMLResponse)
    async def energy_page(request: Request) -> HTMLResponse:
        return _render_energy_page(request)

    @router.get("/utilities/meters/{id}", response_class=HTMLResponse)
    async def meter_page(request: Request, id: int) -> HTMLResponse:
        return _render_meter_page(request, id)

    # Meters

    @router.post("/utilities/meters")
    async def add_meter_route(request: Request):
        return await _submit(
            request,
            "add-meter",
            METER_FIELDS,
            lambda v: Meter(v["name"], v["kind"]),
            add_meter,
        )

    @router.post("/utilities/meters/{id}/delete")
    async def delete_meter_route(request: Request, id: int):
        return _delete(request, lambda conn: delete_meter(conn, id))

    # Readings

    @router.post("/utilities/meters/{id}/readings")
    async def add_reading_route(request: Request, id: int):
        return await _submit(
            request,
            f"meter-{id}-add-reading",
            READING_FIELDS,
            _reading_from,
            lambda conn, reading: add_reading(conn, id, reading),
        )

    @router.post("/utilities/readings/{id}/edit")
    async def edit_reading_route(request: Request, id: int):
        return await _submit(
            request,
            f"reading-{id}-edit",
            READING_FIELDS,
            _reading_from,
            lambda conn, reading: update_reading(conn, id, reading),
            meter_of=lambda conn: meter_of_reading(conn, id),
        )

    @router.post("/utilities/readings/{id}/delete")
    async def delete_reading_route(request: Request, id: int):
        return _delete(
            request,
            lambda conn: delete_reading(conn, id),
            lambda conn: meter_of_reading(conn, id),
        )

    # Exchanges

    @router.post("/utilities/meters/{id}/exchanges")
    async def add_exchange_route(request: Request, id: int):
        return await _submit(
            request,
            f"meter-{id}-add-exchange",
            EXCHANGE_FIELDS,
            _exchange_from,
            lambda conn, exchange: add_exchange(conn, id, exchange),
            meter_of=lambda conn: id,
        )

    @router.post("/utilities/exchanges/{id}/edit")
    async def edit_exchange_route(request: Request, id: int):
        return await _submit(
            request,
            f"exchange-{id}-edit",
            EXCHANGE_FIELDS,
            _exchange_from,
            lambda conn, exchange: update_exchange(conn, id, exchange),
            meter_of=lambda conn: meter_of_exchange(conn, id),
        )

    @router.post("/utilities/exchanges/{id}/delete")
    async def delete_exchange_route(request: Request, id: int):
        return _delete(
            request,
            lambda conn: delete_exchange(conn, id),
            lambda conn: meter_of_exchange(conn, id),
        )

    # Billing periods

    @router.post("/utilities/meters/{id}/periods")
    async def add_period_route(request: Request, id: int):
        return await _submit(
            request,
            f"meter-{id}-new-period",
            PERIOD_FIELDS,
            _period_from,
            lambda conn, period: add_period(conn, id, period),
            meter_of=lambda conn: id,
        )

    @router.post("/utilities/periods/{id}/edit")
    async def edit_period_route(request: Request, id: int):
        return await _submit(
            request,
            f"period-{id}-edit",
            PERIOD_FIELDS,
            _period_from,
            lambda conn, period: update_period(conn, id, period),
            meter_of=lambda conn: meter_of_period(conn, id),
        )

    @router.post("/utilities/periods/{id}/delete")
    async def delete_period_route(request: Request, id: int):
        return _delete(
            request,
            lambda conn: delete_period(conn, id),
            lambda conn: meter_of_period(conn, id),
        )

    return router
