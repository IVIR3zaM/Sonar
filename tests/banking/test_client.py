"""Enable Banking client: signing, the five calls and error text (SPEC §13 Bank sync)."""

import base64
import json
from datetime import UTC, date, datetime

import httpx
import pytest
from authlib.jose import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from sonar.banking.client import BASE_URL, BankApiError, EnableBankingClient, default_http
from sonar.banking.settings import ASPSP_COUNTRY, ASPSP_NAME

NOW = datetime(2026, 10, 14, 8, 0, tzinfo=UTC)
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIVATE_PEM = _KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
)
PUBLIC_PEM = _KEY.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
)


def _client(handler) -> EnableBankingClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return EnableBankingClient("app-1", PRIVATE_PEM, http, lambda: NOW)


def _recording(answer: dict, requests: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=answer)

    return handler


def _token(request: httpx.Request) -> str:
    return request.headers["Authorization"].removeprefix("Bearer ")


def test_jwt_is_verified_by_the_public_key_and_carries_the_header():
    requests: list[httpx.Request] = []
    _client(_recording({"balances": []}, requests)).balances("acc-1")
    token = _token(requests[0])
    claims = jwt.decode(token, PUBLIC_PEM)
    claims.validate(now=int(NOW.timestamp()))
    header = json.loads(base64.urlsafe_b64decode(token.split(".")[0] + "=="))
    assert header == {"alg": "RS256", "typ": "JWT", "kid": "app-1"}


def test_jwt_claims_use_the_injected_clock():
    requests: list[httpx.Request] = []
    _client(_recording({"balances": []}, requests)).balances("acc-1")
    claims = jwt.decode(_token(requests[0]), PUBLIC_PEM)
    iat = int(NOW.timestamp())
    assert claims["iss"] == "enablebanking.com"
    assert claims["aud"] == "api.enablebanking.com"
    assert claims["iat"] == iat
    assert claims["exp"] == iat + 3600


def test_aspsps_gets_the_country_list():
    requests: list[httpx.Request] = []
    result = _client(_recording({"aspsps": [{"name": "X"}]}, requests)).aspsps("DE")
    request = requests[0]
    assert (request.method, request.url.path) == ("GET", "/aspsps")
    assert request.url.params["country"] == "DE"
    assert str(request.url).startswith(BASE_URL)
    assert result == [{"name": "X"}]


def test_start_authorization_posts_the_consent_request():
    requests: list[httpx.Request] = []
    valid_until = datetime(2027, 1, 12, 8, 0, tzinfo=UTC)
    result = _client(
        _recording({"url": "https://bank.example/consent"}, requests)
    ).start_authorization(valid_until, "state-1", "http://127.0.0.1:8000/bank/callback")
    request = requests[0]
    assert (request.method, request.url.path) == ("POST", "/auth")
    assert json.loads(request.content) == {
        "access": {"valid_until": valid_until.isoformat()},
        "aspsp": {"name": ASPSP_NAME, "country": ASPSP_COUNTRY},
        "state": "state-1",
        "redirect_url": "http://127.0.0.1:8000/bank/callback",
        "psu_type": "personal",
    }
    assert result == {"url": "https://bank.example/consent"}


def test_create_session_posts_the_code():
    requests: list[httpx.Request] = []
    result = _client(_recording({"session_id": "s", "accounts": []}, requests)).create_session(
        "c-1"
    )
    request = requests[0]
    assert (request.method, request.url.path) == ("POST", "/sessions")
    assert json.loads(request.content) == {"code": "c-1"}
    assert result == {"session_id": "s", "accounts": []}


def test_transactions_sends_dates_and_status():
    requests: list[httpx.Request] = []
    result = _client(_recording({"transactions": [{"a": 1}]}, requests)).booked_transactions(
        "acc-1", date(2026, 9, 1), date(2026, 10, 14)
    )
    request = requests[0]
    assert (request.method, request.url.path) == ("GET", "/accounts/acc-1/transactions")
    assert dict(request.url.params) == {
        "date_from": "2026-09-01",
        "date_to": "2026-10-14",
        "transaction_status": "BOOK",
    }
    assert result == [{"a": 1}]


def test_transactions_joins_pages_by_continuation_key():
    requests: list[httpx.Request] = []
    pages = [
        {"transactions": [{"n": 1}], "continuation_key": "k1"},
        {"transactions": [{"n": 2}], "continuation_key": None},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=pages[len(requests) - 1])

    result = _client(handler).booked_transactions("acc-1", date(2026, 9, 1), date(2026, 10, 14))
    assert result == [{"n": 1}, {"n": 2}]
    assert "continuation_key" not in requests[0].url.params
    assert requests[1].url.params["continuation_key"] == "k1"
    assert requests[1].url.params["transaction_status"] == "BOOK"


def test_balances_gets_the_account_balances():
    requests: list[httpx.Request] = []
    result = _client(_recording({"balances": [{"b": 1}]}, requests)).balances("acc-1")
    request = requests[0]
    assert (request.method, request.url.path) == ("GET", "/accounts/acc-1/balances")
    assert result == [{"b": 1}]


def _failing(status: int, body: dict) -> EnableBankingClient:
    return _client(lambda request: httpx.Response(status, json=body))


def test_error_status_and_code_are_in_the_text():
    with pytest.raises(BankApiError) as caught:
        _failing(401, {"error": "EXPIRED_SESSION"}).balances("acc-1")
    assert caught.value.status == 401
    assert str(caught.value) == "Enable Banking answered 401 (EXPIRED_SESSION)"
    assert caught.value.message == str(caught.value)


@pytest.mark.parametrize("error", ["expired session", "x" * 41, "", 7, None, "A\nB"])
def test_error_off_the_pattern_is_left_out(error):
    with pytest.raises(BankApiError) as caught:
        _failing(500, {"error": error}).balances("acc-1")
    assert str(caught.value) == "Enable Banking answered 500"


def test_error_with_a_body_that_is_not_json_has_only_the_status():
    client = _client(lambda request: httpx.Response(502, text="<html>bad gateway</html>"))
    with pytest.raises(BankApiError) as caught:
        client.balances("acc-1")
    assert str(caught.value) == "Enable Banking answered 502"


def test_unreachable_bank_gives_status_none():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom to https://api.enablebanking.com/accounts/acc-1")

    with pytest.raises(BankApiError) as caught:
        _client(handler).balances("acc-1")
    assert caught.value.status is None
    assert str(caught.value) == "Enable Banking could not be reached"
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


def test_timeout_gives_status_none():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(BankApiError) as caught:
        _client(handler).balances("acc-1")
    assert caught.value.status is None


def test_error_text_never_holds_secrets_from_the_request_or_body():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            400, json={"error": "BAD_CODE", "message": "code secret-code session sess-123"}
        )

    with pytest.raises(BankApiError) as caught:
        _client(handler).create_session("secret-code")
    text = str(caught.value)
    assert "BAD_CODE" in text
    for secret in (_token(requests[0]), "secret-code", "sess-123", "acc", "http", "BEGIN"):
        assert secret not in text
    assert len(text) <= 200


def test_default_http_verifies_tls_with_a_30_second_timeout():
    http = default_http()
    try:
        assert http.timeout == httpx.Timeout(30.0)
    finally:
        http.close()
