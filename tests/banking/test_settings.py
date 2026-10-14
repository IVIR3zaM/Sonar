"""Bank sync settings and private key check (SPEC §13 Bank sync)."""

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from sonar.banking.settings import (
    ASPSP_COUNTRY,
    ASPSP_NAME,
    BANK_ENV_VARS,
    BankSettings,
    bank_settings,
    read_private_key,
)

FULL_ENV = {
    "SONAR_ENABLE_BANKING_APP_ID": "app-id",
    "SONAR_ENABLE_BANKING_KEY_PATH": "/keys/enable.pem",
}


def _pem() -> bytes:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def test_the_bank_is_deutsche_bank_germany():
    assert (ASPSP_NAME, ASPSP_COUNTRY) == ("Deutsche Bank", "DE")


def test_bank_settings_none_when_unset():
    assert bank_settings({"SONAR_DB_PATH": "x.db"}) is None


def test_bank_settings_empty_values_count_as_unset():
    assert bank_settings(dict.fromkeys(BANK_ENV_VARS, "")) is None


@pytest.mark.parametrize("missing", BANK_ENV_VARS)
def test_bank_settings_one_setting_alone_names_the_missing_one(missing):
    env = {name: value for name, value in FULL_ENV.items() if name != missing}

    with pytest.raises(ValueError, match=f"missing: {missing}$"):
        bank_settings(env)


def test_bank_settings_an_empty_value_in_a_partial_set_is_named_missing():
    env = {**FULL_ENV, "SONAR_ENABLE_BANKING_APP_ID": ""}

    with pytest.raises(ValueError, match="SONAR_ENABLE_BANKING_APP_ID"):
        bank_settings(env)


def test_bank_settings_redirect_url_from_the_base_url_without_trailing_slash():
    env = {**FULL_ENV, "SONAR_BASE_URL": "https://sonar.example.com/", "SONAR_PORT": "9000"}

    settings = bank_settings(env)

    assert settings is not None
    assert settings.redirect_url == "https://sonar.example.com/bank/callback"
    assert settings.app_id == "app-id"
    assert str(settings.key_path) == "/keys/enable.pem"


def test_bank_settings_redirect_url_from_the_port_without_a_base_url():
    settings = bank_settings({**FULL_ENV, "SONAR_PORT": "9000"})

    assert settings is not None
    assert settings.redirect_url == "http://127.0.0.1:9000/bank/callback"


def test_bank_settings_redirect_url_defaults_to_port_8000_and_ignores_an_empty_base_url():
    settings = bank_settings({**FULL_ENV, "SONAR_BASE_URL": "", "SONAR_PORT": ""})

    assert isinstance(settings, BankSettings)
    assert settings.redirect_url == "http://127.0.0.1:8000/bank/callback"


def test_private_key_returns_the_file_bytes(tmp_path):
    served = tmp_path / "static"
    served.mkdir()
    key_file = tmp_path / "enable.pem"
    key_file.write_bytes(data := _pem())

    assert read_private_key(key_file, served) == data


def test_private_key_under_the_served_dir_is_refused(tmp_path):
    served = tmp_path / "static"
    served.mkdir()
    key_file = served / "enable.pem"
    key_file.write_bytes(_pem())

    with pytest.raises(ValueError, match="enable.pem"):
        read_private_key(key_file, served)


def test_private_key_reached_by_a_symlink_into_the_served_dir_is_refused(tmp_path):
    served = tmp_path / "static"
    served.mkdir()
    (served / "enable.pem").write_bytes(_pem())
    link = tmp_path / "link.pem"
    link.symlink_to(served / "enable.pem")

    with pytest.raises(ValueError, match="link.pem"):
        read_private_key(link, served)


def test_private_key_missing_path_is_refused(tmp_path):
    with pytest.raises(ValueError, match="missing.pem"):
        read_private_key(tmp_path / "missing.pem", tmp_path / "static")


def test_private_key_directory_is_refused(tmp_path):
    keys = tmp_path / "keys"
    keys.mkdir()

    with pytest.raises(ValueError, match="keys"):
        read_private_key(keys, tmp_path / "static")


def test_private_key_non_pem_file_is_refused_without_its_text(tmp_path):
    key_file = tmp_path / "enable.pem"
    key_file.write_text("super-secret-not-a-key")

    with pytest.raises(ValueError, match="enable.pem") as error:
        read_private_key(key_file, tmp_path / "static")

    assert "super-secret" not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__
