"""Tests for the in-memory sign-in code store (SPEC §13 Sign-in)."""

import re
from datetime import UTC, datetime, timedelta

import pytest

from sonar.auth.codes import SignInCodes, TooManyAttempts

OWNER = "owner@example.com"
CLIENT = "203.0.113.5"
TEN = datetime(2026, 10, 12, 10, 0, tzinfo=UTC)


def minutes(n: int) -> timedelta:
    return timedelta(minutes=n)


def test_valid_code_redeems_to_its_email_inside_the_ttl():
    codes = SignInCodes()
    code = codes.issue(OWNER, TEN)
    assert codes.redeem(code, CLIENT, TEN + minutes(4)) == OWNER


def test_every_code_is_six_digits():
    codes = SignInCodes()
    for _ in range(50):
        assert re.fullmatch(r"\d{6}", codes.issue(OWNER, TEN))


@pytest.mark.parametrize(
    "age", [minutes(5), minutes(6), minutes(60)], ids=["exact", "after", "hour"]
)
def test_code_is_rejected_from_five_minutes_on(age):
    codes = SignInCodes()
    code = codes.issue(OWNER, TEN)
    assert codes.redeem(code, CLIENT, TEN + age) is None


def test_code_is_single_use():
    codes = SignInCodes()
    code = codes.issue(OWNER, TEN)
    assert codes.redeem(code, CLIENT, TEN + minutes(1)) == OWNER
    assert codes.redeem(code, CLIENT, TEN + minutes(2)) is None


def test_wrong_code_is_rejected():
    codes = SignInCodes()
    code = codes.issue(OWNER, TEN)
    wrong = f"{(int(code) + 1) % 10**6:06d}"
    assert codes.redeem(wrong, CLIENT, TEN + minutes(1)) is None
    assert codes.redeem(code, CLIENT, TEN + minutes(2)) == OWNER


@pytest.mark.parametrize("bad", ["12345", "12a456", "", "1234567", "١٢٣٤٥٦"])
def test_malformed_code_is_rejected(bad):
    codes = SignInCodes()
    codes.issue(OWNER, TEN)
    assert codes.redeem(bad, CLIENT, TEN + minutes(1)) is None


def test_code_is_trimmed_before_checking():
    codes = SignInCodes()
    code = codes.issue(OWNER, TEN)
    assert codes.redeem(f" {code}\n", CLIENT, TEN + minutes(1)) == OWNER


def test_second_issue_for_the_same_email_voids_the_first():
    codes = SignInCodes()
    first = codes.issue(OWNER, TEN)
    second = codes.issue(OWNER, TEN + minutes(1))
    if first != second:
        assert codes.redeem(first, CLIENT, TEN + minutes(2)) is None
    assert codes.redeem(second, CLIENT, TEN + minutes(2)) == OWNER


def test_codes_for_different_emails_coexist():
    codes = SignInCodes()
    a = codes.issue(OWNER, TEN)
    b = codes.issue("spouse@example.com", TEN)
    if a != b:
        assert codes.redeem(b, CLIENT, TEN + minutes(1)) == "spouse@example.com"
        assert codes.redeem(a, CLIENT, TEN + minutes(1)) == OWNER


def test_sixth_attempt_from_one_client_raises_even_with_a_valid_code():
    codes = SignInCodes()
    code = codes.issue(OWNER, TEN)
    for i in range(5):
        assert codes.redeem("000000x", CLIENT, TEN + minutes(i)) is None
    with pytest.raises(TooManyAttempts):
        codes.redeem(code, CLIENT, TEN + minutes(6))


def test_limited_attempt_is_not_counted_or_checked():
    codes = SignInCodes()
    code = codes.issue(OWNER, TEN)
    for i in range(5):
        codes.redeem("abc", "198.51.100.1", TEN + minutes(i * 2))
    # the pending code was dropped by the store-wide lock, so reissue
    code = codes.issue(OWNER, TEN + minutes(9))
    for _ in range(3):
        with pytest.raises(TooManyAttempts):
            codes.redeem(code, "198.51.100.1", TEN + minutes(9))
    # still valid for another client: the limited attempts did not burn it
    assert codes.redeem(code, CLIENT, TEN + minutes(9)) == OWNER


def test_client_succeeds_again_after_fifteen_minutes():
    codes = SignInCodes()
    for _ in range(5):
        codes.redeem("abc", CLIENT, TEN)
    with pytest.raises(TooManyAttempts):
        codes.redeem("abc", CLIENT, TEN + minutes(14))
    code = codes.issue(OWNER, TEN + minutes(15))
    assert codes.redeem(code, CLIENT, TEN + minutes(15)) == OWNER


def test_successful_attempts_count_toward_the_limit():
    codes = SignInCodes()
    for i in range(5):
        code = codes.issue(OWNER, TEN + minutes(i))
        assert codes.redeem(code, CLIENT, TEN + minutes(i)) == OWNER
    code = codes.issue(OWNER, TEN + minutes(6))
    with pytest.raises(TooManyAttempts):
        codes.redeem(code, CLIENT, TEN + minutes(6))


def test_another_client_is_not_limited():
    codes = SignInCodes()
    for _ in range(4):
        codes.redeem("abc", CLIENT, TEN)
    code = codes.issue(OWNER, TEN)
    assert codes.redeem(code, "198.51.100.9", TEN) == OWNER


def test_five_rejections_across_clients_invalidate_pending_codes():
    codes = SignInCodes()
    code = codes.issue(OWNER, TEN)
    for i in range(5):
        assert codes.redeem("abc", f"198.51.100.{i}", TEN + minutes(1)) is None
    assert codes.redeem(code, CLIENT, TEN + minutes(2)) is None


def test_failure_counter_resets_after_invalidation():
    codes = SignInCodes()
    codes.issue(OWNER, TEN)
    for i in range(5):
        codes.redeem("abc", f"198.51.100.{i}", TEN)
    code = codes.issue(OWNER, TEN + minutes(1))
    for i in range(4):
        codes.redeem("abc", f"198.51.101.{i}", TEN + minutes(1))
    assert codes.redeem(code, CLIENT, TEN + minutes(1)) == OWNER


def test_plaintext_code_is_never_stored():
    codes = SignInCodes()
    code = codes.issue(OWNER, TEN)
    assert code.encode() not in repr(vars(codes)).encode()
    assert code not in repr(vars(codes))


def test_expired_codes_and_stale_attempts_are_pruned():
    codes = SignInCodes()
    for i in range(20):
        codes.issue(f"user{i}@example.com", TEN)
        codes.redeem("abc", f"198.51.100.{i}", TEN)
    codes.redeem("abc", CLIENT, TEN + minutes(30))
    state = vars(codes)
    sizes = [len(v) for v in state.values() if hasattr(v, "__len__") and not isinstance(v, bytes)]
    assert max(sizes) <= 1
