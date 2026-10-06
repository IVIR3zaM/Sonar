from sonar.debts.payoff import LadderDebt, payoff_ladder


def _debt(
    id: int,
    name: str,
    remaining_cents: int,
    rate_cents: int = 1000,
    kind: str = "loan",
    interval_months: int = 1,
) -> LadderDebt:
    return LadderDebt(
        id=id,
        kind=kind,  # type: ignore[arg-type]
        name=name,
        remaining_cents=remaining_cents,
        rate_cents=rate_cents,
        interval_months=interval_months,
        end_date=None,
    )


def test_worked_example_with_shuffled_input():
    tv = _debt(1, "TV", 30000, 4000, kind="installment")
    laptop = _debt(2, "Laptop", 100000, 45000, kind="installment", interval_months=3)
    car = _debt(3, "Car", 1800000, 70000)
    mortgage = _debt(4, "Mortgage", 12000000, 150000)

    steps = payoff_ladder([mortgage, laptop, tv, car], 300000, 345000)

    assert [s.number for s in steps] == [1, 2, 3, 4]
    assert [[d.name for d in s.debts] for s in steps] == [
        ["TV"],
        ["TV", "Laptop"],
        ["TV", "Laptop", "Car"],
        ["TV", "Laptop", "Car", "Mortgage"],
    ]
    assert [s.pay_now_cents for s in steps] == [30000, 130000, 1930000, 13930000]
    assert [s.freed_cents for s in steps] == [4000, 49000, 119000, 269000]
    assert [s.after_min_cents for s in steps] == [296000, 296000, 226000, 76000]
    assert [s.after_max_cents for s in steps] == [341000, 296000, 226000, 76000]
    assert all((s.before_min_cents, s.before_max_cents) == (300000, 345000) for s in steps)


def test_zero_remaining_debt_is_left_out():
    paid = _debt(1, "Paid", 0, 5000)
    open_ = _debt(2, "Open", 9000, 7000)

    steps = payoff_ladder([paid, open_], 100000, 100000)

    assert [[d.name for d in s.debts] for s in steps] == [["Open"]]


def test_remaining_tie_is_ordered_by_name_then_id():
    b = _debt(1, "Beta", 5000)
    a = _debt(2, "Alpha", 5000)

    steps = payoff_ladder([b, a], 100000, 100000)

    assert [d.name for d in steps[-1].debts] == ["Alpha", "Beta"]


def test_no_debts_gives_empty_tuple():
    assert payoff_ladder([], 100000, 100000) == ()
