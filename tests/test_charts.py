"""Chart geometry and SVG chart macros (SPEC §12 Dashboard)."""

from datetime import date
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup

from sonar.app import create_app, templates
from sonar.charts import bars, columns, line_points, month_label, runway


@pytest.fixture
def render(tmp_path):
    # Built through create_app so the macros see exactly the env the pages use.
    create_app(db_path=tmp_path / "test.db")

    def _render(macro: str, call: str, **context) -> BeautifulSoup:
        source = f'{{% from "components/charts.html" import {macro} %}}{{{{ {call} }}}}'
        html = templates.env.from_string(source).render(**context)
        return BeautifulSoup(html, "html.parser")

    return _render


def test_runway_puts_zero_between_limit_and_balance():
    g = runway(-50000, 100000, -20000, 30000, 300)
    assert g.limit_x < g.zero_x < g.balance_x
    assert (g.limit_x, g.zero_x, g.balance_x) == (0, 100, 300)


def test_runway_band_lies_inside_the_width():
    g = runway(-50000, 100000, -20000, 30000, 300)
    assert 0 <= g.band_start_x <= g.band_end_x <= 300
    assert (g.band_start_x, g.band_end_x) == (60, 160)


def test_runway_orders_the_band_even_if_worst_exceeds_best():
    g = runway(-50000, 100000, 30000, -20000, 300)
    assert (g.band_start_x, g.band_end_x) == (60, 160)


def test_runway_stretches_to_a_projection_below_the_limit():
    g = runway(-10000, 5000, -40000, -20000, 90)
    assert g.band_start_x == 0
    assert g.balance_x == 90
    assert 0 < g.limit_x < g.zero_x < g.balance_x


def test_runway_all_zero_is_safe():
    g = runway(0, 0, 0, 0, 300)
    assert (g.limit_x, g.zero_x, g.balance_x, g.band_start_x, g.band_end_x) == (0, 0, 0, 0, 0)


def test_runway_orders_limit_zero_band_and_balance_on_one_axis():
    # Regression for the "detached track" defect: band, limit, zero and
    # balance must land in this order for a real overdraft-limit projection.
    g = runway(-50000, 125000, -324382, -258416, 300)
    assert 0 <= g.band_start_x < g.band_end_x <= g.limit_x < g.zero_x < g.balance_x <= 300


def test_columns_scale_the_largest_value_to_full_height():
    assert columns([0, 100, 50], 80) == [0, 80, 40]


def test_columns_use_magnitude_for_outgoing_amounts():
    assert columns([-100, -25], 80) == [80, 20]


def test_columns_all_zero_is_safe():
    assert columns([0, 0], 80) == [0, 0]
    assert columns([], 80) == []


def test_bars_scale_the_largest_value_to_full_width():
    assert bars([200, 50], 300) == [300, 75]


def test_month_label():
    assert month_label(date(2026, 9, 1)) == "Sep 2026"


def test_line_points_puts_the_larger_value_higher_on_a_shared_scale():
    points = line_points([[0, 10], [0, 5]], width=100, height=50)
    # Same value (0) at index 0 lands at the same y in both series.
    assert points[0][0][1] == points[1][0][1]
    # 10 is the larger of the two, so its y is smaller (higher on screen).
    assert points[0][1][1] < points[1][1][1]
    assert [x for x, _ in points[0]] == [0, 100]


def test_line_points_single_point_and_all_zero_do_not_divide_by_zero():
    assert line_points([[5]], width=100, height=50) == [[(0, 0)]]
    zeros = line_points([[0, 0, 0]], width=100, height=50)
    assert zeros == [[(0, 50), (50, 50), (100, 50)]]


def test_runway_bar_macro_is_an_accessible_svg(render):
    soup = render("runway_bar", "runway_bar(-50000, 100000, -20000, 30000)")
    svg = soup.find("svg")
    assert svg["role"] == "img"
    assert svg["aria-label"]
    assert svg.find("title").get_text(strip=True)
    assert svg["data-worst"] == "-20000"
    assert svg["data-best"] == "30000"


