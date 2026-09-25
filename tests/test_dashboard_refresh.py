"""Dashboard refresh tests (SPEC §9): GET / reflects new data without a restart.

Seed data: the real fixture's footer balance is -448.43 (-44843 cents) as of
2026-09-23, salary day 26, today pinned to 2026-09-23. No recurring payments
or debts are added, so due stays empty and there is no Keep-the-lights-on
category (the taxonomy is empty), which leaves worst == best == the balance
itself for the traffic light (SPEC §9, §13 Forecast: nothing to forecast
gives worst == best; here there are zero lights-on rows at all).
"""

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from sonar.app import create_app
from tests.html import cents, soup
from tests.seed import seed

FIXTURE = Path(__file__).parent / "fixtures" / "db_girokonto.csv"
TODAY = date(2026, 9, 23)


def _today() -> date:
    return TODAY


def _figures(client: TestClient) -> tuple[int, str, int]:
    """Balance cents, traffic light and overdraft limit cents shown on GET /."""
    page = soup(client.get("/"))
    return (
        cents(page.select_one("#balance")),
        page.select_one("#traffic-light")["data-light"],
        cents(page.select_one("#overdraft-limit")),
    )


def test_dashboard_reflects_import_and_settings_without_restart(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)
    content = FIXTURE.read_bytes()

    with TestClient(create_app(db_path, today=_today)) as client:
        client.post("/import", files=[("files", ("giro.csv", content, "text/csv"))])

        assert (
            client.post(
                "/settings",
                data={"salary_day": "26", "overdraft_limit": "-500.00"},
                follow_redirects=False,
            ).status_code
            == 303
        )

        # due_total = 0 (no recurring payments/debts) and no lights-on category
        # exists in the empty taxonomy, so worst == best == -44843. -44843 is
        # more than -50000, so green.
        assert _figures(client) == (-44_843, "green", -50_000)

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

        # worst == best == -60000, which is below -50000 (not green) and
        # below -50000 again for the yellow check (best < limit), so red.
        assert _figures(client) == (-60_000, "red", -50_000)

        assert (
            client.post(
                "/settings",
                data={"salary_day": "26", "overdraft_limit": "-1000"},
                follow_redirects=False,
            ).status_code
            == 303
        )

        # worst == best == -60000, which is >= -100000, so green.
        assert _figures(client) == (-60_000, "green", -100_000)

        # POST /reapply must not change any of the figures above.
        reapply_response = client.post("/reapply")
        assert reapply_response.status_code == 200

        assert _figures(client) == (-60_000, "green", -100_000)

        # Re-uploading the same file adds 0 rows and re-stores the same
        # import balance (same date, same amount), which changes nothing.
        client.post("/import", files=[("files", ("giro.csv", content, "text/csv"))])

        assert _figures(client) == (-60_000, "green", -100_000)

    # A fresh app instance simulates a restart against the same database.
    with TestClient(create_app(db_path, today=_today)) as client:
        assert _figures(client) == (-60_000, "green", -100_000)
