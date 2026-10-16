"""Tests for the Utilities page (SPEC §13 Utilities): meters, readings, exchanges, periods."""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest
from fastapi.testclient import TestClient

from sonar.db import connect
from sonar.utilities.model import BillingPeriod, Meter, Reading
from sonar.utilities.store import (
    add_meter,
    add_period,
    add_reading,
    list_meters,
    list_readings,
)
from sonar.web.app import create_app
from tests.html import cents, soup, text
from tests.seed import seed
from tests.utilities.test_settlement import (
    WATER_BOOKINGS,
    WATER_TODAY,
    water_periods,
)

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


def _page(client):
    return soup(client.get("/utilities"))


def _error(response) -> str:
    assert response.status_code == 400
    return text(soup(response).select_one("#form-error"))


def _input(page, selector: str) -> str:
    return page.select_one(selector)["value"]


# Page and meters


def test_the_card_shows_the_latest_reading_of_its_meter(client, db_path):
    meter = _gas_meter(db_path)
    _store(db_path, lambda conn: add_reading(conn, meter, Reading(date(2026, 1, 5), 12_345)))
    _store(db_path, lambda conn: add_reading(conn, meter, Reading(date(2026, 1, 9), 13_000)))

    sections = _page(client).select("[data-meter-id]")

    assert [section["data-meter-id"] for section in sections] == [str(meter)]
    latest = sections[0].select_one(f"#meter-{meter}-latest-reading")
    assert latest.select_one('[data-field="date"] time')["datetime"] == "2026-01-09"
    assert text(latest.select_one('[data-field="reading"]')) == "13.000"


def test_a_card_without_readings_has_no_latest_reading(client, db_path):
    meter = _gas_meter(db_path)

    assert _page(client).select_one(f"#meter-{meter}-latest-reading") is None


def test_the_card_has_stats_chart_add_reading_form_and_history_link_only(client, db_path):
    meter = _with_months(
        db_path,
        [
            (date(2026, 1, 1), 1_000_000),
            (date(2026, 2, 1), 1_100_000),
            (date(2026, 3, 1), 1_250_000),
        ],
    )
    card = _page(client).select_one(f"#meter-{meter}")

    assert card.select_one(f"#meter-{meter}-cost-so-far") is not None
    assert card.select_one("[data-utility-chart]") is not None
    assert card.select_one(f"#meter-{meter}-add-reading") is not None
    assert card.select_one(f"#meter-{meter}-history")["href"] == f"/utilities/meters/{meter}"
    for gone in (
        f"#meter-{meter}-readings",
        f"#meter-{meter}-exchanges",
        f"#meter-{meter}-periods",
        f"#meter-{meter}-add-exchange",
        f"#meter-{meter}-new-period",
        "[data-reading-id]",
    ):
        assert card.select_one(gone) is None


def test_no_meters_shows_the_add_meter_card_only(client):
    page = _page(client)

    assert page.select("[data-meter-id]") == []
    assert page.select_one("#add-meter") is not None


def test_utilities_is_a_nav_item_after_payoff(client):
    links = [a["href"] for a in _page(client).select("nav a[href]")]

    assert links[links.index("/payoff") + 1] == "/utilities"


# Status


def test_status_stats_carry_cents(client, db_path):
    meter = _with_readings(db_path, expected_usage=3_650)  # 10 kWh a day for the rest of the year
    _insert_debit(db_path, "2026-01-03", -5_000, "Utilities")
    page = _page(client)

    def stat(name: str) -> int:
        return cents(page.select_one(f"#meter-{meter}-{name}"))

    # 100 kWh x 3 ct + 10 days of the 12 EUR fee (10 x 1200 / 31) = 687 cents so far.
    assert stat("cost-so-far") == 687
    assert stat("paid") == 5_000
    assert stat("left") == 5_000 - 687
    # Projected: 10 kWh a day at 3 ct all year plus 12 fees is 25350 cents in all.
    # 5000 paid + 10 more advances of 5000 (11 a year, one paid) - 25350 = 29650 refund.
    settlement = page.select_one(f"#meter-{meter}-settlement")
    assert cents(settlement) == 29_650
    assert settlement["data-kind"] == "refund"
    assert stat("worst-case") == 29_650
    # (25350 - 5000 paid) over 10 advances left and the settlement = 1850, rounded up.
    assert stat("suggested-advance") == 1_900
    assert page.select_one(f"#meter-{meter}-settlement-date")["datetime"] == "2026-12-31"


