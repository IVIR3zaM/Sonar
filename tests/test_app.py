"""Tests for the FastAPI app factory."""

import sqlite3

from fastapi.testclient import TestClient

from sonar.app import create_app


def test_get_index_renders_page_and_migrates_db(tmp_path):
    db_path = tmp_path / "t.db"

    with TestClient(create_app(db_path)) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "<title>Sonar</title>" in response.text
    assert "htmx" in response.text and "<script" in response.text

    conn = sqlite3.connect(db_path)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "schema_migrations" in tables
