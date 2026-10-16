import calendar
from dataclasses import replace
from datetime import date
from fractions import Fraction

from sonar.utilities.model import BillingPeriod, Reading
from sonar.utilities.settlement import (
    MeterStatus,
    MonthFigure,
    cost,
    current_period,
    cycle_months,
    daily_kwh,
    meter_status,
    month_figures,
    round_half_up,
    same_day_last_year,
    seasonal_daily_kwh,
    suggested_advance,
    worst_daily_kwh,
)
from sonar.utilities.usage import continuous_series, daily_usage


def electricity_period(
    start: date,
    end: date,
    *,
    fee: int = 0,
    price: int = 100_000,
    advance: int = 5000,
    expected_usage: int = 0,
) -> BillingPeriod:
    return BillingPeriod(start, end, fee, price, None, None, advance, expected_usage, None)


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


def test_status_back_payment_and_worst_equals_projection_without_a_trend():
    # 20 kWh a day for 10 days: 2000 ct + 1000 ct fee so far; no trend or last year and no
    # expected kWh, so the 21 more days cost only their fee: 2100
    usage = usage_of((date(2026, 1, 1), 0), (date(2026, 1, 11), kwh(200)))
    status = meter_status("electricity", [JANUARY], usage, [], date(2026, 1, 11))
    assert status == MeterStatus(
        as_of=date(2026, 1, 11),
        cost_so_far_cents=3000,
        paid_cents=0,
        paid_since=date(2026, 1, 1),
        advance_count=1,
        left_cents=-3000,
        projected_cost_cents=5100,
        remaining_advance_count=1,
        remaining_advances_cents=5000,  # none paid: the start's day, so 1 Jan counts
        settlement_cents=-100,
        worst_settlement_cents=-100,
        suggested_advance_cents=2600,  # 5100 over this and 1 more advance, rounded up
    )


def test_status_refund_and_worst_case_from_expected_usage():
    period = electricity_period(
        date(2026, 1, 1), date(2026, 1, 31), fee=3100, advance=5000, expected_usage=3650
    )
    usage = usage_of((date(2026, 1, 1), 0), (date(2026, 1, 11), kwh(10)))
    status = meter_status(
        "electricity", [period], usage, [(date(2026, 1, 1), -5000)], date(2026, 1, 11)
    )
    # so far 100 + 1000; 21 more days at the expected 10 kWh (2100) and the fee (2100)
    assert status.cost_so_far_cents == 1100
    assert status.paid_cents == 5000
    assert status.left_cents == 3900
    assert status.projected_cost_cents == 5300
    assert status.remaining_advances_cents == 0
    assert status.settlement_cents == -300
    assert status.worst_settlement_cents == -300
    assert status.suggested_advance_cents == 300  # 5300 - 5000 paid, no advance left


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
    # projected: 1100 so far + 2100 fee (no expected kWh); worst: 21 days at 20 kWh (4200) more
    assert status.projected_cost_cents == 3200
    assert status.worst_settlement_cents == 5000 - 7400


def test_status_worst_case_counts_last_year_even_without_a_period_in_force():
    usage = usage_of(
        (date(2025, 1, 1), 0),
        (date(2025, 2, 1), kwh(620)),  # used, but no billing period covers it
        (date(2026, 1, 1), kwh(620)),
        (date(2026, 1, 11), kwh(630)),
    )
    status = meter_status(
        "electricity", [JANUARY], usage, [(date(2026, 1, 1), -5000)], date(2026, 1, 11)
    )
    assert status.worst_settlement_cents == 5000 - 7400


def test_same_day_last_year_maps_29_february_to_28_february():
    assert same_day_last_year(date(2028, 2, 29)) == date(2027, 2, 28)
    assert same_day_last_year(date(2026, 1, 11)) == date(2025, 1, 11)


def test_status_suggested_advance_rounds_up_to_whole_euros():
    period = electricity_period(
        date(2026, 1, 1), date(2026, 3, 31), advance=5000, expected_usage=3651
    )
    usage = usage_of((date(2026, 1, 1), 0), (date(2026, 2, 1), kwh(310)))
    status = meter_status(
        "electricity", [period], usage, [(date(2026, 1, 3), -3100)], date(2026, 2, 1)
    )
    # 3100 ct so far, 59 days at 3651 / 365 kWh: 5901.6 ct; advances due on 3 Feb and 3 Mar
    assert status.projected_cost_cents == 9002
    assert status.remaining_advances_cents == 10_000
    assert status.settlement_cents == 3100 + 10_000 - 9002
    assert status.remaining_advance_count == 2
    assert status.suggested_advance_cents == 2000  # (9001.6 - 3100) over 3 is 1967.2


