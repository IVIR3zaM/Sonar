"""Tests for the meter page (SPEC §13 Utilities): readings, exchanges and billing periods."""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest
from fastapi.testclient import TestClient

from sonar.categorization.store import add_category
from sonar.db import connect
from sonar.recurring.schedule import SchedulePeriod
from sonar.recurring.store import add_manual
from sonar.utilities.model import BillingPeriod, Charge, Exchange, Meter, Reading
from sonar.utilities.store import (
    add_exchange,
    add_meter,
    add_period,
    add_reading,
    list_exchanges,
    list_periods,
    list_readings,
    list_zeroed,
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


def _water_meter(db_path) -> int:
    return _store(db_path, lambda conn: add_meter(conn, Meter("Water", "water")))


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
    "advance_mode": "flexible",
    "advance_dates": "",
    "settlement_debit_days": "0",
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


def test_a_flexible_gas_period_row_reads_like_the_rest_of_the_app(client, db_path):
    meter = _gas_meter(db_path)
    period = _period(
        unit_price_micro=93_800,
        state_factor_e4=9_653,
        calorific_value_e4=115_000,
        settlement_debit_days=1,
    )
    _store(db_path, lambda conn: add_period(conn, meter, period))

    row = _page(client, meter).select_one(f"#meter-{meter}-periods [data-row]")

    assert text(row.select_one('[data-field="unit_price"]')) == "9,38 ct/kWh"
    assert text(row.select_one('[data-field="state_factor"]')) == "0,9653"
    assert text(row.select_one('[data-field="calorific_value"]')) == "11,50 kWh/m³"
    mode = row.select_one('[data-field="advance_mode"]')
    assert (text(mode), mode["data-mode"]) == ("Flexible", "flexible")
    dates = row.select_one('[data-field="advance_dates"]')
    assert text(dates) == "–"
    assert dates.select_one("time") is None
    debit = row.select_one('[data-field="settlement_debit_days"]')
    assert (text(debit), debit["data-days"]) == ("1 day after settlement", "1")


def test_a_period_debited_on_the_settlement_date_says_so(client, db_path):
    meter = _electricity_meter(db_path)
    _store(db_path, lambda conn: add_period(conn, meter, _period(settlement_debit_days=0)))

    row = _page(client, meter).select_one(f"#meter-{meter}-periods [data-row]")

    debit = row.select_one('[data-field="settlement_debit_days"]')
    assert (text(debit), debit["data-days"]) == ("On the settlement date", "0")


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


# Water periods, advance modes and debit days

WATER_PERIOD = {
    "start_date": "2026-01-01",
    "settlement_date": "2026-12-31",
    "drinking_price": "114",
    "drinking_base_fee": "36.00",
    "drinking_vat": "7",
    "wastewater_price": "369",
    "wastewater_base_fee": "96.00",
    "wastewater_vat": "0",
    "advance_mode": "schedule",
    "advance_dates": "2026-04-15, 2026-06-15 2026-08-15,2026-10-15 2026-12-15",
    "advance": "240.00",
    "expected_usage": "150",
    "settlement_debit_days": "55",
    "category": "Utilities",
}
WATER_DATES = (
    date(2026, 4, 15),
    date(2026, 6, 15),
    date(2026, 8, 15),
    date(2026, 10, 15),
    date(2026, 12, 15),
)


def _water_period(**changes) -> BillingPeriod:
    values = {
        "start_date": date(2026, 1, 1),
        "settlement_date": date(2026, 12, 31),
        "base_fee_cents": None,
        "unit_price_micro": None,
        "state_factor_e4": None,
        "calorific_value_e4": None,
        "advance_cents": 24_000,
        "expected_usage": 150,
        "category": "Utilities",
        "drinking": Charge(1_140_000, 3_600, 7),
        "wastewater": Charge(3_690_000, 9_600, 0),
        "advance_mode": "schedule",
        "advance_dates": WATER_DATES,
        "settlement_debit_days": 55,
    }
    return BillingPeriod(**{**values, **changes})


def test_a_water_period_is_created_listed_and_edited(client, db_path):
    meter = _water_meter(db_path)

    added = client.post(f"/utilities/meters/{meter}/periods", data=WATER_PERIOD)

    assert added.status_code == 303
    [stored] = _store(db_path, lambda conn: list_periods(conn, meter))
    assert stored.item == _water_period()
    page = _page(client, meter)
    row = page.select_one(f"#meter-{meter}-periods [data-row]")
    mode = row.select_one('[data-field="advance_mode"]')
    assert text(mode) == "Supplier schedule"
    assert mode["data-mode"] == "schedule"
    dates = row.select_one('[data-field="advance_dates"]')
    assert [t["datetime"] for t in dates.select("time")] == [
        "2026-04-15",
        "2026-06-15",
        "2026-08-15",
        "2026-10-15",
        "2026-12-15",
    ]
    debit = row.select_one('[data-field="settlement_debit_days"]')
    assert text(debit) == "55 days after settlement"
    assert debit["data-days"] == "55"
    drinking = row.select_one('[data-charge="drinking"]')
    assert text(drinking.select_one('[data-field="price"]')) == "114,00 ct/m³"
    assert cents(drinking.select_one('[data-field="base_fee"]')) == 3_600
    assert text(drinking.select_one('[data-field="vat"]')) == "7 %"
    wastewater = row.select_one('[data-charge="wastewater"]')
    assert text(wastewater.select_one('[data-field="price"]')) == "369,00 ct/m³"
    assert cents(wastewater.select_one('[data-field="base_fee"]')) == 9_600
    assert text(wastewater.select_one('[data-field="vat"]')) == "0 %"
    assert row.select_one('[data-field="unit_price"]') is None
    assert text(row.select_one('[data-field="expected_usage"]')) == "150 m³"

    form = page.select_one(f"#period-{stored.id}-edit")
    assert form.select_one("input[name=base_fee]") is None
    assert form.select_one("input[name=unit_price]") is None
    assert _input(form, "[data-charge=drinking] input[name=drinking_price]") == "114.0000"
    assert _input(form, "[data-charge=wastewater] input[name=wastewater_base_fee]") == "96.00"
    assert _input(form, "input[name=advance_dates]") == (
        "2026-04-15, 2026-06-15, 2026-08-15, 2026-10-15, 2026-12-15"
    )
    assert form.select_one("select[name=advance_mode] option[selected]")["value"] == "schedule"
    assert _input(form, "input[name=settlement_debit_days]") == "55"
    edited = client.post(
        form["action"],
        data={
            **WATER_PERIOD,
            "drinking_vat": "19",
            "advance_mode": "flexible",
            "advance_dates": "",
        },
    )
    assert edited.status_code == 303
    after = _store(db_path, lambda conn: list_periods(conn, meter))[0].item
    assert after == _water_period(
        drinking=Charge(1_140_000, 3_600, 19), advance_mode="flexible", advance_dates=()
    )


@pytest.mark.parametrize(
    ("change", "message", "name", "typed"),
    [
        (
            {"advance_dates": "2026-04-15, soon"},
            "Scheduled advance dates: enter dates like 2026-04-15, 2026-06-15",
            "advance_dates",
            "2026-04-15, soon",
        ),
        ({"drinking_price": ""}, "Drinking water price:", "drinking_price", ""),
        (
            {"wastewater_vat": "101"},
            "Wastewater VAT must be 0 to 100 percent.",
            "wastewater_vat",
            "101",
        ),
    ],
)
def test_a_bad_water_entry_is_a_400_that_keeps_every_entry(
    client, db_path, change, message, name, typed
):
    meter = _water_meter(db_path)

    response = client.post(f"/utilities/meters/{meter}/periods", data={**WATER_PERIOD, **change})

    assert message in _error(response)
    form = soup(response).select_one(f"#meter-{meter}-new-period")
    assert _input(form, f"input[name={name}]") == typed
    assert _input(form, "input[name=wastewater_price]") == change.get("wastewater_price", "369")
    assert _store(db_path, lambda conn: list_periods(conn, meter)) == []


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"advance_dates": ""}, "Enter at least one scheduled advance date."),
        (
            {"advance_dates": "2027-06-01"},
            "Scheduled advance dates must fall between the start date "
            "and 14 days after the settlement date.",
        ),
        ({"settlement_debit_days": "366"}, "Settlement debit days must be 0 to 365."),
        ({"drinking_price": "0"}, "Drinking water price must be positive."),
        ({"wastewater_base_fee": "-1"}, "Wastewater base fee must not be negative."),
    ],
)
def test_the_new_model_errors_have_plain_sentences(client, db_path, change, message):
    meter = _water_meter(db_path)

    response = client.post(f"/utilities/meters/{meter}/periods", data={**WATER_PERIOD, **change})

    assert _error(response) == message


