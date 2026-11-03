"""Debt labels use the latest categorized matching debit (SPEC §13)."""

from datetime import date

import pytest

from sonar.debts.model import MatchRule, latest_category
from tests.debts.test_model_last_payment import _installment, _tx


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        (
            [
                (_tx(-100, date(2026, 1, 5)), "Old"),
                (_tx(-100, date(2026, 3, 5)), "Latest"),
                (_tx(-100, date(2026, 2, 5)), "Middle"),
            ],
            "Latest",
        ),
        (
            [
                (_tx(-100, date(2026, 1, 5)), "Categorized"),
                (_tx(-100, date(2026, 2, 5)), None),
            ],
            "Categorized",
        ),
        (
            [
                (_tx(100, date(2026, 3, 5)), "Credit"),
                (_tx(-100, date(2026, 2, 5), counterparty="Other"), "Unrelated"),
                (_tx(-100, date(2026, 1, 5)), "Matched"),
            ],
            "Matched",
        ),
        (
            [
                (_tx(-100, date(2026, 1, 5)), "First"),
                (_tx(-100, date(2026, 1, 5)), "Later row"),
            ],
            "Later row",
        ),
        ([], None),
        ([(_tx(-100, date(2026, 1, 5)), None)], None),
        (
            [
                (_tx(100, date(2026, 1, 5)), "Credit"),
                (_tx(-100, date(2026, 1, 5), counterparty="Other"), "Unrelated"),
            ],
            None,
        ),
    ],
)
def test_latest_category(rows, expected):
    debt = _installment(MatchRule("counterparty", "Sofa Store"))

    assert latest_category(debt, iter(rows)) == expected
