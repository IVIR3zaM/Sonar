"""Tests for groups.py: the five category types and group totals."""

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

from sonar.categorization.groups import (
    FIXED,
    INCOME,
    LIGHTS_ON,
    OCCASIONAL,
    TRANSFER,
    TYPES,
    GroupTotals,
    group_totals,
)


@dataclass(frozen=True)
class _FakeTotal:
    category: str | None
    category_type: str | None
    total_cents: int


def test_group_totals_sums_each_group_and_leaves_out_transfer_and_income():
    totals = [
        _FakeTotal("Housing", FIXED, -1_000),
        _FakeTotal("Groceries", LIGHTS_ON, -2_000),
        _FakeTotal("Dining", OCCASIONAL, -300),
        _FakeTotal("Own transfers", TRANSFER, -5_000),
        _FakeTotal("Salary", INCOME, 300_000),
        _FakeTotal(None, None, -400),
    ]

    assert group_totals(totals) == GroupTotals(
        fixed_cents=-1_000,
        lights_on_cents=-2_000,
        occasional_cents=-300,
        uncategorized_cents=-400,
    )


def test_group_totals_raises_on_unknown_type():
    with pytest.raises(ValueError, match="unknown category type"):
        group_totals([_FakeTotal("Weird", "bogus", -100)])


def test_no_hardcoded_type_strings():
    """Guard: type values live only in groups.py, never hard-coded elsewhere."""
    sonar_dir = Path(__file__).parents[2] / "src" / "sonar"
    groups_file = sonar_dir / "categorization" / "groups.py"
    for py_file in sorted(sonar_dir.glob("**/*.py")):
        if py_file == groups_file:
            continue
        with open(py_file, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        # Find all string constants
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in TYPES:
                    # Report file:line
                    raise AssertionError(
                        f"{py_file.relative_to(sonar_dir.parent.parent)}:{node.lineno} "
                        f"hard-codes type {node.value!r}"
                    )
