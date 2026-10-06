"""Tests for the Payoff page: every step is server-rendered, the slider is a hidden extra."""

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from sonar.cashflow.service import load_payoff
from sonar.db import connect
from sonar.debts.model import Installment, Loan, MatchRule
from sonar.debts.store import add_debt
from sonar.web import charts
from sonar.web.app import create_app
from tests.html import cents, soup
from tests.seed import seed

TODAY = date(2026, 9, 10)


def _today() -> date:
    return TODAY


def _installment(name: str, total_cents: int, rate_cents: int, interval_months: int = 1):
    return Installment(
        name=name,
        total_cents=total_cents,
        rate_cents=rate_cents,
        interval_months=interval_months,
        first_payment_date=date(2026, 9, 15),
        payments_count=total_cents // rate_cents,
        match=MatchRule("counterparty", name),
    )


def _loan(name: str, balance_cents: int, rate_cents: int):
    return Loan(
        name=name,
        balance_cents=balance_cents,
        balance_as_of=date(2026, 9, 1),
        rate_cents=rate_cents,
        interest_bp=None,
        match=MatchRule("counterparty", name),
    )


def _db(tmp_path: Path, debts) -> Path:
    db_path = tmp_path / "t.db"
    seed(db_path)
    conn = connect(db_path)
    try:
        for debt in debts:
            add_debt(conn, debt)
    finally:
        conn.close()
    return db_path


def _payoff(db_path: Path):
    conn = connect(db_path)
    try:
        return load_payoff(conn, TODAY)
    finally:
        conn.close()


def _get(db_path: Path, path: str = "/payoff"):
    with TestClient(create_app(db_path, today=_today)) as client:
        return client.get(path)


def _range_cents(el) -> tuple[int, int]:
    holder = el if el.has_attr("data-min-cents") else el.select_one("[data-min-cents]")
    return int(holder["data-min-cents"]), int(holder["data-max-cents"])


DEBTS = [
    _installment("Sofa", 60_000, 20_000),
    _installment("Laptop", 30_000, 10_000),
    _installment("Bike", 120_000, 20_000, interval_months=3),
]


def test_each_step_matches_the_ladder_in_ascending_order(tmp_path):
    db_path = _db(tmp_path, DEBTS)
    payoff = _payoff(db_path)

    page = soup(_get(db_path))

    cards = page.select("[data-step]")
    assert len(cards) == len(payoff.steps) == 3
    assert [c["data-step"] for c in cards] == ["1", "2", "3"]
    pay_now = [cents(c.select_one("[data-part=pay-now]")) for c in cards]
    assert pay_now == [s.pay_now_cents for s in payoff.steps]
    assert pay_now == sorted(pay_now)
    for card, step in zip(cards, payoff.steps, strict=True):
        assert _range_cents(card.select_one("[data-part=freed]")) == (
            step.freed_min_cents,
            step.freed_max_cents,
        )
        assert _range_cents(card.select_one("[data-part=fixed-after]")) == (
            step.after_min_cents,
            step.after_max_cents,
        )


def test_step_tables_list_the_included_debts_in_ladder_order(tmp_path):
    db_path = _db(tmp_path, [*DEBTS, _loan("Car", 90_000, 15_000)])
    payoff = _payoff(db_path)

    page = soup(_get(db_path))

    for step in payoff.steps:
        rows = page.select(f"#payoff-step-{step.number}-debts tbody tr")
        assert [r["data-debt"] for r in rows] == [str(d.id) for d in step.debts]
        assert [r["data-kind"] for r in rows] == [d.kind for d in step.debts]
    assert any(r["data-kind"] == "loan" for r in page.select("[data-debt]"))
    for row in page.select("[data-debt]"):
        assert row.select_one("td").get_text(strip=True) == row["data-kind"]


