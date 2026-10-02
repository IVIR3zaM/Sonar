"""Tests for the __main__ entry point."""

from unittest.mock import patch

import pytest
from fastapi import FastAPI

from sonar.auth.settings import AUTH_ENV_VARS, AuthSettings

FULL_AUTH_ENV = {
    "SONAR_GOOGLE_CLIENT_ID": "client-id",
    "SONAR_GOOGLE_CLIENT_SECRET": "client-secret",
    "SONAR_SESSION_SECRET": "session-secret",
    "SONAR_BASE_URL": "https://sonar.example.com/",
}


@pytest.fixture(autouse=True)
def no_server_env(monkeypatch):
    """The developer's own shell must not turn sign-in on or move the port in these tests."""
    for name in (*AUTH_ENV_VARS, "SONAR_PORT"):
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


def test_server_db_path_is_sonar_db_path_when_set(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.argv", ["sonar"])
    monkeypatch.setenv("SONAR_DB_PATH", str(tmp_path / "env.db"))
    with (
        patch("sonar.__main__.uvicorn") as mock_uvicorn,
        patch("sonar.__main__.create_app") as mock_create_app,
    ):
        from sonar.__main__ import main

        main()

    mock_create_app.assert_called_once_with(tmp_path / "env.db", auth=None)
    assert mock_uvicorn.run.call_args.args == (mock_create_app.return_value,)
    assert mock_uvicorn.run.call_args.kwargs == {
        "host": "127.0.0.1",
        "port": 8000,
        "proxy_headers": True,
        "forwarded_allow_ips": "127.0.0.1",
    }


def test_server_db_path_defaults_to_data_sonar_db(monkeypatch):
    monkeypatch.setattr("sys.argv", ["sonar"])
    monkeypatch.delenv("SONAR_DB_PATH", raising=False)
    with patch("sonar.__main__.uvicorn"), patch("sonar.__main__.create_app") as mock_create_app:
        from pathlib import Path

        from sonar.__main__ import main

        main()

    mock_create_app.assert_called_once_with(Path("data/sonar.db"), auth=None)


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