def test_a_gas_and_an_electricity_period_take_mode_dates_and_debit_days(client, db_path):
    meter = _electricity_meter(db_path)
    data = {
        **NEW_PERIOD,
        "advance_mode": "schedule",
        "advance_dates": "2027-02-15 2027-03-15",
        "settlement_debit_days": "30",
    }

    response = client.post(f"/utilities/meters/{meter}/periods", data=data)

    assert response.status_code == 303
    period = _store(db_path, lambda conn: list_periods(conn, meter))[0].item
    assert period.advance_mode == "schedule"
    assert period.advance_dates == (date(2027, 2, 15), date(2027, 3, 15))
    assert period.settlement_debit_days == 30
    form = _page(client, meter).select_one(f"#meter-{meter}-new-period")
    assert form.select_one("[data-charge]") is None
    assert form.select_one("input[name=drinking_price]") is None
    row = _page(client, meter).select_one(f"#meter-{meter}-periods [data-row]")
    mode = row.select_one('[data-field="advance_mode"]')
    assert text(mode) == "Supplier schedule"
    assert mode["data-mode"] == "schedule"
    dates = row.select_one('[data-field="advance_dates"]')
    assert [t["datetime"] for t in dates.select("time")] == ["2027-02-15", "2027-03-15"]
    debit = row.select_one('[data-field="settlement_debit_days"]')
    assert text(debit) == "30 days after settlement"
    assert debit["data-days"] == "30"


