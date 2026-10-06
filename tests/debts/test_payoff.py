import pytest

from sonar.debts.payoff import LadderDebt, payoff_ladder


def _debt(
    id: int,
    name: str,
    remaining_cents: int,
    months: tuple[int, ...],
    kind: str = "loan",
    interval_months: int = 1,
) -> LadderDebt:
    return LadderDebt(
        id=id,
        kind=kind,  # type: ignore[arg-type]
        name=name,
        remaining_cents=remaining_cents,
        rate_cents=months[0] or 1,
        interval_months=interval_months,
        end_date=None,
        months=months,
    )


def test_worked_example_with_shuffled_input():
    fixed = [300000] * 12
    tv = _debt(1, "TV", 30000, (4000,) * 12, kind="installment")
    car = _debt(2, "Car", 1800000, (70000,) * 12)
    mortgage = _debt(3, "Mortgage", 12000000, (150000,) * 12)

    steps = payoff_ladder([mortgage, tv, car], fixed)

    assert [s.number for s in steps] == [1, 2, 3]
    assert [[d.name for d in s.debts] for s in steps] == [
        ["TV"],
        ["TV", "Car"],
        ["TV", "Car", "Mortgage"],
    ]
    assert [s.pay_now_cents for s in steps] == [30000, 1830000, 13830000]
    assert [s.freed_cents for s in steps] == [4000, 74000, 224000]
    assert [s.after_min_cents for s in steps] == [296000, 226000, 76000]
    assert [s.after_max_cents for s in steps] == [296000, 226000, 76000]
    assert all(s.before_min_cents == s.before_max_cents == 300000 for s in steps)


def test_quarterly_debt_over_uneven_base_uses_range_formulas():
    fixed = [60000, 20000, 20000, 50000, 20000, 20000] * 2
    quarterly = _debt(
        1,
        "Insurance plan",
        500000,
        (10000, 0, 0, 30000, 0, 0) * 2,
        kind="installment",
        interval_months=3,
    )

    (step,) = payoff_ladder([quarterly], fixed)

    assert (step.before_min_cents, step.before_max_cents) == (20000, 60000)
    assert (step.after_min_cents, step.after_max_cents) == (20000, 50000)
    assert step.freed_cents == 10000


def test_zero_remaining_debt_is_left_out():
    fixed = [100000] * 3
    paid = _debt(1, "Paid", 0, (5000,) * 3)
    open_ = _debt(2, "Open", 9000, (7000,) * 3)

    steps = payoff_ladder([paid, open_], fixed)

    assert [[d.name for d in s.debts] for s in steps] == [["Open"]]


def test_remaining_tie_is_ordered_by_name_then_id():
    fixed = [100000] * 2
    b = _debt(1, "Beta", 5000, (1000,) * 2)
    a = _debt(2, "Alpha", 5000, (1000,) * 2)

    steps = payoff_ladder([b, a], fixed)

    assert [d.name for d in steps[-1].debts] == ["Alpha", "Beta"]


def test_months_length_mismatch_raises():
    debt = _debt(1, "Short", 5000, (1000,) * 2)

    with pytest.raises(ValueError):
        payoff_ladder([debt], [100000] * 3)


def test_no_debts_gives_empty_tuple():
    assert payoff_ladder([], [100000] * 3) == ()
