from datetime import date
from fractions import Fraction

import pytest

from sonar.energy.model import Exchange, FieldError, Reading
from sonar.energy.usage import check_series, continuous_series, daily_usage


def reading(day: date, value_milli: int) -> Reading:
    return Reading(day, value_milli)


GAS_READINGS = [reading(date(2026, 1, 1), 1_000_000), reading(date(2026, 3, 1), 30_000)]
GAS_EXCHANGE = [Exchange(date(2026, 2, 1), old_final_milli=1_050_000, new_start_milli=0)]


def test_exchange_example_series():
    assert continuous_series(GAS_READINGS, GAS_EXCHANGE) == [
        (date(2026, 1, 1), 1_000_000),
        (date(2026, 2, 1), 1_050_000),
        (date(2026, 3, 1), 1_080_000),
    ]


def test_exchange_example_daily_usage_in_meter_units():
    usage = daily_usage(continuous_series(GAS_READINGS, GAS_EXCHANGE))
    assert {usage[date(2026, 1, day)] for day in range(1, 32)} == {Fraction(50, 31)}
    assert {usage[date(2026, 2, day)] for day in range(1, 29)} == {Fraction(30, 28)}
    assert len(usage) == 31 + 28
    assert date(2026, 3, 1) not in usage


def test_two_exchanges_in_a_row():
    readings = [
        reading(date(2026, 1, 1), 100_000),
        reading(date(2026, 4, 1), 20_000),
    ]
    exchanges = [
        Exchange(date(2026, 2, 1), old_final_milli=150_000, new_start_milli=0),
        Exchange(date(2026, 3, 1), old_final_milli=40_000, new_start_milli=5_000),
    ]
    assert continuous_series(readings, exchanges) == [
        (date(2026, 1, 1), 100_000),
        (date(2026, 2, 1), 150_000),
        # second exchange point: old_final plus the first exchange's offset
        (date(2026, 3, 1), 190_000),
        # reading: 20 + 150 + (40 - 5)
        (date(2026, 4, 1), 205_000),
    ]


def test_no_exchanges_is_the_plain_series():
    readings = [reading(date(2026, 2, 1), 5_000), reading(date(2026, 1, 1), 3_000)]
    assert continuous_series(readings, []) == [
        (date(2026, 1, 1), 3_000),
        (date(2026, 2, 1), 5_000),
    ]


def test_reading_on_an_exchange_date_is_a_date_error():
    readings = [reading(date(2026, 1, 1), 1_000), reading(date(2026, 2, 1), 10)]
    exchanges = [Exchange(date(2026, 2, 1), old_final_milli=1_200, new_start_milli=0)]
    with pytest.raises(FieldError) as error:
        check_series(readings, exchanges)
    assert error.value.field == "date"


def test_two_readings_on_one_date_is_a_date_error():
    readings = [reading(date(2026, 1, 1), 1_000), reading(date(2026, 1, 1), 2_000)]
    with pytest.raises(FieldError) as error:
        check_series(readings, [])
    assert error.value.field == "date"


def test_two_exchanges_on_one_date_is_a_date_error():
    exchanges = [
        Exchange(date(2026, 2, 1), old_final_milli=1_200, new_start_milli=0),
        Exchange(date(2026, 2, 1), old_final_milli=1_300, new_start_milli=0),
    ]
    with pytest.raises(FieldError) as error:
        check_series([], exchanges)
    assert error.value.field == "date"


def test_a_drop_is_a_value_error_naming_its_date():
    readings = [
        reading(date(2026, 1, 1), 5_000),
        reading(date(2026, 2, 1), 7_000),
        reading(date(2026, 3, 1), 6_000),
        reading(date(2026, 4, 1), 1_000),
    ]
    with pytest.raises(FieldError) as error:
        check_series(readings, [])
    assert error.value.field == "value"
    assert "2026-03-01" in str(error.value)
    assert "2026-04-01" not in str(error.value)


def test_an_exchange_that_drops_below_the_last_reading_is_a_value_error():
    readings = [reading(date(2026, 1, 1), 5_000)]
    exchanges = [Exchange(date(2026, 2, 1), old_final_milli=4_000, new_start_milli=0)]
    with pytest.raises(FieldError) as error:
        check_series(readings, exchanges)
    assert error.value.field == "value"
    assert "2026-02-01" in str(error.value)


def test_a_flat_series_is_valid():
    check_series([reading(date(2026, 1, 1), 5_000), reading(date(2026, 2, 1), 5_000)], [])


def test_the_example_is_valid():
    check_series(GAS_READINGS, GAS_EXCHANGE)


def test_fewer_than_two_points_have_no_daily_usage():
    assert daily_usage([]) == {}
    assert daily_usage([(date(2026, 1, 1), 1_000)]) == {}
