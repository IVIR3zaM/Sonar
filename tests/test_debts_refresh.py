"""Tests for the re-run paths of debts (SPEC §7): restart, re-import, re-detect.

`debt_overview` recomputes status and links fresh from stored transactions on
every call (see debt_store.py), so these tests exercise the app's existing
routes (restart, /import, /reapply) rather than any dedicated sync step.
"""

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from sonar.app import create_app

FIXTURE = Path(__file__).parent / "fixtures" / "db_girokonto.csv"
FIXTURE_LINES = FIXTURE.read_text(encoding="utf-8-sig").splitlines()
PREAMBLE_AND_HEADER = FIXTURE_LINES[:8]  # lines 1-8: preamble + the 18-column header
FOOTER = FIXTURE_LINES[-1]  # "Account balance;9/23/2026;;;-448.43;EUR"

FITNESS_VARIABLE_TOML = """
[[category]]
name = "Fitness"
type = "variable"

[[rule]]
category = "Fitness"
counterparty = "Fake Gym"
"""


def _today() -> date:
    return date(2026, 9, 23)


def _empty_categories(tmp_path: Path) -> Path:
    path = tmp_path / "categories.toml"
    path.write_text("", encoding="utf-8")
    return path


def _debit_row(booking_date: str, counterparty: str, debit: str) -> str:
    # Same 18-column layout as the fixture's data rows; only booking/value
    # date, counterparty, purpose and the Debit column are filled in.
    fields = [
        booking_date,
        booking_date,
        "Standing Order",
        counterparty,
        "Payment",
        "",  # IBAN
        "",  # BIC
        "",  # Customer Reference
        "",  # Mandate Reference
        "",  # Creditor ID
        "",  # Compensation amount
        "",  # Original Amount
        "",  # Ultimate creditor
        "",  # Number of transactions
        "",  # Number of cheques
        debit,  # Debit
        "",  # Credit
        "EUR",
    ]
    return ";".join(fields)


def _csv_bytes(rows: list[str]) -> bytes:
    return "\n".join([*PREAMBLE_AND_HEADER, *rows, FOOTER]).encode("utf-8")


def test_debts_survive_restart_against_same_db(tmp_path):
    db_path = tmp_path / "t.db"
    categories_path = _empty_categories(tmp_path)

    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
        assert (
            client.post(
                "/debts/installments",
                follow_redirects=False,
                data={
                    "name": "Sofa",
                    "total": "1200.00",
                    "rate": "100.00",
                    "interval_months": "1",
                    "first_payment_date": "2026-01-05",
                    "payments_count": "12",
                    "match_field": "counterparty",
                    "match_value": "Sofa Shop",
                },
            ).status_code
            == 303
        )
        assert (
            client.post(
                "/debts/loans",
                follow_redirects=False,
                data={
                    "name": "Car loan",
                    "balance": "5000.00",
                    "balance_as_of": "2026-06-30",
                    "rate": "1000.00",
                    "interest": "",
                    "match_field": "mandate",
                    "match_value": "CAR-1",
                },
            ).status_code
            == 303
        )

    # A fresh app instance simulates a restart against the same database.
    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
        page = client.get("/debts")
        assert page.status_code == 200
        assert "Sofa" in page.text
        assert "Car loan" in page.text


def test_paid_so_far_tracks_reupload_and_new_debits(tmp_path):
    db_path = tmp_path / "t.db"
    categories_path = _empty_categories(tmp_path)

    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
        assert (
            client.post(
                "/debts/installments",
                follow_redirects=False,
                data={
                    "name": "Shop Debt",
                    "total": "10000.00",
                    "rate": "100.00",
                    "interval_months": "1",
                    "first_payment_date": "2026-01-01",
                    "payments_count": "24",
                    "match_field": "counterparty",
                    "match_value": "Shop A",
                },
            ).status_code
            == 303
        )

        two_rows = [
            _debit_row("1/5/2026", "Shop A", "-100.00"),
            _debit_row("2/5/2026", "Shop A", "-100.00"),
        ]
        content_two = _csv_bytes(two_rows)
        client.post("/import", files=[("files", ("a.csv", content_two, "text/csv"))])
        assert "200.00" in client.get("/debts").text

        # Re-uploading the exact same file must not double-count the debits.
        client.post("/import", files=[("files", ("a.csv", content_two, "text/csv"))])
        assert "200.00" in client.get("/debts").text

        # An overlapping upload that adds one more debit brings the total up.
        three_rows = [*two_rows, _debit_row("3/5/2026", "Shop A", "-100.00")]
        content_three = _csv_bytes(three_rows)
        client.post("/import", files=[("files", ("a.csv", content_three, "text/csv"))])
        assert "300.00" in client.get("/debts").text


def test_upload_links_detected_series_without_extra_action(tmp_path):
    db_path = tmp_path / "t.db"
    categories_path = _empty_categories(tmp_path)  # uncategorized rows are detected too

    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
        assert (
            client.post(
                "/debts/installments",
                follow_redirects=False,
                data={
                    "name": "Gym Membership",
                    "total": "10000.00",
                    "rate": "50.00",
                    "interval_months": "1",
                    "first_payment_date": "2026-07-01",
                    "payments_count": "24",
                    "match_field": "counterparty",
                    "match_value": "Fake Gym",
                },
            ).status_code
            == 303
        )

        # Before any matching transactions exist, "Fake Gym" only shows up
        # once, in the debt's own match-rule column.
        before = client.get("/debts").text
        assert before.count("Fake Gym") == 1

        rows = [_debit_row(d, "Fake Gym", "-50.00") for d in ("7/1/2026", "8/1/2026", "9/1/2026")]
        client.post("/import", files=[("files", ("gym.csv", _csv_bytes(rows), "text/csv"))])

        # A single /import call both stores the debits and (via sync_detected)
        # detects the recurring series; /debts must show the link right away,
        # once for the match rule and once for the linked payment's name.
        after = client.get("/debts").text
        assert after.count("Fake Gym") == 2


def test_reapply_making_series_variable_removes_the_link(tmp_path):
    db_path = tmp_path / "t.db"
    categories_path = _empty_categories(tmp_path)

    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
        client.post(
            "/debts/installments",
            data={
                "name": "Gym Membership",
                "total": "10000.00",
                "rate": "50.00",
                "interval_months": "1",
                "first_payment_date": "2026-07-01",
                "payments_count": "24",
                "match_field": "counterparty",
                "match_value": "Fake Gym",
            },
        )
        rows = [_debit_row(d, "Fake Gym", "-50.00") for d in ("7/1/2026", "8/1/2026", "9/1/2026")]
        client.post("/import", files=[("files", ("gym.csv", _csv_bytes(rows), "text/csv"))])
        assert client.get("/debts").text.count("Fake Gym") == 2  # linked, per the test above

        # Marking the matching counterparty's category "variable" makes
        # detection drop the series; /reapply must re-run detection and the
        # debt page's link must disappear with it.
        categories_path.write_text(FITNESS_VARIABLE_TOML, encoding="utf-8")
        response = client.post("/reapply")
        assert response.status_code == 200

        after = client.get("/debts").text
        assert after.count("Fake Gym") == 1  # back to just the match-rule column