def test_status_suggested_advance_is_still_given_on_the_settlement_day():
    usage = usage_of((date(2026, 1, 1), 0), (date(2026, 1, 31), kwh(300)))
    status = meter_status(
        "electricity", [JANUARY], usage, [(date(2026, 1, 15), -5000)], date(2026, 1, 31)
    )
    assert status.suggested_advance_cents == 1100  # 6100 projected - 5000 paid, divisor 1
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
        remaining_advance_count=0,
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


# --- seasonal projection, worst case and suggested advance -------------------

AS_OF = date(2026, 11, 1)
YEAR_2026 = electricity_period(date(2026, 1, 1), date(2026, 12, 31), expected_usage=3650)


def spread(usage: dict, year: int, month: int, total_kwh: int) -> None:
    """Add `total_kwh` evenly over every day of a month."""
    days = calendar.monthrange(year, month)[1]
    for day in range(1, days + 1):
        usage[date(year, month, day)] = Fraction(total_kwh, days)


def seasonal_usage(*, last_october=50, last_november=100, this_october=40) -> dict:
    usage: dict = {}
    spread(usage, 2025, 10, last_october)
    spread(usage, 2025, 11, last_november)
    spread(usage, 2026, 10, this_october)
    return usage


def month_total(result: dict, month: int) -> Fraction:
    return sum((v for day, v in result.items() if day.month == month), start=Fraction(0))


def test_seasonal_november_is_last_year_scaled_by_the_october_ratio():
    result = seasonal_daily_kwh("electricity", YEAR_2026, seasonal_usage(), AS_OF)
    assert month_total(result, 11) == 90  # 100 kWh x (1 + 40/50) / 2


def test_seasonal_covers_every_day_from_as_of_to_the_settlement():
    result = seasonal_daily_kwh("electricity", YEAR_2026, seasonal_usage(), AS_OF)
    assert (min(result), max(result)) == (AS_OF, date(2026, 12, 31))
    assert seasonal_daily_kwh("electricity", YEAR_2026, seasonal_usage(), date(2027, 1, 1)) == {}


def test_seasonal_day_without_last_years_usage_uses_expected_usage_per_day():
    result = seasonal_daily_kwh("electricity", YEAR_2026, seasonal_usage(), AS_OF)
    assert result[date(2026, 12, 15)] == 10  # 3650 / 365


def test_seasonal_without_a_full_month_in_the_period_uses_expected_usage_per_day():
    period = replace(YEAR_2026, start_date=date(2026, 10, 15))
    result = seasonal_daily_kwh("electricity", period, seasonal_usage(), AS_OF)
    assert set(result.values()) == {Fraction(10)}


def test_seasonal_with_a_gap_in_the_months_days_uses_expected_usage_per_day():
    usage = seasonal_usage()
    del usage[date(2026, 10, 20)]
    assert set(seasonal_daily_kwh("electricity", YEAR_2026, usage, AS_OF).values()) == {10}


def test_seasonal_without_last_years_month_uses_expected_usage_per_day():
    usage = seasonal_usage()
    for day in range(1, 32):
        del usage[date(2025, 10, day)]
    assert set(seasonal_daily_kwh("electricity", YEAR_2026, usage, AS_OF).values()) == {10}


def test_seasonal_with_last_years_month_at_zero_uses_expected_usage_per_day():
    usage = seasonal_usage(last_october=0)
    assert set(seasonal_daily_kwh("electricity", YEAR_2026, usage, AS_OF).values()) == {10}


def test_seasonal_gas_units_convert_with_the_current_periods_factors():
    period = replace(gas_period(date(2026, 1, 1), date(2026, 12, 31)), expected_usage=0)
    result = seasonal_daily_kwh("gas", period, seasonal_usage(), AS_OF)
    assert month_total(result, 11) == 90 * Fraction(9653 * 115_000, 10**8)


def test_seasonal_gas_fallback_is_already_kwh():
    period = replace(gas_period(date(2026, 1, 1), date(2026, 12, 31)), expected_usage=3650)
    result = seasonal_daily_kwh("gas", period, {}, AS_OF)
    assert set(result.values()) == {Fraction(10)}


