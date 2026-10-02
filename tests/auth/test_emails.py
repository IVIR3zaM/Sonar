"""Tests for the pure email normalizer (SPEC §13 Access list)."""

import pytest

from sonar.auth.emails import normalize_email


def test_normalize_trims_and_lowercases():
    assert normalize_email("  Owner@Example.COM ") == "owner@example.com"


@pytest.mark.parametrize(
    "bad",
    ["a@b@example.com", "nobody", "@example.com", "owner@", "", "   ", "@"],
    ids=["two_at", "no_at", "empty_local", "empty_domain", "empty", "blank", "only_at"],
)
def test_normalize_rejects_invalid_email(bad):
    with pytest.raises(ValueError, match="email"):
        normalize_email(bad)
