"""Tests for the __main__ entry point."""

from unittest.mock import patch

from fastapi import FastAPI


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

    mock_create_app.assert_called_once_with(tmp_path / "env.db")
    assert mock_uvicorn.run.call_args.args == (mock_create_app.return_value,)
    assert mock_uvicorn.run.call_args.kwargs == {"host": "127.0.0.1", "port": 8000}


def test_server_db_path_defaults_to_data_sonar_db(monkeypatch):
    monkeypatch.setattr("sys.argv", ["sonar"])
    monkeypatch.delenv("SONAR_DB_PATH", raising=False)
    with patch("sonar.__main__.uvicorn"), patch("sonar.__main__.create_app") as mock_create_app:
        from pathlib import Path

        from sonar.__main__ import main

        main()

    mock_create_app.assert_called_once_with(Path("data/sonar.db"))
