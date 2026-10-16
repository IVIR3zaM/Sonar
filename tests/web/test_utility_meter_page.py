"""Tests for the meter page (SPEC §13 Utilities): readings, exchanges and billing periods."""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest
from fastapi.testclient import TestClient

from sonar.db import connect
from sonar.utilities.model import BillingPeriod, Exchange, Meter, Reading
from sonar.utilities.store import (
    add_exchange,
    add_meter,
    add_period,
    add_reading,
    list_exchanges,
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
        "expected_usage": 3_000,
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


def _with_readings(db_path, **period_changes) -> int:
    """An electricity meter with a 2026 period and 100 kWh over the first ten days."""
    meter = _electricity_meter(db_path)
    _store(db_path, lambda conn: add_period(conn, meter, _period(**period_changes)))
    _store(db_path, lambda conn: add_reading(conn, meter, Reading(date(2026, 1, 1), 1_000_000)))
    _store(db_path, lambda conn: add_reading(conn, meter, Reading(date(2026, 1, 11), 1_100_000)))
    return meter


def _page(client, meter: int):
    return soup(client.get(f"/utilities/meters/{meter}"))


def _error(response) -> str:
    assert response.status_code == 400
    return text(soup(response).select_one("#form-error"))


def _input(page, selector: str) -> str:
    return page.select_one(selector)["value"]


# Page


def test_readings_list_newest_first_with_usage_and_kwh_per_day(client, db_path):
    meter = _with_readings(db_path)
    _store(db_path, lambda conn: add_reading(conn, meter, Reading(date(2026, 1, 16), 1_125_000)))

    rows = _page(client, meter).select(f"#meter-{meter}-readings tbody [data-row]")

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

    row = _page(client, meter).select(f"#meter-{meter}-readings tbody [data-row]")[0]

    # 100 m³ in 10 days x 0.95 x 11 kWh per m³ = 104.5 kWh per day, rounded half up.
    assert text(row.select_one('[data-field="usage"]')) == "100.000"
    assert text(row.select_one('[data-field="kwh_per_day"]')) == "105"


def test_edit_reading_prefills_and_saves(client, db_path):
    meter = _with_readings(db_path)
    stored = _store(db_path, lambda conn: list_readings(conn, meter))[1]
    form = _page(client, meter).select_one(f"#reading-{stored.id}-edit")
    assert form.select_one("input[name=value]")["value"] == "1100.000"
    assert form.select_one("input[name=date]")["value"] == "2026-01-11"

    response = client.post(form["action"], data={"date": "2026-01-12", "value": "1100.5"})

    assert response.status_code == 303
    updated = _store(db_path, lambda conn: list_readings(conn, meter))[1]
    assert updated.item == Reading(date(2026, 1, 12), 1_100_500)


def test_delete_reading(client, db_path):
    meter = _with_readings(db_path)
    stored = _store(db_path, lambda conn: list_readings(conn, meter))[1]
    form = _page(client, meter).select_one(f"#reading-{stored.id}-delete")
    assert form["hx-confirm"]

    response = client.post(form["action"])

    assert response.status_code == 303
    assert len(_store(db_path, lambda conn: list_readings(conn, meter))) == 1


def test_a_bad_edit_reopens_that_rows_drawer_with_the_entry(client, db_path):
    meter = _with_readings(db_path)
    stored = _store(db_path, lambda conn: list_readings(conn, meter))[1]

    response = client.post(
        f"/utilities/readings/{stored.id}/edit", data={"date": "2026-01-11", "value": "abc"}
    )

    _error(response)
    page = soup(response)
    assert _input(page, f"#reading-{stored.id}-edit input[name=value]") == "abc"
    assert page.select_one(f"#reading-{stored.id}-edit").find_parent("details").has_attr("open")


# Exchanges


def test_add_edit_and_delete_an_exchange(client, db_path):
    meter = _electricity_meter(db_path)
    _store(db_path, lambda conn: add_reading(conn, meter, Reading(date(2026, 1, 1), 1_000)))

    added = client.post(
        f"/utilities/meters/{meter}/exchanges",
        data={"date": "2026-02-01", "old_final": "1500", "new_start": "0,5"},
    )

    assert added.status_code == 303
    stored = _store(db_path, lambda conn: list_exchanges(conn, meter))
    assert [s.item for s in stored] == [Exchange(date(2026, 2, 1), 1_500_000, 500)]

    form = _page(client, meter).select_one(f"#exchange-{stored[0].id}-edit")
    assert form.select_one("input[name=old_final]")["value"] == "1500.000"
    edited = client.post(
        form["action"], data={"date": "2026-02-02", "old_final": "1600", "new_start": "0"}
    )
    assert edited.status_code == 303
    after = _store(db_path, lambda conn: list_exchanges(conn, meter))
    assert [s.item for s in after] == [Exchange(date(2026, 2, 2), 1_600_000, 0)]

    deleted = client.post(f"/utilities/exchanges/{stored[0].id}/delete")
    assert deleted.status_code == 303
    assert _store(db_path, lambda conn: list_exchanges(conn, meter)) == []


def test_an_exchange_on_a_reading_date_is_a_400(client, db_path):
    meter = _with_readings(db_path)

    response = client.post(
        f"/utilities/meters/{meter}/exchanges",
        data={"date": "2026-01-11", "old_final": "1100", "new_start": "0"},
    )

    assert "2026-01-11" in _error(response)
    assert _input(soup(response), f"#meter-{meter}-add-exchange input[name=old_final]") == "1100"


def test_rejected_delete_of_an_exchange_answers_400_on_the_meter_page(client, db_path):
    meter = _electricity_meter(db_path)
    _store(db_path, lambda conn: add_reading(conn, meter, Reading(date(2026, 1, 1), 1_000_000)))
    exchange = Exchange(date(2026, 1, 6), 1_000_000, 0)
    exchange_id = _store(db_path, lambda conn: add_exchange(conn, meter, exchange))
    _store(db_path, lambda conn: add_reading(conn, meter, Reading(date(2026, 1, 11), 100_000)))

    response = client.post(f"/utilities/exchanges/{exchange_id}/delete")

    assert "drops on 2026-01-11" in _error(response)
    assert soup(response).select_one(f"#meter-{meter}-history-card") is not None
    assert len(_store(db_path, lambda conn: list_exchanges(conn, meter))) == 1


def test_rejected_delete_of_a_reading_answers_400_on_the_meter_page(client, db_path):
    meter = _electricity_meter(db_path)
    # A series that already drops (written around the store) rejects every later delete.
    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            "INSERT INTO utility_readings (meter_id, reading_date, value_milli) VALUES (?, ?, ?)",
            [
                (meter, "2026-01-01", 1_000_000),
                (meter, "2026-01-11", 500_000),
                (meter, "2026-01-21", 2_000_000),
            ],
        )
        conn.commit()
    finally:
        conn.close()
    last = _store(db_path, lambda conn: list_readings(conn, meter))[-1]

    response = client.post(f"/utilities/readings/{last.id}/delete")

    assert "drops on 2026-01-11" in _error(response)
    assert soup(response).select_one(f"#meter-{meter}-history-card") is not None
    assert len(_store(db_path, lambda conn: list_readings(conn, meter))) == 3