def test_table_shows_remaining_rate_every_and_end_date(tmp_path):
    db_path = _db(tmp_path, [_installment("Bike", 120_000, 20_000, interval_months=3)])
    [step] = _payoff(db_path).steps
    [debt] = step.debts

    page = soup(_get(db_path))

    [row] = page.select("#payoff-step-1-debts tbody tr")
    cells = row.find_all("td")
    assert cells[1].get_text(strip=True) == "Bike"
    assert cents(cells[2]) == debt.remaining_cents
    assert cents(cells[3]) == debt.rate_cents
    assert cells[4].get_text(strip=True) == "3 month(s)"
    assert cells[5].select_one("time")["datetime"] == debt.end_date.isoformat()


def test_a_range_with_equal_ends_shows_one_amount(tmp_path):
    db_path = _db(tmp_path, [_installment("Sofa", 120_000, 10_000)])
    [step] = _payoff(db_path).steps
    assert step.freed_min_cents == step.freed_max_cents

    page = soup(_get(db_path))

    freed = page.select_one("[data-step] [data-part=freed]")
    assert len(freed.select("[data-cents]")) == 1


def test_a_range_with_different_ends_shows_both_amounts(tmp_path):
    db_path = _db(tmp_path, [_installment("Bike", 120_000, 40_000, interval_months=3)])
    [step] = _payoff(db_path).steps
    assert step.freed_min_cents != step.freed_max_cents

    page = soup(_get(db_path))

    freed = page.select_one("[data-step] [data-part=freed]")
    assert [cents(a) for a in freed.select("[data-cents]")] == [
        step.freed_min_cents,
        step.freed_max_cents,
    ]


def test_fixed_now_shows_the_before_range_and_the_estimate_date(tmp_path):
    db_path = _db(tmp_path, DEBTS)
    payoff = _payoff(db_path)

    page = soup(_get(db_path))

    assert _range_cents(page.select_one("#payoff-fixed-now")) == (
        payoff.before_min_cents,
        payoff.before_max_cents,
    )
    assert page.select_one("time#payoff-as-of")["datetime"] == payoff.estimate_date.isoformat()


def test_ticks_match_the_steps(tmp_path):
    db_path = _db(tmp_path, DEBTS)
    payoff = _payoff(db_path)
    expected = charts.payoff_ticks([s.pay_now_cents for s in payoff.steps])

    page = soup(_get(db_path))

    ticks = page.select("#payoff-slider-block [data-tick]")
    assert [t["data-tick"] for t in ticks] == ["1", "2", "3"]
    assert [int(t["data-cents"]) for t in ticks] == [s.pay_now_cents for s in payoff.steps]
    assert [int(t["data-position"]) for t in ticks] == [t.position for t in expected]
    cards = page.select("[data-step]")
    assert [int(c["data-position"]) for c in cards] == [t.position for t in expected]


def test_the_slider_block_is_hidden_but_no_step_is(tmp_path):
    db_path = _db(tmp_path, DEBTS)

    page = soup(_get(db_path))

    assert page.select_one("#payoff-slider-block").has_attr("hidden")
    assert page.select_one("#payoff-slider-block #payoff-slider") is not None
    assert not any(c.has_attr("hidden") for c in page.select("[data-step]"))


def test_without_debts_the_page_shows_only_the_empty_state(tmp_path):
    db_path = _db(tmp_path, [])

    page = soup(_get(db_path))

    assert page.select_one("#payoff-empty a[href='/debts']") is not None
    assert page.select_one("#payoff-slider") is None
    assert page.select("[data-step]") == []


def test_the_nav_lists_payoff_after_installments_and_loans(tmp_path):
    db_path = _db(tmp_path, DEBTS)

    page = soup(_get(db_path))

    nav = page.select_one("nav")
    links = [a["href"] for a in nav.select("a[href]")]
    assert links.index("/payoff") == links.index("/debts") + 1
    assert [a["href"] for a in nav.select('a[aria-current="page"]')] == ["/payoff"]
