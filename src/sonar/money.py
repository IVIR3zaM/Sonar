"""Money parsing: convert text to integer cents or basis points."""


def _parse_amount(text: str) -> int:
    """Parse text amount to a non-negative integer amount in cents.

    Strips spaces and leading €. Accepts digits with at most one decimal
    separator (. or ,) and at most 2 decimal places. Shared by parse_cents
    and parse_signed_cents, which each add their own sign handling on top.

    Raises ValueError for empty, multiple separators, or >2 decimals.
    """
    text = text.strip()
    if text.startswith("€"):
        text = text[1:].strip()

    if not text:
        raise ValueError("Empty amount")

    has_dot = "." in text
    has_comma = "," in text
    # Both separators means a thousands separator, which is not accepted.
    if has_dot and has_comma:
        raise ValueError("Ambiguous decimal separator (both . and ,)")

    if has_dot:
        parts = text.split(".")
        if len(parts) != 2:
            raise ValueError("Multiple decimal separators")
        integer_part, decimal_part = parts
    elif has_comma:
        parts = text.split(",")
        if len(parts) != 2:
            raise ValueError("Multiple decimal separators")
        integer_part, decimal_part = parts
    else:
        integer_part = text
        decimal_part = ""

    if not integer_part or not integer_part.isdigit():
        raise ValueError("Invalid integer part")

    if decimal_part and not decimal_part.isdigit():
        raise ValueError("Invalid decimal part")

    if len(decimal_part) > 2:
        raise ValueError("Too many decimal places")

    decimal_part = decimal_part.ljust(2, "0")

    return int(integer_part) * 100 + int(decimal_part)


def parse_cents(text: str) -> int:
    """Parse text amount to integer cents (positive only).

    Strips spaces and leading €. Accepts digits with at most one decimal
    separator (. or ,) and at most 2 decimal places. Returns amount in cents.

    Raises ValueError for empty, multiple separators, >2 decimals, or <=0.
    """
    cents = _parse_amount(text)

    if cents <= 0:
        raise ValueError("Amount must be positive")

    return cents


def parse_signed_cents(text: str) -> int:
    """Parse text amount to a signed integer amount in cents.

    A balance can be zero or overdrawn, unlike a payment amount, so this
    accepts an optional leading "-" (checked before the € strip, since a
    balance may be written as "-€5") and does not reject zero or negatives.

    Raises ValueError for empty, multiple separators, >2 decimals, or a
    malformed sign (e.g. "-", "--5").
    """
    text = text.strip()

    negative = text.startswith("-")
    if negative:
        text = text[1:]

    cents = _parse_amount(text)

    return -cents if negative else cents


def parse_basis_points(text: str) -> int:
    """Parse text percentage to integer basis points (positive only).

    Strips spaces and one trailing %. Then reuses parse_cents, because
    a percent with 2 decimals uses the same fixed-point format as cents.
    Returns basis points (e.g., 3.5% -> 350, 0.99% -> 99).

    Raises ValueError for empty, invalid format, or <=0.
    """
    text = text.strip()
    if text.endswith("%"):
        text = text[:-1].strip()

    return parse_cents(text)
