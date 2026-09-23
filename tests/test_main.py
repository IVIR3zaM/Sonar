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
