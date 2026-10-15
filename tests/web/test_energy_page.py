"""Tests for the Energy page (SPEC §13 Energy): meters, readings, exchanges, periods."""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest
from fastapi.testclient import TestClient

from sonar.db import connect
from sonar.energy.model import BillingPeriod, Exchange, Meter, Reading
from sonar.energy.store import (
    add_meter,
    add_period,
    add_reading,
    list_exchanges,
    list_meters,
    list_periods,
    list_readings,
)
from sonar.web.app import create_app
from tests.html import cents, soup, text
from tests.seed import seed

TODAY = date(2026, 1, 11)
CATEGORIES = """
[[category]]
name = "Utilities"
type = "fixed"

[[category]]
name = "Dining"
type = "occasional"
"""


def _today() -> date:
    return TODAY


def _period(**changes) -> BillingPeriod:
    values = {
        "start_date": date(2026, 1, 1),
        "settlement_date": date(2026, 12, 31),
        "base_fee_cents": 1_200,
        "unit_price_micro": 30_000,
        "state_factor_e4": None,
        "calorific_value_e4": None,
        "advance_cents": 5_000,
        "expected_kwh": 3_000,
        "category": "Utilities",
    }
    return BillingPeriod(**{**values, **changes})


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "t.db"
    seed(path, CATEGORIES)
    return path


@pytest.fixture
def client(db_path):
    with TestClient(create_app(db_path, today=_today), follow_redirects=False) as client:
        yield client


def _store(db_path, action):
    conn = connect(db_path)
    try:
        return action(conn)
    finally:
        conn.close()


