"""Tests for the JSON API's debt draft endpoints (SPEC §13 Draft debts, Debts API): N04."""

from __future__ import annotations

import pytest

from tests.web.test_api_debts import (
    AUTH,
    INSTALLMENT,
    LOAN,
    TOKEN,
    _bearer,
    _client,
    _open_drafts,
    _stored,
    db_path,  # noqa: F401  (fixture)
)

DRAFT_KEYS = {
    "id",
    "detection_key",
    "name",
    "rate_cents",
    "interval_months",
    "first_payment_date",
    "match_field",
    "match_value",
}


def _draft_id(client) -> int:
    [draft] = client.get("/api/debts/drafts").json()
    return draft["id"]


def test_get_lists_the_open_draft_with_its_prefill(db_path):  # noqa: F811
    with _client(db_path) as client:
        response = client.get("/api/debts/drafts")

    assert response.status_code == 200
    [draft] = response.json()
    assert set(draft) == DRAFT_KEYS
    assert draft["rate_cents"] == 10_000
    assert draft["interval_months"] == 1
    assert draft["first_payment_date"] == "2026-07-05"
    assert draft["match_field"] == "counterparty"
    assert draft["match_value"] == "Car Bank"
    assert draft["name"]
    assert draft["detection_key"]


def test_post_installment_completes_the_draft_and_get_no_longer_lists_it(db_path):  # noqa: F811
    with _client(db_path) as client:
        draft_id = _draft_id(client)
        posted = client.post(f"/api/debts/drafts/{draft_id}", json=INSTALLMENT)
        after = client.get("/api/debts/drafts")
        debts = client.get("/api/debts").json()

    assert posted.status_code == 201
    assert posted.json()["kind"] == "installment"
    assert posted.json() == debts[0]
    assert after.json() == []
    assert _open_drafts(db_path) == 0
    assert len(_stored(db_path)) == 1


def test_post_loan_completes_the_draft(db_path):  # noqa: F811
    with _client(db_path) as client:
        draft_id = _draft_id(client)
        posted = client.post(f"/api/debts/drafts/{draft_id}", json=LOAN)
        after = client.get("/api/debts/drafts")

    assert posted.status_code == 201
    assert posted.json()["kind"] == "loan"
    assert posted.json()["balance_cents"] == 500_000
    assert after.json() == []
    assert [s.debt.name for s in _stored(db_path)] == ["Home Bank"]


def test_second_post_on_the_same_draft_is_404_and_adds_nothing(db_path):  # noqa: F811
    with _client(db_path) as client:
        draft_id = _draft_id(client)
        client.post(f"/api/debts/drafts/{draft_id}", json=INSTALLMENT)
        second = client.post(f"/api/debts/drafts/{draft_id}", json=INSTALLMENT)

    assert second.status_code == 404
    assert second.json() == {"error": f"No such draft: {draft_id}"}
    assert len(_stored(db_path)) == 1


def test_post_unknown_draft_is_404(db_path):  # noqa: F811
    with _client(db_path) as client:
        response = client.post("/api/debts/drafts/999", json=INSTALLMENT)

    assert response.status_code == 404
    assert response.json() == {"error": "No such draft: 999"}
    assert _stored(db_path) == []


@pytest.mark.parametrize(
    "body,field",
    [
        ({**INSTALLMENT, "kind": "mortgage"}, "kind"),
        ({**INSTALLMENT, "balance_cents": 5}, "balance_cents"),
        ({**INSTALLMENT, "total_cents": 0}, "total_cents"),
        ({**INSTALLMENT, "first_payment_date": "05/07/2026"}, "first_payment_date"),
        ({**INSTALLMENT, "match_field": "iban"}, "match_field"),
    ],
)
def test_post_bad_body_answers_400_with_field_and_keeps_the_draft(db_path, body, field):  # noqa: F811
    with _client(db_path) as client:
        draft_id = _draft_id(client)
        response = client.post(f"/api/debts/drafts/{draft_id}", json=body)

    assert response.status_code == 400
    assert response.json()["field"] == field
    assert response.json()["error"]
    assert _stored(db_path) == []
    assert _open_drafts(db_path) == 1


def test_bad_body_for_an_unknown_draft_is_400_not_404(db_path):  # noqa: F811
    with _client(db_path) as client:
        response = client.post("/api/debts/drafts/999", json={**INSTALLMENT, "total_cents": 0})

    assert response.status_code == 400
    assert response.json()["field"] == "total_cents"


def test_get_drafts_does_not_clash_with_delete_by_id(db_path):  # noqa: F811
    with _client(db_path) as client:
        created = client.post("/api/debts", json=INSTALLMENT).json()
        deleted = client.delete(f"/api/debts/{created['id']}")
        listed = client.get("/api/debts/drafts")

    assert deleted.status_code == 200
    assert listed.status_code == 200


def test_with_sign_in_on_the_right_bearer_reaches_post_and_a_wrong_one_gets_401(db_path):  # noqa: F811
    with _client(db_path, auth=AUTH) as client:
        draft_id = _draft_id_with(client, _bearer(TOKEN))
        wrong = client.post(
            f"/api/debts/drafts/{draft_id}", json=INSTALLMENT, headers=_bearer("wrong")
        )
        right = client.post(
            f"/api/debts/drafts/{draft_id}", json=INSTALLMENT, headers=_bearer(TOKEN)
        )

    assert wrong.status_code == 401
    assert right.status_code == 201
    assert len(_stored(db_path)) == 1


def _draft_id_with(client, headers) -> int:
    [draft] = client.get("/api/debts/drafts", headers=headers).json()
    return draft["id"]