def test_the_new_period_form_defaults_to_flexible_and_zero_debit_days(client, db_path):
    meter = _electricity_meter(db_path)

    form = _page(client, meter).select_one(f"#meter-{meter}-new-period")

    assert form.select_one("select[name=advance_mode] option[selected]")["value"] == "flexible"
    assert _input(form, "input[name=settlement_debit_days]") == "0"
    assert _input(form, "input[name=advance_dates]") == ""


def test_start_new_period_copies_the_water_period_and_moves_dates_a_year(client, db_path):
    meter = _water_meter(db_path)
    _store(db_path, lambda conn: add_period(conn, meter, _water_period()))

    form = _page(client, meter).select_one(f"#meter-{meter}-new-period")

    assert _input(form, "input[name=start_date]") == "2027-01-01"
    assert _input(form, "input[name=advance_dates]") == (
        "2027-04-15, 2027-06-15, 2027-08-15, 2027-10-15, 2027-12-15"
    )
    assert form.select_one("select[name=advance_mode] option[selected]")["value"] == "schedule"
    assert _input(form, "input[name=drinking_price]") == "114.0000"
    assert _input(form, "input[name=drinking_base_fee]") == "36.00"
    assert _input(form, "input[name=drinking_vat]") == "7"
    assert _input(form, "input[name=wastewater_price]") == "369.0000"
    assert _input(form, "input[name=settlement_debit_days]") == "55"
    assert _input(form, "input[name=expected_usage]") == "150"


