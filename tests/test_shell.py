"""Tests for the page shell in base.html: nav, badge, drawer and theme (SPEC §12)."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from sonar.app import create_app, templates
from tests.html import soup, text
from tests.seed import seed

FIXTURE = Path(__file__).parent / "fixtures" / "db_girokonto.csv"

NAV = [
    ("/", "Dashboard"),
    ("/monthly", "Monthly spending"),
    ("/lights-on", "Keep the lights on"),
    ("/import", "Import"),
    ("/uncategorized", "Uncategorized"),
    ("/recurring", "Fixed payments"),
    ("/debts", "Installments and loans"),
    ("/settings", "Settings"),
]

# One category, no rules: every fixture row stays uncategorized until the
# rule below is written, which lets a test move the count with /reapply.
NO_RULES_TOML = """
[[category]]
name = "Dining"
type = "variable"
"""

RESTAURANT_RULE_TOML = (
    NO_RULES_TOML
    + """
[[rule]]
category = "Dining"
counterparty = "Restaurant XYZ"
"""
)


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path, NO_RULES_TOML)
    app = create_app(db_path)
    with TestClient(app) as client:
        client.db_path = db_path
        yield client


def _current_links(page) -> list[str]:
    return [link["href"] for link in page.select('a[aria-current="page"]')]


def _import_fixture(client) -> None:
    client.post("/import", files=[("files", ("giro.csv", FIXTURE.read_bytes(), "text/csv"))])


def test_nav_lists_every_page_in_order(client):
    nav = soup(client.get("/")).select_one("nav")

    assert [(link["href"], text(link)) for link in nav.select("a[href]")] == NAV


@pytest.mark.parametrize("path", [path for path, _ in NAV])
def test_only_the_current_page_is_marked_in_the_nav(client, path):
    assert _current_links(soup(client.get(path))) == [path]


def test_dashboard_is_marked_only_on_the_exact_root_path(client):
    # "/" is a prefix of every path, so a prefix match would mark Dashboard
    # on every page alongside the real one.
    assert _current_links(soup(client.get("/recurring"))) == ["/recurring"]
    assert _current_links(soup(client.get("/"))) == ["/"]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/debts/7/delete", ["/debts"]),
        ("/recurring/3/edit", ["/recurring"]),
        # A shared prefix without a "/" boundary is a different page.
        ("/importer", []),
    ],
)
def test_a_nested_path_marks_its_section(path, expected):
    request = SimpleNamespace(url=SimpleNamespace(path=path))
    html = templates.get_template("base.html").render(request=request)

    assert _current_links(BeautifulSoup(html, "html.parser")) == expected


def test_nav_badge_placeholder_loads_the_fragment(client):
    placeholder = soup(client.get("/settings")).select_one("nav #nav-uncategorized-badge")

    assert placeholder["hx-get"] == "/uncategorized/badge"
    assert "load" in placeholder["hx-trigger"]
    assert placeholder["hx-swap"] == "outerHTML"


def test_nav_badge_counts_uncategorized_transactions(client):
    _import_fixture(client)
    page_count = int(text(soup(client.get("/uncategorized")).select_one("#uncategorized-count")))

    response = client.get("/uncategorized/badge")

    assert response.status_code == 200
    badge = soup(response).select_one("#nav-uncategorized-badge")
    assert int(badge["data-count"]) == page_count == 7
    assert text(badge) == "7"
    assert not badge.has_attr("hidden")


def test_nav_badge_is_hidden_at_zero(client):
    badge = soup(client.get("/uncategorized/badge")).select_one("#nav-uncategorized-badge")

    assert badge["data-count"] == "0"
    assert badge.has_attr("hidden")


def test_reapply_updates_the_count_and_the_nav_badge_out_of_band(client):
    _import_fixture(client)
    seed(client.db_path, RESTAURANT_RULE_TOML)

    page = soup(client.post("/reapply"))

    assert int(text(page.select_one("#uncategorized-count"))) == 5
    badge = page.select_one("#nav-uncategorized-badge")
    assert badge["hx-swap-oob"] == "true"
    assert badge["data-count"] == "5"


def test_mobile_drawer_holds_the_nav_and_has_open_and_close_controls(client):
    page = soup(client.get("/"))

    drawer = page.select_one("dialog#nav-drawer")
    assert drawer.select_one("nav") is not None
    opener = page.select_one("#nav-open")
    assert "nav-drawer" in opener["onclick"] and "showModal" in opener["onclick"]
    # A method=dialog form closes the drawer without any script.
    assert drawer.select_one('form[method="dialog"] button') is not None


def test_head_sets_the_theme_before_the_stylesheet_paints(client):
    head = soup(client.get("/")).select_one("head")
    children = [el for el in head.find_all(["script", "link"])]
    theme_script = next(el for el in children if el.name == "script" and "localStorage" in el.text)
    stylesheet = head.select_one('link[rel="stylesheet"]')

    assert children.index(theme_script) < children.index(stylesheet)
    assert '"theme"' in theme_script.text
    assert "prefers-color-scheme: dark" in theme_script.text


def test_theme_toggle_stores_the_choice(client):
    toggle = soup(client.get("/")).select_one("button#theme-toggle")

    assert "localStorage" in toggle["onclick"]
    assert "dark" in toggle["onclick"]


def test_viewport_meta_is_set(client):
    viewport = soup(client.get("/")).select_one('meta[name="viewport"]')

    assert "width=device-width" in viewport["content"]


def test_base_script_scrolls_and_focuses_form_error(client):
    # SPEC §12 Friendly errors: a 400 re-render can land the alert far below
    # the fold, so base.html must bring it into view and focus it on load.
    scripts = soup(client.get("/")).select("script")
    form_error_script = next((s for s in scripts if "form-error" in s.text), None)

    assert form_error_script is not None
    assert "scrollIntoView" in form_error_script.text
    assert ".focus()" in form_error_script.text
