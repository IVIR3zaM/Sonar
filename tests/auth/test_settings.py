"""Sign-in settings from the environment (SPEC §13 Sign-in)."""

from itertools import combinations

import pytest

from sonar.auth.settings import AUTH_ENV_VARS, AuthSettings, auth_settings

FULL_ENV = {
    "SONAR_GOOGLE_CLIENT_ID": "client-id",
    "SONAR_GOOGLE_CLIENT_SECRET": "client-secret",
    "SONAR_SESSION_SECRET": "session-secret",
    "SONAR_BASE_URL": "https://sonar.example.com/",
}


def test_no_settings_means_no_sign_in():
    assert auth_settings({"SONAR_DB_PATH": "x.db"}) is None


def test_empty_values_count_as_unset():
    assert auth_settings(dict.fromkeys(AUTH_ENV_VARS, "")) is None


def test_all_four_settings_turn_sign_in_on_without_trailing_slash():
    assert auth_settings(FULL_ENV) == AuthSettings(
        google_client_id="client-id",
        google_client_secret="client-secret",
        session_secret="session-secret",
        base_url="https://sonar.example.com",
    )


@pytest.mark.parametrize(
    "missing",
    [set(names) for size in (1, 2, 3) for names in combinations(AUTH_ENV_VARS, size)],
)
def test_a_partial_set_names_exactly_the_missing_vars(missing):
    env = {name: value for name, value in FULL_ENV.items() if name not in missing}

    with pytest.raises(ValueError) as error:
        auth_settings(env)

    named = {name for name in AUTH_ENV_VARS if name in str(error.value)}
    assert named == missing


def test_an_empty_value_in_a_partial_set_is_named_missing():
    env = {**FULL_ENV, "SONAR_SESSION_SECRET": ""}

    with pytest.raises(ValueError, match="SONAR_SESSION_SECRET"):
        auth_settings(env)


def test_secure_cookies_only_with_an_https_base_url():
    https = auth_settings(FULL_ENV)
    http = auth_settings({**FULL_ENV, "SONAR_BASE_URL": "http://localhost:8000"})

    assert https is not None and https.secure_cookies
    assert http is not None and not http.secure_cookies