def test_usage_units_say_m3_for_water_and_kwh_for_the_others(client, db_path):
    water = _water_meter(db_path)
    power = _with_readings(db_path)
    _store(db_path, lambda conn: add_period(conn, water, _water_period()))
    for day, value in ((date(2026, 1, 1), 1_000), (date(2026, 1, 11), 2_000)):
        _store(db_path, lambda conn, d=day, v=value: add_reading(conn, water, Reading(d, v)))

    water_page = _page(client, water)
    power_page = _page(client, power)

    assert "m³ per day" in text(water_page.select_one(f"#meter-{water}-readings thead"))
    assert "kWh per day" in text(power_page.select_one(f"#meter-{power}-readings thead"))
    assert "m³" in text(
        water_page.select_one(f"#meter-{water}-new-period label[for$=expected-usage]")
    )
    assert "kWh" in text(
        power_page.select_one(f"#meter-{power}-new-period label[for$=expected-usage]")
    )
    power_row = power_page.select_one(f"#meter-{power}-periods [data-row]")
    assert text(power_row.select_one('[data-field="expected_usage"]')) == "3000 kWh"


# Garden meter fee (D10)


def test_a_water_period_stores_the_garden_fee_and_prefills_it_on_edit(client, db_path):
    meter = _water_meter(db_path)

    added = client.post(
        f"/utilities/meters/{meter}/periods", data={**WATER_PERIOD, "garden_fee": "12.00"}
    )

    assert added.status_code == 303
    [stored] = _store(db_path, lambda conn: list_periods(conn, meter))
    assert stored.item == _water_period(garden_fee_cents=1_200)
    page = _page(client, meter)
    assert _input(page, f"#period-{stored.id}-edit input[name=garden_fee]") == "12.00"


def test_a_water_period_without_a_garden_fee_stores_none(client, db_path):
    meter = _water_meter(db_path)

    client.post(f"/utilities/meters/{meter}/periods", data={**WATER_PERIOD, "garden_fee": ""})

    [stored] = _store(db_path, lambda conn: list_periods(conn, meter))
    assert stored.item.garden_fee_cents is None
    page = _page(client, meter)
    assert _input(page, f"#period-{stored.id}-edit input[name=garden_fee]") == ""


def test_only_the_water_period_form_has_the_garden_fee(client, db_path):
    water = _water_meter(db_path)
    power = _electricity_meter(db_path)

    form = _page(client, water).select_one(f"#meter-{water}-new-period")
    assert "per year, net" in text(form.select_one("label[for$=garden-fee]"))
    assert form.select_one("input[name=garden_fee]") is not None
    assert _page(client, power).select_one("input[name=garden_fee]") is None


@pytest.mark.parametrize(
    ("typed", "message"),
    [
        ("lots", "Garden meter fee: enter a number like 1234.56 or -250.50"),
        ("-1.00", "garden fee must not be negative"),
    ],
)
def test_a_bad_garden_fee_is_a_400_that_keeps_the_entry(client, db_path, typed, message):
    meter = _water_meter(db_path)

    response = client.post(
        f"/utilities/meters/{meter}/periods", data={**WATER_PERIOD, "garden_fee": typed}
    )

    assert message in _error(response)
    form = soup(response).select_one(f"#meter-{meter}-new-period")
    assert _input(form, "input[name=garden_fee]") == typed
    assert _store(db_path, lambda conn: list_periods(conn, meter)) == []


def test_start_new_period_copies_the_garden_fee(client, db_path):
    meter = _water_meter(db_path)
    _store(db_path, lambda conn: add_period(conn, meter, _water_period(garden_fee_cents=1_200)))

    form = _page(client, meter).select_one(f"#meter-{meter}-new-period")

    assert _input(form, "input[name=garden_fee]") == "12.00"
    assert _input(form, "input[name=start_date]") == "2027-01-01"


