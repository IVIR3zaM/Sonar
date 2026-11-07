"""Monthly income bar integration through stable page hooks (SPEC §13)."""

from datetime import date
from types import SimpleNamespace

from sonar.cashflow.monthly import Upcoming
from sonar.categorization.groups import GroupTotals
from sonar.web.app import create_app, templates
from tests.html import cents, soup, text
from tests.web.test_charts_income_bar import ledger_for
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
        '{% from "components/charts.html" import income_bar %}{{ income_bar(ledger) }}'
    )
    html = template.render(
        ledger=ledger_for(GroupTotals(-100_000, -100_000, -100_000, -50_000), 100_000)
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


def test_income_bar_legend_lists_every_segment_even_when_too_narrow_for_a_label(tmp_path):
    create_app(tmp_path / "legend.db")
    template = templates.env.from_string(
        '{% from "components/charts.html" import income_bar %}{{ income_bar(ledger) }}'
    )
    html = template.render(ledger=ledger_for(GroupTotals(-500_000, -1_000, -500, 0), 600_000))
    bar = soup(SimpleNamespace(text=html)).select_one("#income-bar")
    segments = bar.select("[data-segment]")
    legend = bar.select('[data-part="legend"] [data-legend]')
    assert [item["data-legend"] for item in legend] == [s["data-segment"] for s in segments]
    assert [cents(item) for item in legend] == [int(s["data-cents"]) for s in segments]
    assert [text(item) for item in legend] == [
        "Fixed payments 5.000,00 €",
        "Keep the lights on 10,00 €",
        "Occasional payments 5,00 €",
        "Residual income 985,00 €",
    ]


def test_bar_segments_legend_and_category_badges_share_group_tones(client):
    page = soup(client.get("/monthly?month=2026-09"))
    bar = page.select_one("#income-bar")
    for segment in bar.select("[data-segment]"):
        assert segment["data-tone"] == segment["data-segment"]
    for item in bar.select("[data-legend]"):
        assert item.select_one("[data-tone]")["data-tone"] == item["data-legend"]
    tone_of = {
        "Fixed payments": "fixed",
        "Keep the lights on": "lights_on",
        "Occasional payments": "occasional",
    }
    badges = page.select('#category-totals [data-field="group"] [data-tone]')
    assert badges
    for badge in badges:
        assert badge["data-tone"] == tone_of[text(badge)]


def test_income_bar_labels_paid_and_upcoming_in_titles_and_legend(tmp_path):
    create_app(tmp_path / "upcoming.db")
    template = templates.env.from_string(
        '{% from "components/charts.html" import income_bar %}{{ income_bar(ledger) }}'
    )
    upcoming = Upcoming(
        date(2026, 11, 8), date(2026, 11, 30), -20_000, -10_000, (("Salary", 10_000),)
    )
    html = template.render(
        ledger=ledger_for(GroupTotals(-10_000, -5_000, -1_000, -500), 90_000, upcoming)
    )
    bar = soup(SimpleNamespace(text=html)).select_one("#income-bar")
    assert int(bar["data-income-cents"]) == 100_000
    expected = [
        ("fixed", "paid", "Fixed payments paid: 100,00 €"),
        ("fixed", "upcoming", "Fixed payments upcoming: 200,00 €"),
        ("lights_on", "paid", "Keep the lights on paid: 50,00 €"),
        ("lights_on", "upcoming", "Keep the lights on upcoming: 100,00 €"),
        ("occasional", "paid", "Occasional payments paid: 10,00 €"),
        ("uncategorized", "paid", "Uncategorized paid: 5,00 €"),
        ("residual", "paid", "Residual income paid: 535,00 €"),
    ]
    for segment, item, (part, kind, label) in zip(
        bar.select("[data-segment]"), bar.select("[data-legend]"), expected, strict=True
    ):
        assert segment["data-segment"] == part
        assert segment["data-kind"] == kind
        assert " ".join(segment["title"].split()) == label
        assert segment["aria-label"] == segment["title"]
        assert text(item) == label
