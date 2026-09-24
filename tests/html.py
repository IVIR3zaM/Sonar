"""Hook-based HTML helpers for page tests (SPEC §12 Tests).

Page tests read stable hooks (ids, data-cents, <time datetime>, data-field,
data-row) instead of display text, so a restyle or a new display format
never breaks them.
"""

from bs4 import BeautifulSoup, Tag


def soup(response) -> BeautifulSoup:
    return BeautifulSoup(response.text, "html.parser")


def text(el: Tag) -> str:
    return " ".join(el.get_text().split())


def cents(el: Tag) -> int:
    holder = el if el.has_attr("data-cents") else el.select_one("[data-cents]")
    if holder is None:
        raise AssertionError(f"no data-cents in {el}")
    return int(holder["data-cents"])


def value(el: Tag) -> int | str:
    """Cents for an amount, the ISO date for a date, otherwise the text."""
    if el.has_attr("data-cents") or el.select_one("[data-cents]"):
        return cents(el)
    time = el if el.name == "time" else el.select_one("time[datetime]")
    if time is not None:
        return time["datetime"]
    return text(el)


def fields(el: Tag) -> dict[str, int | str]:
    return {field["data-field"]: value(field) for field in el.select("[data-field]")}


def records(el: Tag) -> list[dict[str, int | str]]:
    return [fields(row) for row in el.select("[data-row]")]


def table_rows(page: BeautifulSoup, table_id: str) -> list[list[str]]:
    table = page.select_one(f"#{table_id}")
    if table is None:
        raise AssertionError(f"no table #{table_id}")
    return [[text(cell) for cell in row.find_all("td")] for row in table.select("tbody tr")]
