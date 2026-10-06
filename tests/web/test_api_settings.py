"""Tests for the JSON API's settings endpoints (SPEC §4, §13)."""

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from sonar.auth.settings import AuthSettings
from sonar.cashflow.store import DEFAULT_OVERDRAFT_LIMIT_CENTS
from sonar.web.app import create_app
from tests.seed import seed

TODAY = date(2026, 9, 23)


def _client(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "t.db"
    seed(db_path)
    return TestClient(create_app(db_path, today=lambda: TODAY))


def test_put_salary_day_on_fresh_db_then_get_shows_it_with_default_overdraft(tmp_path):
    with _client(tmp_path) as client:
        put = client.put("/api/settings", json={"salary_day": 25})
        got = client.get("/api/settings")

    assert put.status_code == 200
    expected = {
        "salary_day": 25,
        "overdraft_limit_cents": DEFAULT_OVERDRAFT_LIMIT_CENTS,
        "balance": None,
    }
    assert got.status_code == 200
    assert got.json() == expected
    assert put.json() == expected


def test_get_on_fresh_db_has_no_salary_day_and_null_balance(tmp_path):
    with _client(tmp_path) as client:
        body = client.get("/api/settings").json()

    assert body["salary_day"] is None
    assert body["balance"] is None


def test_get_shows_a_manual_balance(tmp_path):
    with _client(tmp_path) as client:
        client.post("/api/settings/balance", json={"amount_cents": 123_45, "as_of": "2026-09-20"})
        body = client.get("/api/settings").json()

    assert body["balance"] == {"amount_cents": 123_45, "as_of": "2026-09-20", "source": "manual"}


def test_partial_put_keeps_the_other_value(tmp_path):
    with _client(tmp_path) as client:
        client.put("/api/settings", json={"salary_day": 25, "overdraft_limit_cents": -50_000})
        only_salary = client.put("/api/settings", json={"salary_day": 10})
        only_limit = client.put("/api/settings", json={"overdraft_limit_cents": -20_000})

    assert only_salary.json()["salary_day"] == 10
    assert only_salary.json()["overdraft_limit_cents"] == -50_000
    assert only_limit.json()["salary_day"] == 10
    assert only_limit.json()["overdraft_limit_cents"] == -20_000


def test_put_without_any_salary_day_on_a_fresh_db_is_400(tmp_path):
    with _client(tmp_path) as client:
        response = client.put("/api/settings", json={"overdraft_limit_cents": -100})

    assert response.status_code == 400
    assert response.json() == {"error": "salary_day is required", "field": "salary_day"}


def test_put_salary_day_out_of_range_is_400_on_that_field(tmp_path):
    with _client(tmp_path) as client:
        responses = [client.put("/api/settings", json={"salary_day": day}) for day in (0, 32)]

    for response in responses:
        assert response.status_code == 400
        assert response.json()["field"] == "salary_day"
        assert response.json()["error"] == "Salary day must be between 1 and 31."


def test_put_positive_overdraft_limit_is_400_on_that_field(tmp_path):
    with _client(tmp_path) as client:
        response = client.put("/api/settings", json={"salary_day": 25, "overdraft_limit_cents": 1})

    assert response.status_code == 400
    assert response.json()["field"] == "overdraft_limit_cents"


def test_put_text_in_an_int_field_is_422(tmp_path):
    with _client(tmp_path) as client:
        response = client.put("/api/settings", json={"salary_day": "abc"})

    assert response.status_code == 422


def test_post_balance_accepts_a_negative_amount(tmp_path):
    with _client(tmp_path) as client:
        response = client.post(
            "/api/settings/balance", json={"amount_cents": -250_00, "as_of": "2026-09-23"}
        )

    assert response.status_code == 200
    assert response.json()["balance"] == {
        "amount_cents": -250_00,
        "as_of": "2026-09-23",
        "source": "manual",
    }


def test_post_balance_in_the_future_is_400_on_as_of(tmp_path):
    with _client(tmp_path) as client:
        response = client.post(
            "/api/settings/balance", json={"amount_cents": 100, "as_of": "2026-09-24"}
        )

    assert response.status_code == 400
    assert response.json()["field"] == "as_of"


def test_post_balance_with_a_non_iso_date_is_400_on_as_of(tmp_path):
    with _client(tmp_path) as client:
        response = client.post(
            "/api/settings/balance", json={"amount_cents": 100, "as_of": "23.09.2026"}
        )

    assert response.status_code == 400
    assert response.json()["field"] == "as_of"


def test_post_balance_with_a_missing_key_is_400_on_that_field(tmp_path):
    with _client(tmp_path) as client:
        no_amount = client.post("/api/settings/balance", json={"as_of": "2026-09-20"})
        no_date = client.post("/api/settings/balance", json={"amount_cents": 100})

    assert no_amount.status_code == 400
    assert no_amount.json()["field"] == "amount_cents"
    assert no_date.status_code == 400
    assert no_date.json()["field"] == "as_of"


def test_post_balance_text_in_the_amount_is_422(tmp_path):
    with _client(tmp_path) as client:
        response = client.post(
            "/api/settings/balance", json={"amount_cents": "12.50", "as_of": "2026-09-20"}
        )

    assert response.status_code == 422


def test_settings_api_needs_the_bearer_token_when_sign_in_is_on(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)
    auth = AuthSettings(
        google_client_id="client-id",
        google_client_secret="client-secret",
        session_secret="session-secret",
        base_url="http://testserver",
        api_token="s3cret-token",
    )
    with TestClient(create_app(db_path, auth=auth), follow_redirects=False) as client:
        refused = client.get("/api/settings")
        allowed = client.get("/api/settings", headers={"Authorization": "Bearer s3cret-token"})

    assert refused.status_code == 401
    assert allowed.status_code == 200
