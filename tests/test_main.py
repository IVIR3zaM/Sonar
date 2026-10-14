"""Tests for the __main__ entry point."""

import logging
import logging.config
from unittest.mock import patch

import pytest
from fastapi import FastAPI

from sonar.auth.settings import AUTH_ENV_VARS, AuthSettings
from sonar.banking.settings import BANK_ENV_VARS, BankSettings
from sonar.web.app import STATIC_DIR

FULL_AUTH_ENV = {
    "SONAR_GOOGLE_CLIENT_ID": "client-id",
    "SONAR_GOOGLE_CLIENT_SECRET": "client-secret",
    "SONAR_SESSION_SECRET": "session-secret",
    "SONAR_BASE_URL": "https://sonar.example.com/",
}


@pytest.fixture(autouse=True)
def no_server_env(monkeypatch):
    """The developer's own shell must not turn sign-in on or move the port in these tests."""
    for name in (*AUTH_ENV_VARS, *BANK_ENV_VARS, "SONAR_API_TOKEN", "SONAR_PORT"):
        monkeypatch.delenv(name, raising=False)


def test_main_runs_uvicorn_with_correct_args():
    """main() calls uvicorn.run with FastAPI app, host="127.0.0.1" and port=8000."""
    with patch("sonar.__main__.uvicorn") as mock_uvicorn:
        from sonar.__main__ import main

        main()

        # Verify uvicorn.run was called exactly once
        assert mock_uvicorn.run.call_count == 1

        # Get the call arguments
        call_args = mock_uvicorn.run.call_args
        args, kwargs = call_args

        # Verify the first argument is a FastAPI app
        assert len(args) == 1
        assert isinstance(args[0], FastAPI)

        # Verify host and port
        assert kwargs.get("host") == "127.0.0.1"
        assert kwargs.get("port") == 8000


def _served_log_config() -> dict:
    from sonar.__main__ import _access_log_config

    return _access_log_config()


def _access_line(path: str, capsys) -> str:
    """The line uvicorn's access logger writes for `path` under the config `serve` passes."""
    import uvicorn.config

    try:
        logging.config.dictConfig(_served_log_config())
        logging.getLogger("uvicorn.access").info(
            '%s - "%s %s HTTP/%s" %d', "10.0.0.1:5000", "GET", path, "1.1", 200
        )
    finally:
        logging.config.dictConfig(uvicorn.config.LOGGING_CONFIG)
    return capsys.readouterr().out


@pytest.mark.parametrize("path", ["/bank/callback", "/auth/callback"])
def test_access_log_drops_the_query_string(path, capsys):
    line = _access_line(f"{path}?state=s3cret&code=c0de", capsys)

    assert path in line
    assert "s3cret" not in line
    assert "c0de" not in line
    assert "200" in line
    assert "10.0.0.1:5000" in line


def test_access_log_keeps_a_path_without_a_query_unchanged(capsys):
    line = _access_line("/monthly", capsys)

    assert '"GET /monthly HTTP/1.1" 200' in line


def test_access_log_config_does_not_mutate_uvicorns_own(capsys):
    import uvicorn.config

    before = repr(uvicorn.config.LOGGING_CONFIG)

    _served_log_config()

    assert repr(uvicorn.config.LOGGING_CONFIG) == before


def test_access_log_filter_leaves_other_records_alone():
    from sonar.__main__ import _QueryFreeAccessLog

    record = logging.LogRecord("uvicorn.error", logging.INFO, "f", 1, "see ?x=1 %s", ("a?b",), None)

    assert _QueryFreeAccessLog().filter(record) is True
    assert record.args == ("a?b",)


