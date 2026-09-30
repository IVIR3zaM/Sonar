"""Tests for the Uncategorized page's copy-to-Claude-Code export (SPEC §5)."""

from dataclasses import replace
from datetime import date

from sonar.categorization.export import HEADER, build_categorization_request, group_uncategorized
from sonar.transactions import ParsedTransaction


def _tx(**overrides: object) -> ParsedTransaction:
    base = ParsedTransaction(
        account="DE00 1234",
        booking_date=date(2024, 3, 1),
        value_date=date(2024, 3, 1),
        amount_cents=-1234,
        currency="EUR",
        counterparty="Example Bakery",
        purpose="Card payment 0815",
        raw_row="raw",
    )
    return replace(base, **overrides)


def test_first_line_is_exact() -> None:
    request = build_categorization_request([])

    assert request.splitlines()[0] == HEADER
    assert HEADER == "Categorization request: follow the Categorization workflow in CLAUDE.md."


def test_empty_input_gives_header_only() -> None:
    request = build_categorization_request([])

    assert request.splitlines() == [HEADER]


def test_case_and_space_variants_are_grouped() -> None:
    txs = [
        _tx(counterparty="Example Bakery"),
        _tx(counterparty="  EXAMPLE   bakery "),
    ]

    request = build_categorization_request(txs)

    lines = request.splitlines()
    assert len(lines) == 2
    assert lines[1].startswith("2x example bakery |")


def test_amount_and_date_ranges() -> None:
    txs = [
        _tx(amount_cents=-1234, booking_date=date(2024, 3, 1)),
        _tx(amount_cents=4500, booking_date=date(2024, 5, 10)),
    ]

    request = build_categorization_request(txs)

    line = request.splitlines()[1]
    assert "-12.34..45.00 EUR" in line
    assert "2024-03-01..2024-05-10" in line


def test_up_to_two_distinct_purposes_shown() -> None:
    txs = [
        _tx(purpose="First purpose"),
        _tx(purpose="Second purpose"),
        _tx(purpose="Third purpose"),
    ]

    request = build_categorization_request(txs)

    line = request.splitlines()[1]
    assert "First purpose" in line
    assert "Second purpose" in line
    assert "Third purpose" not in line


def test_purpose_truncated_to_about_80_chars() -> None:
    long_purpose = "x" * 200
    txs = [_tx(purpose=long_purpose)]

    request = build_categorization_request(txs)

    line = request.splitlines()[1]
    sample = line.split("|")[-1].strip()
    assert sample == "x" * 80 + "…"


def test_empty_counterparty_shows_placeholder() -> None:
    txs = [_tx(counterparty=""), _tx(counterparty="   ")]

    request = build_categorization_request(txs)

    line = request.splitlines()[1]
    assert line.startswith("2x (no counterparty) |")


def test_groups_sorted_by_count_desc_then_key() -> None:
    txs = [
        _tx(counterparty="Zebra Shop"),
        _tx(counterparty="Apple Store"),
        _tx(counterparty="Apple Store"),
    ]

    request = build_categorization_request(txs)

    lines = request.splitlines()[1:]
    assert lines[0].startswith("2x apple store |")
    assert lines[1].startswith("1x zebra shop |")


def test_group_uncategorized_same_order_and_counts_as_the_text_export() -> None:
    txs = [
        _tx(counterparty="Zebra Shop"),
        _tx(counterparty="Apple Store"),
        _tx(counterparty="Apple Store"),
    ]

    groups = group_uncategorized(txs)

    assert [(g.key, g.count) for g in groups] == [("apple store", 2), ("zebra shop", 1)]


def test_group_uncategorized_fields() -> None:
    txs = [
        _tx(amount_cents=-1234, booking_date=date(2024, 3, 1), purpose="First purpose"),
        _tx(amount_cents=4500, booking_date=date(2024, 5, 10), purpose="Second purpose"),
    ]

    (group,) = group_uncategorized(txs)

    assert group.key == "example bakery"
    assert group.count == 2
    assert group.min_amount == "-12.34"
    assert group.max_amount == "45.00"
    assert group.first_date == date(2024, 3, 1)
    assert group.last_date == date(2024, 5, 10)
    assert group.sample_purposes == ["First purpose", "Second purpose"]
