"""Tests for banking/consent.py: state handling, session parsing, banners (SPEC §13 Bank sync)."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from sonar.banking.consent import (
    BankConnection,
    Banner,
    banner,
    card_status,
    consent_seconds,
    new_state,
    parse_session,
    requested_valid_until,
    state_hash,
    state_matches,
)

NOW = datetime(2026, 10, 14, 8, 0, tzinfo=UTC)
ENDS = datetime(2027, 4, 12, 7, 50, tzinfo=UTC)


def _connection(**changes) -> BankConnection:
    base = BankConnection(
        session_id="session-1",
        account_uid="uid-1",
        iban_last4="1234",
        consent_valid_until=ENDS,
        connected_at=NOW,
        last_sync_at=None,
        last_sync_status=None,
        last_sync_added=None,
        last_sync_error=None,
    )
    return replace(base, **changes)


def _account(uid: str, iban: str, cash_account_type: str | None = None) -> dict:
    account = {"uid": uid, "account_id": {"iban": iban}}
    if cash_account_type:
        account["cash_account_type"] = cash_account_type
    return account


def _session(accounts: list[dict]) -> dict:
    return {
        "session_id": "session-1",
        "accounts": accounts,
        "access": {"valid_until": "2027-04-12T07:50:00+00:00"},
    }


def test_requested_valid_until_is_the_maximum_less_ten_minutes():
    assert requested_valid_until(NOW, 15552000) == NOW + timedelta(days=180, minutes=-10)


def test_consent_seconds_of_the_named_bank():
    aspsps = [
        {"name": "Other Bank", "maximum_consent_validity": 100},
        {"name": "Deutsche Bank", "maximum_consent_validity": 15552000},
    ]
    assert consent_seconds(aspsps, "Deutsche Bank") == 15552000


def test_consent_seconds_of_a_missing_bank_raises():
    with pytest.raises(ValueError):
        consent_seconds([{"name": "Other Bank", "maximum_consent_validity": 100}], "Deutsche Bank")


def test_new_states_are_distinct_and_hash_is_sha256_hex():
    assert new_state() != new_state()
    assert len(state_hash("abc")) == 64
    assert state_hash("abc") == state_hash("abc")


def test_matching_state_within_thirty_minutes():
    assert state_matches("s", state_hash("s"), NOW, NOW + timedelta(minutes=29))


def test_wrong_state_does_not_match():
    assert not state_matches("other", state_hash("s"), NOW, NOW)


def test_thirty_minute_old_state_does_not_match():
    assert not state_matches("s", state_hash("s"), NOW, NOW + timedelta(minutes=30))


def test_parse_session_with_one_account():
    parsed = parse_session(_session([_account("uid-1", "DE00000000000000001234")]), NOW)
    assert parsed.session_id == "session-1"
    assert parsed.account_uid == "uid-1"
    assert parsed.iban_last4 == "1234"
    assert parsed.consent_valid_until == ENDS
    assert parsed.connected_at == NOW


def test_parse_session_normalizes_the_consent_end_to_utc():
    session = _session([_account("uid-1", "DE00000000000000001234")])
    session["access"]["valid_until"] = "2027-04-12T09:50:00+02:00"
    assert parse_session(session, NOW).consent_valid_until == ENDS


def test_parse_session_with_two_accounts_picks_the_current_account():
    accounts = [
        _account("uid-s", "DE00000000000000009999", "SVGS"),
        _account("uid-c", "DE00000000000000001234", "CACC"),
    ]
    assert parse_session(_session(accounts), NOW).account_uid == "uid-c"


def test_parse_session_with_no_usable_account_raises():
    accounts = [_account("uid-a", "DE1", "SVGS"), _account("uid-b", "DE2", "SVGS")]
    with pytest.raises(ValueError):
        parse_session(_session(accounts), NOW)
    with pytest.raises(ValueError):
        parse_session(_session([]), NOW)


def test_parse_session_with_a_missing_field_raises():
    session = _session([_account("uid-1", "DE00000000000000001234")])
    del session["access"]
    with pytest.raises(ValueError):
        parse_session(session, NOW)


def test_banner_none_fifteen_days_before_the_end():
    assert banner(_connection(), date(2027, 3, 28)) is None


def test_banner_expiring_fourteen_days_before_the_end():
    assert banner(_connection(), date(2027, 3, 29)) == Banner("expiring", date(2027, 4, 12))


def test_banner_expired_on_the_end_date():
    assert banner(_connection(), date(2027, 4, 12)) == Banner("expired", date(2027, 4, 12))


def test_banner_failed_after_a_failed_sync():
    failed = _connection(
        last_sync_at=datetime(2026, 11, 2, 4, 30, tzinfo=UTC),
        last_sync_status="error",
        last_sync_error="Bank unreachable",
    )
    assert banner(failed, date(2026, 11, 3)) == Banner(
        "failed", date(2026, 11, 2), "Bank unreachable"
    )


def test_banner_expired_beats_failed():
    failed = _connection(
        last_sync_at=datetime(2027, 4, 11, 4, 30, tzinfo=UTC),
        last_sync_status="error",
        last_sync_error="Bank unreachable",
    )
    assert banner(failed, date(2027, 4, 12)).kind == "expired"


def test_banner_failed_beats_expiring():
    failed = _connection(
        last_sync_at=datetime(2027, 4, 1, 4, 30, tzinfo=UTC),
        last_sync_status="error",
        last_sync_error="Bank unreachable",
    )
    assert banner(failed, date(2027, 4, 2)).kind == "failed"


def test_banner_none_when_never_connected():
    assert banner(None, date(2027, 4, 12)) is None


def test_card_statuses():
    assert card_status(None, date(2026, 10, 14)) == "Not connected"
    assert card_status(_connection(), date(2026, 10, 14)) == "Connected"
    assert card_status(_connection(), date(2027, 3, 29)) == "Ends soon"
    assert card_status(_connection(), date(2027, 4, 12)) == "Expired"