# Billing periods

NEW_PERIOD = {
    "start_date": "2027-01-01",
    "settlement_date": "2027-12-31",
    "base_fee": "12,50",
    "unit_price": "31.5",
    "state_factor": "",
    "calorific_value": "",
    "advance": "60",
    "expected_usage": "3100",
    "category": "Utilities",
}


def test_add_edit_and_delete_a_period(client, db_path):
    meter = _electricity_meter(db_path)

    added = client.post(f"/utilities/meters/{meter}/periods", data=NEW_PERIOD)

    assert added.status_code == 303
    stored = _store(db_path, lambda conn: list_periods(conn, meter))
    assert [s.item for s in stored] == [
        _period(
            start_date=date(2027, 1, 1),
            settlement_date=date(2027, 12, 31),
            base_fee_cents=1_250,
            unit_price_micro=315_000,
            advance_cents=6_000,
            expected_usage=3_100,
        )
    ]

    form = _page(client, meter).select_one(f"#period-{stored[0].id}-edit")
    assert form.select_one("input[name=unit_price]")["value"] == "31.5000"
    assert form.select_one("input[name=base_fee]")["value"] == "12.50"
    edited = client.post(form["action"], data={**NEW_PERIOD, "unit_price": "32", "category": ""})
    assert edited.status_code == 303
    after = _store(db_path, lambda conn: list_periods(conn, meter))[0].item
    assert (after.unit_price_micro, after.category) == (320_000, None)

    deleted = client.post(f"/utilities/periods/{stored[0].id}/delete")
    assert deleted.status_code == 303
    assert _store(db_path, lambda conn: list_periods(conn, meter)) == []