def test_a_back_payment_is_worded_as_such(client, db_path):
    meter = _electricity_meter(db_path)
    _store(
        db_path,
        lambda conn: add_period(conn, meter, _period(advance_cents=1_000, expected_usage=3_650)),
    )
    _store(db_path, lambda conn: add_reading(conn, meter, Reading(date(2026, 1, 1), 1_000_000)))
    _store(db_path, lambda conn: add_reading(conn, meter, Reading(date(2026, 1, 11), 1_100_000)))

    settlement = _page(client).select_one(f"#meter-{meter}-settlement")

    # Nothing paid: 11 advances of 1000 (11 a year) - 25350 projected.
    assert settlement["data-kind"] == "back-payment"
    assert cents(settlement) == 14_350


def _with_previous_period(db_path, settled: int | None) -> int:
    meter = _with_readings(db_path)
    previous = _period(
        start_date=date(2025, 1, 1), settlement_date=date(2025, 12, 31), settled_cents=settled
    )
    _store(db_path, lambda conn: add_period(conn, meter, previous))
    return meter


def test_paid_so_far_says_since_when(client, db_path):
    meter = _with_readings(db_path)

    since = _page(client).select_one(f"#meter-{meter}-paid-since")

    assert since["datetime"] == "2026-01-01"


def test_paid_since_follows_the_previous_settlement(client, db_path):
    meter = _with_previous_period(db_path, None)

    since = _page(client).select_one(f"#meter-{meter}-paid-since")

    assert since["datetime"] == "2026-01-15"  # the previous settlement date + 15 days


def test_the_last_settlement_of_a_back_payment(client, db_path):
    meter = _with_previous_period(db_path, -3_169)

    line = _page(client).select_one(f"#meter-{meter}-last-settlement")

    assert line["data-kind"] == "back-payment"
    assert text(line) == "Last settlement: back-payment 31,69 € on 31 Dec 2025"
    assert line.select_one("time")["datetime"] == "2025-12-31"


def test_the_last_settlement_of_a_refund(client, db_path):
    meter = _with_previous_period(db_path, 1_250)

    line = _page(client).select_one(f"#meter-{meter}-last-settlement")

    assert line["data-kind"] == "refund"
    assert text(line) == "Last settlement: refund 12,50 € on 31 Dec 2025"


def test_no_last_settlement_without_a_settled_previous_period(client, db_path):
    unsettled = _with_previous_period(db_path, None)

    assert _page(client).select_one(f"#meter-{unsettled}-last-settlement") is None


def test_no_last_settlement_without_a_previous_period(client, db_path):
    meter = _with_readings(db_path)

    assert _page(client).select_one(f"#meter-{meter}-last-settlement") is None


def _suggested_hint(client, meter: int) -> str:
    stat = _page(client).select_one(f"#meter-{meter}-suggested-advance").parent.parent
    return text(stat)


def test_the_suggested_advance_hint_names_the_remaining_advances_and_the_settlement(
    client, db_path
):
    meter = _with_readings(db_path, expected_usage=3_650)  # nothing paid: 11 advances left

    hint = _suggested_hint(client, meter)

    assert "per advance for the next 11 advances, about the same at settlement on" in hint
    assert "31 Dec 2026" in hint


def test_the_suggested_advance_hint_says_advance_for_one_left(client, db_path):
    meter = _with_readings(db_path, settlement_date=date(2026, 1, 31))  # advance count 1

    assert "next 1 advance," in _suggested_hint(client, meter)


def test_the_suggested_advance_hint_without_an_advance_left_names_the_settlement(client, db_path):
    meter = _with_readings(db_path, settlement_date=date(2026, 1, 31))
    _insert_debit(db_path, "2026-01-03", -5_000, "Utilities")

    hint = _suggested_hint(client, meter)

    assert "no advance left, about this at settlement on 31 Jan 2026" in hint
    assert "next" not in hint


