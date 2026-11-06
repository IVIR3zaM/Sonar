"""Monthly income bar integration through stable page hooks (SPEC §13)."""

from types import SimpleNamespace

from sonar.categorization.groups import GroupTotals
from sonar.web.app import create_app, templates
from tests.html import cents, soup, text
from tests.web.test_monthly_page import client as client


def test_monthly_income_bar_matches_group_stats_and_shows_residual(client):
    page = soup(client.get("/monthly?month=2026-09"))
    bar = page.select_one("#income-bar")
    assert bar is not None
    assert int(bar["data-income-cents"]) == 123_456
    total = 0
    for segment in bar.select("[data-segment]"):
        part = segment["data-segment"]
        if part == "residual":
            assert cents(segment) == cents(page.select_one("#residual-income"))
        else:
            assert cents(segment) == -cents(page.select_one(f"#group-{part.replace('_', '-')}"))
            total += cents(segment)
        assert segment["title"] == segment["aria-label"]
        assert text(segment).strip() or segment["aria-label"]
        assert segment["style"] == f"width: {segment['data-width']}%"
    assert int(bar["data-spent-cents"]) == total
    assert cents(bar.select_one('[data-part="spent"]')) == total
    assert cents(bar.select_one('[data-part="income"]')) == 123_456
    assert cents(page.select_one("#residual-income")) == 123_456 - total
    assert bar.select_one('[data-zone="income"]')["style"] == "width: 70%"
    assert bar.select_one('[data-zone="overspend"]')["style"] == "width: 30%"
    assert bar.select_one('[data-part="over"]') is None


def test_monthly_without_income_omits_bar_and_residual(client):
    page = soup(client.get("/monthly?month=2026-08"))
    assert page.select_one("#categories-card") is not None
    assert page.select_one("#income-bar") is None
    assert page.select_one("#residual-income") is None


def test_income_bar_markup_labels_overspending_and_capped_segments(tmp_path):
    create_app(tmp_path / "bar.db")
    template = templates.env.from_string(
        '{% from "components/charts.html" import income_bar %}{{ income_bar(groups, income) }}'
    )
    html = template.render(
        groups=GroupTotals(-100_000, -100_000, -100_000, -50_000), income=100_000
    )
    page = soup(SimpleNamespace(text=html))
    bar = page.select_one("#income-bar")
    assert cents(bar.select_one('[data-part="over"]')) == 250_000
    assert text(bar.select_one('[data-part="over"]')) == "2.500,00 € over income"
    assert text(bar.select_one('[data-part="spent"]')) == "Spent 3.500,00 €"
    for segment, label in zip(
        bar.select("[data-segment]"),
        [
            "Fixed payments: 1.000,00 €",
            "Keep the lights on: 1.000,00 €",
            "Occasional payments: 1.000,00 €",
            "Uncategorized: 500,00 €",
        ],
        strict=True,
    ):
        assert " ".join(segment["title"].split()) == label
        assert segment["title"] == segment["aria-label"]
    assert bar.select_one('[data-segment="residual"]') is None
