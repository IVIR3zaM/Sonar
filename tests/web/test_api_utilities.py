"""Tests for the JSON API's utilities endpoints (SPEC §13 Utilities)."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sonar.auth.settings import AuthSettings
from sonar.categorization.store import add_category
from sonar.db import MIGRATIONS_DIR, apply_migrations, connect
from sonar.recurring.schedule import SchedulePeriod
from sonar.recurring.store import add_manual
from sonar.web.app import create_app

TODAY = date(2026, 1, 20)
TOKEN = "s3cret-token"
AUTH = AuthSettings(
    google_client_id="client-id",
    google_client_secret="client-secret",
    session_secret="session-secret",
    base_url="http://testserver",
    api_token=TOKEN,
)

PERIOD = {
    "start_date": "2026-01-01",
    "settlement_date": "2026-12-31",
    "base_fee_cents": 1_200,
    "unit_price_micro": 80_000,
    "state_factor_e4": 9_500,
    "calorific_value_e4": 110_000,
    "advance_cents": 9_000,
    "expected_usage": 15_000,
    "category": "Utilities",
    "settled_cents": None,
}
# Period fields a gas body may leave out.
PERIOD_DEFAULTS = {
    "drinking": None,
    "wastewater": None,
    "advance_mode": "flexible",
    "advance_dates": [],
    "settlement_debit_days": 0,
    "garden_fee_cents": None,
}


DRINKING = {"unit_price_micro": 1_900_000, "base_fee_cents": 4_800, "vat_percent": 7}
WASTEWATER = {"unit_price_micro": 2_500_000, "base_fee_cents": 3_600, "vat_percent": 0}
WATER_PERIOD = {
    "start_date": "2026-01-01",
    "settlement_date": "2026-12-31",
    "advance_cents": 5_500,
    "expected_usage": 90_000,
    "category": "Utilities",
    "drinking": DRINKING,
    "wastewater": WASTEWATER,
    "advance_mode": "schedule",
    "advance_dates": ["2026-02-05", "2026-05-05", "2026-11-05"],
    "settlement_debit_days": 55,
}


def _today() -> date:
    return TODAY


@pytest.fixture
def db_path(tmp_path) -> Path:
    path = tmp_path / "t.db"
    conn = sqlite3.connect(path)
    try:
        apply_migrations(conn, MIGRATIONS_DIR)
    finally:
        conn.close()
    return path


@pytest.fixture
def client(db_path) -> TestClient:
    return TestClient(create_app(db_path, today=_today), follow_redirects=False)


def _gas(client: TestClient) -> int:
    response = client.post("/api/utilities/meters", json={"name": "Gas", "kind": "gas"})
    assert response.status_code == 201
    return response.json()["id"]


def _water(client: TestClient) -> int:
    response = client.post("/api/utilities/meters", json={"name": "Water", "kind": "water"})
    assert response.status_code == 201
    assert response.json()["kind"] == "water"
    return response.json()["id"]


def _debit(db_path: Path, booked: str, cents: int, category: str) -> None:
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
            (booked, booked, cents, f"{booked}{cents}", category),
        )
        conn.commit()
    finally:
        conn.close()


def test_get_lists_a_meter_with_its_status_and_paid_advances(client, db_path):
    meter_id = _gas(client)
    assert client.post(f"/api/utilities/meters/{meter_id}/periods", json=PERIOD).status_code == 201
    for day, value in (("2026-01-01", 1_000_000), ("2026-01-11", 1_100_000)):
        reading = {"date": day, "value_milli": value}
        assert (
            client.post(f"/api/utilities/meters/{meter_id}/readings", json=reading).status_code
            == 201
        )
    _debit(db_path, "2026-01-05", -10_000, "Utilities")

    [meter] = client.get("/api/utilities").json()["meters"]

    assert meter["name"] == "Gas"
    assert meter["status"]["paid_cents"] == 10_000
    assert meter["status"]["as_of"] == "2026-01-11"
    assert meter["status"]["charges"] == []
    assert meter["status"]["advance_mode"] == "flexible"
    assert meter["status"]["remaining_advance_dates"] == []
    assert meter["status"]["debit_date"] == "2026-12-31"
    assert meter["periods"][0]["category"] == "Utilities"
    assert [r["date"] for r in meter["readings"]] == ["2026-01-01", "2026-01-11"]
    assert meter["exchanges"] == []
    assert set(meter) == {
        "id",
        "name",
        "kind",
        "main_meter_id",
        "garden_conflicts",
        "status",
        "periods",
        "exchanges",
        "readings",
    }
    assert meter["main_meter_id"] is None
    assert meter["garden_conflicts"] == []


def test_a_water_period_with_a_schedule_round_trips_and_reports_its_status(client):
    meter_id = _water(client)

    created = client.post(f"/api/utilities/meters/{meter_id}/periods", json=WATER_PERIOD)
    for day, value in (("2026-01-01", 10_000), ("2026-01-11", 12_000)):
        reading = {"date": day, "value_milli": value}
        client.post(f"/api/utilities/meters/{meter_id}/readings", json=reading)
    [meter] = client.get("/api/utilities").json()["meters"]

    assert created.status_code == 201
    assert created.json() == {
        "id": created.json()["id"],
        **WATER_PERIOD,
        "base_fee_cents": None,
        "unit_price_micro": None,
        "state_factor_e4": None,
        "calorific_value_e4": None,
        "settled_cents": None,
        "garden_fee_cents": None,
    }
    assert meter["periods"] == [created.json()]
    status = meter["status"]
    assert [c["name"] for c in status["charges"]] == ["drinking", "wastewater"]
    assert status["advance_mode"] == "schedule"
    assert status["remaining_advance_dates"] == ["2026-02-05", "2026-05-05", "2026-11-05"]
    assert status["debit_date"] == "2027-02-24"


def test_put_replaces_a_periods_dates_and_charges(client):
    meter_id = _water(client)
    period_id = client.post(f"/api/utilities/meters/{meter_id}/periods", json=WATER_PERIOD).json()[
        "id"
    ]
    body = {
        **WATER_PERIOD,
        "advance_dates": ["2026-03-05"],
        "drinking": {**DRINKING, "vat_percent": 19},
        "settlement_debit_days": 10,
    }

    updated = client.put(f"/api/utilities/periods/{period_id}", json=body)
    [meter] = client.get("/api/utilities").json()["meters"]

    assert updated.status_code == 200
    assert meter["periods"] == [updated.json()]
    assert updated.json()["advance_dates"] == ["2026-03-05"]
    assert updated.json()["drinking"]["vat_percent"] == 19
    assert updated.json()["settlement_debit_days"] == 10
    assert client.delete(f"/api/utilities/periods/{period_id}").status_code == 200
    assert client.get("/api/utilities").json()["meters"][0]["periods"] == []


def _gas_period(**changes):
    return {**PERIOD, **changes}


@pytest.mark.parametrize(
    ("kind", "changes", "field"),
    [
        ("water", {"drinking": None}, "drinking"),
        ("gas", {"drinking": DRINKING}, "drinking"),
        ("water", {"drinking": {**DRINKING, "vat_percent": 101}}, "drinking_vat_percent"),
        ("water", {"advance_dates": []}, "advance_dates"),
        ("water", {"advance_mode": "flexible"}, "advance_dates"),
        ("water", {"advance_dates": ["2027-02-01"]}, "advance_dates"),
        ("water", {"advance_dates": ["2026-02-05", "2026-02-05"]}, "advance_dates"),
        ("water", {"advance_dates": ["2026-13-01"]}, "advance_dates"),
        ("water", {"settlement_debit_days": -1}, "settlement_debit_days"),
    ],
)
def test_an_invalid_new_period_field_is_a_400_naming_it(client, kind, changes, field):
    if kind == "water":
        meter_id = _water(client)
        body = {**WATER_PERIOD, **changes}
    else:
        meter_id = _gas(client)
        body = _gas_period(**changes)

    response = client.post(f"/api/utilities/meters/{meter_id}/periods", json=body)

    assert response.status_code == 400
    assert response.json()["field"] == field
    assert client.get("/api/utilities").json()["meters"][0]["periods"] == []


@pytest.mark.parametrize(
    "changes",
    [
        {"drinking": {**DRINKING, "colour": "blue"}},
        {"advance_dates": "2026-02-05"},
    ],
)
def test_an_unknown_charge_key_or_a_string_for_dates_is_a_422(client, changes):
    meter_id = _water(client)

    response = client.post(
        f"/api/utilities/meters/{meter_id}/periods", json={**WATER_PERIOD, **changes}
    )

    assert response.status_code == 422


def test_status_is_null_without_a_current_period(client):
    _gas(client)

    [meter] = client.get("/api/utilities").json()["meters"]

    assert meter["status"] is None


def test_meter_create_rename_and_delete(client):
    meter_id = _gas(client)

    renamed = client.put(f"/api/utilities/meters/{meter_id}", json={"name": "Heating"})
    deleted = client.delete(f"/api/utilities/meters/{meter_id}")

    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Heating"
    assert deleted.status_code == 200
    assert deleted.json()["id"] == meter_id
    assert client.get("/api/utilities").json() == {"meters": []}


def test_reading_create_update_and_delete(client):
    meter_id = _gas(client)

    created = client.post(
        f"/api/utilities/meters/{meter_id}/readings", json={"date": "2026-01-01", "value_milli": 5}
    )
    reading_id = created.json()["id"]
    updated = client.put(
        f"/api/utilities/readings/{reading_id}", json={"date": "2026-01-02", "value_milli": 7}
    )
    deleted = client.delete(f"/api/utilities/readings/{reading_id}")

    assert created.status_code == 201
    assert created.json() == {"id": reading_id, "date": "2026-01-01", "value_milli": 5}
    assert updated.json() == {"id": reading_id, "date": "2026-01-02", "value_milli": 7}
    assert deleted.json() == updated.json()
    assert client.get("/api/utilities").json()["meters"][0]["readings"] == []


def test_exchange_create_update_and_delete(client):
    meter_id = _gas(client)
    client.post(
        f"/api/utilities/meters/{meter_id}/readings",
        json={"date": "2026-01-01", "value_milli": 100},
    )
    body = {"date": "2026-02-01", "old_final_milli": 200, "new_start_milli": 0}

    created = client.post(f"/api/utilities/meters/{meter_id}/exchanges", json=body)
    exchange_id = created.json()["id"]
    updated = client.put(
        f"/api/utilities/exchanges/{exchange_id}", json={**body, "old_final_milli": 300}
    )
    deleted = client.delete(f"/api/utilities/exchanges/{exchange_id}")

    assert created.status_code == 201
    assert created.json() == {"id": exchange_id, **body}
    assert updated.json()["old_final_milli"] == 300
    assert deleted.json() == updated.json()
    assert client.get("/api/utilities").json()["meters"][0]["exchanges"] == []


def test_period_create_update_and_delete(client):
    meter_id = _gas(client)

    created = client.post(f"/api/utilities/meters/{meter_id}/periods", json=PERIOD)
    period_id = created.json()["id"]
    updated = client.put(
        f"/api/utilities/periods/{period_id}", json={**PERIOD, "advance_cents": 9_500}
    )
    deleted = client.delete(f"/api/utilities/periods/{period_id}")

    assert created.status_code == 201
    assert created.json() == {"id": period_id, **PERIOD, **PERIOD_DEFAULTS}
    assert updated.json()["advance_cents"] == 9_500
    assert deleted.json() == updated.json()
    assert client.get("/api/utilities").json()["meters"][0]["periods"] == []


def test_a_dropping_reading_is_a_400_naming_value(client):
    meter_id = _gas(client)
    client.post(
        f"/api/utilities/meters/{meter_id}/readings",
        json={"date": "2026-01-01", "value_milli": 500},
    )

    response = client.post(
        f"/api/utilities/meters/{meter_id}/readings",
        json={"date": "2026-01-02", "value_milli": 400},
    )

    assert response.status_code == 400
    assert response.json()["field"] == "value"
    assert len(client.get("/api/utilities").json()["meters"][0]["readings"]) == 1


def test_a_reading_on_an_exchange_date_is_a_400_naming_date(client):
    meter_id = _gas(client)
    client.post(
        f"/api/utilities/meters/{meter_id}/exchanges",
        json={"date": "2026-02-01", "old_final_milli": 200, "new_start_milli": 0},
    )

    response = client.post(
        f"/api/utilities/meters/{meter_id}/readings", json={"date": "2026-02-01", "value_milli": 5}
    )

    assert response.status_code == 400
    assert response.json()["field"] == "date"


def test_settled_cents_round_trips_in_post_put_and_get(client):
    meter_id = _gas(client)

    created = client.post(
        f"/api/utilities/meters/{meter_id}/periods", json={**PERIOD, "settled_cents": -27_013}
    )
    period_id = created.json()["id"]
    listed = client.get("/api/utilities").json()["meters"][0]["periods"][0]
    updated = client.put(
        f"/api/utilities/periods/{period_id}", json={**PERIOD, "settled_cents": -100}
    )
    omitted = client.put(
        f"/api/utilities/periods/{period_id}",
        json={k: v for k, v in PERIOD.items() if k != "settled_cents"},
    )

    assert created.json()["settled_cents"] == -27_013
    assert listed["settled_cents"] == -27_013
    assert updated.json()["settled_cents"] == -100
    assert omitted.json()["settled_cents"] is None


def test_a_string_settled_cents_is_a_422(client):
    meter_id = _gas(client)

    response = client.post(
        f"/api/utilities/meters/{meter_id}/periods", json={**PERIOD, "settled_cents": "12"}
    )

    assert response.status_code == 422


def test_an_overlapping_period_is_a_400_naming_start_date(client):
    meter_id = _gas(client)
    client.post(f"/api/utilities/meters/{meter_id}/periods", json=PERIOD)

    response = client.post(
        f"/api/utilities/meters/{meter_id}/periods", json={**PERIOD, "start_date": "2026-06-01"}
    )

    assert response.status_code == 400
    assert response.json()["field"] == "start_date"


def test_an_unknown_category_is_a_400_naming_category(client):
    meter_id = _gas(client)

    response = client.post(
        f"/api/utilities/meters/{meter_id}/periods", json={**PERIOD, "category": "Nope"}
    )

    assert response.status_code == 400
    assert response.json()["field"] == "category"


def test_a_gas_period_without_a_state_factor_is_a_400_naming_it(client):
    meter_id = _gas(client)
    period = {k: v for k, v in PERIOD.items() if k != "state_factor_e4"}

    response = client.post(f"/api/utilities/meters/{meter_id}/periods", json=period)

    assert response.status_code == 400
    assert response.json()["field"] == "state_factor_e4"


def test_a_bad_date_is_a_400_naming_the_field(client):
    meter_id = _gas(client)

    response = client.post(
        f"/api/utilities/meters/{meter_id}/readings", json={"date": "tomorrow", "value_milli": 5}
    )

    assert response.status_code == 400
    assert response.json()["field"] == "date"


def test_a_bad_meter_kind_is_a_400_naming_kind(client):
    response = client.post("/api/utilities/meters", json={"name": "Fuel", "kind": "oil"})

    assert response.status_code == 400
    assert response.json()["field"] == "kind"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("put", "/api/utilities/meters/99", {"name": "X"}),
        ("delete", "/api/utilities/meters/99", None),
        ("post", "/api/utilities/meters/99/readings", {"date": "2026-01-01", "value_milli": 1}),
        ("put", "/api/utilities/readings/99", {"date": "2026-01-01", "value_milli": 1}),
        ("delete", "/api/utilities/readings/99", None),
        (
            "post",
            "/api/utilities/meters/99/exchanges",
            {"date": "2026-01-01", "old_final_milli": 1, "new_start_milli": 0},
        ),
        (
            "put",
            "/api/utilities/exchanges/99",
            {"date": "2026-01-01", "old_final_milli": 1, "new_start_milli": 0},
        ),
        ("delete", "/api/utilities/exchanges/99", None),
        ("post", "/api/utilities/meters/99/periods", PERIOD),
        ("put", "/api/utilities/periods/99", PERIOD),
        ("delete", "/api/utilities/periods/99", None),
    ],
)
def test_an_unknown_id_is_a_404(client, method, path, body):
    response = client.request(method, path, json=body) if body else client.request(method, path)

    assert response.status_code == 404
    assert "error" in response.json()


def test_deleting_a_meter_with_rows_is_a_409_and_keeps_it(client):
    meter_id = _gas(client)
    client.post(
        f"/api/utilities/meters/{meter_id}/readings", json={"date": "2026-01-01", "value_milli": 5}
    )

    response = client.delete(f"/api/utilities/meters/{meter_id}")

    assert response.status_code == 409
    assert len(client.get("/api/utilities").json()["meters"]) == 1


def test_an_unknown_key_is_a_422(client):
    response = client.post(
        "/api/utilities/meters", json={"name": "Gas", "kind": "gas", "color": "x"}
    )

    assert response.status_code == 422


def test_a_wrong_json_type_is_a_422(client):
    meter_id = _gas(client)

    response = client.post(
        f"/api/utilities/meters/{meter_id}/readings",
        json={"date": "2026-01-01", "value_milli": "5"},
    )

    assert response.status_code == 422


def test_with_sign_in_on_no_session_gets_401_and_the_bearer_gets_in(db_path):
    app = create_app(db_path, today=_today, auth=AUTH)
    with TestClient(app, follow_redirects=False) as client:
        anonymous = client.get("/api/utilities")
        bearer = client.get("/api/utilities", headers={"Authorization": f"Bearer {TOKEN}"})

    assert anonymous.status_code == 401
    assert bearer.status_code == 200


# Garden meters


def _garden(client: TestClient, main_id: int, name: str = "Garden") -> int:
    response = client.post(
        "/api/utilities/meters", json={"name": name, "kind": "water", "main_meter_id": main_id}
    )
    assert response.status_code == 201
    return response.json()["id"]


def _read(client: TestClient, meter_id: int, readings: dict[str, int]) -> dict[str, int]:
    ids = {}
    for day, value in readings.items():
        reading = {"date": day, "value_milli": value}
        response = client.post(f"/api/utilities/meters/{meter_id}/readings", json=reading)
        assert response.status_code == 201
        ids[day] = response.json()["id"]
    return ids


def _meters(client: TestClient) -> dict[str, dict]:
    return {m["name"]: m for m in client.get("/api/utilities").json()["meters"]}


def test_a_garden_meter_links_to_its_main_water_meter(client):
    main_id = _water(client)

    created = client.post(
        "/api/utilities/meters",
        json={"name": "Garden", "kind": "water", "main_meter_id": main_id},
    )
    meters = _meters(client)

    assert created.status_code == 201
    assert created.json()["main_meter_id"] == main_id
    assert meters["Garden"]["main_meter_id"] == main_id
    assert meters["Water"]["main_meter_id"] is None


def test_a_garden_linked_to_a_gas_meter_is_a_400_naming_main_meter_id(client):
    gas_id = _gas(client)

    response = client.post(
        "/api/utilities/meters",
        json={"name": "Garden", "kind": "water", "main_meter_id": gas_id},
    )

    assert response.status_code == 400
    assert response.json()["field"] == "main_meter_id"


def test_a_period_on_a_garden_meter_is_a_400(client):
    garden_id = _garden(client, _water(client))

    response = client.post(f"/api/utilities/meters/{garden_id}/periods", json=WATER_PERIOD)

    assert response.status_code == 400
    assert response.json()["field"] == "meter"


def test_deleting_a_main_meter_with_gardens_is_a_409_naming_garden_meters(client):
    main_id = _water(client)
    _garden(client, main_id)

    response = client.delete(f"/api/utilities/meters/{main_id}")

    assert response.status_code == 409
    assert "garden meters" in response.json()["error"]
    assert len(client.get("/api/utilities").json()["meters"]) == 2


def test_a_garden_fee_round_trips_and_null_means_no_fee(client):
    meter_id = _water(client)

    with_fee = client.post(
        f"/api/utilities/meters/{meter_id}/periods",
        json={**WATER_PERIOD, "garden_fee_cents": 1_500},
    )
    updated = client.put(
        f"/api/utilities/periods/{with_fee.json()['id']}",
        json={**WATER_PERIOD, "garden_fee_cents": None},
    )

    assert with_fee.status_code == 201
    assert with_fee.json()["garden_fee_cents"] == 1_500
    assert _meters(client)["Water"]["periods"][0]["garden_fee_cents"] is None
    assert updated.json()["garden_fee_cents"] is None


def test_a_negative_garden_fee_is_a_400_naming_it(client):
    meter_id = _water(client)

    response = client.post(
        f"/api/utilities/meters/{meter_id}/periods", json={**WATER_PERIOD, "garden_fee_cents": -1}
    )

    assert response.status_code == 400
    assert response.json()["field"] == "garden_fee_cents"


def test_volumes_are_empty_without_gardens_and_listed_with_one(client):
    main_id = _water(client)
    client.post(f"/api/utilities/meters/{main_id}/periods", json=WATER_PERIOD)
    _read(client, main_id, {"2026-01-01": 10_000, "2026-01-11": 12_000})

    assert _meters(client)["Water"]["status"]["volumes"] == []

    garden_id = _garden(client, main_id)
    _read(client, garden_id, {"2026-01-01": 0, "2026-01-11": 1_000})
    volumes = _meters(client)["Water"]["status"]["volumes"]

    assert [v["name"] for v in volumes] == ["main", "garden", "wastewater"]


def _conflict(client: TestClient) -> tuple[int, dict[str, int]]:
    """A garden that measured 5 m³ in ten days while the main measured 2 m³."""
    main_id = _water(client)
    client.post(f"/api/utilities/meters/{main_id}/periods", json=WATER_PERIOD)
    _read(client, main_id, {"2026-01-01": 10_000, "2026-01-11": 12_000})
    garden_id = _garden(client, main_id)
    ids = _read(client, garden_id, {"2026-01-01": 0, "2026-01-11": 5_000})
    return garden_id, ids


def test_a_conflict_is_listed_on_the_main_and_the_garden(client):
    garden_id, ids = _conflict(client)
    meters = _meters(client)

    expected = {
        "start_date": "2026-01-01",
        "end_date": "2026-01-11",
        "excess_milli": 3_000,
        "zeroed": False,
        "gardens": [
            {
                "meter_id": garden_id,
                "start_date": "2026-01-01",
                "end_date": "2026-01-11",
                "used_milli": 5_000,
                "reading_id": ids["2026-01-11"],
                "exchange_id": None,
            }
        ],
    }
    assert meters["Water"]["garden_conflicts"] == [expected]
    assert meters["Garden"]["garden_conflicts"] == meters["Water"]["garden_conflicts"]


def test_the_zero_action_on_the_main_marks_the_case_zeroed(client):
    _conflict(client)
    main_id = _meters(client)["Water"]["id"]

    response = client.post(
        f"/api/utilities/meters/{main_id}/conflicts/zero",
        json={"start_date": "2026-01-01", "end_date": "2026-01-11"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == main_id
    assert [c["zeroed"] for c in response.json()["garden_conflicts"]] == [True]
    assert [c["zeroed"] for c in _meters(client)["Garden"]["garden_conflicts"]] == [True]


def test_the_zero_action_on_a_garden_is_a_400_and_on_an_unknown_meter_a_404(client):
    garden_id, _ = _conflict(client)
    main_id = _meters(client)["Water"]["id"]
    body = {"start_date": "2026-01-01", "end_date": "2026-01-11"}

    on_garden = client.post(f"/api/utilities/meters/{garden_id}/conflicts/zero", json=body)
    unknown = client.post("/api/utilities/meters/99/conflicts/zero", json=body)
    bad_date = client.post(
        f"/api/utilities/meters/{main_id}/conflicts/zero",
        json={"start_date": "soon", "end_date": "2026-01-11"},
    )

    assert on_garden.status_code == 400
    assert on_garden.json()["field"] == "meter"
    assert unknown.status_code == 404
    assert bad_date.status_code == 400
    assert bad_date.json()["field"] == "start_date"
    assert [c["zeroed"] for c in _meters(client)["Water"]["garden_conflicts"]] == [False]


def test_the_exchange_action_swaps_a_reading_for_an_exchange(client):
    garden_id, ids = _conflict(client)

    response = client.post(
        f"/api/utilities/readings/{ids['2026-01-11']}/exchange", json={"old_final_milli": 1_500}
    )
    garden = _meters(client)["Garden"]

    assert response.status_code == 201
    assert response.json()["date"] == "2026-01-11"
    assert response.json()["old_final_milli"] == 1_500
    assert response.json()["new_start_milli"] == 5_000
    assert [r["date"] for r in garden["readings"]] == ["2026-01-01"]
    assert [e["id"] for e in garden["exchanges"]] == [response.json()["id"]]


def test_the_exchange_action_is_a_400_when_the_series_would_drop(client):
    _, ids = _conflict(client)

    response = client.post(
        f"/api/utilities/readings/{ids['2026-01-11']}/exchange", json={"old_final_milli": -1}
    )

    assert response.status_code == 400
    assert response.json()["field"] == "value"
    assert [r["date"] for r in _meters(client)["Garden"]["readings"]] == [
        "2026-01-01",
        "2026-01-11",
    ]


def test_the_exchange_action_on_an_unknown_reading_is_a_404(client):
    response = client.post("/api/utilities/readings/99/exchange", json={"old_final_milli": 1})

    assert response.status_code == 404


def test_the_status_names_the_payment_that_pays_a_schedules_advances(client, db_path):
    conn = connect(db_path)
    try:
        add_category(conn, "Water", "fixed")
        payment = add_manual(
            conn, "Water bill", "Water", SchedulePeriod(date(2026, 1, 1), None, 25_000, 1, 18)
        )
    finally:
        conn.close()
    schedule = {**WATER_PERIOD, "category": "Water"}
    for name, kind, period in (
        ("Water", "water", schedule),
        ("Water 2", "water", schedule),
        ("Gas", "gas", {**PERIOD, **PERIOD_DEFAULTS}),
    ):
        meter = client.post("/api/utilities/meters", json={"name": name, "kind": kind}).json()
        assert (
            client.post(f"/api/utilities/meters/{meter['id']}/periods", json=period).status_code
            == 201
        )
        for day, value in (("2026-01-01", 1_000_000), ("2026-01-11", 1_100_000)):
            reading = {"date": day, "value_milli": value}
            client.post(f"/api/utilities/meters/{meter['id']}/readings", json=reading)

    meters = {m["name"]: m for m in client.get("/api/utilities").json()["meters"]}

    assert meters["Water"]["status"]["recurring_payment_id"] == payment
    assert meters["Water 2"]["status"]["recurring_payment_id"] is None
    assert meters["Gas"]["status"]["recurring_payment_id"] is None