def test_the_worst_case_hint_names_what_it_takes_the_highest_of(client, db_path):
    meter = _with_readings(db_path, expected_usage=3_650)

    stat = _page(client).select_one(f"#meter-{meter}-worst-case").parent.parent

    assert "highest" in text(stat)
    assert "last year" in text(stat)


def test_a_meter_without_a_current_period_shows_no_projection(client, db_path):
    meter = _electricity_meter(db_path)
    past = _period(start_date=date(2025, 1, 1), settlement_date=date(2025, 12, 31))
    _store(db_path, lambda conn: add_period(conn, meter, past))

    page = _page(client)

    assert page.select_one(f"#meter-{meter}-cost-so-far") is None
    assert "2025-12-31" in str(page.select_one(f"#meter-{meter}-settled"))


# Meters


def test_add_meter_redirects_and_lists_it(client, db_path):
    response = client.post("/utilities/meters", data={"name": "Flat gas", "kind": "gas"})

    assert response.status_code == 303
    assert response.headers["location"] == "/utilities"
    assert _store(db_path, list_meters)[0].item == Meter("Flat gas", "gas")


def test_add_meter_with_a_blank_name_is_a_400_that_keeps_the_entry(client):
    response = client.post("/utilities/meters", data={"name": "  ", "kind": "electricity"})

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

    response = client.post(f"/utilities/meters/{meter}/delete")

    assert "readings" in _error(response)
    assert len(_store(db_path, list_meters)) == 1


# Readings


