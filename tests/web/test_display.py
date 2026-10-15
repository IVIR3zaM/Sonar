"""Tests for the eur/date/cadence display filters (SPEC §12 Display formats)."""

from datetime import UTC, date, datetime

from sonar.web.app import _format_cents
from sonar.web.display import berlin_time, cadence, days_until, display_date, eur


def test_eur_negative_uses_nbsp_and_minus_sign():
    assert eur(-123456) == "−1.234,56 €"


def test_eur_zero():
    assert eur(0) == "0,00 €"


def test_eur_small_positive():
    assert eur(5) == "0,05 €"


def test_eur_no_minus_sign_for_positive():
    assert eur(100) == "1,00 €"
    assert "−" not in eur(100)


def test_display_date_uses_fixed_english_month_table():
    assert display_date(date(2026, 9, 24)) == "24 Sep 2026"


def test_display_date_january_and_december():
    assert display_date(date(2026, 1, 1)) == "1 Jan 2026"
    assert display_date(date(2026, 12, 31)) == "31 Dec 2026"


def test_cadence_monthly():
    assert cadence(1, 15) == "monthly · day 15"


def test_cadence_every_n_months():
    assert cadence(3, 15) == "every 3 mo · day 15"


def test_cadence_every_two_months():
    assert cadence(2, 1) == "every 2 mo · day 1"


def test_cadence_every_six_months():
    assert cadence(6, 28) == "every 6 mo · day 28"


def test_cadence_yearly():
    assert cadence(12, 15) == "yearly · day 15"


def test_money_filter_unchanged():
    assert _format_cents(-150) == "-1.50"


def test_days_until_zero():
    assert days_until(0) == "today"


def test_days_until_one():
    assert days_until(1) == "in 1 day"


def test_days_until_past_days():
    assert days_until(-1) == "1 day ago"
    assert days_until(-3) == "3 days ago"


def test_days_until_multiple_days():
    assert days_until(15) == "in 15 days"


def test_berlin_time_in_summer_time():
    assert berlin_time(datetime(2026, 10, 14, 12, 0, tzinfo=UTC)) == "14 Oct 2026 14:00 CEST"


def test_berlin_time_in_winter_time():
    assert berlin_time(datetime(2026, 12, 1, 12, 0, tzinfo=UTC)) == "1 Dec 2026 13:00 CET"


def test_berlin_time_uses_the_berlin_date_across_midnight():
    assert berlin_time(datetime(2026, 12, 31, 23, 30, tzinfo=UTC)) == "1 Jan 2027 00:30 CET"
