"""Tests for `POST /api/reapply` (SPEC §5, §13)."""

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from sonar.web.app import create_app
from tests.seed import seed

FIXTURE = Path(__file__).parent.parent / "fixtures" / "db_girokonto.csv"
TODAY = date(2026, 9, 23)

RESTAURANT_RULE_TOML = """
[[category]]
name = "Dining"
type = "variable"

[[rule]]
category = "Dining"
counterparty = "Restaurant XYZ"
"""


def test_reapply_categorizes_after_a_rule_lands_in_the_store_and_returns_the_new_count(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)

    with TestClient(create_app(db_path, today=lambda: TODAY)) as client:
        client.post("/import", files=[("files", ("giro.csv", FIXTURE.read_bytes(), "text/csv"))])
        before = client.get("/api/uncategorized").json()["count"]

        seed(db_path, RESTAURANT_RULE_TOML)
        response = client.post("/api/reapply")
        after = client.get("/api/uncategorized").json()["count"]

    assert before == 7
    assert response.status_code == 200
    assert response.json() == {"uncategorized": 5}
    assert after == 5