def test_server_db_path_is_sonar_db_path_when_set(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.argv", ["sonar"])
    monkeypatch.setenv("SONAR_DB_PATH", str(tmp_path / "env.db"))
    with (
        patch("sonar.__main__.uvicorn") as mock_uvicorn,
        patch("sonar.__main__.create_app") as mock_create_app,
    ):
        from sonar.__main__ import main

        main()

    mock_create_app.assert_called_once_with(
        tmp_path / "env.db", auth=None, bank=None, bank_client=None
    )
    assert mock_uvicorn.run.call_args.args == (mock_create_app.return_value,)
    assert mock_uvicorn.run.call_args.kwargs == {
        "host": "127.0.0.1",
        "port": 8000,
        "proxy_headers": True,
        "forwarded_allow_ips": "127.0.0.1",
        "log_config": _served_log_config(),
    }


def test_server_db_path_defaults_to_data_sonar_db(monkeypatch):
    monkeypatch.setattr("sys.argv", ["sonar"])
    monkeypatch.delenv("SONAR_DB_PATH", raising=False)
    with patch("sonar.__main__.uvicorn"), patch("sonar.__main__.create_app") as mock_create_app:
        from pathlib import Path

        from sonar.__main__ import main

        main()

    mock_create_app.assert_called_once_with(
        Path("data/sonar.db"), auth=None, bank=None, bank_client=None
    )


def _run_server(monkeypatch, env: dict[str, str]):
    monkeypatch.setattr("sys.argv", ["sonar"])
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with (
        patch("sonar.__main__.uvicorn") as mock_uvicorn,
        patch("sonar.__main__.create_app") as mock_create_app,
    ):
        from sonar.__main__ import main

        main()
    return mock_create_app, mock_uvicorn


def test_full_auth_env_passes_auth_settings_to_the_app(monkeypatch):
    mock_create_app, _ = _run_server(monkeypatch, FULL_AUTH_ENV)

    assert mock_create_app.call_args.kwargs["auth"] == AuthSettings(
        google_client_id="client-id",
        google_client_secret="client-secret",
        session_secret="session-secret",
        base_url="https://sonar.example.com",
    )


def test_partial_auth_env_refuses_to_start(monkeypatch, capsys):
    env = {
        "SONAR_GOOGLE_CLIENT_ID": "client-id",
        "SONAR_SESSION_SECRET": "session-secret",
    }

    with pytest.raises(SystemExit) as exit_info:
        _run_server(monkeypatch, env)

    assert exit_info.value.code == 1
    out = capsys.readouterr().out
    assert "SONAR_GOOGLE_CLIENT_SECRET" in out
    assert "SONAR_BASE_URL" in out
    assert "SONAR_GOOGLE_CLIENT_ID" not in out
    assert "SONAR_SESSION_SECRET" not in out


def test_partial_auth_env_never_calls_uvicorn(monkeypatch):
    monkeypatch.setattr("sys.argv", ["sonar"])
    monkeypatch.setenv("SONAR_BASE_URL", "https://sonar.example.com")
    with patch("sonar.__main__.uvicorn") as mock_uvicorn, pytest.raises(SystemExit):
        from sonar.__main__ import main

        main()

    mock_uvicorn.run.assert_not_called()


def test_sonar_port_sets_the_server_port(monkeypatch):
    _, mock_uvicorn = _run_server(monkeypatch, {"SONAR_PORT": "8123"})

    assert mock_uvicorn.run.call_args.kwargs["port"] == 8123


def test_email_subcommands_run_with_a_partial_auth_env(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SONAR_BASE_URL", "https://sonar.example.com")
    monkeypatch.setattr(
        "sys.argv", ["sonar", "allow-email", "owner@example.com", "--db", str(tmp_path / "t.db")]
    )
    from sonar.__main__ import main

    main()

    assert capsys.readouterr().out.strip() == "Allowed owner@example.com."


def test_full_auth_env_with_a_token_passes_the_token_to_the_app(monkeypatch):
    mock_create_app, _ = _run_server(monkeypatch, {**FULL_AUTH_ENV, "SONAR_API_TOKEN": "api-token"})

    assert mock_create_app.call_args.kwargs["auth"].api_token == "api-token"


def test_bank_env_off_passes_no_bank_to_the_app(monkeypatch):
    mock_create_app, _ = _run_server(monkeypatch, {})

    assert mock_create_app.call_args.kwargs["bank"] is None
    assert mock_create_app.call_args.kwargs["bank_client"] is None


def test_full_bank_env_passes_settings_and_a_client_to_the_app(monkeypatch, tmp_path):
    key_path = tmp_path / "bank.pem"
    env = {
        "SONAR_ENABLE_BANKING_APP_ID": "app-id",
        "SONAR_ENABLE_BANKING_KEY_PATH": str(key_path),
    }
    with (
        patch("sonar.__main__.read_private_key", return_value=b"pem") as read_key,
        patch("sonar.__main__.EnableBankingClient") as client_class,
    ):
        mock_create_app, _ = _run_server(monkeypatch, env)

    read_key.assert_called_once_with(key_path, STATIC_DIR)
    assert mock_create_app.call_args.kwargs["bank"] == BankSettings(
        app_id="app-id", key_path=key_path, redirect_url="http://127.0.0.1:8000/bank/callback"
    )
    assert mock_create_app.call_args.kwargs["bank_client"] is client_class.return_value


def test_partial_bank_env_refuses_to_start(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exit_info:
        _run_server(monkeypatch, {"SONAR_ENABLE_BANKING_APP_ID": "app-id"})

    assert exit_info.value.code == 1
    assert "SONAR_ENABLE_BANKING_KEY_PATH" in capsys.readouterr().out


def test_bank_key_in_the_served_static_files_refuses_to_start(monkeypatch, capsys):
    env = {
        "SONAR_ENABLE_BANKING_APP_ID": "app-id",
        "SONAR_ENABLE_BANKING_KEY_PATH": str(STATIC_DIR / "sonar.css"),
    }
    monkeypatch.setattr("sys.argv", ["sonar"])
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with patch("sonar.__main__.uvicorn") as mock_uvicorn, pytest.raises(SystemExit) as exit_info:
        from sonar.__main__ import main

        main()

    assert exit_info.value.code == 1
    mock_uvicorn.run.assert_not_called()
    assert "static files" in capsys.readouterr().out
