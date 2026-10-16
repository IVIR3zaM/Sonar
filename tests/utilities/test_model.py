from dataclasses import replace
from datetime import date

import pytest

from sonar.utilities.model import BillingPeriod, FieldError, Meter, check_period, check_periods

GAS = BillingPeriod(
    start_date=date(2026, 1, 1),
    settlement_date=date(2026, 12, 31),
    base_fee_cents=995,
    unit_price_micro=98_600,
    state_factor_e4=9_653,
    calorific_value_e4=115_000,
    advance_cents=9_000,
    expected_usage=12_000,
    category=None,
)
ELECTRICITY = replace(GAS, state_factor_e4=None, calorific_value_e4=None, category="Utilities")


def field_of(period: BillingPeriod, kind: str) -> str:
    with pytest.raises(FieldError) as error:
        check_period(period, kind)
    return error.value.field


def test_valid_periods_pass():
    check_period(GAS, "gas")
    check_period(ELECTRICITY, "electricity")


def test_a_one_day_period_is_valid():
    check_period(replace(GAS, settlement_date=GAS.start_date), "gas")


def test_settlement_before_start_is_rejected():
    assert field_of(replace(GAS, settlement_date=date(2025, 12, 31)), "gas") == "settlement_date"


def test_price_must_be_positive():
    assert field_of(replace(GAS, unit_price_micro=0), "gas") == "unit_price_micro"


@pytest.mark.parametrize("name", ["base_fee_cents", "advance_cents", "expected_usage"])
def test_negative_amounts_are_rejected(name):
    assert field_of(replace(GAS, **{name: -1}), "gas") == name


def test_zero_fee_advance_and_expected_are_valid():
    check_period(replace(GAS, base_fee_cents=0, advance_cents=0, expected_usage=0), "gas")


@pytest.mark.parametrize("name", ["state_factor_e4", "calorific_value_e4"])
def test_gas_needs_both_factors(name):
    assert field_of(replace(GAS, **{name: None}), "gas") == name
    assert field_of(replace(GAS, **{name: 0}), "gas") == name


@pytest.mark.parametrize("name", ["state_factor_e4", "calorific_value_e4"])
def test_electricity_has_no_factors(name):
    assert field_of(replace(ELECTRICITY, **{name: 10_000}), "electricity") == name


def test_overlapping_periods_are_rejected():
    later = replace(GAS, start_date=date(2026, 12, 31), settlement_date=date(2027, 12, 30))
    with pytest.raises(FieldError) as error:
        check_periods([later, GAS], "gas")
    assert error.value.field == "start_date"


def test_back_to_back_periods_are_valid():
    later = replace(GAS, start_date=date(2027, 1, 1), settlement_date=date(2027, 12, 31))
    check_periods([later, GAS], "gas")


def test_check_periods_checks_each_period():
    with pytest.raises(FieldError) as error:
        check_periods([replace(GAS, unit_price_micro=-5)], "gas")
    assert error.value.field == "unit_price_micro"


def test_meter_needs_a_name_and_a_known_kind():
    Meter("Gas", "gas")
    with pytest.raises(FieldError) as error:
        Meter("  ", "gas")
    assert error.value.field == "name"
    with pytest.raises(FieldError) as error:
        Meter("Water", "water")
    assert error.value.field == "kind"
