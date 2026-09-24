"""Tests for the hook-based HTML helpers in tests/html.py (SPEC §12 Tests)."""

import httpx
from bs4 import BeautifulSoup

from tests.html import cents, fields, records, soup, table_rows, text, value

PAGE = """
<div id="balance">Balance: <span data-field="amount" data-cents="-123456">-1234.56</span>
  as of <time data-field="as_of" datetime="2026-09-24">24 Sep 2026</time></div>
<table id="due">
  <thead><tr><th>Name</th><th>Amount</th></tr></thead>
  <tbody>
    <tr data-row><td data-field="name">  Rent
      </td><td data-field="amount"><span data-cents="50000">500.00</span></td></tr>
    <tr data-row><td data-field="name">Gym</td>
      <td data-field="amount"><span data-cents="5">0.05</span></td></tr>
  </tbody>
</table>
"""


def _page() -> BeautifulSoup:
    return BeautifulSoup(PAGE, "html.parser")


def test_soup_parses_the_response_body():
    response = httpx.Response(200, text='<p id="x">hi</p>')

    assert soup(response).select_one("#x").get_text() == "hi"


def test_cents_reads_int_data_cents_on_the_element_or_inside_it():
    page = _page()

    assert cents(page.select_one("[data-cents]")) == -123456
    assert cents(page.select_one("#balance")) == -123456


def test_text_collapses_whitespace():
    assert text(_page().select_one("[data-field=name]")) == "Rent"


def test_table_rows_returns_body_cell_texts():
    assert table_rows(_page(), "due") == [["Rent", "500.00"], ["Gym", "0.05"]]


def test_value_prefers_cents_then_iso_date_then_text():
    page = _page()

    assert value(page.select_one("tr td[data-field=amount]")) == 50000
    assert value(page.select_one("time")) == "2026-09-24"
    assert value(page.select_one("td[data-field=name]")) == "Rent"


def test_fields_maps_each_data_field_to_its_value():
    assert fields(_page().select_one("#balance")) == {"amount": -123456, "as_of": "2026-09-24"}


def test_records_returns_the_fields_of_each_data_row():
    assert records(_page().select_one("#due")) == [
        {"name": "Rent", "amount": 50000},
        {"name": "Gym", "amount": 5},
    ]
