from dataclasses import replace
from datetime import date
from fractions import Fraction

from sonar.energy.model import BillingPeriod, Reading
from sonar.energy.settlement import (
    MeterStatus,
    MonthFigure,
    cost,
    current_period,
    daily_kwh,
    meter_status,
    month_figures,
    same_day_last_year,
)
from sonar.energy.usage import continuous_series, daily_usage


def electricity_period(
    start: date,
    end: date,
    *,
    fee: int = 0,
    price: int = 100_000,
    advance: int = 5000,
    expected_kwh: int = 0,
) -> BillingPeriod:
    return BillingPeriod(start, end, fee, price, None, None, advance, expected_kwh, None)


def gas_period(start: date, end: date) -> BillingPeriod:
    return BillingPeriod(start, end, 995, 98_600, 9653, 115_000, 0, 0, None)


def usage_of(*points: tuple[date, int]):
    """Daily usage from (date, value_milli) readings."""
    readings = [Reading(day, value) for day, value in points]
    return daily_usage(continuous_series(readings, []))


def kwh(amount: int) -> int:
    return amount * 1000


# --- daily_kwh, cost and month figures -------------------------------------


def test_electricity_units_are_kwh():
    period = electricity_period(date(2026, 3, 1), date(2026, 3, 31))
    usage = usage_of((date(2026, 3, 1), 0), (date(2026, 3, 11), kwh(50)))
    result = daily_kwh("electricity", [period], usage)
    assert result[date(2026, 3, 1)] == 5
    assert date(2026, 3, 11) not in result


def test_gas_cubic_meters_become_kwh_by_factor_and_calorific_value():
    period = gas_period(date(2026, 3, 1), date(2026, 3, 31))
    usage = usage_of((date(2026, 3, 1), 0), (date(2026, 4, 1), kwh(18)))
    total = sum(daily_kwh("gas", [period], usage).values())
    assert total == Fraction(18 * 9653 * 115_000, 10**8)


def test_days_outside_every_period_have_no_kwh_or_cost():
    period = electricity_period(date(2026, 3, 1), date(2026, 3, 10))
    usage = usage_of((date(2026, 3, 1), 0), (date(2026, 3, 21), kwh(20)))
    assert set(daily_kwh("electricity", [period], usage)) == {
        date(2026, 3, day) for day in range(1, 11)
    }
    assert cost("electricity", [period], usage, date(2026, 3, 11), date(2026, 3, 20)) == 0


def test_cost_electricity_pin():
    period = electricity_period(date(2026, 3, 1), date(2026, 3, 31), fee=1041, price=318_189)
    usage = usage_of((date(2026, 3, 1), 0), (date(2026, 4, 1), 541_000))
    assert cost("electricity", [period], usage, date(2026, 3, 1), date(2026, 3, 31)) == 18255


def test_cost_gas_pin():
    period = gas_period(date(2026, 3, 1), date(2026, 3, 31))
    usage = usage_of((date(2026, 3, 1), 0), (date(2026, 4, 1), 18_000))
    assert cost("gas", [period], usage, date(2026, 3, 1), date(2026, 3, 31)) == 2965


def test_half_a_thirty_day_month_costs_half_the_fee():
    period = electricity_period(date(2026, 4, 1), date(2026, 4, 15), fee=1000)
    usage = usage_of((date(2026, 4, 1), 0), (date(2026, 4, 16), 0))
    assert cost("electricity", [period], usage, date(2026, 4, 1), date(2026, 4, 30)) == 500


def test_cost_across_a_price_change_prices_each_day_by_its_period():
    first = electricity_period(date(2026, 3, 1), date(2026, 3, 15), price=100_000)
    second = electricity_period(date(2026, 3, 16), date(2026, 3, 31), price=200_000)
    usage = usage_of((date(2026, 3, 1), 0), (date(2026, 4, 1), kwh(31)))
    # 15 days at 1 kWh and 10 ct, 16 days at 1 kWh and 20 ct
    assert cost("electricity", [first, second], usage, date(2026, 3, 1), date(2026, 3, 31)) == 470


