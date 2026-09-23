"""Sonar entry point for one-command start."""

import uvicorn

from sonar.app import create_app


def main() -> None:
    """Start the Sonar web app on 127.0.0.1:8000."""
    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
