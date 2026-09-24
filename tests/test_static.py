"""Static file serving tests."""

from fastapi.testclient import TestClient

from sonar.app import create_app


def test_static_vendor_htmx_returns_200(tmp_path):
    """GET /static/vendor/htmx.min.js returns 200."""
    app = create_app(db_path=tmp_path / "test.db")
    with TestClient(app) as client:
        response = client.get("/static/vendor/htmx.min.js")
    assert response.status_code == 200
    assert "htmx" in response.text


def test_static_sonar_css_returns_200(tmp_path):
    """GET /static/sonar.css returns 200."""
    app = create_app(db_path=tmp_path / "test.db")
    with TestClient(app) as client:
        response = client.get("/static/sonar.css")
    assert response.status_code == 200


def test_index_references_vendored_htmx(tmp_path):
    """GET / has no 'unpkg'/'cdn' script src but references /static/vendor/htmx.min.js."""
    app = create_app(db_path=tmp_path / "test.db")
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    text = response.text
    assert "unpkg" not in text
    assert "cdn" not in text
    assert "/static/vendor/htmx.min.js" in text