def test_status_projects_the_remaining_days_seasonally():
    period = replace(YEAR_2026, expected_usage=0)
    status = meter_status("electricity", [period], seasonal_usage(), [], AS_OF)
    # 10 ct a kWh: October's 40 kWh so far, 90 kWh in November, nothing known for December
    assert status.cost_so_far_cents == 400
    assert status.projected_cost_cents == 400 + 900


def worst_of(*, this_october, last_year_day, expected_usage):
    """Worst kWh of 2 November when last year's usage on that day was `last_year_day`."""
    usage = seasonal_usage(last_october=40, this_october=this_october)
    usage[date(2025, 11, 2)] = Fraction(last_year_day)
    period = replace(YEAR_2026, expected_usage=expected_usage)
    return worst_daily_kwh("electricity", period, usage, AS_OF)[date(2026, 11, 2)]


def test_worst_day_takes_the_seasonal_projection_when_it_is_highest():
    # ratio 3: seasonal 20 x (1 + 3) / 2 = 40 beats last year's 20 and expected 10
    assert worst_of(this_october=120, last_year_day=20, expected_usage=3650) == 40


def test_worst_day_takes_expected_usage_per_day_when_it_is_highest():
    # ratio 1: seasonal 2 equals last year's 2, expected 10 wins
    assert worst_of(this_october=40, last_year_day=2, expected_usage=3650) == 10


def test_worst_day_takes_last_years_usage_when_it_is_highest():
    # ratio 0: seasonal 10, last year's 20 wins over expected 5
    assert worst_of(this_october=0, last_year_day=20, expected_usage=1825) == 20


def test_worst_day_ignores_the_current_daily_rate():
    usage = seasonal_usage(last_october=3100, this_october=3100)  # 100 kWh a day so far
    period = replace(YEAR_2026, expected_usage=3650)
    assert max(worst_daily_kwh("electricity", period, usage, AS_OF).values()) < 100


def suggested_for(price: int, fee: int, kwh_a_year: int) -> int | None:
    period = electricity_period(
        date(2026, 1, 1), date(2026, 12, 31), fee=fee, price=price, expected_usage=kwh_a_year
    )
    usage = usage_of((date(2026, 1, 1), 0), (date(2027, 1, 1), kwh(kwh_a_year)))
    status = meter_status("electricity", [period], usage, [], date(2026, 12, 31))
    assert status.advance_count == 11
    return status.suggested_advance_cents


def test_suggested_advance_is_what_is_left_to_pay_over_this_and_the_remaining_advances():
    # prod, 2026-10-15: 2457.38 EUR projected, 1505.00 paid, 3 advances left
    assert suggested_advance(Fraction(245_738), 150_500, 3) == 23_900


def test_suggested_advance_rounds_the_exact_figure_up_once():
    assert suggested_advance(Fraction(40_001, 2), 0, 1) == 10_100  # 10000.25 a time
    assert suggested_advance(Fraction(20_000), 0, 1) == 10_000


def test_suggested_advance_is_zero_when_paid_covers_the_projection():
    assert suggested_advance(Fraction(10_000), 10_000, 3) == 0
    assert suggested_advance(Fraction(10_000), 12_000, 3) == 0


def test_suggested_advance_with_no_advance_left_is_what_is_left_at_settlement():
    assert suggested_advance(Fraction(6_100), 5_000, 0) == 1_100


def test_suggested_advance_pins_over_eleven_remaining_advances_and_the_settlement():
    assert suggested_for(price=93_800, fee=1595, kwh_a_year=15701) == 13_900  # 166415.38 over 12
    assert suggested_for(price=318_325, fee=1041, kwh_a_year=8558) == 23_800  # 284914.5 over 12


def test_suggested_advance_is_none_without_a_projection():
    usage = usage_of((date(2025, 12, 1), 0), (date(2026, 1, 1), kwh(100)))
    status = meter_status("electricity", [JANUARY], usage, [], date(2026, 1, 5))
    assert status.suggested_advance_cents is None


# --- cycle chart months ----------------------------------------------------

GAS_PREVIOUS = gas_period(date(2025, 9, 3), date(2026, 8, 25))
GAS_CURRENT = gas_period(date(2026, 8, 26), date(2027, 8, 25))
GAS_TODAY = date(2026, 10, 10)


