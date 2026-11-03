"""Bare minimum geometry and accessible SVGs (SPEC §12)."""

from datetime import date
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup

from sonar.web import charts
from sonar.web.app import create_app, templates


@pytest.mark.parametrize(
    "fixed, lights, income, width, expected",
    [
        (200, 100, 600, 300, (100, 50, 300)),
        (200, 100, 300, 300, (200, 100, 300)),
        (200, 100, 150, 300, (200, 100, 150)),
        (200, 0, 300, 300, (200, 0, 300)),
        (0, 0, 0, 300, (0, 0, 0)),
        (1, 1, 4, 3, (1, 1, 3)),
    ],
)
def test_need_segments_share_the_need_scale(fixed, lights, income, width, expected):
    geometry = charts.need_bar(fixed, lights, income, width)
    assert (geometry.fixed_width, geometry.lights_width, geometry.income_x) == expected
    peak = max(fixed + lights, income)
    need_width = round((fixed + lights) * width / peak) if peak else 0
    assert geometry.fixed_width + geometry.lights_width == need_width


@pytest.mark.parametrize(
    "values, expected",
    [
        ([300, -100], [(0, 90, 1), (90, 30, -1)]),
        ([300, 100], [(0, 90, 1), (60, 30, 1)]),
        ([-300, -100], [(90, 90, -1), (90, 30, -1)]),
        ([0, 0], [(90, 0, 0), (90, 0, 0)]),
        ([], []),
    ],
)
def test_residuals_extend_from_zero_with_a_shared_magnitude_scale(values, expected):
    bars = charts.residual_bars(values, 90)
    assert [(bar.y, bar.height, bar.sign) for bar in bars] == expected


@pytest.fixture
def render(tmp_path):
    create_app(db_path=tmp_path / "test.db")

    def draw(macro, call, **context):
        source = f'{{% from "components/charts.html" import {macro} %}}{{{{ {call} }}}}'
        return BeautifulSoup(templates.env.from_string(source).render(**context), "html.parser")

    return draw


def accessible_svg(page):
    svg = page.select_one('svg[role="img"][aria-label]')
    assert svg is not None
    assert svg.title.text == svg["aria-label"]
    assert not page.select("[style]")
    return svg


def test_need_macro_labels_each_amount_and_places_income_beyond_need(render):
    svg = accessible_svg(render("need_bar", "need_bar(20000, 10000, 60000)"))
    fixed = svg.select_one('[data-part="fixed"][data-cents="20000"]')
    lights = svg.select_one('[data-part="lights"][data-cents="10000"]')
    income = svg.select_one('[data-part="income"][data-cents="60000"]')
    assert "200,00" in fixed.title.text
    assert "100,00" in lights.title.text
    assert "600,00" in income.title.text
    assert int(income["x1"]) > int(lights["x"]) + int(lights["width"])


def test_residual_macro_marks_the_tightest_cycle_and_zero(render):
    cycles = [
        SimpleNamespace(start=date(2026, 1, 1), end=date(2026, 1, 31), residual_cents=30000),
        SimpleNamespace(start=date(2026, 2, 1), end=date(2026, 2, 28), residual_cents=-10000),
    ]
    svg = accessible_svg(render("residual_chart", "residual_chart(cycles)", cycles=cycles))
    bars = svg.select("rect[data-cents]")
    assert [int(bar["data-cents"]) for bar in bars] == [30000, -10000]
    assert "300,00" in bars[0].title.text
    assert "100,00" in bars[1].title.text
    assert svg.select("[data-max]") == [bars[1]]
    zero = svg.select_one('[data-part="zero"]')
    assert int(bars[0]["y"]) < int(zero["y1"]) == int(bars[1]["y"])


def test_residual_macro_handles_no_cycles(render):
    svg = accessible_svg(render("residual_chart", "residual_chart([])"))
    assert not svg.select("rect[data-cents]")


def test_share_macro_names_its_percentage(render):
    svg = accessible_svg(render("share_bar", "share_bar(37)"))
    assert "37%" in svg.title.text
    assert svg.select_one('[data-part="share"]')["width"] == "37%"
