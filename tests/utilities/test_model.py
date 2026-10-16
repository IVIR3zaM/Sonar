from dataclasses import replace
from datetime import date

import pytest

from sonar.utilities.model import (
    BillingPeriod,
    Charge,
    FieldError,
    Meter,
    check_period,
    check_periods,
)

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
WATER = replace(
    GAS,
    base_fee_cents=None,
    unit_price_micro=None,
    state_factor_e4=None,
    calorific_value_e4=None,
    drinking=Charge(unit_price_micro=1_800_000, base_fee_cents=350, vat_percent=7),
    wastewater=Charge(unit_price_micro=2_400_000, base_fee_cents=0, vat_percent=0),
)


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
    Meter("Water", "water")
    with pytest.raises(FieldError) as error:
        Meter("Fuel", "oil")
    assert error.value.field == "kind"


def test_new_period_fields_default_to_flexible_without_charges():
    assert GAS.drinking is None
    assert GAS.wastewater is None
    assert GAS.advance_mode == "flexible"
    assert GAS.advance_dates == ()
    assert GAS.settlement_debit_days == 0


@pytest.mark.parametrize("kind", ["gas", "electricity"])
@pytest.mark.parametrize("value", [None, 0, -1])
def test_gas_and_electricity_need_a_positive_unit_price(kind, value):
    period = GAS if kind == "gas" else ELECTRICITY
    assert field_of(replace(period, unit_price_micro=value), kind) == "unit_price_micro"


@pytest.mark.parametrize("kind", ["gas", "electricity"])
@pytest.mark.parametrize("value", [None, -1])
def test_gas_and_electricity_need_a_base_fee(kind, value):
    period = GAS if kind == "gas" else ELECTRICITY
    assert field_of(replace(period, base_fee_cents=value), kind) == "base_fee_cents"


@pytest.mark.parametrize("name", ["drinking", "wastewater"])
@pytest.mark.parametrize("kind", ["gas", "electricity"])
def test_gas_and_electricity_have_no_charges(kind, name):
    period = GAS if kind == "gas" else ELECTRICITY
    charge = Charge(unit_price_micro=1, base_fee_cents=0, vat_percent=0)
    assert field_of(replace(period, **{name: charge}), kind) == name


def test_a_water_period_is_valid():
    check_period(WATER, "water")


@pytest.mark.parametrize("name", ["drinking", "wastewater"])
def test_water_needs_both_charges(name):
    assert field_of(replace(WATER, **{name: None}), "water") == name


@pytest.mark.parametrize("name", ["drinking", "wastewater"])
@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"unit_price_micro": 0}, "price_micro"),
        ({"unit_price_micro": -1}, "price_micro"),
        ({"base_fee_cents": -1}, "base_fee_cents"),
        ({"vat_percent": -1}, "vat_percent"),
        ({"vat_percent": 101}, "vat_percent"),
    ],
)
def test_water_charges_are_range_checked(name, changes, field):
    charge = replace(getattr(WATER, name), **changes)
    assert field_of(replace(WATER, **{name: charge}), "water") == f"{name}_{field}"


@pytest.mark.parametrize("name", ["drinking", "wastewater"])
def test_water_charge_bounds_are_valid(name):
    charge = Charge(unit_price_micro=1, base_fee_cents=0, vat_percent=100)
    check_period(replace(WATER, **{name: charge}), "water")


@pytest.mark.parametrize(
    "name", ["unit_price_micro", "base_fee_cents", "state_factor_e4", "calorific_value_e4"]
)
def test_water_has_no_gas_or_electricity_fields(name):
    assert field_of(replace(WATER, **{name: 1}), "water") == name


def test_advance_mode_is_flexible_or_schedule():
    assert field_of(replace(GAS, advance_mode="weekly"), "gas") == "advance_mode"


def test_a_schedule_period_needs_dates_inside_the_period_plus_14_days():
    scheduled = replace(GAS, advance_mode="schedule")
    assert field_of(scheduled, "gas") == "advance_dates"
    check_period(replace(scheduled, advance_dates=(date(2026, 1, 1),)), "gas")
    check_period(replace(scheduled, advance_dates=(date(2027, 1, 14),)), "gas")
    for outside in (date(2025, 12, 31), date(2027, 1, 15)):
        assert field_of(replace(scheduled, advance_dates=(outside,)), "gas") == "advance_dates"


def test_schedule_dates_must_be_unique():
    dates = (date(2026, 2, 1), date(2026, 2, 1))
    scheduled = replace(GAS, advance_mode="schedule", advance_dates=dates)
    assert field_of(scheduled, "gas") == "advance_dates"


def test_a_flexible_period_has_no_dates():
    flexible = replace(GAS, advance_dates=(date(2026, 2, 1),))
    assert field_of(flexible, "gas") == "advance_dates"


@pytest.mark.parametrize("days", [0, 365])
def test_settlement_debit_days_bounds_are_valid(days):
    check_period(replace(GAS, settlement_debit_days=days), "gas")


@pytest.mark.parametrize("days", [-1, 366])
def test_settlement_debit_days_outside_0_to_365_are_rejected(days):
    assert field_of(replace(GAS, settlement_debit_days=days), "gas") == "settlement_debit_days"


def test_a_meter_may_link_to_a_main_meter_and_defaults_to_none():
    assert Meter("Water", "water").main_meter_id is None
    assert Meter("Garden", "water", 3).main_meter_id == 3


def test_garden_fee_is_water_only_and_not_negative():
    assert field_of(replace(GAS, garden_fee_cents=0), "gas") == "garden_fee_cents"
    assert field_of(replace(ELECTRICITY, garden_fee_cents=100), "electricity") == "garden_fee_cents"
    assert field_of(replace(WATER, garden_fee_cents=-1), "water") == "garden_fee_cents"
    check_period(replace(WATER, garden_fee_cents=0), "water")
    check_period(replace(WATER, garden_fee_cents=1_500), "water")
    check_period(WATER, "water")
    assert WATER.garden_fee_cents is None
