"""Human-facing display filters: eur amounts, dates and payment cadence.

Distinct from `money` in app.py, which formats cents as a plain "-1.50" for
form `value=` prefills that must round-trip through `parse_signed_cents`.
These filters are for read-only display and are not meant to be parsed back.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

# Non-breaking space before the currency sign and a true minus sign (U+2212,
# not a hyphen) match the SPEC's exact display format, not locale formatting.
_NBSP = " "
_MINUS = "−"

# Fixed English abbreviations rather than locale strftime, so the display
# does not change with the server's locale settings.
_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def eur(cents: int) -> str:
    """Format integer cents as "1.234,56 €" with a non-breaking space and U+2212 minus."""
    sign = _MINUS if cents < 0 else ""
    whole, remainder = divmod(abs(cents), 100)
    # Thousands grouping via the "," format spec, then swapped to "." for
    # the European convention; the decimal separator is "," accordingly.
    grouped = f"{whole:,}".replace(",", ".")
    return f"{sign}{grouped},{remainder:02d}{_NBSP}€"


def decimal(value: int, places: int) -> str:
    """Format an integer scaled by 10**places as "1.234,5678", trimming trailing
    zeros down to two decimals ("114,00"); a places of 0 has no decimals.
    """
    whole, fraction = divmod(abs(value), 10**places)
    sign = _MINUS if value < 0 else ""
    grouped = f"{whole:,}".replace(",", ".")
    if places == 0:
        return f"{sign}{grouped}"
    digits = f"{fraction:0{places}d}".rstrip("0").ljust(2, "0")
    return f"{sign}{grouped},{digits}"


def display_date(d: date) -> str:
    """Format a date as "24 Sep 2026" using the fixed English month table."""
    return f"{d.day} {_MONTHS[d.month - 1]} {d.year}"


_BERLIN = ZoneInfo("Europe/Berlin")


def berlin_time(moment: datetime) -> str:
    """Format an aware moment as "14 Oct 2026 14:00 CEST" in Berlin time.

    The owner reads the bank sync time on the wall clock of the bank's
    country, and the zone abbreviation keeps summer/winter time explicit.
    """
    local = moment.astimezone(_BERLIN)
    return f"{display_date(local.date())} {local:%H:%M} {local.tzname()}"


def cadence(interval_months: int, day: int) -> str:
    """Format a payment's recurrence as "monthly · day 15" / "every 3 mo · day 15".

    A yearly (12-month) cadence reads as "yearly" rather than "every 12 mo",
    since that is how the same interval is named in normal speech.
    """
    if interval_months == 1:
        label = "monthly"
    elif interval_months == 12:
        label = "yearly"
    else:
        label = f"every {interval_months} mo"
    return f"{label} · day {day}"


def days_until(n: int) -> str:
    """Format the number of days until payday.

    Returns "today" for n=0, "in 1 day" for n=1, "in N days" for n>1, and
    "1 day ago" / "N days ago" once the payday has passed.
    """
    if n == 0:
        return "today"
    if n == 1:
        return "in 1 day"
    if n == -1:
        return "1 day ago"
    if n < 0:
        return f"{-n} days ago"
    return f"in {n} days"
