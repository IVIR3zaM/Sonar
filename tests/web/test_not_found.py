"""Unknown routes and unknown ids render the styled error page (SPEC §12)."""

from pathlib import Path

from fastapi.testclient import TestClient

from sonar.web.app import create_app
from tests.html import soup
from tests.seed import seed


def _app(tmp_path: Path):
    db_path = tmp_path / "t.db"
    seed(db_path)
    return create_app(db_path)


def test_unknown_route_returns_404_with_friendly_message(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        response = client.get("/nope")

    assert response.status_code == 404
    page = soup(response)
    heading = page.select_one("#error-page h1")
    assert heading is not None
    assert heading.get_text(strip=True) == "Page not found"
    detail = page.select_one("#error-message")
    assert detail is not None
    assert detail.get_text(strip=True) == "That page or item does not exist."


def test_unknown_payment_dismiss_returns_404_with_error_message(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        response = client.post("/recurring/999/dismiss")

    assert response.status_code == 404
    page = soup(response)
    detail = page.select_one("#error-message")
    assert detail is not None
    assert "No such payment" in detail.get_text(strip=True)