def test_month_figures_cover_only_months_fully_inside_the_usage():
    period = electricity_period(date(2026, 1, 1), date(2026, 12, 31))
    usage = usage_of((date(2026, 1, 15), 0), (date(2026, 3, 15), kwh(59)))
    assert month_figures("electricity", [period], usage) == [
        MonthFigure(date(2026, 2, 1), kwh=28, cost_cents=280)
    ]


def test_month_figures_leave_out_months_not_fully_covered_by_periods():
    period = electricity_period(date(2026, 2, 1), date(2026, 3, 15))
    usage = usage_of((date(2026, 1, 1), 0), (date(2026, 4, 1), kwh(90)))
    assert [figure.month for figure in month_figures("electricity", [period], usage)] == [
        date(2026, 2, 1)
    ]


def test_month_figures_round_half_up_once():
    period = electricity_period(date(2026, 2, 1), date(2026, 2, 28), price=100_000)
    usage = usage_of((date(2026, 2, 1), 0), (date(2026, 3, 1), 1_500))  # 1.5 kWh
    figure = month_figures("electricity", [period], usage)[0]
    assert (figure.kwh, figure.cost_cents) == (2, 15)


# --- current period --------------------------------------------------------


def test_current_period_contains_today_inclusive_else_none():
    january = electricity_period(date(2026, 1, 1), date(2026, 1, 31))
    february = electricity_period(date(2026, 2, 1), date(2026, 2, 28))
    assert current_period([january, february], date(2026, 1, 31)) == january
    assert current_period([january, february], date(2026, 2, 1)) == february
    assert current_period([january, february], date(2026, 3, 1)) is None


# --- status ----------------------------------------------------------------

JANUARY = electricity_period(date(2026, 1, 1), date(2026, 1, 31), fee=3100, advance=5000)


def test_status_back_payment_and_worst_equals_projection_when_rate_is_highest():
    # 20 kWh a day for 10 days: 2000 ct + 1000 ct fee so far; 21 more days: 4200 + 2100
    usage = usage_of((date(2026, 1, 1), 0), (date(2026, 1, 11), kwh(200)))
    status = meter_status("electricity", [JANUARY], usage, [], date(2026, 1, 11))
    assert status == MeterStatus(
        as_of=date(2026, 1, 11),
        cost_so_far_cents=3000,
        paid_cents=0,
        paid_since=date(2026, 1, 1),
        advance_count=1,
        left_cents=-3000,
        projected_cost_cents=9300,
        remaining_advances_cents=5000,  # none paid: the start's day, so 1 Jan counts
        settlement_cents=-4300,
        worst_settlement_cents=-4300,
        suggested_advance_cents=9300,
    )


def test_status_refund_and_worst_case_from_expected_kwh():
    period = electricity_period(
        date(2026, 1, 1), date(2026, 1, 31), fee=3100, advance=5000, expected_kwh=3650
    )
    usage = usage_of((date(2026, 1, 1), 0), (date(2026, 1, 11), kwh(10)))
    status = meter_status(
        "electricity", [period], usage, [(date(2026, 1, 1), -5000)], date(2026, 1, 11)
    )
    # so far 100 + 1000; projected adds 210 + 2100; worst adds 21 days at 10 kWh: 2100 + 2100
    assert status.cost_so_far_cents == 1100
    assert status.paid_cents == 5000
    assert status.left_cents == 3900
    assert status.projected_cost_cents == 3410
    assert status.remaining_advances_cents == 0
    assert status.settlement_cents == 1590
    assert status.worst_settlement_cents == -300
    assert status.suggested_advance_cents is None


def test_status_worst_case_from_last_year_on_the_same_days():
    last_year = electricity_period(date(2025, 1, 1), date(2025, 1, 31), fee=3100)
    usage = usage_of(
        (date(2025, 1, 1), 0),
        (date(2025, 2, 1), kwh(620)),  # 20 kWh a day in January 2025
        (date(2026, 1, 1), kwh(620)),
        (date(2026, 1, 11), kwh(630)),  # 1 kWh a day so far
    )
    status = meter_status(
        "electricity", [last_year, JANUARY], usage, [(date(2026, 1, 1), -5000)], date(2026, 1, 11)
    )
    # worst: 1100 so far + 21 days at 20 kWh (4200) + 2100 fee
    assert status.projected_cost_cents == 3410
    assert status.worst_settlement_cents == 5000 - 7400