@pytest.mark.parametrize(
    ("typed", "stored"),
    [("-31,69", -3_169), ("31.69", 3_169), ("0", 0), ("", None)],
)
def test_settled_amount_is_stored_signed_on_create_and_edit(client, db_path, typed, stored):
    meter = _electricity_meter(db_path)

    created = client.post(
        f"/utilities/meters/{meter}/periods", data={**NEW_PERIOD, "settled": typed}
    )

    assert created.status_code == 303
    period = _store(db_path, lambda conn: list_periods(conn, meter))[0]
    assert period.item.settled_cents == stored
    edited = client.post(
        f"/utilities/periods/{period.id}/edit", data={**NEW_PERIOD, "settled": "-5,00"}
    )
    assert edited.status_code == 303
    after = _store(db_path, lambda conn: list_periods(conn, meter))[0].item
    assert after.settled_cents == -500
    cleared = client.post(
        f"/utilities/periods/{period.id}/edit", data={**NEW_PERIOD, "settled": ""}
    )
    assert cleared.status_code == 303
    assert _store(db_path, lambda conn: list_periods(conn, meter))[0].item.settled_cents is None


def test_an_invalid_settled_amount_is_a_400_that_keeps_the_value(client, db_path):
    meter = _electricity_meter(db_path)

    response = client.post(
        f"/utilities/meters/{meter}/periods", data={**NEW_PERIOD, "settled": "abc"}
    )

    assert "Settled amount" in _error(response)
    form = soup(response).select_one(f"#meter-{meter}-new-period")
    assert form.select_one("input[name=settled]")["value"] == "abc"
    assert _store(db_path, lambda conn: list_periods(conn, meter)) == []


def test_the_edit_form_prefills_the_settled_amount_and_new_period_leaves_it_empty(client, db_path):
    meter = _electricity_meter(db_path)
    period = _store(db_path, lambda conn: add_period(conn, meter, _period(settled_cents=-3_169)))

    page = _page(client, meter)

    assert _input(page, f"#period-{period}-edit input[name=settled]") == "-31.69"
    assert _input(page, f"#meter-{meter}-new-period input[name=settled]") == ""


def test_the_period_list_shows_the_settled_amount(client, db_path):
    meter = _electricity_meter(db_path)
    _store(db_path, lambda conn: add_period(conn, meter, _period(settled_cents=-3_169)))

    row = _page(client, meter).select_one(f"#meter-{meter}-periods [data-row]")

    assert cents(row.select_one('[data-field="settled"]')) == -3_169


def test_the_period_list_shows_a_dash_without_a_settled_amount(client, db_path):
    meter = _electricity_meter(db_path)
    _store(db_path, lambda conn: add_period(conn, meter, _period()))

    row = _page(client, meter).select_one(f"#meter-{meter}-periods [data-row]")

    assert text(row.select_one('[data-field="settled"]')) == "–"


def test_a_gas_period_takes_the_state_factor_and_calorific_value(client, db_path):
    meter = _gas_meter(db_path)

    response = client.post(
        f"/utilities/meters/{meter}/periods",
        data={**NEW_PERIOD, "state_factor": "0,95", "calorific_value": "11.0"},
    )

    assert response.status_code == 303
    period = _store(db_path, lambda conn: list_periods(conn, meter))[0].item
    assert (period.state_factor_e4, period.calorific_value_e4) == (9_500, 110_000)


def test_an_electricity_period_form_has_no_gas_fields(client, db_path):
    meter = _electricity_meter(db_path)
    page = _page(client, meter)

    form = page.select_one(f"#meter-{meter}-new-period")
    assert form.select_one("input[name=state_factor]") is None
    assert form.select_one("input[name=unit_price]") is not None