# Garden meter page (SPEC §13 Utilities: garden conflicts)


def _garden_pair(db_path, closing_exchange: bool = False) -> tuple[int, int]:
    """A main at 100 m³ and a garden at 65 m³: one case 2026-06-01 to 2026-10-01, 2.991 m³ over."""
    main = _water_meter(db_path)
    for day, milli in ((date(2026, 3, 1), 0), (date(2026, 10, 1), 100_000)):
        _store(db_path, lambda conn, d=day, v=milli: add_reading(conn, main, Reading(d, v)))
    garden = _store(db_path, lambda conn: add_meter(conn, Meter("Garden", "water", main)))
    readings = [(date(2026, 3, 1), 0), (date(2026, 6, 1), 5_000)]
    if not closing_exchange:
        readings.append((date(2026, 10, 1), 65_000))
    for day, milli in readings:
        _store(db_path, lambda conn, d=day, v=milli: add_reading(conn, garden, Reading(d, v)))
    if closing_exchange:
        exchange = Exchange(date(2026, 10, 1), 65_000, 0)
        _store(db_path, lambda conn: add_exchange(conn, garden, exchange))
    return main, garden


def _closing_reading_id(db_path, garden: int) -> int:
    readings = _store(db_path, lambda conn: list_readings(conn, garden))
    return next(r.id for r in readings if r.item.reading_date == date(2026, 10, 1))


def test_the_garden_page_lists_its_open_case_with_the_three_choices(client, db_path):
    _, garden = _garden_pair(db_path)
    reading = _closing_reading_id(db_path, garden)

    cases = _page(client, garden).select("[data-conflict]")

    assert len(cases) == 1
    case = cases[0]
    assert (case["data-start"], case["data-end"]) == ("2026-06-01", "2026-10-01")
    assert case.select_one('[data-field="excess"]')["data-milli"] == "2991"
    assert text(case.select_one('[data-field="excess"]')) == "2.991"
    assert [form["data-action"] for form in case.select("form[data-action]")] == [
        "zero",
        "reject",
        "exchange",
    ]
    assert case.select_one('[data-action="zero"]')["action"] == (
        f"/utilities/meters/{garden}/conflicts/zero"
    )
    assert _input(case, '[data-action="zero"] input[name=start_date]') == "2026-06-01"
    assert _input(case, '[data-action="zero"] input[name=end_date]') == "2026-10-01"
    assert case.select_one('[data-action="reject"]')["action"] == (
        f"/utilities/readings/{reading}/delete"
    )
    assert case.select_one('[data-action="exchange"]')["action"] == (
        f"/utilities/readings/{reading}/exchange"
    )


def test_the_garden_page_links_its_main_and_has_no_periods(client, db_path):
    main, garden = _garden_pair(db_path)

    page = _page(client, garden)

    assert page.select_one("#main-meter-link")["href"] == f"/utilities/meters/{main}"
    assert page.select_one("[data-period-id]") is None
    assert page.select_one(f"#meter-{garden}-new-period") is None
    assert page.select_one(f"#meter-{garden}-periods") is None
    assert [row["data-reading-id"] for row in page.select("[data-reading-id]")]
    assert page.select_one(f"#meter-{garden}-chart, #meter-{garden}-chart-empty") is not None
    assert page.select_one(f"#meter-{garden}-add-exchange") is not None


def test_a_garden_below_its_main_lists_no_case(client, db_path):
    main = _water_meter(db_path)
    _store(db_path, lambda conn: add_reading(conn, main, Reading(date(2026, 3, 1), 0)))
    _store(db_path, lambda conn: add_reading(conn, main, Reading(date(2026, 10, 1), 100_000)))
    garden = _store(db_path, lambda conn: add_meter(conn, Meter("Garden", "water", main)))
    _store(db_path, lambda conn: add_reading(conn, garden, Reading(date(2026, 3, 1), 0)))
    _store(db_path, lambda conn: add_reading(conn, garden, Reading(date(2026, 10, 1), 20_000)))

    assert _page(client, garden).select_one("[data-conflict]") is None


