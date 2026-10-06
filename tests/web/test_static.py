"""Static file serving tests."""

from fastapi.testclient import TestClient

from sonar.web.app import create_app


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


def test_index_links_favicon_and_home_screen_icon(tmp_path):
    """GET / links an SVG favicon and an iOS home-screen icon, and both are served."""
    app = create_app(db_path=tmp_path / "test.db")
    with TestClient(app) as client:
        text = client.get("/").text
        favicon = client.get("/static/icons/favicon.svg")
        touch_icon = client.get("/static/icons/apple-touch-icon.png")
    assert 'rel="icon" href="/static/icons/favicon.svg"' in text
    assert 'rel="apple-touch-icon" href="/static/icons/apple-touch-icon.png"' in text
    assert favicon.status_code == 200
    assert touch_icon.status_code == 200
    assert touch_icon.headers["content-type"] == "image/png"


def test_static_payoff_script_returns_200(tmp_path):
    """GET /static/payoff.js answers 200 and drives the payoff slider."""
    app = create_app(db_path=tmp_path / "test.db")
    with TestClient(app) as client:
        response = client.get("/static/payoff.js")
    assert response.status_code == 200
    assert "payoff-slider" in response.text