def test_a_bad_price_is_a_400_that_keeps_every_entry(client, db_path):
    meter = _electricity_meter(db_path)

    response = client.post(
        f"/utilities/meters/{meter}/periods", data={**NEW_PERIOD, "unit_price": "12.34567"}
    )

    assert "Unit price" in _error(response)
    form = soup(response).select_one(f"#meter-{meter}-new-period")
    assert form.select_one("input[name=unit_price]")["value"] == "12.34567"
    assert form.select_one("input[name=advance]")["value"] == "60"
    assert _store(db_path, lambda conn: list_periods(conn, meter)) == []


def test_a_negative_expected_usage_shows_a_friendly_error(client, db_path):
    meter = _electricity_meter(db_path)

    response = client.post(
        f"/utilities/meters/{meter}/periods", data={**NEW_PERIOD, "expected_usage": "-1"}
    )

    assert _error(response) == "Expected usage must not be negative."


def test_a_gas_period_without_a_state_factor_is_a_400(client, db_path):
    meter = _gas_meter(db_path)

    response = client.post(f"/utilities/meters/{meter}/periods", data=NEW_PERIOD)

    assert "State factor" in _error(response)


def test_an_overlapping_period_is_a_400(client, db_path):
    meter = _with_readings(db_path)

    response = client.post(
        f"/utilities/meters/{meter}/periods", data={**NEW_PERIOD, "start_date": "2026-06-01"}
    )

    assert "overlaps" in _error(response)


def test_the_new_period_form_is_prefilled_from_the_latest_period(client, db_path):
    meter = _with_readings(db_path)

    form = _page(client, meter).select_one(f"#meter-{meter}-new-period")

    def value(name: str) -> str:
        return form.select_one(f"input[name={name}]")["value"]

    assert value("start_date") == "2027-01-01"
    assert value("settlement_date") == "2027-12-31"
    assert value("base_fee") == "12.00"
    assert value("unit_price") == "3.0000"
    assert value("advance") == "50.00"
    assert value("expected_usage") == "3000"
    assert form.select_one("select[name=category] option[selected]")["value"] == "Utilities"


def test_category_choices_are_the_categories(client, db_path):
    meter = _electricity_meter(db_path)

    form = _page(client, meter).select_one(f"#meter-{meter}-new-period")

    assert [o["value"] for o in form.select("select[name=category] option")] == [
        "",
        "Utilities",
        "Dining",
    ]


def test_the_new_period_form_is_empty_without_a_period(client, db_path):
    meter = _electricity_meter(db_path)

    form = _page(client, meter).select_one(f"#meter-{meter}-new-period")

    assert form.select_one("input[name=start_date]")["value"] == ""


# Meter page


def test_the_meter_page_lists_readings_newest_first(client, db_path):
    meter = _with_readings(db_path)

    response = client.get(f"/utilities/meters/{meter}")

    assert response.status_code == 200
    rows = soup(response).select(f"#meter-{meter}-readings tbody [data-row]")
    assert [row.select_one("time")["datetime"] for row in rows] == ["2026-01-11", "2026-01-01"]


def test_an_unknown_meter_is_a_404(client):
    response = client.get("/utilities/meters/99")

    assert response.status_code == 404
    assert soup(response).select_one("#error-page") is not None


def test_the_meter_page_keeps_utilities_current_in_the_nav_and_links_back(client, db_path):
    meter = _gas_meter(db_path)

    page = _page(client, meter)

    current = [a["href"] for a in page.select('nav a[aria-current="page"]')]
    assert current == ["/utilities"]
    assert page.select_one("#back-to-utilities")["href"] == "/utilities"


def test_the_meter_page_has_the_exchange_and_period_lists_with_their_forms(client, db_path):
    meter = _with_readings(db_path)
    client.post(
        f"/utilities/meters/{meter}/exchanges",
        data={"date": "2026-02-01", "old_final": "1500", "new_start": "0"},
    )
    page = _page(client, meter)

    assert len(page.select(f"#meter-{meter}-exchanges [data-row]")) == 1
    assert len(page.select(f"#meter-{meter}-periods [data-row]")) == 1
    assert page.select_one(f"#meter-{meter}-add-exchange") is not None
    assert page.select_one(f"#meter-{meter}-new-period") is not None
    assert page.select_one(f"#meter-{meter}-add-reading") is None