def test_add_reading(client, db_path):
    meter = _gas_meter(db_path)

    response = client.post(
        f"/utilities/meters/{meter}/readings", data={"date": "2026-01-05", "value": "12,345"}
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/utilities"
    stored = _store(db_path, lambda conn: list_readings(conn, meter))
    assert [s.item for s in stored] == [Reading(date(2026, 1, 5), 12_345)]


def test_a_dropping_reading_is_a_400_that_keeps_the_entry_and_writes_nothing(client, db_path):
    meter = _with_readings(db_path)

    response = client.post(
        f"/utilities/meters/{meter}/readings", data={"date": "2026-01-20", "value": "999.5"}
    )

    assert "2026-01-20" in _error(response)
    page = soup(response)
    assert _input(page, f"#meter-{meter}-add-reading input[name=value]") == "999.5"
    assert _input(page, f"#meter-{meter}-add-reading input[name=date]") == "2026-01-20"
    assert len(_store(db_path, lambda conn: list_readings(conn, meter))) == 2


def test_a_reading_with_too_many_decimals_is_a_400(client, db_path):
    meter = _gas_meter(db_path)

    response = client.post(
        f"/utilities/meters/{meter}/readings", data={"date": "2026-01-05", "value": "1.2345"}
    )

    assert "Reading" in _error(response)
    assert _input(soup(response), f"#meter-{meter}-add-reading input[name=value]") == "1.2345"


def test_a_missing_reading_is_a_404(client):
    assert client.post("/utilities/readings/99/delete").status_code == 404
    assert (
        client.post(
            "/utilities/meters/99/readings", data={"date": "2026-01-05", "value": "1"}
        ).status_code
        == 404
    )


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

    charts = page.select("[data-utility-chart]")
    chart = page.select_one(f"#meter-{meter} [data-utility-chart] [data-view=all]")
    months = len(chart.select('[data-series="usage"] rect'))

    assert len(charts) == 1
    assert page.select_one(f"#meter-{other} [data-utility-chart]") is None
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

    chart = _page(client).select_one("[data-utility-chart]")

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

    svg = _page(client).select_one("[data-utility-chart] svg")

    assert svg["role"] == "img"
    assert svg["aria-label"]
    assert svg.select_one("title") is not None
    legend = text(_page(client).select_one("[data-utility-chart] ul"))
    assert "kWh" in legend
    assert "€" in legend


def test_fewer_than_two_months_shows_an_empty_state_instead_of_a_chart(client, db_path):
    meter = _electricity_meter(db_path)
    january = _period(settlement_date=date(2026, 1, 31))
    _store(db_path, lambda conn: add_period(conn, meter, january))
    for day, value_milli in [(date(2026, 1, 1), 1_000_000), (date(2026, 2, 1), 1_100_000)]:
        reading = Reading(day, value_milli)
        _store(db_path, lambda conn, reading=reading: add_reading(conn, meter, reading))

    card = _page(client).select_one(f"#meter-{meter}")

    assert card.select_one("[data-utility-chart]") is None
    assert card.select_one("[data-utility-chart-empty]") is not None


def _with_two_cycles(db_path) -> int:
    """2025 and 2026 periods; Nov and Dec 2025 and Jan 2026 measured, the rest of 2026 projected."""
    meter = _electricity_meter(db_path)
    last_year = _period(start_date=date(2025, 1, 1), settlement_date=date(2025, 12, 31))
    _store(db_path, lambda conn: add_period(conn, meter, last_year))
    _store(db_path, lambda conn: add_period(conn, meter, _period()))
    for day, value_milli in [
        (date(2025, 11, 1), 1_000_000),
        (date(2025, 12, 1), 1_300_000),
        (date(2026, 1, 1), 1_650_000),
        (date(2026, 2, 1), 1_950_000),
    ]:
        reading = Reading(day, value_milli)
        _store(db_path, lambda conn, reading=reading: add_reading(conn, meter, reading))
    return meter


def _cycles(view) -> list[tuple[str, str]]:
    return [
        (rect["data-cycle"], rect["data-projected"])
        for rect in view.select('[data-series="usage"] rect')
    ]


def test_the_chart_marks_previous_current_and_projected_months(client, db_path):
    _with_two_cycles(db_path)

    full = _page(client).select_one("[data-utility-chart] [data-view=all]")

    assert _cycles(full) == (
        [("previous", "false")] * 2 + [("current", "false")] + [("current", "true")] * 11
    )
    assert full.select_one('[data-series="cost"]') is not None
    assert full.select_one('[data-series="cost-projected"]') is not None


def test_the_chart_legend_names_every_series(client, db_path):
    _with_two_cycles(db_path)

    chart = _page(client).select_one("[data-utility-chart]")

    assert {item["data-legend"] for item in chart.select("[data-legend]")} == {
        "previous",
        "current",
        "projected",
        "cost",
        "cost-projected",
    }


def test_the_chart_has_a_current_cycle_only_view_for_small_screens(client, db_path):
    _with_two_cycles(db_path)

    current = _page(client).select_one("[data-utility-chart] [data-view=current]")

    assert _cycles(current) == [("current", "false")] + [("current", "true")] * 11


def test_toggle_memory_script_keeps_the_chart_toggles_in_local_storage(client, db_path):
    _with_two_cycles(db_path)

    page = _page(client)
    scripts = page.select("script[data-utility-chart-memory]")

    assert len(scripts) == 1
    script = scripts[0].string
    assert "localStorage" in script and "data-toggle" in script
    assert script.count("try") >= 2 and script.count("catch") >= 2
    assert [
        box.has_attr("checked") for box in page.select("[data-utility-chart] [data-toggle]")
    ] == [
        False,
        False,
    ]


# Water, schedule and flexible cards (D6, D7, D11)


@pytest.fixture
def water_client(tmp_path):
    path = tmp_path / "water.db"
    seed(path, CATEGORIES + '\n[[category]]\nname = "Water"\ntype = "fixed"\n')
    meter = _store(path, lambda conn: add_meter(conn, Meter("Water", "water")))
    for period in water_periods():
        _store(path, lambda conn, p=period: add_period(conn, meter, p))
    for day, value in (
        (date(2025, 5, 31), 238_000),
        (date(2025, 12, 31), 355_000),
        (date(2026, 10, 16), 516_000),
    ):
        _store(path, lambda conn, d=day, v=value: add_reading(conn, meter, Reading(d, v)))
    with TestClient(create_app(path, today=lambda: WATER_TODAY)) as client:
        # Booked after startup, which re-applies the rules and would clear the category.
        for booked, amount in WATER_BOOKINGS:
            _insert_debit(path, booked.isoformat(), amount, "Water")
        yield client, meter


def _hook_cents(card, selector: str) -> int:
    return cents(card.select_one(selector))


def test_the_water_card_shows_each_charge_and_the_totals(water_client):
    client, meter = water_client
    card = _page(client).select_one(f"#meter-{meter}")

    for name, so_far, projected in (
        ("drinking", 22_615, 28_608),
        ("wastewater", 66_791, 84_489),
    ):
        block = card.select_one(f'[data-charge="{name}"]')
        assert _hook_cents(block, '[data-field="cost_so_far"]') == so_far
        assert _hook_cents(block, '[data-field="projected_cost"]') == projected
    assert text(card.select_one('[data-charge="drinking"]')).startswith("Drinking water")
    assert text(card.select_one('[data-charge="wastewater"]')).startswith("Wastewater")
    assert _hook_cents(card, f"#meter-{meter}-cost-so-far") == 89_406
    assert _hook_cents(card, f"#meter-{meter}-projected-cost") == 113_097
    assert _hook_cents(card, f"#meter-{meter}-paid") == 96_000


def test_the_water_card_shows_the_schedule_and_the_settlement_dates(water_client):
    client, meter = water_client
    card = _page(client).select_one(f"#meter-{meter}")

    remaining = card.select_one(f"#meter-{meter}-remaining-advances")
    assert cents(remaining) == 24_000
    assert text(card.select_one(f'#meter-{meter} [data-field="remaining_count"]')) == "1"
    assert card.select_one(f"#meter-{meter}-next-advance")["datetime"] == "2026-12-15"
    settlement = card.select_one(f"#meter-{meter}-settlement")
    assert cents(settlement) == 6_903
    assert settlement["data-kind"] == "refund"
    assert card.select_one(f"#meter-{meter}-settlement-date")["datetime"] == "2026-12-31"
    assert card.select_one(f"#meter-{meter}-debit-date")["datetime"] == "2027-02-24"
    assert cents(card.select_one(f"#meter-{meter}-worst-case")) == 6_903
    assert text(card.select_one(f"#meter-{meter}-set-by-supplier")) == "Set by the supplier"
    assert card.select_one(f"#meter-{meter}-suggested-advance") is None


def test_the_water_chart_says_m3(water_client):
    client, meter = water_client
    chart = _page(client).select_one(f"#meter-{meter}-chart")

    assert chart is not None
    assert "m³" in text(chart.select_one("svg title"))
    assert "kWh" not in text(chart)


def test_a_flexible_card_keeps_the_suggested_advance_and_adds_the_remaining_advances(
    client, db_path
):
    meter = _with_readings(db_path, expected_usage=3_650)
    card = _page(client).select_one(f"#meter-{meter}")

    assert cents(card.select_one(f"#meter-{meter}-suggested-advance")) > 0
    assert cents(card.select_one(f"#meter-{meter}-remaining-advances")) > 0
    assert int(text(card.select_one('[data-field="remaining_count"]'))) == 11
    assert card.select_one(f"#meter-{meter}-debit-date")["datetime"] == "2026-12-31"
    assert card.select_one(f"#meter-{meter}-projected-cost") is not None
    assert card.select_one(f"#meter-{meter}-next-advance") is None
    assert card.select_one(f"#meter-{meter}-set-by-supplier") is None
    assert card.select_one("[data-charge]") is None
    assert "kWh" in text(card.select_one(f"#meter-{meter}-chart"))


def test_add_a_meter_offers_water_and_creates_one(client, db_path):
    options = _page(client).select("#add-meter select[name=kind] option")
    assert [option["value"] for option in options] == ["gas", "electricity", "water"]

    response = client.post("/utilities/meters", data={"name": "Flat water", "kind": "water"})

    assert response.status_code == 303
    assert _store(db_path, list_meters)[0].item == Meter("Flat water", "water")
