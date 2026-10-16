"""The old /energy pages redirect and the /api/energy alias is gone (SPEC §13 Utilities)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sonar.web.app import create_app
from tests.seed import seed


@pytest.fixture
def client(tmp_path):
    path = tmp_path / "t.db"
    seed(path, "")
    with TestClient(create_app(path), follow_redirects=False) as client:
        yield client


@pytest.mark.parametrize(
    ("old", "new"),
    [("/energy", "/utilities"), ("/energy/meters/7", "/utilities/meters/7")],
)
def test_the_old_energy_pages_redirect_permanently(client, old, new):
    response = client.get(old)

    assert response.status_code == 301
    assert response.headers["location"] == new


def test_the_api_lives_under_utilities_only(client):
    assert client.get("/api/energy").status_code == 404
    assert client.get("/api/utilities").json() == {"meters": []}