def test_the_meter_page_edits_redirect_to_the_meter_page(client, db_path):
    meter = _with_readings(db_path)
    reading = _store(db_path, lambda conn: list_readings(conn, meter))[0]
    period = _store(db_path, lambda conn: list_periods(conn, meter))[0]
    exchange = client.post(
        f"/utilities/meters/{meter}/exchanges",
        data={"date": "2026-02-01", "old_final": "1500", "new_start": "0"},
    )
    exchange_id = _store(db_path, lambda conn: list_exchanges(conn, meter))[0].id
    back = f"/utilities/meters/{meter}"

    assert exchange.headers["location"] == back
    responses = [
        client.post(
            f"/utilities/readings/{reading.id}/edit", data={"date": "2026-01-01", "value": "1000"}
        ),
        client.post(f"/utilities/periods/{period.id}/edit", data=NEW_PERIOD),
        client.post(
            f"/utilities/exchanges/{exchange_id}/edit",
            data={"date": "2026-02-01", "old_final": "1500", "new_start": "1"},
        ),
        client.post(f"/utilities/exchanges/{exchange_id}/delete"),
        client.post(f"/utilities/readings/{reading.id}/delete"),
        client.post(
            f"/utilities/meters/{meter}/periods",
            data={**NEW_PERIOD, "start_date": "2028-01-01", "settlement_date": "2028-12-31"},
        ),
        client.post(f"/utilities/periods/{period.id}/delete"),
    ]
    assert [(r.status_code, r.headers["location"]) for r in responses] == [(303, back)] * 7


def test_an_invalid_reading_edit_re_renders_the_meter_page(client, db_path):
    meter = _with_readings(db_path)
    reading = _store(db_path, lambda conn: list_readings(conn, meter))[0]

    response = client.post(
        f"/utilities/readings/{reading.id}/edit", data={"date": "2026-01-01", "value": "abc"}
    )

    assert "Reading" in _error(response)
    page = soup(response)
    assert page.select_one(f"#meter-{meter}-readings") is not None
    assert page.select_one("#back-to-utilities") is not None
    assert _input(page, f"#reading-{reading.id}-edit input[name=value]") == "abc"


def test_an_invalid_exchange_edit_re_renders_the_meter_page(client, db_path):
    meter = _with_readings(db_path)
    client.post(
        f"/utilities/meters/{meter}/exchanges",
        data={"date": "2026-02-01", "old_final": "1500", "new_start": "0"},
    )
    exchange = _store(db_path, lambda conn: list_exchanges(conn, meter))[0]

    response = client.post(
        f"/utilities/exchanges/{exchange.id}/edit",
        data={"date": "2026-02-01", "old_final": "x", "new_start": "0"},
    )

    assert "Old meter final" in _error(response)
    page = soup(response)
    assert page.select_one("#back-to-utilities") is not None
    assert _input(page, f"#exchange-{exchange.id}-edit input[name=old_final]") == "x"


def test_an_invalid_period_edit_re_renders_the_meter_page(client, db_path):
    meter = _with_readings(db_path)
    period = _store(db_path, lambda conn: list_periods(conn, meter))[0]

    response = client.post(
        f"/utilities/periods/{period.id}/edit", data={**NEW_PERIOD, "unit_price": "12.34567"}
    )

    assert "Unit price" in _error(response)
    page = soup(response)
    assert page.select_one("#back-to-utilities") is not None
    assert _input(page, f"#period-{period.id}-edit input[name=unit_price]") == "12.34567"


def test_an_invalid_new_period_re_renders_the_meter_page(client, db_path):
    meter = _electricity_meter(db_path)

    response = client.post(
        f"/utilities/meters/{meter}/periods", data={**NEW_PERIOD, "unit_price": "12.34567"}
    )

    assert soup(response).select_one("#back-to-utilities")["href"] == "/utilities"


def test_a_missing_record_on_the_meter_page_routes_is_a_404(client):
    for path in (
        "/utilities/readings/99/edit",
        "/utilities/exchanges/99/edit",
        "/utilities/periods/99/edit",
        "/utilities/readings/99/delete",
        "/utilities/exchanges/99/delete",
        "/utilities/periods/99/delete",
    ):
        assert client.post(path, data={"date": "2026-01-01"}).status_code == 404