def test_zero_it_out_resolves_the_case(client, db_path):
    _, garden = _garden_pair(db_path)

    response = client.post(
        f"/utilities/meters/{garden}/conflicts/zero",
        data={"start_date": "2026-06-01", "end_date": "2026-10-01"},
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/utilities/meters/{garden}"
    assert _store(db_path, lambda conn: list_zeroed(conn, garden)) == [
        (date(2026, 6, 1), date(2026, 10, 1))
    ]
    assert _page(client, garden).select_one("[data-conflict]") is None


def test_a_bad_zero_date_is_a_400_on_the_garden_page(client, db_path):
    _, garden = _garden_pair(db_path)

    response = client.post(
        f"/utilities/meters/{garden}/conflicts/zero",
        data={"start_date": "soon", "end_date": "2026-10-01"},
    )

    assert "Start" in _error(response)
    assert _store(db_path, lambda conn: list_zeroed(conn, garden)) == []


def test_zeroing_a_meter_that_does_not_exist_is_a_404(client):
    response = client.post(
        "/utilities/meters/999/conflicts/zero",
        data={"start_date": "2026-06-01", "end_date": "2026-10-01"},
    )

    assert response.status_code == 404


def test_reject_the_reading_posts_to_the_delete_route(client, db_path):
    _, garden = _garden_pair(db_path)
    case = _page(client, garden).select_one("[data-conflict]")

    response = client.post(case.select_one('[data-action="reject"]')["action"])

    assert response.status_code == 303
    assert response.headers["location"] == f"/utilities/meters/{garden}"
    assert _store(
        db_path, lambda conn: [r.item.value_milli for r in list_readings(conn, garden)]
    ) == [
        0,
        5_000,
    ]
    assert _page(client, garden).select_one("[data-conflict]") is None


def test_record_as_exchange_turns_the_closing_reading_into_an_exchange(client, db_path):
    _, garden = _garden_pair(db_path)
    reading = _closing_reading_id(db_path, garden)

    response = client.post(f"/utilities/readings/{reading}/exchange", data={"old_final": "5.000"})

    assert response.status_code == 303
    assert response.headers["location"] == f"/utilities/meters/{garden}"
    exchanges = _store(db_path, lambda conn: list_exchanges(conn, garden))
    assert [e.item for e in exchanges] == [Exchange(date(2026, 10, 1), 5_000, 65_000)]
    page = _page(client, garden)
    assert page.select_one("[data-conflict]") is None
    assert [row["data-exchange-id"] for row in page.select("[data-exchange-id]")] == [
        str(exchanges[0].id)
    ]
    assert page.select_one(f'[data-reading-id="{reading}"]') is None


def test_an_old_final_below_the_previous_reading_is_a_400_with_the_form_open(client, db_path):
    _, garden = _garden_pair(db_path)
    reading = _closing_reading_id(db_path, garden)

    response = client.post(f"/utilities/readings/{reading}/exchange", data={"old_final": "4.000"})

    assert "drops" in _error(response)
    page = soup(response)
    form = page.select_one(f"#reading-{reading}-exchange")
    assert form.find_parent("details").has_attr("open")
    assert _input(form, "input[name=old_final]") == "4.000"
    assert _store(db_path, lambda conn: list_exchanges(conn, garden)) == []
    assert len(page.select("[data-conflict]")) == 1


def test_an_unreadable_old_final_is_a_400_that_keeps_the_entry(client, db_path):
    _, garden = _garden_pair(db_path)
    reading = _closing_reading_id(db_path, garden)

    response = client.post(f"/utilities/readings/{reading}/exchange", data={"old_final": "lots"})

    assert "Old meter final" in _error(response)
    assert _input(soup(response), f"#reading-{reading}-exchange input[name=old_final]") == "lots"


def test_a_case_closed_by_an_exchange_offers_only_zero_and_reject(client, db_path):
    _, garden = _garden_pair(db_path, closing_exchange=True)
    exchange = _store(db_path, lambda conn: list_exchanges(conn, garden))[0]

    case = _page(client, garden).select_one("[data-conflict]")

    assert case["data-end"] == "2026-10-01"
    assert [form["data-action"] for form in case.select("form[data-action]")] == ["zero", "reject"]
    assert case.select_one('[data-action="reject"]')["action"] == (
        f"/utilities/exchanges/{exchange.id}/delete"
    )


def test_rejecting_the_closing_exchange_resolves_the_case(client, db_path):
    _, garden = _garden_pair(db_path, closing_exchange=True)
    exchange = _store(db_path, lambda conn: list_exchanges(conn, garden))[0]

    response = client.post(f"/utilities/exchanges/{exchange.id}/delete")

    assert response.headers["location"] == f"/utilities/meters/{garden}"
    assert _page(client, garden).select_one("[data-conflict]") is None


def test_the_main_meter_page_keeps_its_periods_and_shows_no_garden_parts(client, db_path):
    main, _ = _garden_pair(db_path)
    _store(db_path, lambda conn: add_period(conn, main, _water_period()))

    page = _page(client, main)

    assert page.select_one("[data-period-id]") is not None
    assert page.select_one(f"#meter-{main}-new-period") is not None
    assert page.select_one("#main-meter-link") is None
    assert page.select_one("[data-conflict]") is None
    assert page.select_one(f"#meter-{main}-chart, #meter-{main}-chart-empty") is None


# Advance link on the period in force (D19)


def _scheduled_water(**changes) -> BillingPeriod:
    return _period(
        base_fee_cents=None,
        unit_price_micro=None,
        advance_cents=24_000,
        expected_usage=150,
        category="Water",
        drinking=Charge(1_140_000, 3600, 7),
        wastewater=Charge(3_690_000, 9600, 0),
        advance_mode="schedule",
        advance_dates=(date(2026, 6, 15), date(2026, 9, 15), date(2026, 12, 15)),
        **changes,
    )


def _water_with_schedule(db_path, name: str) -> int:
    meter = _store(db_path, lambda conn: add_meter(conn, Meter(name, "water")))
    _store(db_path, lambda conn: add_period(conn, meter, _scheduled_water()))
    return meter


def _bill_payment(db_path) -> int:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT id FROM recurring_payments WHERE name = 'Water bill'").fetchone()
        return row[0]
    finally:
        conn.close()


def test_the_period_in_force_links_to_the_payment_that_pays_its_advances(client, db_path):
    _store(db_path, lambda conn: add_category(conn, "Water", "fixed"))
    water = _water_with_schedule(db_path, "Water")
    _store(
        db_path,
        lambda conn: add_manual(
            conn, "Water bill", "Water", SchedulePeriod(date(2026, 1, 1), None, 25_000, 1, 18)
        ),
    )

    link = _page(client, water).select_one('[data-period-id] [data-field="recurring"] a')

    assert text(link) == "Water bill"
    assert link["href"] == f"/recurring#payment-{_bill_payment(db_path)}"


def test_an_unlinked_period_in_force_says_it_is_forecast_as_the_meters_advance(client, db_path):
    _store(db_path, lambda conn: add_category(conn, "Water", "fixed"))
    water = _water_with_schedule(db_path, "Water 2")

    note = _page(client, water).select_one('[data-period-id] [data-field="recurring"]')

    assert text(note) == "Forecast as Water 2 advance"
    assert note.select_one("a") is None


def test_a_flexible_period_shows_no_advance_note(client, db_path):
    meter = _with_readings(db_path)

    assert _page(client, meter).select_one('[data-field="recurring"]') is None