def test_runway_bar_macro_marks_band_and_balance(render):
    soup = render("runway_bar", "runway_bar(-50000, 100000, -20000, 30000)")
    band = soup.select_one("[data-part=band]")
    assert band["x"] == "60"
    assert band["width"] == "100"
    assert "−200,00 €" in band.find("title").get_text()
    balance = soup.select_one("[data-part=balance]")
    assert balance["data-cents"] == "100000"
    assert balance.find("title").get_text(strip=True)


def test_runway_bar_macro_draws_one_continuous_track(render):
    soup = render("runway_bar", "runway_bar(-50000, 125000, -324382, -258416)")
    beyond = soup.select_one("[data-part=beyond-limit]")
    overdraft = soup.select_one("[data-part=overdraft]")
    funds = soup.select_one("[data-part=funds]")
    # The three track segments must be contiguous across the full [0, 300] axis.
    assert int(beyond["x"]) == 0
    assert int(beyond["x"]) + int(beyond["width"]) == int(overdraft["x"])
    assert int(overdraft["x"]) + int(overdraft["width"]) == int(funds["x"])
    assert int(funds["x"]) + int(funds["width"]) == 300
    limit = soup.select_one("[data-part=limit]")
    assert limit["data-cents"] == "-50000"
    # The marker is centered on the limit line, so it sits within a pixel of
    # the beyond-limit/overdraft boundary.
    assert abs(int(limit["x"]) - int(overdraft["x"])) <= 1
    assert limit.find("title").get_text(strip=True)


def test_month_columns_macro_has_one_rect_per_month(render):
    months = [
        SimpleNamespace(month=date(2026, 10, 1), total_cents=0),
        SimpleNamespace(month=date(2026, 11, 1), total_cents=-10000),
        SimpleNamespace(month=date(2026, 12, 1), total_cents=-5000),
    ]
    soup = render("month_columns", "month_columns(months)", months=months)
    svg = soup.find("svg")
    assert svg["role"] == "img"
    assert svg["aria-label"]
    rects = svg.find_all("rect")
    assert [r["data-cents"] for r in rects] == ["0", "-10000", "-5000"]
    assert [r["height"] for r in rects] == ["0", "80", "40"]
    assert "Nov 2026" in rects[1].find("title").get_text()


def test_category_bars_macro_has_one_rect_per_category(render):
    categories = [
        SimpleNamespace(category="groceries", expected_cents=20000),
        SimpleNamespace(category="fuel", expected_cents=5000),
    ]
    soup = render("category_bars", "category_bars(categories)", categories=categories)
    svg = soup.find("svg")
    assert svg["role"] == "img"
    assert svg["aria-label"]
    rects = svg.find_all("rect")
    assert [r["data-cents"] for r in rects] == ["20000", "5000"]
    assert "groceries" in rects[0].find("title").get_text()
    assert int(rects[0]["width"]) > int(rects[1]["width"])


def test_line_chart_macro_has_one_polyline_per_series(render):
    series = [
        {"name": "Keep the lights on", "values": [10000, 12000, 14000]},
        {"name": "Groceries", "values": [8000, 9000, 10000]},
        {"name": "Occasional payments (not forecast)", "values": [1000, 2000, 1500], "muted": True},
    ]
    labels = ["Feb 2026", "Mar 2026", "Apr 2026"]
    soup = render(
        "line_chart",
        "line_chart('lights-on-chart', 'Daily average per month', labels, series)",
        labels=labels,
        series=series,
    )
    svg = soup.find("svg", id="lights-on-chart")
    assert svg["role"] == "img"
    assert svg["aria-label"]
    polylines = svg.find_all("polyline")
    assert [p["data-series"] for p in polylines] == [s["name"] for s in series]
    assert all(len(p["points"].split()) == 3 for p in polylines)
    legend_items = [li.get_text(strip=True) for li in soup.select("ul li")]
    assert legend_items == [s["name"] for s in series]