def gas_cycle_usage():
    return usage_of(
        (date(2025, 7, 1), 0),
        (date(2025, 10, 1), kwh(90)),
        (date(2026, 1, 1), kwh(600)),
        (date(2026, 4, 1), kwh(1100)),
        (date(2026, 9, 1), kwh(1250)),
        (date(2026, 10, 10), kwh(1350)),
    )


def gas_cycle_months():
    return cycle_months("gas", [GAS_PREVIOUS, GAS_CURRENT], gas_cycle_usage(), GAS_TODAY)


def months_from(first: date, count: int) -> list[date]:
    return [
        date(first.year + (first.month - 1 + i) // 12, (first.month - 1 + i) % 12 + 1, 1)
        for i in range(count)
    ]


def test_cycle_months_split_previous_current_and_projected():
    months = gas_cycle_months()
    shape = [(m.month, m.cycle, m.projected) for m in months]
    assert shape == (
        [(month, "previous", False) for month in months_from(date(2025, 10, 1), 11)]
        + [(date(2026, 9, 1), "current", False)]
        + [(month, "current", True) for month in months_from(date(2026, 10, 1), 11)]
    )


def test_cycle_months_actual_months_are_the_month_figures():
    usage = gas_cycle_usage()
    figures = {
        f.month: (f.kwh, f.cost_cents)
        for f in month_figures("gas", [GAS_PREVIOUS, GAS_CURRENT], usage)
    }
    for month in gas_cycle_months():
        if not month.projected:
            assert (month.kwh, month.cost_cents) == figures[month.month]


def projected_days(first: date, last: date) -> dict[date, Fraction]:
    usage = gas_cycle_usage()
    measured = daily_kwh("gas", [GAS_PREVIOUS, GAS_CURRENT], usage)
    seasonal = seasonal_daily_kwh("gas", GAS_CURRENT, usage, GAS_TODAY)
    both = {**measured, **seasonal}
    return {day: kwh for day, kwh in both.items() if first <= day <= last}


def expected_figures(days: dict[date, Fraction], fee_days: int, month_days: int):
    total = sum(days.values(), start=Fraction(0))
    cost_cents = total * 98_600 / 10**4 + Fraction(995 * fee_days, month_days)
    return round_half_up(total), round_half_up(cost_cents)


def test_cycle_months_october_sums_measured_days_and_seasonal_days():
    days = projected_days(date(2026, 10, 1), date(2026, 10, 31))
    assert len(days) == 31
    october = next(m for m in gas_cycle_months() if m.month == date(2026, 10, 1))
    assert (october.kwh, october.cost_cents) == expected_figures(days, 31, 31)


def test_cycle_months_settlement_month_stops_at_the_settlement_date():
    days = projected_days(date(2027, 8, 1), date(2027, 8, 31))
    assert max(days) == date(2027, 8, 25)
    august = gas_cycle_months()[-1]
    assert august.month == date(2027, 8, 1)
    assert (august.kwh, august.cost_cents) == expected_figures(days, 25, 31)


def test_cycle_months_without_a_current_period_show_the_latest_and_the_one_before():
    months = cycle_months("gas", [GAS_PREVIOUS, GAS_CURRENT], gas_cycle_usage(), date(2027, 9, 1))
    assert {m.cycle for m in months} == {"previous", "current"}
    assert not any(m.projected for m in months)
    assert [m.month for m in months if m.cycle == "current"] == [date(2026, 9, 1)]


def test_cycle_months_project_nothing_without_usage_in_the_current_period():
    usage = usage_of((date(2025, 7, 1), 0), (date(2026, 8, 1), kwh(900)))
    months = cycle_months("gas", [GAS_PREVIOUS, GAS_CURRENT], usage, GAS_TODAY)
    assert months and not any(m.projected for m in months)


def test_cycle_months_keep_the_latest_24():
    first = electricity_period(date(2024, 1, 1), date(2024, 12, 31))
    latest = electricity_period(date(2025, 1, 1), date(2026, 6, 30))
    usage = usage_of((date(2024, 1, 1), 0), (date(2026, 7, 1), kwh(9000)))
    months = cycle_months("electricity", [first, latest], usage, date(2026, 8, 1))
    assert [m.month for m in months] == months_from(date(2024, 7, 1), 24)
