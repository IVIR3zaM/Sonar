"""Helpers the form pages share: parse fields, pick row errors, word domain errors."""

from __future__ import annotations

from collections.abc import Callable


def row_error(errors: dict, kind: str, row_id: int) -> dict | None:
    # Only the row whose form was actually submitted gets its error and kept
    # values; every other row on the page renders exactly as a fresh GET would.
    error = errors.get(kind)
    return error if error and error["id"] == row_id else None


# One hint per parser shape, not per field, since the format they accept
# (not the meaning of the field) is what the visitor needs to know.
FIELD_HINTS = {
    "amount": "enter a number like 1234.56 or -250.50",
    "date": "pick a date",
    "int": "enter a whole number",
    "percent": "enter a percent like 3.5",
    "decimal3": "enter a number with up to 3 decimals, like 1234.567",
    "decimal4": "enter a number with up to 4 decimals, like 8.1234",
}


def field(label: str, raw: str, kind: str, parser: Callable[[str], object]) -> object:
    """Parse one form field, replacing a parser's developer-facing message
    (e.g. "invalid literal for int() with base 10: 'x'") with one naming the
    field and the expected format.
    """
    try:
        return parser(raw)
    except ValueError:
        raise ValueError(f"{label}: {FIELD_HINTS[kind]}") from None


# Domain modules (recurring/schedule.py, debts/model.py, cashflow/store.py) raise ValueErrors
# written for developers, e.g. "total must be positive, got -100". A needle
# found in that text maps to one sentence naming the field for the page;
# anything unmapped falls back to the raw message rather than hiding it.
DOMAIN_ERROR_HINTS = {
    "salary_day must be between": "Salary day must be between 1 and 31.",
    "overdraft_limit_cents must not be positive": "Overdraft limit must be zero or negative.",
    "is in the future": "That date cannot be in the future.",
    "amount must be positive": "Amount must be positive.",
    "interval must be at least 1 month": "Interval must be at least 1 month.",
    "day must be within 1..31": "Day must be between 1 and 31.",
    "name must not be blank": "Name must not be blank.",
    "total must be positive": "Total must be positive.",
    "rate must be positive": "Rate must be positive.",
    "payments_count must be at least 1": "Number of payments must be at least 1.",
    "balance must be positive": "Balance must be positive.",
    "interest_bp must be positive when set": "Interest must be positive when set.",
    "value must not be blank": "Match value must not be blank.",
    "field must be one of": "Match field must be counterparty or mandate.",
    "unit price must be positive": "Unit price must be positive.",
    "base_fee_cents must not be negative": "Base fee must not be negative.",
    "advance_cents must not be negative": "Advance must not be negative.",
    "expected_usage must not be negative": "Expected usage must not be negative.",
    "state_factor_e4 is required": "State factor is required for gas and must be positive.",
    "calorific_value_e4 is required": "Calorific value is required for gas and must be positive.",
    "settlement date must not be before": "Settlement date must not be before the start date.",
}


def friendly(error: ValueError) -> str:
    text = str(error)
    for needle, human in DOMAIN_ERROR_HINTS.items():
        if needle in text:
            return human
    return text


def parse_scaled(text: str, places: int) -> int:
    """Parse a non-negative decimal with at most `places` decimals into an integer
    of 10**-places units, e.g. "12,345" at 3 places -> 12345.

    Accepts one "." or "," as the decimal separator and no thousands separator,
    like parse_cents; raises ValueError for blank, malformed or too precise text.
    """
    text = text.strip()
    if not text:
        raise ValueError("Empty number")
    if sum(text.count(separator) for separator in ".,") > 1:
        raise ValueError("Multiple decimal separators")
    whole, _, fraction = text.replace(",", ".").partition(".")
    if not whole or not (whole + fraction).isascii() or not (whole + fraction).isdecimal():
        raise ValueError("Invalid number")
    if len(fraction) > places:
        raise ValueError("Too many decimal places")
    return int(whole + fraction.ljust(places, "0"))


def format_scaled(value: int, places: int) -> str:
    """The inverse of parse_scaled, for form prefills and displayed readings."""
    sign = "-" if value < 0 else ""
    whole, fraction = divmod(abs(value), 10**places)
    return f"{sign}{whole}.{fraction:0{places}d}"
