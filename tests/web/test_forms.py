"""Tests for the decimal helpers the utility forms share (SPEC §13 Utilities)."""

import pytest

from sonar.web.forms import field, format_scaled, friendly, parse_scaled


@pytest.mark.parametrize(
    ("text", "places", "expected"),
    [
        ("12,345", 3, 12_345),
        ("12.345", 3, 12_345),
        ("12.3456", 4, 123_456),
        ("12.3", 3, 12_300),
        ("12", 3, 12_000),
        (" 8,1 ", 4, 81_000),
        ("0", 3, 0),
        ("0.0005", 4, 5),
    ],
)
def test_parse_scaled_returns_the_value_in_units_of_ten_to_minus_places(text, places, expected):
    assert parse_scaled(text, places) == expected


@pytest.mark.parametrize("text", ["", "   ", "1.2.3", "1,2,3", "1.234,5", "-1", "abc", "1e3", ".5"])
def test_parse_scaled_rejects_bad_text(text):
    with pytest.raises(ValueError):
        parse_scaled(text, 4)


def test_parse_scaled_rejects_too_many_decimals():
    with pytest.raises(ValueError, match="decimal"):
        parse_scaled("12.3456", 3)


def test_parse_scaled_rejects_blank():
    with pytest.raises(ValueError):
        parse_scaled("", 3)


@pytest.mark.parametrize(
    ("value", "places", "expected"),
    [(12_345, 3, "12.345"), (80_000, 4, "8.0000"), (5, 3, "0.005"), (0, 3, "0.000")],
)
def test_format_scaled_round_trips_through_parse_scaled(value, places, expected):
    assert format_scaled(value, places) == expected
    assert parse_scaled(expected, places) == value


def test_a_bad_date_list_names_the_field_and_the_format():
    with pytest.raises(ValueError, match="Dates: enter dates like 2026-04-15, 2026-06-15"):
        field("Dates", "x", "dates", int)


@pytest.mark.parametrize(
    ("raw", "sentence"),
    [
        ("drinking VAT must be 0 to 100 percent", "Drinking water VAT must be 0 to 100 percent."),
        ("wastewater price must be positive", "Wastewater price must be positive."),
        (
            "a schedule needs at least one advance date",
            "Enter at least one scheduled advance date.",
        ),
        ("debit days must be 0 to 365", "Settlement debit days must be 0 to 365."),
    ],
)
def test_friendly_words_the_water_and_advance_errors(raw, sentence):
    assert friendly(ValueError(raw)) == sentence
