"""Dashboard refresh tests (SPEC §9): GET / reflects new data without a restart.

Seed data: the real fixture's footer balance is -448.43 (-44843 cents) as of
2026-09-23, salary day 26, today pinned to 2026-09-23. No recurring payments
or debts are added, so due stays empty and there is no variable category
(the categories.toml is empty), which leaves worst == best == the balance
itself for the traffic light (SPEC §9, T9: "fewer than 3 cycles" gives
worst == best; here there are zero variable rows at all).
"""

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from sonar.app import create_app

FIXTURE = Path(__file__).parent / "fixtures" / "db_girokonto.csv"
TODAY = date(2026, 9, 23)


def _today() -> date:
    return TODAY


def _empty_categories(tmp_path: Path) -> Path:
    path = tmp_path / "categories.toml"
    path.write_text("", encoding="utf-8")
    return path


def test_dashboard_reflects_import_and_settings_without_restart(tmp_path):
    db_path = tmp_path / "t.db"
    categories_path = _empty_categories(tmp_path)
    content = FIXTURE.read_bytes()

    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
        client.post("/import", files=[("files", ("giro.csv", content, "text/csv"))])

        assert (
            client.post(
                "/settings",
                data={"salary_day": "26", "overdraft_limit": "-500.00"},
                follow_redirects=False,
            ).status_code
            == 303
        )

        page = client.get("/").text
        assert "-448.43" in page
        # due_total = 0 (no recurring payments/debts) and no variable category
        # exists in the empty toml, so worst == best == -44843. -44843 is
        # more than -50000, so green.
        assert 'class="light-green"' in page
        assert "Overdraft limit: -500.00" in page

        # The import's footer balance is dated 2026-09-23; posting a manual
        # balance for that same date is a tie, and manual wins ties.
        assert (
            client.post(
                "/settings/balance",
                data={"amount": "-600.00", "as_of": "2026-09-23"},
                follow_redirects=False,
            ).status_code
            == 303
        )

        page = client.get("/").text
        assert "-600.00" in page
        # worst == best == -60000, which is below -50000 (not green) and
        # below -50000 again for the yellow check (best < limit), so red.
        assert 'class="light-red"' in page
        assert "Overdraft limit: -500.00" in page

        assert (
            client.post(
                "/settings",
                data={"salary_day": "26", "overdraft_limit": "-1000"},
                follow_redirects=False,
            ).status_code
            == 303
        )

        page = client.get("/").text
        # worst == best == -60000, which is >= -100000, so green.
        assert 'class="light-green"' in page
        assert "Overdraft limit: -1000.00" in page

        # POST /reapply must not change any of the figures above.
        reapply_response = client.post("/reapply")
        assert reapply_response.status_code == 200

        page = client.get("/").text
        assert "-600.00" in page
        assert 'class="light-green"' in page
        assert "Overdraft limit: -1000.00" in page

        # Re-uploading the same file adds 0 rows and re-stores the same
        # import balance (same date, same amount), which changes nothing.
        client.post("/import", files=[("files", ("giro.csv", content, "text/csv"))])

        page = client.get("/").text
        assert "-600.00" in page
        assert 'class="light-green"' in page
        assert "Overdraft limit: -1000.00" in page

    # A fresh app instance simulates a restart against the same database.
    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
        page = client.get("/").text
        assert "-600.00" in page
        assert 'class="light-green"' in page
        assert "Overdraft limit: -1000.00" in page