def test_status_ignores_last_year_without_a_period_in_force():
    usage = usage_of(
        (date(2025, 1, 1), 0),
        (date(2025, 2, 1), kwh(620)),  # used, but no billing period covers it
        (date(2026, 1, 1), kwh(620)),
        (date(2026, 1, 11), kwh(630)),
    )
    status = meter_status(
        "electricity", [JANUARY], usage, [(date(2026, 1, 1), -5000)], date(2026, 1, 11)
    )
    assert status.worst_settlement_cents == status.settlement_cents


def test_same_day_last_year_maps_29_february_to_28_february():
    assert same_day_last_year(date(2028, 2, 29)) == date(2027, 2, 28)
    assert same_day_last_year(date(2026, 1, 11)) == date(2025, 1, 11)


def test_status_suggested_advance_rounds_up_to_whole_euros():
    period = electricity_period(date(2026, 1, 1), date(2026, 3, 31), advance=5000)
    usage = usage_of((date(2026, 1, 1), 0), (date(2026, 2, 1), kwh(310)))
    status = meter_status(
        "electricity", [period], usage, [(date(2026, 1, 3), -3100)], date(2026, 2, 1)
    )
    # 3100 ct so far, 59 days at 10 kWh: 5900 ct; advances due on 3 Feb and 3 Mar
    assert status.projected_cost_cents == 9000
    assert status.remaining_advances_cents == 10_000
    assert status.settlement_cents == 3100 + 10_000 - 9000
    assert status.suggested_advance_cents == 3000  # 2950 rounded up


def test_status_suggested_advance_is_none_on_the_settlement_day():
    usage = usage_of((date(2026, 1, 1), 0), (date(2026, 1, 31), kwh(300)))
    status = meter_status(
        "electricity", [JANUARY], usage, [(date(2026, 1, 15), -5000)], date(2026, 1, 31)
    )
    assert status.suggested_advance_cents is None
    assert status.remaining_advances_cents == 0


def test_status_ignores_credits_and_advances_before_the_start_or_after_today():
    usage = usage_of((date(2026, 1, 1), 0), (date(2026, 1, 11), kwh(10)))
    advances = [
        (date(2025, 12, 15), -5000),  # before the start
        (date(2026, 1, 5), 2000),  # a credit
        (date(2026, 1, 8), -4000),
        (date(2026, 1, 20), -4000),  # after today
    ]
    status = meter_status("electricity", [JANUARY], usage, advances, date(2026, 1, 11))
    assert status.paid_cents == 4000


def test_status_without_a_reading_after_the_start_has_no_cost_or_projection():
    usage = usage_of((date(2025, 12, 1), 0), (date(2026, 1, 1), kwh(100)))
    status = meter_status(
        "electricity", [JANUARY], usage, [(date(2026, 1, 1), -5000)], date(2026, 1, 5)
    )
    assert status == MeterStatus(
        as_of=None,
        cost_so_far_cents=None,
        paid_cents=5000,
        paid_since=date(2026, 1, 1),
        advance_count=1,
        left_cents=None,
        projected_cost_cents=None,
        remaining_advances_cents=0,
        settlement_cents=None,
        worst_settlement_cents=None,
        suggested_advance_cents=None,
    )


def test_status_starts_cost_at_the_first_point_when_it_is_after_the_period_start():
    usage = usage_of((date(2026, 1, 6), 0), (date(2026, 1, 11), kwh(50)))
    status = meter_status("electricity", [JANUARY], usage, [], date(2026, 1, 11))
    # 5 days at 10 kWh and a fee of 100 ct a day
    assert status.cost_so_far_cents == 500 + 500


def test_status_is_none_without_a_current_period():
    usage = usage_of((date(2026, 1, 1), 0), (date(2026, 1, 11), kwh(10)))
    assert meter_status("electricity", [JANUARY], usage, [], date(2026, 2, 1)) is None


# --- paid window, settled amount and remaining advances --------------------