def _insert_debit(db_path, booking_date: str, amount_cents: int, category: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO transactions (
                source, account, booking_date, value_date, amount_cents, currency,
                counterparty, purpose, iban, mandate_ref, creditor_id, raw_row,
                fingerprint, occurrence, category
            ) VALUES ('test', 'acc', ?, ?, ?, 'EUR', 'Utility Co', '', NULL, NULL, NULL,
                      'raw', ?, 1, ?)
            """,
            (
                booking_date,
                booking_date,
                amount_cents,
                f"fp-{booking_date}-{amount_cents}",
                category,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _gas_meter(db_path) -> int:
    return _store(db_path, lambda conn: add_meter(conn, Meter("Gas", "gas")))


def _electricity_meter(db_path) -> int:
    return _store(db_path, lambda conn: add_meter(conn, Meter("Power", "electricity")))


def _with_readings(db_path) -> int:
    """An electricity meter with a 2026 period and 100 kWh over the first ten days."""
    meter = _electricity_meter(db_path)
    _store(db_path, lambda conn: add_period(conn, meter, _period()))
    _store(db_path, lambda conn: add_reading(conn, meter, Reading(date(2026, 1, 1), 1_000_000)))
    _store(db_path, lambda conn: add_reading(conn, meter, Reading(date(2026, 1, 11), 1_100_000)))
    return meter


def _page(client):
    return soup(client.get("/energy"))


def _error(response) -> str:
    assert response.status_code == 400
    return text(soup(response).select_one("#form-error"))


def _input(page, selector: str) -> str:
    return page.select_one(selector)["value"]


# Page and meters


def test_a_reading_of_a_gas_meter_shows_in_its_meter_section(client, db_path):
    meter = _gas_meter(db_path)
    _store(db_path, lambda conn: add_reading(conn, meter, Reading(date(2026, 1, 5), 12_345)))

    sections = _page(client).select("[data-meter-id]")

    assert [section["data-meter-id"] for section in sections] == [str(meter)]
    rows = sections[0].select("tbody [data-row]")
    assert [row.select_one('[data-field="date"] time')["datetime"] for row in rows] == [
        "2026-01-05"
    ]
    assert text(rows[0].select_one('[data-field="reading"]')) == "12.345"


def test_no_meters_shows_the_add_meter_card_only(client):
    page = _page(client)

    assert page.select("[data-meter-id]") == []
    assert page.select_one("#add-meter") is not None


def test_energy_is_a_nav_item_after_payoff(client):
    links = [a["href"] for a in _page(client).select("nav a[href]")]

    assert links[links.index("/payoff") + 1] == "/energy"


def test_readings_list_newest_first_with_usage_and_kwh_per_day(client, db_path):
    meter = _with_readings(db_path)
    _store(db_path, lambda conn: add_reading(conn, meter, Reading(date(2026, 1, 16), 1_125_000)))

    rows = _page(client).select(f"#meter-{meter}-readings tbody [data-row]")

    assert [row.select_one("time")["datetime"] for row in rows] == [
        "2026-01-16",
        "2026-01-11",
        "2026-01-01",
    ]
    assert [text(row.select_one('[data-field="usage"]')) for row in rows] == [
        "25.000",
        "100.000",
        "",
    ]
    # 25 kWh over 5 days and 100 kWh over 10 days; the first reading has no previous one.
    assert [text(row.select_one('[data-field="kwh_per_day"]')) for row in rows] == [
        "5",
        "10",
        "",
    ]


def test_gas_usage_is_converted_to_kwh_per_day_by_the_period(client, db_path):
    meter = _gas_meter(db_path)
    period = _period(state_factor_e4=9_500, calorific_value_e4=110_000)
    _store(db_path, lambda conn: add_period(conn, meter, period))
    _store(db_path, lambda conn: add_reading(conn, meter, Reading(date(2026, 1, 1), 1_000)))
    _store(db_path, lambda conn: add_reading(conn, meter, Reading(date(2026, 1, 11), 101_000)))

    row = _page(client).select(f"#meter-{meter}-readings tbody [data-row]")[0]

    # 100 m³ in 10 days x 0.95 x 11 kWh per m³ = 104.5 kWh per day, rounded half up.
    assert text(row.select_one('[data-field="usage"]')) == "100.000"
    assert text(row.select_one('[data-field="kwh_per_day"]')) == "105"


# Status


def test_status_stats_carry_cents(client, db_path):
    meter = _with_readings(db_path)
    _insert_debit(db_path, "2026-01-03", -5_000, "Utilities")
    page = _page(client)

    def stat(name: str) -> int:
        return cents(page.select_one(f"#meter-{meter}-{name}"))

    # 100 kWh x 3 ct + 10 days of the 12 EUR fee (10 x 1200 / 31) = 687 cents so far.
    assert stat("cost-so-far") == 687
    assert stat("paid") == 5_000
    assert stat("left") == 5_000 - 687
    # Projected: 10 kWh a day at 3 ct all year plus 12 fees is 25350 cents in all.
    # 5000 paid + 11 more advances of 5000 (3 Feb .. 3 Dec) - 25350 = 34650 refund.
    settlement = page.select_one(f"#meter-{meter}-settlement")
    assert cents(settlement) == 34_650
    assert settlement["data-kind"] == "refund"
    assert stat("worst-case") == 34_650
    # (25350 - 5000) / 11 advances = 1850, rounded up to whole euros.
    assert stat("suggested-advance") == 1_900
    assert page.select_one(f"#meter-{meter}-settlement-date")["datetime"] == "2026-12-31"


def test_a_back_payment_is_worded_as_such(client, db_path):
    meter = _electricity_meter(db_path)
    _store(db_path, lambda conn: add_period(conn, meter, _period(advance_cents=1_000)))
    _store(db_path, lambda conn: add_reading(conn, meter, Reading(date(2026, 1, 1), 1_000_000)))
    _store(db_path, lambda conn: add_reading(conn, meter, Reading(date(2026, 1, 11), 1_100_000)))

    settlement = _page(client).select_one(f"#meter-{meter}-settlement")

    # Nothing paid: 12 advances of 1000 (the 1st of each month) - 25350 projected.
    assert settlement["data-kind"] == "back-payment"
    assert cents(settlement) == 13_350


def test_a_meter_without_a_current_period_shows_no_projection(client, db_path):
    meter = _electricity_meter(db_path)
    past = _period(start_date=date(2025, 1, 1), settlement_date=date(2025, 12, 31))
    _store(db_path, lambda conn: add_period(conn, meter, past))

    page = _page(client)

    assert page.select_one(f"#meter-{meter}-cost-so-far") is None
    assert "2025-12-31" in str(page.select_one(f"#meter-{meter}-settled"))


# Meters


def test_add_meter_redirects_and_lists_it(client, db_path):
    response = client.post("/energy/meters", data={"name": "Flat gas", "kind": "gas"})

    assert response.status_code == 303
    assert response.headers["location"] == "/energy"
    assert _store(db_path, list_meters)[0].item == Meter("Flat gas", "gas")


def test_add_meter_with_a_blank_name_is_a_400_that_keeps_the_entry(client):
    response = client.post("/energy/meters", data={"name": "  ", "kind": "electricity"})

    assert "Name" in _error(response)
    assert _input(soup(response), "#add-meter input[name=name]") == "  "
    assert (
        soup(response).select_one('#add-meter option[value="electricity"]')["selected"] is not None
    )


def test_an_empty_meter_can_be_deleted(client, db_path):
    meter = _gas_meter(db_path)
    page = _page(client)
    form = page.select_one(f"#meter-{meter}-delete")

    response = client.post(form["action"])

    assert response.status_code == 303
    assert _store(db_path, list_meters) == []


def test_a_meter_with_data_has_no_delete_form(client, db_path):
    meter = _with_readings(db_path)

    assert _page(client).select_one(f"#meter-{meter}-delete") is None


def test_deleting_a_meter_with_data_is_a_400(client, db_path):
    meter = _with_readings(db_path)

    response = client.post(f"/energy/meters/{meter}/delete")

    assert "readings" in _error(response)
    assert len(_store(db_path, list_meters)) == 1


# Readings


def test_add_reading(client, db_path):
    meter = _gas_meter(db_path)

    response = client.post(
        f"/energy/meters/{meter}/readings", data={"date": "2026-01-05", "value": "12,345"}
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/energy"
    stored = _store(db_path, lambda conn: list_readings(conn, meter))
    assert [s.item for s in stored] == [Reading(date(2026, 1, 5), 12_345)]


def test_edit_reading_prefills_and_saves(client, db_path):
    meter = _with_readings(db_path)
    stored = _store(db_path, lambda conn: list_readings(conn, meter))[1]
    form = _page(client).select_one(f"#reading-{stored.id}-edit")
    assert form.select_one("input[name=value]")["value"] == "1100.000"
    assert form.select_one("input[name=date]")["value"] == "2026-01-11"

    response = client.post(form["action"], data={"date": "2026-01-12", "value": "1100.5"})

    assert response.status_code == 303
    updated = _store(db_path, lambda conn: list_readings(conn, meter))[1]
    assert updated.item == Reading(date(2026, 1, 12), 1_100_500)


def test_delete_reading(client, db_path):
    meter = _with_readings(db_path)
    stored = _store(db_path, lambda conn: list_readings(conn, meter))[1]
    form = _page(client).select_one(f"#reading-{stored.id}-delete")
    assert form["hx-confirm"]

    response = client.post(form["action"])

    assert response.status_code == 303
    assert len(_store(db_path, lambda conn: list_readings(conn, meter))) == 1


def test_a_dropping_reading_is_a_400_that_keeps_the_entry_and_writes_nothing(client, db_path):
    meter = _with_readings(db_path)

    response = client.post(
        f"/energy/meters/{meter}/readings", data={"date": "2026-01-20", "value": "999.5"}
    )

    assert "2026-01-20" in _error(response)
    page = soup(response)
    assert _input(page, f"#meter-{meter}-add-reading input[name=value]") == "999.5"
    assert _input(page, f"#meter-{meter}-add-reading input[name=date]") == "2026-01-20"
    assert len(_store(db_path, lambda conn: list_readings(conn, meter))) == 2


def test_a_reading_with_too_many_decimals_is_a_400(client, db_path):
    meter = _gas_meter(db_path)

    response = client.post(
        f"/energy/meters/{meter}/readings", data={"date": "2026-01-05", "value": "1.2345"}
    )

    assert "Reading" in _error(response)
    assert _input(soup(response), f"#meter-{meter}-add-reading input[name=value]") == "1.2345"


def test_a_bad_edit_reopens_that_rows_drawer_with_the_entry(client, db_path):
    meter = _with_readings(db_path)
    stored = _store(db_path, lambda conn: list_readings(conn, meter))[1]

    response = client.post(
        f"/energy/readings/{stored.id}/edit", data={"date": "2026-01-11", "value": "abc"}
    )

    _error(response)
    page = soup(response)
    assert _input(page, f"#reading-{stored.id}-edit input[name=value]") == "abc"
    assert page.select_one(f"#reading-{stored.id}-edit").find_parent("details").has_attr("open")


def test_a_missing_reading_is_a_404(client):
    assert client.post("/energy/readings/99/delete").status_code == 404
    assert (
        client.post(
            "/energy/meters/99/readings", data={"date": "2026-01-05", "value": "1"}
        ).status_code
        == 404
    )


# Exchanges


def test_add_edit_and_delete_an_exchange(client, db_path):
    meter = _electricity_meter(db_path)
    _store(db_path, lambda conn: add_reading(conn, meter, Reading(date(2026, 1, 1), 1_000)))

    added = client.post(
        f"/energy/meters/{meter}/exchanges",
        data={"date": "2026-02-01", "old_final": "1500", "new_start": "0,5"},
    )

    assert added.status_code == 303
    stored = _store(db_path, lambda conn: list_exchanges(conn, meter))
    assert [s.item for s in stored] == [Exchange(date(2026, 2, 1), 1_500_000, 500)]

    form = _page(client).select_one(f"#exchange-{stored[0].id}-edit")
    assert form.select_one("input[name=old_final]")["value"] == "1500.000"
    edited = client.post(
        form["action"], data={"date": "2026-02-02", "old_final": "1600", "new_start": "0"}
    )
    assert edited.status_code == 303
    after = _store(db_path, lambda conn: list_exchanges(conn, meter))
    assert [s.item for s in after] == [Exchange(date(2026, 2, 2), 1_600_000, 0)]

    deleted = client.post(f"/energy/exchanges/{stored[0].id}/delete")
    assert deleted.status_code == 303
    assert _store(db_path, lambda conn: list_exchanges(conn, meter)) == []


def test_an_exchange_on_a_reading_date_is_a_400(client, db_path):
    meter = _with_readings(db_path)

    response = client.post(
        f"/energy/meters/{meter}/exchanges",
        data={"date": "2026-01-11", "old_final": "1100", "new_start": "0"},
    )

    assert "2026-01-11" in _error(response)
    assert _input(soup(response), f"#meter-{meter}-add-exchange input[name=old_final]") == "1100"


# Billing periods

NEW_PERIOD = {
    "start_date": "2027-01-01",
    "settlement_date": "2027-12-31",
    "base_fee": "12,50",
    "unit_price": "31.5",
    "state_factor": "",
    "calorific_value": "",
    "advance": "60",
    "expected_kwh": "3100",
    "category": "Utilities",
}


def test_add_edit_and_delete_a_period(client, db_path):
    meter = _electricity_meter(db_path)

    added = client.post(f"/energy/meters/{meter}/periods", data=NEW_PERIOD)

    assert added.status_code == 303
    stored = _store(db_path, lambda conn: list_periods(conn, meter))
    assert [s.item for s in stored] == [
        _period(
            start_date=date(2027, 1, 1),
            settlement_date=date(2027, 12, 31),
            base_fee_cents=1_250,
            unit_price_micro=315_000,
            advance_cents=6_000,
            expected_kwh=3_100,
        )
    ]

    form = _page(client).select_one(f"#period-{stored[0].id}-edit")
    assert form.select_one("input[name=unit_price]")["value"] == "31.5000"
    assert form.select_one("input[name=base_fee]")["value"] == "12.50"
    edited = client.post(form["action"], data={**NEW_PERIOD, "unit_price": "32", "category": ""})
    assert edited.status_code == 303
    after = _store(db_path, lambda conn: list_periods(conn, meter))[0].item
    assert (after.unit_price_micro, after.category) == (320_000, None)

    deleted = client.post(f"/energy/periods/{stored[0].id}/delete")
    assert deleted.status_code == 303
    assert _store(db_path, lambda conn: list_periods(conn, meter)) == []


def test_a_gas_period_takes_the_state_factor_and_calorific_value(client, db_path):
    meter = _gas_meter(db_path)

    response = client.post(
        f"/energy/meters/{meter}/periods",
        data={**NEW_PERIOD, "state_factor": "0,95", "calorific_value": "11.0"},
    )

    assert response.status_code == 303
    period = _store(db_path, lambda conn: list_periods(conn, meter))[0].item
    assert (period.state_factor_e4, period.calorific_value_e4) == (9_500, 110_000)


def test_an_electricity_period_form_has_no_gas_fields(client, db_path):
    meter = _electricity_meter(db_path)
    page = _page(client)

    form = page.select_one(f"#meter-{meter}-new-period")
    assert form.select_one("input[name=state_factor]") is None
    assert form.select_one("input[name=unit_price]") is not None


def test_a_bad_price_is_a_400_that_keeps_every_entry(client, db_path):
    meter = _electricity_meter(db_path)

    response = client.post(
        f"/energy/meters/{meter}/periods", data={**NEW_PERIOD, "unit_price": "12.34567"}
    )

    assert "Unit price" in _error(response)
    form = soup(response).select_one(f"#meter-{meter}-new-period")
    assert form.select_one("input[name=unit_price]")["value"] == "12.34567"
    assert form.select_one("input[name=advance]")["value"] == "60"
    assert _store(db_path, lambda conn: list_periods(conn, meter)) == []


def test_a_gas_period_without_a_state_factor_is_a_400(client, db_path):
    meter = _gas_meter(db_path)

    response = client.post(f"/energy/meters/{meter}/periods", data=NEW_PERIOD)

    assert "State factor" in _error(response)


def test_an_overlapping_period_is_a_400(client, db_path):
    meter = _with_readings(db_path)

    response = client.post(
        f"/energy/meters/{meter}/periods", data={**NEW_PERIOD, "start_date": "2026-06-01"}
    )

    assert "overlaps" in _error(response)


def test_the_new_period_form_is_prefilled_from_the_latest_period(client, db_path):
    meter = _with_readings(db_path)

    form = _page(client).select_one(f"#meter-{meter}-new-period")

    def value(name: str) -> str:
        return form.select_one(f"input[name={name}]")["value"]

    assert value("start_date") == "2027-01-01"
    assert value("settlement_date") == "2027-12-31"
    assert value("base_fee") == "12.00"
    assert value("unit_price") == "3.0000"
    assert value("advance") == "50.00"
    assert value("expected_kwh") == "3000"
    assert form.select_one("select[name=category] option[selected]")["value"] == "Utilities"


def test_category_choices_are_the_categories(client, db_path):
    meter = _electricity_meter(db_path)

    form = _page(client).select_one(f"#meter-{meter}-new-period")

    assert [o["value"] for o in form.select("select[name=category] option")] == [
        "",
        "Utilities",
        "Dining",
    ]


def test_the_new_period_form_is_empty_without_a_period(client, db_path):
    meter = _electricity_meter(db_path)

    form = _page(client).select_one(f"#meter-{meter}-new-period")

    assert form.select_one("input[name=start_date]")["value"] == ""


# Usage and cost chart


def _with_months(db_path, readings: list[tuple[date, int]]) -> int:
    meter = _electricity_meter(db_path)
    _store(db_path, lambda conn: add_period(conn, meter, _period()))
    for day, value_milli in readings:
        reading = Reading(day, value_milli)
        _store(db_path, lambda conn, reading=reading: add_reading(conn, meter, reading))
    return meter


def test_a_chart_per_meter_has_both_series_and_a_trend_for_each(client, db_path):
    meter = _with_months(
        db_path,
        [
            (date(2026, 1, 1), 1_000_000),
            (date(2026, 2, 1), 1_100_000),
            (date(2026, 3, 1), 1_250_000),
            (date(2026, 4, 1), 1_300_000),
        ],
    )
    other = _gas_meter(db_path)
    page = _page(client)

    charts = page.select("[data-energy-chart]")
    chart = page.select_one(f"#meter-{meter} [data-energy-chart]")
    months = len(chart.select('[data-series="usage"] rect'))

    assert len(charts) == 1
    assert page.select_one(f"#meter-{other} [data-energy-chart]") is None
    assert months >= 2
    assert chart.select_one('[data-series="cost"]') is not None
    assert len(chart.select("[data-trend]")) == 2
    assert {el["data-trend"] for el in chart.select("[data-trend]")} == {"usage", "cost"}
    for series in ("usage", "cost"):
        assert len(chart.select(f'[data-value-label="{series}"]')) == months


def test_the_chart_toggles_are_unchecked_checkboxes_and_need_no_script(client, db_path):
    _with_months(
        db_path,
        [
            (date(2026, 1, 1), 1_000_000),
            (date(2026, 2, 1), 1_100_000),
            (date(2026, 3, 1), 1_250_000),
        ],
    )

    chart = _page(client).select_one("[data-energy-chart]")

    for toggle in ("values", "trend"):
        box = chart.select_one(f'input[data-toggle="{toggle}"]')
        assert box["type"] == "checkbox"
        assert not box.has_attr("checked")
    assert chart.select_one("script") is None


def test_the_chart_is_a_labelled_image_naming_both_series_and_units(client, db_path):
    _with_months(
        db_path,
        [
            (date(2026, 1, 1), 1_000_000),
            (date(2026, 2, 1), 1_100_000),
            (date(2026, 3, 1), 1_250_000),
        ],
    )

    svg = _page(client).select_one("[data-energy-chart] svg")

    assert svg["role"] == "img"
    assert svg["aria-label"]
    assert svg.select_one("title") is not None
    legend = text(_page(client).select_one("[data-energy-chart] ul"))
    assert "kWh" in legend
    assert "€" in legend


def test_fewer_than_two_months_shows_an_empty_state_instead_of_a_chart(client, db_path):
    meter = _with_months(db_path, [(date(2026, 1, 1), 1_000_000), (date(2026, 2, 1), 1_100_000)])

    card = _page(client).select_one(f"#meter-{meter}")

    assert card.select_one("[data-energy-chart]") is None
    assert card.select_one("[data-energy-chart-empty]") is not None
