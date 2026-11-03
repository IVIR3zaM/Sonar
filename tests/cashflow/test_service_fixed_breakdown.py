"""Fixed payment labels and debt deduplication on the dashboard (SPEC §13)."""

import sqlite3
from datetime import date

import pytest

from sonar.cashflow.service import load_dashboard
from sonar.cashflow.store import save_settings, set_manual_balance
from sonar.db import MIGRATIONS_DIR, apply_migrations
from sonar.debts.model import Loan, MatchRule
from sonar.debts.store import add_debt
from sonar.recurring.schedule import SchedulePeriod
from sonar.recurring.store import add_manual
from tests.cashflow.test_service import TODAY, _insert_detected, _insert_tx, _installment


@pytest.mark.parametrize("salary_day", [None, 26])
@pytest.mark.parametrize("with_balance", [False, True])
def test_fixed_breakdown_labels_each_source_and_counts_linked_payments_once(
    salary_day, with_balance
):
    with sqlite3.connect(":memory:") as conn:
        apply_migrations(conn, MIGRATIONS_DIR)
        if salary_day is not None:
            save_settings(conn, salary_day, -50_000)
        if with_balance:
            set_manual_balance(conn, TODAY, 100_000, TODAY)
        period = SchedulePeriod(date(2026, 1, 1), None, 5_000, 1, 15)
        add_manual(conn, "Gym", "Fitness", period)
        add_manual(conn, "Unlabelled subscription", None, period)
        for mandate, name, category in [
            ("loan", "Detected loan", None),
            ("sofa", "Detected sofa", "Furniture"),
        ]:
            _insert_tx(conn, "2026-08-15", -10_000, mandate_ref=mandate, category=category)
            _insert_detected(conn, f"mandate:/{mandate}", name, 15, 10_000)
            conn.execute(
                "UPDATE recurring_payments SET category = ? WHERE name = ?", (category, name)
            )
            conn.commit()
        add_debt(
            conn,
            Loan(
                name="Car loan",
                balance_cents=500_000,
                balance_as_of=date(2026, 8, 15),
                rate_cents=10_000,
                interest_bp=None,
                match=MatchRule("mandate", "loan"),
            ),
        )
        add_debt(conn, _installment("Sofa", "sofa"))
        add_debt(conn, _installment("Phone", "phone"))

        board = load_dashboard(conn, {"Fitness": "fixed", "Furniture": "fixed"}, TODAY)

    breakdown = board.fixed_breakdown
    assert {
        group.name: [payment.name for payment in group.payments] for group in breakdown.groups
    } == {
        "Fitness": ["Gym"],
        "Other": ["Unlabelled subscription"],
        "Loans": ["Car loan"],
        "Furniture": ["Sofa"],
        "Installments": ["Phone"],
    }
    assert breakdown.count == 5
    assert sum(group.total_cents for group in breakdown.groups) == breakdown.total_cents
    assert breakdown.total_cents == board.fixed_costs.monthly_equivalent_cents
    assert all(
        sum(payment.monthly_cents for payment in group.payments) == group.total_cents
        for group in breakdown.groups
    )