def gas_cycle() -> list[BillingPeriod]:
    return [
        gas_period(date(2025, 9, 3), date(2026, 8, 25)),
        gas_period(date(2026, 8, 26), date(2027, 8, 25)),
    ]


def electricity_cycle(**changes) -> list[BillingPeriod]:
    return [
        electricity_period(date(2025, 7, 9), date(2025, 12, 31), **changes),
        electricity_period(date(2026, 1, 1), date(2026, 12, 31), **changes),
    ]


def test_paid_window_starts_fifteen_days_after_the_previous_settlement():
    bookings = [(date(2026, 9, 2), -18000), (date(2026, 10, 2), -18000)]
    status = meter_status("gas", gas_cycle(), {}, bookings, date(2026, 10, 15))
    assert status.paid_cents == 18000
    assert status.paid_since == date(2026, 9, 9)


def test_paid_window_leaves_out_the_grace_days_after_the_previous_settlement():
    bookings = [(date(2026, 1, 6), -20000)]
    status = meter_status("electricity", electricity_cycle(), {}, bookings, date(2026, 1, 20))
    assert status.paid_cents == 0
    assert status.paid_since == date(2026, 1, 15)


def test_paid_window_of_a_first_period_starts_with_the_period():
    period = electricity_period(date(2026, 1, 1), date(2026, 12, 31))
    bookings = [(date(2025, 12, 31), -100), (date(2026, 1, 1), -200)]
    status = meter_status("electricity", [period], {}, bookings, date(2026, 1, 20))
    assert (status.paid_cents, status.paid_since) == (200, date(2026, 1, 1))


def test_paid_window_counts_debits_only():
    period = electricity_period(date(2026, 1, 1), date(2026, 12, 31))
    bookings = [(date(2026, 1, 5), 7000), (date(2026, 1, 6), -300)]
    status = meter_status("electricity", [period], {}, bookings, date(2026, 1, 20))
    assert status.paid_cents == 300


def test_settled_amount_of_the_previous_period_is_not_an_advance():
    periods = electricity_cycle()
    periods[0] = replace(periods[0], settled_cents=-3169)
    today = date(2026, 10, 15)
    assert (
        meter_status("electricity", periods, {}, [(date(2026, 10, 5), -3169)], today).paid_cents
        == 0
    )
    assert (
        meter_status("electricity", periods, {}, [(date(2026, 10, 5), -3170)], today).paid_cents
        == 3170
    )


def test_settled_amount_matches_only_after_the_previous_settlement_date():
    periods = electricity_cycle()
    periods[0] = replace(periods[0], settled_cents=-3169)
    status = meter_status(
        "electricity", periods, {}, [(date(2026, 2, 1), -3169)], date(2026, 10, 15)
    )
    assert status.paid_cents == 0  # booked after the settlement, so the settled rule drops it


def test_advance_count_is_eleven_for_a_twelve_month_period():
    status = meter_status("gas", gas_cycle(), {}, [], date(2026, 10, 15))
    assert status.advance_count == 11
    status = meter_status("electricity", electricity_cycle(), {}, [], date(2026, 10, 15))
    assert status.advance_count == 11


def test_advance_count_of_a_part_year_and_of_one_day():
    status = meter_status("electricity", electricity_cycle(), {}, [], date(2025, 10, 15))
    assert status.advance_count == 5
    one_day = electricity_period(date(2026, 3, 3), date(2026, 3, 3))
    assert meter_status("electricity", [one_day], {}, [], date(2026, 3, 3)).advance_count == 1


def test_remaining_advances_of_gas_after_one_advance_are_ten():
    periods = [replace(period, advance_cents=18000) for period in gas_cycle()]
    status = meter_status("gas", periods, {}, [(date(2026, 10, 2), -18000)], date(2026, 10, 15))
    assert status.remaining_advances_cents == 10 * 18000


def test_remaining_advances_of_electricity_paid_february_to_october_are_two():
    periods = electricity_cycle(advance=4000)
    bookings = [(date(2026, month, 6), -4000) for month in range(2, 11)]
    status = meter_status("electricity", periods, {}, bookings, date(2026, 10, 15))
    assert status.paid_cents == 9 * 4000
    assert status.remaining_advances_cents == 2 * 4000
