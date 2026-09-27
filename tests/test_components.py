"""Tests for the design-system macros in templates/components/ (SPEC §12)."""

from datetime import date

from bs4 import BeautifulSoup

from sonar.app import templates


def render(source: str, **context) -> BeautifulSoup:
    html = templates.env.from_string(source).render(**context)
    return BeautifulSoup(html, "html.parser")


def test_amount_wraps_cents_with_eur_text_and_negative_marker():
    soup = render('{% from "components/amount.html" import amount %}{{ amount(-500) }}')
    span = soup.select_one("span[data-cents]")
    assert span["data-cents"] == "-500"
    assert span.get_text() == "−5,00 €"
    assert span["data-sign"] == "negative"
    assert "text-negative" in span["class"]


def test_amount_marks_positive_and_zero():
    soup = render(
        '{% from "components/amount.html" import amount %}{{ amount(1250) }}{{ amount(0) }}'
    )
    positive, zero = soup.select("span[data-cents]")
    assert positive["data-sign"] == "positive"
    assert "text-positive" in positive["class"]
    assert zero["data-sign"] == "zero"


def test_amount_can_be_neutral_and_carry_an_id():
    soup = render(
        '{% from "components/amount.html" import amount %}'
        '{{ amount(-500, id="due-total", colored=false) }}'
    )
    span = soup.select_one("#due-total")
    assert span["data-cents"] == "-500"
    assert span["data-sign"] == "negative"
    assert "text-negative" not in span.get("class", [])


def test_date_renders_time_with_iso_datetime():
    soup = render(
        '{% from "components/amount.html" import date %}{{ date(d) }}',
        d=date(2026, 9, 24),
    )
    time = soup.select_one("time")
    assert time["datetime"] == "2026-09-24"
    assert time.get_text() == "24 Sep 2026"


def test_field_keeps_value_links_label_and_shows_error():
    soup = render(
        '{% from "components/field.html" import field %}'
        '{{ field("salary_day", "Salary day", value="42", help="Day of month",'
        ' error="Must be 1-31", required=true) }}'
    )
    field_input = soup.select_one("input[name=salary_day]")
    assert field_input["value"] == "42"
    assert field_input.has_attr("required")
    assert field_input["aria-invalid"] == "true"
    label = soup.select_one(f"label[for={field_input['id']}]")
    assert label.get_text(strip=True) == "Salary day"
    assert "Day of month" in soup.get_text()
    assert "Must be 1-31" in soup.get_text()
    described = field_input["aria-describedby"].split()
    assert all(soup.select_one(f"#{ref}") for ref in described)


def test_field_without_error_is_not_invalid():
    soup = render(
        '{% from "components/field.html" import field %}'
        '{{ field("amount", "Amount", attrs={"placeholder": "0.00"}) }}'
    )
    field_input = soup.select_one("input[name=amount]")
    assert field_input["value"] == ""
    assert field_input["placeholder"] == "0.00"
    assert not field_input.has_attr("aria-invalid")


def test_field_renders_select_with_selected_option():
    soup = render(
        '{% from "components/field.html" import field %}'
        '{{ field("match_field", "Match on", value="purpose",'
        ' options=[("counterparty", "Counterparty"), ("purpose", "Purpose")]) }}'
    )
    select = soup.select_one("select[name=match_field]")
    assert select.select_one("option[selected]")["value"] == "purpose"


def test_badge_renders_text_tone_and_attrs():
    soup = render(
        '{% from "components/badge.html" import badge %}'
        '{{ badge("Paid off", tone="positive", id="paid", attrs={"data-count": 3}) }}'
    )
    badge = soup.select_one("#paid")
    assert badge.get_text(strip=True) == "Paid off"
    assert badge["data-tone"] == "positive"
    assert badge["data-count"] == "3"


def test_badge_default_markup_is_unchanged():
    soup = render(
        '{% from "components/badge.html" import badge %}'
        '{{ badge("Paid off", tone="positive", id="paid", attrs={"data-count": 3}) }}'
    )
    badge = soup.select_one("#paid")
    assert badge.get_text(strip=True) == "Paid off"
    assert badge["data-tone"] == "positive"
    assert badge["data-count"] == "3"
    assert "whitespace-nowrap" in badge["class"]
    assert "whitespace-normal" not in badge["class"]


def test_badge_wrap_true_keeps_text_tone_and_attrs():
    soup = render(
        '{% from "components/badge.html" import badge %}'
        '{{ badge("Paid off", tone="positive", id="paid", attrs={"data-count": 3}, wrap=true) }}'
    )
    badge = soup.select_one("#paid")
    assert badge.get_text(strip=True) == "Paid off"
    assert badge["data-tone"] == "positive"
    assert badge["data-count"] == "3"
    assert "whitespace-normal" in badge["class"]
    assert "whitespace-nowrap" not in badge["class"]


def test_stat_renders_label_and_value_markup():
    soup = render(
        '{% from "components/stat.html" import stat %}'
        '{% from "components/amount.html" import amount %}'
        '{{ stat("Total remaining", amount(-120000), id="debts-total", hint="2 debts") }}'
    )
    stat = soup.select_one("#debts-total")
    assert "Total remaining" in stat.get_text()
    assert stat.select_one("span[data-cents]")["data-cents"] == "-120000"
    assert "2 debts" in stat.get_text()


def test_card_renders_title_and_body_slot():
    soup = render(
        '{% from "components/card.html" import card %}'
        '{% call card("Due before payday", id="due") %}<p id="body">rows</p>{% endcall %}'
    )
    card = soup.select_one("#due")
    assert card.select_one("h2").get_text(strip=True) == "Due before payday"
    assert card.select_one("#body").get_text() == "rows"


def test_button_renders_label_type_and_link_variant():
    soup = render(
        '{% from "components/button.html" import button %}'
        '{{ button("Save") }}'
        '{{ button("Delete", variant="danger", attrs={"hx-confirm": "Sure?"}) }}'
        '{{ button("Import", href="/import", variant="secondary") }}'
    )
    save, delete = soup.select("button")
    assert save.get_text(strip=True) == "Save"
    assert save["type"] == "submit"
    assert delete["hx-confirm"] == "Sure?"
    assert delete["data-variant"] == "danger"
    link = soup.select_one("a[href='/import']")
    assert link.get_text(strip=True) == "Import"


def test_button_body_slot_replaces_label():
    soup = render(
        '{% from "components/button.html" import button %}'
        '{% call button(type="button") %}<span id="spin"></span>Re-apply{% endcall %}'
    )
    button = soup.select_one("button")
    assert button["type"] == "button"
    assert button.select_one("#spin") is not None
    assert "Re-apply" in button.get_text()


def test_empty_renders_title_message_and_action_slot():
    soup = render(
        '{% from "components/empty.html" import empty %}'
        '{% call empty("No data yet", "Import a bank export to start.") %}'
        '<a href="/import">Import</a>{% endcall %}'
    )
    assert "No data yet" in soup.get_text()
    assert "Import a bank export to start." in soup.get_text()
    assert soup.select_one("a[href='/import']") is not None
